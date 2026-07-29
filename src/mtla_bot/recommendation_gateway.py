"""Asynchronous verification of MTLA recommendations through BSN and Horizon.

The gateway deliberately keeps transport failures separate from negative business
results.  A caller must handle :class:`RecommendationGatewayError` as a
temporary technical failure and must not turn it into "no recommendation".
"""

from __future__ import annotations

import asyncio
import json
import ssl
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

import aiohttp
from stellar_sdk import Asset, Keypair
from yarl import URL


RECOMMENDATION_TAG = "RecommendToMTLA"
DEFAULT_BSN_URL = "https://bsn.expert"
DEFAULT_HORIZON_URL = "https://horizon.stellar.org"
DEFAULT_MINIMUM_BALANCE = Decimal("2")
DEFAULT_MAX_RECOMMENDERS = 100
DEFAULT_HORIZON_CONCURRENCY = 4
DEFAULT_BSN_BODY_LIMIT = 256 * 1024
DEFAULT_HORIZON_BODY_LIMIT = 1024 * 1024
DEFAULT_BSN_REQUEST_TIMEOUT = aiohttp.ClientTimeout(
    total=25.0,
    connect=2.5,
    sock_connect=2.5,
    sock_read=23.0,
)
DEFAULT_HORIZON_REQUEST_TIMEOUT = aiohttp.ClientTimeout(
    total=4.0,
    connect=1.5,
    sock_connect=1.5,
    sock_read=3.0,
)

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_RETRYABLE_STATUSES = frozenset({408, 425, 429})
_JSON_MEDIA_TYPES = frozenset({"application/json", "application/hal+json"})


class ExternalService(str, Enum):
    INPUT = "input"
    CONFIGURATION = "configuration"
    BSN = "bsn"
    HORIZON = "horizon"


class GatewayErrorCode(str, Enum):
    INVALID_ADDRESS = "invalid_address"
    INVALID_CONFIGURATION = "invalid_configuration"
    BSN_TIMEOUT = "bsn_timeout"
    BSN_UNAVAILABLE = "bsn_unavailable"
    BSN_INVALID_RESPONSE = "bsn_invalid_response"
    BSN_REDIRECT_REJECTED = "bsn_redirect_rejected"
    HORIZON_TIMEOUT = "horizon_timeout"
    HORIZON_UNAVAILABLE = "horizon_unavailable"
    HORIZON_INVALID_RESPONSE = "horizon_invalid_response"


class RecommendationGatewayError(Exception):
    """A typed failure that must not be interpreted as a negative result."""

    def __init__(
        self,
        code: GatewayErrorCode,
        service: ExternalService,
        message: str,
        *,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.service = service
        self.retryable = retryable


class RecommendationStatus(str, Enum):
    NONE = "none"
    UNQUALIFIED = "unqualified"
    QUALIFIED = "qualified"


@dataclass(frozen=True)
class RecommendationEvidence:
    recommender: str
    account_exists: bool
    mtlap_balance: Decimal | None
    is_qualified: bool


@dataclass(frozen=True)
class RecommendationResult:
    candidate: str
    status: RecommendationStatus
    recommender_count: int
    evidence: tuple[RecommendationEvidence, ...]
    checked_at: datetime

    @property
    def has_any_recommendation(self) -> bool:
        return self.recommender_count > 0

    @property
    def has_qualified_recommendation(self) -> bool:
        return self.status is RecommendationStatus.QUALIFIED

    @property
    def qualifying_evidence(self) -> RecommendationEvidence | None:
        return next((item for item in self.evidence if item.is_qualified), None)


def parse_bsn_recommenders(
    payload: object,
    candidate: str,
    *,
    max_recommenders: int = DEFAULT_MAX_RECOMMENDERS,
) -> tuple[str, ...]:
    """Extract incoming ``RecommendToMTLA`` source account IDs.

    BSN currently serializes an empty ``links.income`` as ``[]`` and a
    non-empty value as an object.  Both exact shapes are handled; malformed or
    truncated-looking responses fail closed.
    """

    if max_recommenders < 0:
        raise ValueError("max_recommenders must not be negative")
    root = _require_mapping(payload, ExternalService.BSN, "BSN response")
    account = _require_mapping(root.get("account"), ExternalService.BSN, "account")
    if account.get("id") != candidate:
        raise _invalid_response(
            ExternalService.BSN,
            "BSN account.id does not match the requested candidate",
        )

    links = _require_mapping(root.get("links"), ExternalService.BSN, "links")
    links_count = _require_mapping(
        root.get("links_count"),
        ExternalService.BSN,
        "links_count",
    )
    income_count = links_count.get("income")
    if (
        not isinstance(income_count, int)
        or isinstance(income_count, bool)
        or income_count < 0
    ):
        raise _invalid_response(
            ExternalService.BSN,
            "BSN links_count.income must be a non-negative integer",
        )
    if "income" not in links:
        raise _invalid_response(ExternalService.BSN, "BSN links.income is missing")
    income = links["income"]
    if isinstance(income, list):
        if income:
            raise _invalid_response(
                ExternalService.BSN,
                "BSN links.income must be an empty list or an object",
            )
        if income_count != 0:
            raise _invalid_response(
                ExternalService.BSN,
                "BSN income links and links_count are inconsistent",
            )
        return ()
    income_map = _require_mapping(income, ExternalService.BSN, "links.income")

    if RECOMMENDATION_TAG not in income_map:
        if income_count != 0:
            raise _invalid_response(
                ExternalService.BSN,
                "BSN income links and links_count are inconsistent",
            )
        return ()
    tagged = income_map[RECOMMENDATION_TAG]
    tagged_map = _require_mapping(
        tagged,
        ExternalService.BSN,
        f"links.income.{RECOMMENDATION_TAG}",
    )
    if tagged_map.get("name") != RECOMMENDATION_TAG:
        raise _invalid_response(
            ExternalService.BSN,
            "BSN recommendation tag name is inconsistent",
        )
    if "links" not in tagged_map:
        raise _invalid_response(
            ExternalService.BSN,
            "BSN recommendation links are missing",
        )

    recommender_links = tagged_map["links"]
    if isinstance(recommender_links, list):
        if recommender_links:
            raise _invalid_response(
                ExternalService.BSN,
                "BSN recommendation links must be an empty list or an object",
            )
        if income_count != 0:
            raise _invalid_response(
                ExternalService.BSN,
                "BSN recommendation links and links_count are inconsistent",
            )
        return ()
    recommender_map = _require_mapping(
        recommender_links,
        ExternalService.BSN,
        "BSN recommendation links",
    )
    if len(recommender_map) > max_recommenders:
        raise _invalid_response(
            ExternalService.BSN,
            f"BSN returned more than {max_recommenders} recommenders",
        )
    if len(recommender_map) != income_count:
        raise _invalid_response(
            ExternalService.BSN,
            "BSN recommendation links and links_count are inconsistent",
        )

    recommenders: list[str] = []
    for recommender, details in recommender_map.items():
        if not isinstance(recommender, str) or not _is_public_key(recommender):
            raise _invalid_response(
                ExternalService.BSN,
                "BSN returned an invalid recommender account ID",
            )
        details_map = _require_mapping(
            details,
            ExternalService.BSN,
            f"BSN recommendation from {recommender}",
        )
        if details_map.get("id") != recommender:
            raise _invalid_response(
                ExternalService.BSN,
                "BSN recommendation key and embedded id differ",
            )
        recommenders.append(recommender)
    return tuple(recommenders)


def parse_horizon_mtlap_balance(
    payload: object,
    recommender: str,
    *,
    asset_code: str,
    asset_issuer: str,
) -> Decimal:
    """Return the exact configured asset balance from a Horizon account JSON."""

    root = _require_mapping(payload, ExternalService.HORIZON, "Horizon response")
    if root.get("account_id") != recommender:
        raise _invalid_response(
            ExternalService.HORIZON,
            "Horizon account_id does not match the requested recommender",
        )
    balances = root.get("balances")
    if not isinstance(balances, list):
        raise _invalid_response(
            ExternalService.HORIZON,
            "Horizon balances must be a list",
        )

    expected_asset_type = (
        "credit_alphanum4" if len(asset_code) <= 4 else "credit_alphanum12"
    )
    matching_balances: list[Decimal] = []
    for item in balances:
        item_map = _require_mapping(
            item,
            ExternalService.HORIZON,
            "Horizon balance entry",
        )
        if (
            item_map.get("asset_code") != asset_code
            or item_map.get("asset_issuer") != asset_issuer
        ):
            continue
        if item_map.get("asset_type") != expected_asset_type:
            raise _invalid_response(
                ExternalService.HORIZON,
                "Horizon returned an inconsistent asset_type",
            )
        raw_balance = item_map.get("balance")
        if not isinstance(raw_balance, str):
            raise _invalid_response(
                ExternalService.HORIZON,
                "Horizon asset balance must be a decimal string",
            )
        try:
            balance = Decimal(raw_balance)
        except InvalidOperation as exc:
            raise _invalid_response(
                ExternalService.HORIZON,
                "Horizon returned an invalid decimal balance",
            ) from exc
        if not balance.is_finite() or balance < 0:
            raise _invalid_response(
                ExternalService.HORIZON,
                "Horizon returned a non-finite or negative balance",
            )
        matching_balances.append(balance)

    if len(matching_balances) > 1:
        raise _invalid_response(
            ExternalService.HORIZON,
            "Horizon returned duplicate entries for the configured asset",
        )
    return matching_balances[0] if matching_balances else Decimal("0")


@dataclass(frozen=True)
class _Redirect:
    location: str


class _NotFound:
    pass


_NOT_FOUND = _NotFound()


class _RetryableResponse(Exception):
    def __init__(self, status: int, retry_after: str | None) -> None:
        super().__init__(f"retryable HTTP status {status}")
        self.status = status
        self.retry_after = retry_after


class RecommendationGateway:
    """Verify per-account BSN recommendations against live Horizon balances.

    The injected session is reusable and remains owned by the caller.  The
    gateway never closes it.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        asset_code: str,
        asset_issuer: str,
        minimum_balance: Decimal = DEFAULT_MINIMUM_BALANCE,
        bsn_url: str = DEFAULT_BSN_URL,
        horizon_url: str = DEFAULT_HORIZON_URL,
        bsn_request_timeout: aiohttp.ClientTimeout = DEFAULT_BSN_REQUEST_TIMEOUT,
        horizon_request_timeout: aiohttp.ClientTimeout = DEFAULT_HORIZON_REQUEST_TIMEOUT,
        total_deadline: float = 35.0,
        max_attempts: int = 2,
        retry_backoff: float = 0.2,
        max_redirects: int = 2,
        max_recommenders: int = DEFAULT_MAX_RECOMMENDERS,
        horizon_concurrency: int = DEFAULT_HORIZON_CONCURRENCY,
        bsn_body_limit: int = DEFAULT_BSN_BODY_LIMIT,
        horizon_body_limit: int = DEFAULT_HORIZON_BODY_LIMIT,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._session = session
        self._asset_code, self._asset_issuer = _validated_asset(
            asset_code,
            asset_issuer,
        )
        if not isinstance(minimum_balance, Decimal):
            raise _invalid_configuration("minimum_balance must be a Decimal")
        if not minimum_balance.is_finite() or minimum_balance < 0:
            raise _invalid_configuration("minimum_balance must be finite and non-negative")
        if total_deadline <= 0:
            raise _invalid_configuration("total_deadline must be positive")
        if not isinstance(bsn_request_timeout, aiohttp.ClientTimeout):
            raise _invalid_configuration("bsn_request_timeout must be ClientTimeout")
        if not isinstance(horizon_request_timeout, aiohttp.ClientTimeout):
            raise _invalid_configuration("horizon_request_timeout must be ClientTimeout")
        if max_attempts < 1:
            raise _invalid_configuration("max_attempts must be at least one")
        if retry_backoff < 0:
            raise _invalid_configuration("retry_backoff must not be negative")
        if max_redirects < 0:
            raise _invalid_configuration("max_redirects must not be negative")
        if not 1 <= max_recommenders <= DEFAULT_MAX_RECOMMENDERS:
            raise _invalid_configuration(
                f"max_recommenders must be between 1 and {DEFAULT_MAX_RECOMMENDERS}"
            )
        if horizon_concurrency != DEFAULT_HORIZON_CONCURRENCY:
            raise _invalid_configuration(
                f"horizon_concurrency must be {DEFAULT_HORIZON_CONCURRENCY}"
            )
        if bsn_body_limit <= 0 or horizon_body_limit <= 0:
            raise _invalid_configuration("body limits must be positive")

        self._minimum_balance = minimum_balance
        self._bsn_origin = _validated_origin(bsn_url, "bsn_url")
        self._horizon_origin = _validated_origin(horizon_url, "horizon_url")
        self._bsn_request_timeout = bsn_request_timeout
        self._horizon_request_timeout = horizon_request_timeout
        self._total_deadline = total_deadline
        self._max_attempts = max_attempts
        self._retry_backoff = retry_backoff
        self._max_redirects = max_redirects
        self._max_recommenders = max_recommenders
        self._bsn_body_limit = bsn_body_limit
        self._horizon_body_limit = horizon_body_limit
        self._sleep = sleep
        # Shared by all simultaneous checks made through this gateway instance.
        self._horizon_semaphore = asyncio.Semaphore(DEFAULT_HORIZON_CONCURRENCY)

    async def check(self, candidate: str) -> RecommendationResult:
        """Return a business result or raise a typed technical failure."""

        if not isinstance(candidate, str) or not _is_public_key(candidate):
            raise RecommendationGatewayError(
                GatewayErrorCode.INVALID_ADDRESS,
                ExternalService.INPUT,
                "candidate is not a valid Stellar public key",
                retryable=False,
            )
        if getattr(self._session, "closed", False):
            raise _invalid_configuration("the injected HTTP session is closed")

        phase = ExternalService.BSN

        async def run_check() -> RecommendationResult:
            nonlocal phase
            payload = await self._fetch_bsn_payload(candidate)
            recommenders = parse_bsn_recommenders(
                payload,
                candidate,
                max_recommenders=self._max_recommenders,
            )
            if not recommenders:
                return RecommendationResult(
                    candidate=candidate,
                    status=RecommendationStatus.NONE,
                    recommender_count=0,
                    evidence=(),
                    checked_at=_utc_now(),
                )

            phase = ExternalService.HORIZON
            return await self._check_recommenders(candidate, recommenders)

        try:
            return await asyncio.wait_for(run_check(), timeout=self._total_deadline)
        except RecommendationGatewayError:
            raise
        except TimeoutError as exc:
            raise _timeout_error(phase, "recommendation check exceeded its deadline") from exc

    async def load_horizon_account(
        self,
        address: str,
    ) -> Mapping[str, Any] | None:
        """Load one Horizon account asynchronously using the shared session."""

        if not isinstance(address, str) or not _is_public_key(address):
            raise RecommendationGatewayError(
                GatewayErrorCode.INVALID_ADDRESS,
                ExternalService.INPUT,
                "account is not a valid Stellar public key",
                retryable=False,
            )
        if getattr(self._session, "closed", False):
            raise _invalid_configuration("the injected HTTP session is closed")

        async def load() -> Mapping[str, Any] | None:
            async with self._horizon_semaphore:
                url = self._horizon_origin.with_path(f"/accounts/{address}")
                reply = await self._request_json(
                    url,
                    ExternalService.HORIZON,
                    body_limit=self._horizon_body_limit,
                    not_found_is_negative=True,
                )
                if reply is _NOT_FOUND:
                    return None
                if isinstance(reply, _Redirect):
                    raise _invalid_response(
                        ExternalService.HORIZON,
                        "Horizon unexpectedly redirected an account request",
                    )
                root = _require_mapping(
                    reply,
                    ExternalService.HORIZON,
                    "Horizon response",
                )
                if root.get("account_id") != address:
                    raise _invalid_response(
                        ExternalService.HORIZON,
                        "Horizon account_id does not match the requested account",
                    )
                if not isinstance(root.get("balances"), list):
                    raise _invalid_response(
                        ExternalService.HORIZON,
                        "Horizon balances must be a list",
                    )
                return root

        try:
            return await asyncio.wait_for(load(), timeout=self._total_deadline)
        except RecommendationGatewayError:
            raise
        except TimeoutError as exc:
            raise _timeout_error(
                ExternalService.HORIZON,
                "Horizon account lookup exceeded its deadline",
            ) from exc

    async def _fetch_bsn_payload(self, candidate: str) -> object:
        current_url = self._bsn_origin.with_path(f"/accounts/{candidate}").with_query(
            {"format": "json", "tag": RECOMMENDATION_TAG}
        )
        redirects = 0
        while True:
            reply = await self._request_json(
                current_url,
                ExternalService.BSN,
                body_limit=self._bsn_body_limit,
                not_found_is_negative=False,
            )
            if not isinstance(reply, _Redirect):
                assert reply is not _NOT_FOUND
                return reply
            if redirects >= self._max_redirects:
                raise _redirect_error("BSN redirect limit exceeded")
            redirected_url = self._validated_bsn_redirect(current_url, reply.location)
            current_url = redirected_url
            redirects += 1

    def _validated_bsn_redirect(self, current_url: URL, location: str) -> URL:
        try:
            redirected = current_url.join(URL(location))
        except (TypeError, ValueError) as exc:
            raise _redirect_error("BSN returned an invalid redirect URL") from exc
        if redirected.user is not None or redirected.password is not None:
            raise _redirect_error("BSN redirect contains user information")
        if redirected.origin() != self._bsn_origin:
            raise _redirect_error("BSN redirect left the configured HTTPS origin")
        if (
            redirected.query.getall("format", []) != ["json"]
            or redirected.query.getall("tag", []) != [RECOMMENDATION_TAG]
        ):
            raise _redirect_error("BSN redirect dropped required JSON filters")
        return redirected.with_fragment(None)

    async def _check_recommenders(
        self,
        candidate: str,
        recommenders: tuple[str, ...],
    ) -> RecommendationResult:
        tasks = [
            asyncio.create_task(self._check_one_recommender(recommender))
            for recommender in recommenders
        ]
        evidence: list[RecommendationEvidence] = []
        errors: list[RecommendationGatewayError] = []
        try:
            for completed in asyncio.as_completed(tasks):
                try:
                    item = await completed
                except RecommendationGatewayError as exc:
                    errors.append(exc)
                    continue
                evidence.append(item)
                if item.is_qualified:
                    await _cancel_tasks(tasks)
                    return RecommendationResult(
                        candidate=candidate,
                        status=RecommendationStatus.QUALIFIED,
                        recommender_count=len(recommenders),
                        evidence=tuple(sorted(evidence, key=lambda value: value.recommender)),
                        checked_at=_utc_now(),
                    )
        finally:
            await _cancel_tasks(tasks)

        if errors:
            # Returning UNQUALIFIED would be a false negative because a failed
            # recommender might satisfy the existential business rule.
            raise errors[0]
        return RecommendationResult(
            candidate=candidate,
            status=RecommendationStatus.UNQUALIFIED,
            recommender_count=len(recommenders),
            evidence=tuple(sorted(evidence, key=lambda value: value.recommender)),
            checked_at=_utc_now(),
        )

    async def _check_one_recommender(
        self,
        recommender: str,
    ) -> RecommendationEvidence:
        reply = await self.load_horizon_account(recommender)
        if reply is None:
            return RecommendationEvidence(
                recommender=recommender,
                account_exists=False,
                mtlap_balance=None,
                is_qualified=False,
            )
        balance = parse_horizon_mtlap_balance(
            reply,
            recommender,
            asset_code=self._asset_code,
            asset_issuer=self._asset_issuer,
        )
        return RecommendationEvidence(
            recommender=recommender,
            account_exists=True,
            mtlap_balance=balance,
            is_qualified=balance >= self._minimum_balance,
        )

    async def _request_json(
        self,
        url: URL,
        service: ExternalService,
        *,
        body_limit: int,
        not_found_is_negative: bool,
    ) -> object | _Redirect | _NotFound:
        for attempt in range(self._max_attempts):
            try:
                return await self._request_json_once(
                    url,
                    service,
                    body_limit=body_limit,
                    not_found_is_negative=not_found_is_negative,
                )
            except _RetryableResponse as exc:
                if attempt + 1 >= self._max_attempts:
                    raise _unavailable_error(
                        service,
                        f"upstream returned HTTP {exc.status}",
                        retryable=True,
                    ) from exc
                delay = _bounded_retry_delay(exc.retry_after, self._retry_backoff)
                if delay is None:
                    raise _unavailable_error(
                        service,
                        f"upstream requested an out-of-budget retry after HTTP {exc.status}",
                        retryable=True,
                    ) from exc
                await self._sleep(delay)
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientConnectorCertificateError, ssl.SSLError) as exc:
                raise _unavailable_error(
                    service,
                    "TLS certificate validation failed",
                    retryable=False,
                ) from exc
            except (TimeoutError, aiohttp.ServerTimeoutError) as exc:
                # A cold BSN account page can legitimately take tens of
                # seconds. Give it one generous attempt instead of doubling
                # upstream work with an immediate second long request.
                if service is ExternalService.BSN or attempt + 1 >= self._max_attempts:
                    raise _timeout_error(service, "upstream request timed out") from exc
                await self._sleep(self._retry_backoff)
            except aiohttp.ClientConnectionError as exc:
                if attempt + 1 >= self._max_attempts:
                    raise _unavailable_error(
                        service,
                        "upstream connection failed",
                        retryable=True,
                    ) from exc
                await self._sleep(self._retry_backoff)
            except aiohttp.ClientError as exc:
                raise _unavailable_error(
                    service,
                    "upstream HTTP client failed",
                    retryable=False,
                ) from exc
        raise AssertionError("request retry loop terminated unexpectedly")

    async def _request_json_once(
        self,
        url: URL,
        service: ExternalService,
        *,
        body_limit: int,
        not_found_is_negative: bool,
    ) -> object | _Redirect | _NotFound:
        headers = {
            "Accept": "application/json",
            "User-Agent": "MTLAJoinBot/1.0",
        }
        request_timeout = (
            self._bsn_request_timeout
            if service is ExternalService.BSN
            else self._horizon_request_timeout
        )
        async with self._session.get(
            url,
            headers=headers,
            timeout=request_timeout,
            allow_redirects=False,
        ) as response:
            if response.status == 200:
                return await _read_json_body(response, service, body_limit)
            if response.status == 404 and not_found_is_negative:
                return _NOT_FOUND
            if response.status in _REDIRECT_STATUSES:
                location = _header(response.headers, "Location")
                if not location:
                    raise _invalid_response(service, "redirect has no Location header")
                return _Redirect(location)
            if response.status in _RETRYABLE_STATUSES or 500 <= response.status <= 599:
                raise _RetryableResponse(
                    response.status,
                    _header(response.headers, "Retry-After"),
                )
            raise _unavailable_error(
                service,
                f"upstream rejected the request with HTTP {response.status}",
                retryable=False,
            )


async def _read_json_body(
    response: Any,
    service: ExternalService,
    limit: int,
) -> object:
    media_type = (_header(response.headers, "Content-Type") or "").split(";", 1)[0]
    media_type = media_type.strip().lower()
    if media_type not in _JSON_MEDIA_TYPES and not media_type.endswith("+json"):
        raise _invalid_response(service, "upstream response is not JSON")
    content_length = getattr(response, "content_length", None)
    if content_length is not None and content_length > limit:
        raise _invalid_response(service, "upstream response body is too large")

    chunks: list[bytes] = []
    received = 0
    while True:
        chunk = await response.content.read(min(16 * 1024, limit + 1 - received))
        if not chunk:
            break
        received += len(chunk)
        if received > limit:
            raise _invalid_response(service, "upstream response body is too large")
        chunks.append(chunk)
    try:
        return json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _invalid_response(service, "upstream returned malformed JSON") from exc


async def _cancel_tasks(tasks: list[asyncio.Task[RecommendationEvidence]]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _require_mapping(
    value: object,
    service: ExternalService,
    name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid_response(service, f"{name} must be an object")
    return value


def _is_public_key(value: str) -> bool:
    try:
        Keypair.from_public_key(value)
    except (TypeError, ValueError):
        return False
    return True


def _validated_asset(asset_code: str, asset_issuer: str) -> tuple[str, str]:
    try:
        asset = Asset(asset_code, asset_issuer)
    except (TypeError, ValueError) as exc:
        raise _invalid_configuration("configured MTLAP asset is invalid") from exc
    assert asset.issuer is not None
    return asset.code, asset.issuer


def _validated_origin(raw_url: str, name: str) -> URL:
    try:
        url = URL(raw_url)
    except (TypeError, ValueError) as exc:
        raise _invalid_configuration(f"{name} is not a valid URL") from exc
    if url.scheme != "https" or not url.host or url.user or url.password:
        raise _invalid_configuration(f"{name} must be an HTTPS origin")
    if url.path not in ("", "/") or url.query or url.fragment:
        raise _invalid_configuration(f"{name} must not contain a path, query, or fragment")
    return url.origin()


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def _bounded_retry_delay(raw_retry_after: str | None, default: float) -> float | None:
    if raw_retry_after is None:
        return default
    try:
        requested = float(raw_retry_after)
    except ValueError:
        return default
    if requested < 0 or requested > 1.0:
        return None
    return max(default, requested)


def _invalid_configuration(message: str) -> RecommendationGatewayError:
    return RecommendationGatewayError(
        GatewayErrorCode.INVALID_CONFIGURATION,
        ExternalService.CONFIGURATION,
        message,
        retryable=False,
    )


def _invalid_response(
    service: ExternalService,
    message: str,
) -> RecommendationGatewayError:
    code = (
        GatewayErrorCode.BSN_INVALID_RESPONSE
        if service is ExternalService.BSN
        else GatewayErrorCode.HORIZON_INVALID_RESPONSE
    )
    return RecommendationGatewayError(code, service, message, retryable=False)


def _redirect_error(message: str) -> RecommendationGatewayError:
    return RecommendationGatewayError(
        GatewayErrorCode.BSN_REDIRECT_REJECTED,
        ExternalService.BSN,
        message,
        retryable=False,
    )


def _timeout_error(
    service: ExternalService,
    message: str,
) -> RecommendationGatewayError:
    code = (
        GatewayErrorCode.BSN_TIMEOUT
        if service is ExternalService.BSN
        else GatewayErrorCode.HORIZON_TIMEOUT
    )
    return RecommendationGatewayError(code, service, message, retryable=True)


def _unavailable_error(
    service: ExternalService,
    message: str,
    *,
    retryable: bool,
) -> RecommendationGatewayError:
    code = (
        GatewayErrorCode.BSN_UNAVAILABLE
        if service is ExternalService.BSN
        else GatewayErrorCode.HORIZON_UNAVAILABLE
    )
    return RecommendationGatewayError(code, service, message, retryable=retryable)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
