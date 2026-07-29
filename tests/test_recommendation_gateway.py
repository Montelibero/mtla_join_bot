import asyncio
import json
import unittest
from collections import defaultdict, deque
from decimal import Decimal
from typing import Any

import aiohttp
from stellar_sdk import Keypair

from mtla_bot.recommendation_gateway import (
    GatewayErrorCode,
    RecommendationGateway,
    RecommendationGatewayError,
    RecommendationStatus,
    parse_bsn_recommenders,
    parse_horizon_mtlap_balance,
)


CANDIDATE = "GBACH65OTKJL5VZCYCI4F4FTTODPEORFQQZVNF4PUK7X4AMGFXNP2KZZ"
RECOMMENDER = "GAQPZKOYGJDEWLYO6PBOJ4NG6HNBBNNZSOJNKUUCVJGLBQIQSO5AC26F"
SECOND_RECOMMENDER = "GBJQKGNVJHCT3DQUZT6RQ5MSTVMTUY4VFCBAKMYA7BK74LHXAXVQJQDC"
ASSET_CODE = "MTLAP"
ASSET_ISSUER = "GCNVDZIHGX473FEI7IXCUAEXUJ4BGCKEMHF36VYP5EMS7PX2QBLAMTLA"


def bsn_payload(candidate: str, recommenders: list[str]) -> dict[str, Any]:
    income: object
    if recommenders:
        income = {
            "RecommendToMTLA": {
                "name": "RecommendToMTLA",
                "is_unknown": False,
                "pair": None,
                "pair_strong": False,
                "links": {
                    recommender: {
                        "id": recommender,
                        "short_id": "G...",
                        "display_name": "ignored",
                    }
                    for recommender in recommenders
                },
            }
        }
    else:
        # This is the exact empty shape returned by the live per-account API.
        income = []
    return {
        "account": {"id": candidate, "display_name": "ignored"},
        "links": {"outcome": [], "income": income},
        "links_count": {"outcome": 0, "income": len(recommenders)},
    }


def horizon_payload(
    recommender: str,
    balance: str | None,
    *,
    asset_code: str = ASSET_CODE,
    asset_issuer: str = ASSET_ISSUER,
) -> dict[str, Any]:
    balances: list[dict[str, Any]] = [
        {
            "asset_type": "native",
            "balance": "10.0000000",
        }
    ]
    if balance is not None:
        balances.append(
            {
                "asset_type": (
                    "credit_alphanum4" if len(asset_code) <= 4 else "credit_alphanum12"
                ),
                "asset_code": asset_code,
                "asset_issuer": asset_issuer,
                "balance": balance,
                # Authorization is deliberately irrelevant to the approved rule.
                "is_authorized": False,
            }
        )
    return {"account_id": recommender, "balances": balances}


class FakeBody:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self._offset = 0

    async def read(self, size: int) -> bytes:
        await asyncio.sleep(0)
        if self._offset >= len(self._body):
            return b""
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class FakeResponse:
    def __init__(
        self,
        status: int,
        body: object = None,
        *,
        headers: dict[str, str] | None = None,
        delay: float = 0,
        content_length: int | None | object = ...,  # type: ignore[assignment]
    ) -> None:
        if isinstance(body, bytes):
            raw_body = body
        elif body is None:
            raw_body = b""
        else:
            raw_body = json.dumps(body).encode("utf-8")
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}
        self.content = FakeBody(raw_body)
        self.delay = delay
        self.content_length = (
            len(raw_body) if content_length is ... else content_length
        )


class FakeRequestContext:
    def __init__(self, session: "FakeSession", outcome: object) -> None:
        self._session = session
        self._outcome = outcome

    async def __aenter__(self) -> FakeResponse:
        self._session.active_requests += 1
        self._session.max_active_requests = max(
            self._session.max_active_requests,
            self._session.active_requests,
        )
        if isinstance(self._outcome, BaseException):
            self._session.active_requests -= 1
            raise self._outcome
        assert isinstance(self._outcome, FakeResponse)
        if self._outcome.delay:
            await asyncio.sleep(self._outcome.delay)
        return self._outcome

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        self._session.active_requests -= 1


class FakeSession:
    def __init__(self) -> None:
        self.closed = False
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.active_requests = 0
        self.max_active_requests = 0
        self._routes: defaultdict[str, deque[object]] = defaultdict(deque)

    def add(self, url: str, *outcomes: object) -> None:
        self._routes[url].extend(outcomes)

    def get(self, url: object, **kwargs: Any) -> FakeRequestContext:
        normalized_url = str(url)
        self.calls.append((normalized_url, kwargs))
        if not self._routes[normalized_url]:
            raise AssertionError(f"unexpected fake HTTP request: {normalized_url}")
        return FakeRequestContext(self, self._routes[normalized_url].popleft())


def make_gateway(session: FakeSession, **kwargs: Any) -> RecommendationGateway:
    return RecommendationGateway(
        session,  # type: ignore[arg-type]
        asset_code=ASSET_CODE,
        asset_issuer=ASSET_ISSUER,
        retry_backoff=0,
        **kwargs,
    )


def bsn_url(candidate: str = CANDIDATE) -> str:
    return (
        f"https://bsn.expert/accounts/{candidate}"
        "?format=json&tag=RecommendToMTLA"
    )


def horizon_url(recommender: str) -> str:
    return f"https://horizon.stellar.org/accounts/{recommender}"


class BsnParserTest(unittest.TestCase):
    def test_parses_positive_and_live_empty_shapes(self) -> None:
        self.assertEqual(
            parse_bsn_recommenders(
                bsn_payload(CANDIDATE, [RECOMMENDER]),
                CANDIDATE,
            ),
            (RECOMMENDER,),
        )
        self.assertEqual(
            parse_bsn_recommenders(bsn_payload(CANDIDATE, []), CANDIDATE),
            (),
        )

    def test_rejects_mismatched_account_id(self) -> None:
        payload = bsn_payload(SECOND_RECOMMENDER, [])

        with self.assertRaises(RecommendationGatewayError) as raised:
            parse_bsn_recommenders(payload, CANDIDATE)

        self.assertEqual(raised.exception.code, GatewayErrorCode.BSN_INVALID_RESPONSE)

    def test_does_not_truncate_over_recommender_limit(self) -> None:
        payload = bsn_payload(CANDIDATE, [RECOMMENDER])

        with self.assertRaises(RecommendationGatewayError) as raised:
            parse_bsn_recommenders(payload, CANDIDATE, max_recommenders=0)

        self.assertEqual(raised.exception.code, GatewayErrorCode.BSN_INVALID_RESPONSE)

    def test_rejects_inconsistent_embedded_recommender_id(self) -> None:
        payload = bsn_payload(CANDIDATE, [RECOMMENDER])
        payload["links"]["income"]["RecommendToMTLA"]["links"][RECOMMENDER][
            "id"
        ] = SECOND_RECOMMENDER

        with self.assertRaises(RecommendationGatewayError) as raised:
            parse_bsn_recommenders(payload, CANDIDATE)

        self.assertEqual(raised.exception.code, GatewayErrorCode.BSN_INVALID_RESPONSE)

    def test_rejects_null_tag_and_inconsistent_income_count(self) -> None:
        null_tag = bsn_payload(CANDIDATE, [])
        null_tag["links"]["income"] = {"RecommendToMTLA": None}

        with self.assertRaises(RecommendationGatewayError):
            parse_bsn_recommenders(null_tag, CANDIDATE)

        wrong_count = bsn_payload(CANDIDATE, [])
        wrong_count["links_count"]["income"] = 1

        with self.assertRaises(RecommendationGatewayError):
            parse_bsn_recommenders(wrong_count, CANDIDATE)


class HorizonParserTest(unittest.TestCase):
    def test_uses_exact_asset_and_decimal_boundary(self) -> None:
        payload = horizon_payload(RECOMMENDER, "2.0000000")
        payload["balances"].append(
            {
                "asset_type": "credit_alphanum12",
                "asset_code": ASSET_CODE,
                "asset_issuer": SECOND_RECOMMENDER,
                "balance": "999999999.0000000",
            }
        )

        balance = parse_horizon_mtlap_balance(
            payload,
            RECOMMENDER,
            asset_code=ASSET_CODE,
            asset_issuer=ASSET_ISSUER,
        )

        self.assertEqual(balance, Decimal("2.0000000"))

    def test_missing_exact_asset_is_zero(self) -> None:
        balance = parse_horizon_mtlap_balance(
            horizon_payload(RECOMMENDER, None),
            RECOMMENDER,
            asset_code=ASSET_CODE,
            asset_issuer=ASSET_ISSUER,
        )

        self.assertEqual(balance, Decimal("0"))

    def test_rejects_non_finite_balance(self) -> None:
        with self.assertRaises(RecommendationGatewayError) as raised:
            parse_horizon_mtlap_balance(
                horizon_payload(RECOMMENDER, "NaN"),
                RECOMMENDER,
                asset_code=ASSET_CODE,
                asset_issuer=ASSET_ISSUER,
            )

        self.assertEqual(
            raised.exception.code,
            GatewayErrorCode.HORIZON_INVALID_RESPONSE,
        )


class RecommendationGatewayTest(unittest.IsolatedAsyncioTestCase):
    async def test_uses_per_account_endpoint_and_accepts_same_origin_redirect(self) -> None:
        session = FakeSession()
        redirected_url = (
            "https://bsn.expert/@candidate?format=json&tag=RecommendToMTLA"
        )
        session.add(
            bsn_url(),
            FakeResponse(
                302,
                headers={
                    "Location": "/@candidate?format=json&tag=RecommendToMTLA"
                },
            ),
        )
        session.add(
            redirected_url,
            FakeResponse(200, bsn_payload(CANDIDATE, [RECOMMENDER])),
        )
        session.add(
            horizon_url(RECOMMENDER),
            FakeResponse(
                200,
                horizon_payload(RECOMMENDER, "2.0000000"),
                headers={"Content-Type": "application/hal+json; charset=utf-8"},
            ),
        )

        result = await make_gateway(session).check(CANDIDATE)

        self.assertEqual(result.status, RecommendationStatus.QUALIFIED)
        self.assertEqual(result.recommender_count, 1)
        self.assertEqual(
            result.qualifying_evidence.mtlap_balance,  # type: ignore[union-attr]
            Decimal("2.0000000"),
        )
        self.assertEqual([call[0] for call in session.calls], [
            bsn_url(),
            redirected_url,
            horizon_url(RECOMMENDER),
        ])
        self.assertTrue(
            all(call[1]["allow_redirects"] is False for call in session.calls)
        )
        self.assertEqual(session.calls[0][1]["timeout"].total, 25.0)
        self.assertEqual(session.calls[2][1]["timeout"].total, 4.0)

    async def test_rejects_cross_origin_redirect_before_following_it(self) -> None:
        session = FakeSession()
        session.add(
            bsn_url(),
            FakeResponse(
                302,
                headers={
                    "Location": (
                        "https://evil.example/accounts/x"
                        "?format=json&tag=RecommendToMTLA"
                    )
                },
            ),
        )

        with self.assertRaises(RecommendationGatewayError) as raised:
            await make_gateway(session).check(CANDIDATE)

        self.assertEqual(
            raised.exception.code,
            GatewayErrorCode.BSN_REDIRECT_REJECTED,
        )
        self.assertEqual(len(session.calls), 1)

    async def test_rejects_redirect_with_duplicate_filter_parameters(self) -> None:
        session = FakeSession()
        session.add(
            bsn_url(),
            FakeResponse(
                302,
                headers={
                    "Location": (
                        "/@candidate?format=json&tag=RecommendToMTLA&tag=Other"
                    )
                },
            ),
        )

        with self.assertRaises(RecommendationGatewayError) as raised:
            await make_gateway(session).check(CANDIDATE)

        self.assertEqual(
            raised.exception.code,
            GatewayErrorCode.BSN_REDIRECT_REJECTED,
        )
        self.assertEqual(len(session.calls), 1)

    async def test_none_skips_horizon(self) -> None:
        session = FakeSession()
        session.add(bsn_url(), FakeResponse(200, bsn_payload(CANDIDATE, [])))

        result = await make_gateway(session).check(CANDIDATE)

        self.assertEqual(result.status, RecommendationStatus.NONE)
        self.assertFalse(result.has_any_recommendation)
        self.assertEqual(len(session.calls), 1)

    async def test_retries_transient_bsn_status_once(self) -> None:
        session = FakeSession()
        session.add(
            bsn_url(),
            FakeResponse(503),
            FakeResponse(200, bsn_payload(CANDIDATE, [])),
        )

        result = await make_gateway(session).check(CANDIDATE)

        self.assertEqual(result.status, RecommendationStatus.NONE)
        self.assertEqual(len(session.calls), 2)

    async def test_timeout_is_typed_and_never_becomes_none(self) -> None:
        session = FakeSession()
        session.add(bsn_url(), asyncio.TimeoutError())

        with self.assertRaises(RecommendationGatewayError) as raised:
            await make_gateway(session).check(CANDIDATE)

        self.assertEqual(raised.exception.code, GatewayErrorCode.BSN_TIMEOUT)
        self.assertTrue(raised.exception.retryable)
        self.assertEqual(len(session.calls), 1)

    async def test_horizon_404_is_known_unqualified_evidence(self) -> None:
        session = FakeSession()
        session.add(
            bsn_url(),
            FakeResponse(200, bsn_payload(CANDIDATE, [RECOMMENDER])),
        )
        session.add(horizon_url(RECOMMENDER), FakeResponse(404))

        result = await make_gateway(session).check(CANDIDATE)

        self.assertEqual(result.status, RecommendationStatus.UNQUALIFIED)
        self.assertFalse(result.evidence[0].account_exists)
        self.assertIsNone(result.evidence[0].mtlap_balance)

    async def test_partial_horizon_failure_without_proof_is_not_unqualified(self) -> None:
        session = FakeSession()
        session.add(
            bsn_url(),
            FakeResponse(
                200,
                bsn_payload(CANDIDATE, [RECOMMENDER, SECOND_RECOMMENDER]),
            ),
        )
        session.add(
            horizon_url(RECOMMENDER),
            FakeResponse(503),
            FakeResponse(503),
        )
        session.add(
            horizon_url(SECOND_RECOMMENDER),
            FakeResponse(200, horizon_payload(SECOND_RECOMMENDER, "1.9999999")),
        )

        with self.assertRaises(RecommendationGatewayError) as raised:
            await make_gateway(session).check(CANDIDATE)

        self.assertEqual(
            raised.exception.code,
            GatewayErrorCode.HORIZON_UNAVAILABLE,
        )

    async def test_one_qualified_recommender_is_enough_despite_other_failure(self) -> None:
        session = FakeSession()
        session.add(
            bsn_url(),
            FakeResponse(
                200,
                bsn_payload(CANDIDATE, [RECOMMENDER, SECOND_RECOMMENDER]),
            ),
        )
        session.add(
            horizon_url(RECOMMENDER),
            FakeResponse(503),
            FakeResponse(503),
        )
        session.add(
            horizon_url(SECOND_RECOMMENDER),
            FakeResponse(200, horizon_payload(SECOND_RECOMMENDER, "3.0000000")),
        )

        result = await make_gateway(session).check(CANDIDATE)

        self.assertEqual(result.status, RecommendationStatus.QUALIFIED)
        self.assertEqual(result.qualifying_evidence.recommender, SECOND_RECOMMENDER)  # type: ignore[union-attr]

    async def test_horizon_requests_are_globally_limited_to_four(self) -> None:
        recommenders = [Keypair.random().public_key for _ in range(5)]
        session = FakeSession()
        session.add(
            bsn_url(),
            FakeResponse(200, bsn_payload(CANDIDATE, recommenders)),
        )
        for recommender in recommenders:
            session.add(
                horizon_url(recommender),
                FakeResponse(
                    200,
                    horizon_payload(recommender, "0.0000000"),
                    delay=0.02,
                ),
            )

        result = await make_gateway(session).check(CANDIDATE)

        self.assertEqual(result.status, RecommendationStatus.UNQUALIFIED)
        self.assertEqual(session.max_active_requests, 4)

    async def test_bsn_body_limit_fails_closed(self) -> None:
        session = FakeSession()
        session.add(bsn_url(), FakeResponse(200, bsn_payload(CANDIDATE, [])))

        with self.assertRaises(RecommendationGatewayError) as raised:
            await make_gateway(session, bsn_body_limit=16).check(CANDIDATE)

        self.assertEqual(
            raised.exception.code,
            GatewayErrorCode.BSN_INVALID_RESPONSE,
        )


if __name__ == "__main__":
    unittest.main()
