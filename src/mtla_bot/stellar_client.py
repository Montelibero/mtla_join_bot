"""Stellar account lookup and MTLA recommendation integration."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
import logging
from typing import Any

import aiohttp
from . import config
from .recommendation_gateway import (
    RecommendationGateway,
    RecommendationGatewayError,
)


logger = logging.getLogger(__name__)


class StellarClient:
    """Build one eligibility snapshot without blocking the Telegram event loop."""

    def __init__(
        self,
        recommendation_gateway: RecommendationGateway | None = None,
        *,
        session_factory: Callable[[], aiohttp.ClientSession] = aiohttp.ClientSession,
    ) -> None:
        horizon_url = (
            "https://horizon-testnet.stellar.org"
            if config.STELLAR_NETWORK == "testnet"
            else "https://horizon.stellar.org"
        )
        mtlap_asset = config.get_mtlap_asset()
        self.mtlap_code = mtlap_asset.code
        self.mtlap_issuer = mtlap_asset.issuer
        self._horizon_url = horizon_url
        self._session_factory = session_factory
        self._http_session: aiohttp.ClientSession | None = None
        self._recommendation_gateway = recommendation_gateway
        self._owns_recommendation_gateway = recommendation_gateway is None

    async def start(self) -> None:
        """Create the reusable HTTP session inside the running event loop."""

        if self._recommendation_gateway is not None:
            return

        session = self._session_factory()
        try:
            gateway = RecommendationGateway(
                session,
                asset_code=self.mtlap_code,
                asset_issuer=self.mtlap_issuer,
                bsn_url=config.BSN_URL,
                horizon_url=self._horizon_url,
            )
        except Exception:
            await session.close()
            raise

        self._http_session = session
        self._recommendation_gateway = gateway

    async def close(self) -> None:
        """Close owned network resources; repeated calls are safe."""

        session, self._http_session = self._http_session, None
        if session is not None and not session.closed:
            await session.close()
        if self._owns_recommendation_gateway:
            self._recommendation_gateway = None

    async def _gateway(self) -> RecommendationGateway:
        if self._recommendation_gateway is None:
            await self.start()
        assert self._recommendation_gateway is not None
        return self._recommendation_gateway

    async def check_account_exists(self, address: str) -> bool:
        """Return whether Horizon currently exposes the account."""

        gateway = await self._gateway()
        return await gateway.load_horizon_account(address) is not None

    async def check_trustline(self, address: str) -> bool:
        """Return whether the account has the exact configured MTLAP trustline."""

        gateway = await self._gateway()
        account = await gateway.load_horizon_account(address)
        if account is None:
            return False
        has_trustline, _balance = self._extract_mtlap(account)
        return has_trustline

    async def check_recommendation(self, address: str) -> dict[str, Any]:
        """Check only the candidate's incoming BSN links and live recommenders."""

        try:
            gateway = await self._gateway()
            result = await gateway.check(address)
        except RecommendationGatewayError as error:
            logger.warning(
                "Recommendation lookup failed: service=%s code=%s retryable=%s",
                error.service.value,
                error.code.value,
                error.retryable,
            )
            return {
                "has_recommendation": False,
                "has_any_recommendation": False,
                "error": error.code.value,
            }
        except Exception:
            logger.exception("Unexpected recommendation lookup failure")
            return {
                "has_recommendation": False,
                "has_any_recommendation": False,
                "error": "recommendation_unavailable",
            }

        recommendations = [
            {
                "recommender": evidence.recommender,
                "mtlap_balance": (
                    str(evidence.mtlap_balance)
                    if evidence.mtlap_balance is not None
                    else None
                ),
                "account_exists": evidence.account_exists,
                "is_verified": evidence.is_qualified,
            }
            for evidence in result.evidence
        ]
        verified = [item for item in recommendations if item["is_verified"]]
        return {
            "has_recommendation": result.has_qualified_recommendation,
            "has_any_recommendation": result.has_any_recommendation,
            "total_recommendations": result.recommender_count,
            "verified_recommendations": len(verified),
            "recommendations": recommendations,
            "verified_recommendations_list": verified,
        }

    async def get_account_info(self, address: str) -> dict[str, Any]:
        """Return one coherent candidate snapshot for the eligibility rules."""

        try:
            gateway = await self._gateway()
            account = await gateway.load_horizon_account(address)
            if account is None:
                return {
                    "exists": False,
                    "has_trustline": False,
                    "mtlap_balance": "0",
                    "balances": [],
                    "recommendation": {
                        "has_recommendation": False,
                        "has_any_recommendation": False,
                    },
                }
            balances = self._balances(account)
            has_trustline, mtlap_balance = self._extract_mtlap(account)

            # A positive balance already decides the stronger ALREADY_MEMBER
            # branch, so BSN cannot add information and must not delay it.
            if Decimal(mtlap_balance) > 0:
                recommendation_info = {
                    "has_recommendation": False,
                    "has_any_recommendation": False,
                }
            else:
                recommendation_info = await self.check_recommendation(address)

            return {
                "exists": True,
                "has_trustline": has_trustline,
                "mtlap_balance": mtlap_balance,
                "balances": balances,
                "recommendation": recommendation_info,
            }
        except RecommendationGatewayError as error:
            logger.warning(
                "Candidate lookup failed: service=%s code=%s retryable=%s",
                error.service.value,
                error.code.value,
                error.retryable,
            )
            return {
                "exists": False,
                "has_trustline": False,
                "mtlap_balance": "0",
                "balances": [],
                "recommendation": {
                    "has_recommendation": False,
                    "has_any_recommendation": False,
                },
                "error": error.code.value,
            }
        except Exception:
            logger.exception("Candidate Horizon lookup failed")
            return {
                "exists": False,
                "has_trustline": False,
                "mtlap_balance": "0",
                "balances": [],
                "recommendation": {
                    "has_recommendation": False,
                    "has_any_recommendation": False,
                },
                "error": "horizon_unavailable",
            }

    def _extract_mtlap(self, account: Any) -> tuple[bool, str]:
        expected_asset_type = (
            "credit_alphanum4"
            if len(self.mtlap_code) <= 4
            else "credit_alphanum12"
        )
        matches: list[str] = []
        for balance in self._balances(account):
            asset_code = self._field(balance, "asset_code")
            asset_issuer = self._field(balance, "asset_issuer")
            if (
                asset_code != self.mtlap_code
                or asset_issuer != self.mtlap_issuer
            ):
                continue
            if self._field(balance, "asset_type") != expected_asset_type:
                raise ValueError("invalid_mtlap_asset_type")
            raw_balance = self._field(balance, "balance")
            if not isinstance(raw_balance, str):
                raise ValueError("invalid_mtlap_balance")
            try:
                parsed_balance = Decimal(raw_balance)
            except InvalidOperation as exc:
                raise ValueError("invalid_mtlap_balance") from exc
            if not parsed_balance.is_finite() or parsed_balance < 0:
                raise ValueError("invalid_mtlap_balance")
            matches.append(raw_balance)

        if len(matches) > 1:
            raise ValueError("duplicate_mtlap_balance")
        if matches:
            return True, matches[0]
        return False, "0"

    @staticmethod
    def _balances(account: Any) -> Sequence[Any]:
        balances = (
            account.get("balances")
            if isinstance(account, Mapping)
            else getattr(account, "balances", None)
        )
        if balances is None:
            raw_data = getattr(account, "raw_data", None)
            if isinstance(raw_data, Mapping):
                balances = raw_data.get("balances")
        if not isinstance(balances, Sequence) or isinstance(
            balances,
            (str, bytes, bytearray),
        ):
            raise ValueError("invalid_horizon_balances")
        return balances

    @staticmethod
    def _field(balance: Any, name: str) -> Any:
        if isinstance(balance, Mapping):
            return balance.get(name)
        return getattr(balance, name, None)
