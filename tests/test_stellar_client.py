from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from mtla_bot.bot import MTLAJoinBot
from mtla_bot.recommendation_gateway import (
    ExternalService,
    GatewayErrorCode,
    RecommendationEvidence,
    RecommendationGatewayError,
    RecommendationResult,
    RecommendationStatus,
)
from mtla_bot.stellar_client import StellarClient


ADDRESS = "G" + "A" * 55
RECOMMENDER = "G" + "B" * 55


def account(balance: str | None = "0"):
    balances = [{"asset_type": "native", "balance": "10.0000000"}]
    if balance is not None:
        balances.append(
            {
                "asset_type": "credit_alphanum12",
                "asset_code": "MTLAP",
                "asset_issuer": (
                    "GCNVDZIHGX473FEI7IXCUAEXUJ4BGCKEMHF36VYP5EMS7PX2QBLAMTLA"
                ),
                "balance": balance,
            }
        )
    return SimpleNamespace(balances=balances)


def qualified_result() -> RecommendationResult:
    evidence = RecommendationEvidence(
        recommender=RECOMMENDER,
        account_exists=True,
        mtlap_balance=Decimal("2"),
        is_qualified=True,
    )
    return RecommendationResult(
        candidate=ADDRESS,
        status=RecommendationStatus.QUALIFIED,
        recommender_count=1,
        evidence=(evidence,),
        checked_at=datetime.now(timezone.utc),
    )


class StellarClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_reusable_session_lifecycle_is_idempotent(self) -> None:
        fake_session = SimpleNamespace(closed=False, close=AsyncMock())
        factory = Mock(return_value=fake_session)
        client = StellarClient(session_factory=factory)

        factory.assert_not_called()
        await client.start()
        first_gateway = client._recommendation_gateway
        await client.start()

        factory.assert_called_once_with()
        self.assertIs(client._recommendation_gateway, first_gateway)

        await client.close()
        await client.close()

        fake_session.close.assert_awaited_once_with()

    async def test_candidate_and_recommendation_share_async_gateway(self) -> None:
        gateway = SimpleNamespace(
            load_horizon_account=AsyncMock(return_value=account("0")),
            check=AsyncMock(return_value=qualified_result()),
        )
        client = StellarClient(recommendation_gateway=gateway)

        snapshot = await client.get_account_info(ADDRESS)

        gateway.load_horizon_account.assert_awaited_once_with(ADDRESS)
        gateway.check.assert_awaited_once_with(ADDRESS)
        self.assertTrue(snapshot["has_trustline"])
        self.assertEqual(snapshot["mtlap_balance"], "0")
        self.assertTrue(snapshot["recommendation"]["has_recommendation"])

    async def test_positive_candidate_balance_skips_bsn(self) -> None:
        gateway = SimpleNamespace(
            load_horizon_account=AsyncMock(
                return_value=account("0.0000001")
            ),
            check=AsyncMock(),
        )
        client = StellarClient(recommendation_gateway=gateway)

        snapshot = await client.get_account_info(ADDRESS)

        self.assertEqual(snapshot["mtlap_balance"], "0.0000001")
        gateway.check.assert_not_awaited()

    async def test_recommendation_failure_stays_technical(self) -> None:
        error = RecommendationGatewayError(
            GatewayErrorCode.BSN_TIMEOUT,
            ExternalService.BSN,
            "timeout",
            retryable=True,
        )
        gateway = SimpleNamespace(check=AsyncMock(side_effect=error))
        gateway.load_horizon_account = AsyncMock(return_value=account("0"))
        client = StellarClient(
            recommendation_gateway=gateway,
        )

        snapshot = await client.get_account_info(ADDRESS)

        self.assertEqual(snapshot["recommendation"]["error"], "bsn_timeout")
        self.assertFalse(snapshot["recommendation"]["has_recommendation"])

    async def test_missing_candidate_and_horizon_failure_are_distinct(self) -> None:
        missing_gateway = SimpleNamespace(
            load_horizon_account=AsyncMock(return_value=None),
            check=AsyncMock(),
        )
        missing_client = StellarClient(
            recommendation_gateway=missing_gateway,
        )
        failure = RecommendationGatewayError(
            GatewayErrorCode.HORIZON_UNAVAILABLE,
            ExternalService.HORIZON,
            "horizon down",
            retryable=True,
        )
        failed_gateway = SimpleNamespace(
            load_horizon_account=AsyncMock(side_effect=failure),
            check=AsyncMock(),
        )
        failed_client = StellarClient(
            recommendation_gateway=failed_gateway,
        )

        missing = await missing_client.get_account_info(ADDRESS)
        failed = await failed_client.get_account_info(ADDRESS)

        self.assertFalse(missing["exists"])
        self.assertNotIn("error", missing)
        self.assertEqual(failed["error"], "horizon_unavailable")


class BotLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_ptb_hooks_start_and_close_stellar_client(self) -> None:
        bot = MTLAJoinBot.__new__(MTLAJoinBot)
        bot.stellar_client = SimpleNamespace(
            start=AsyncMock(),
            close=AsyncMock(),
        )
        bot._finalization_task = None
        bot._finalization_loop = AsyncMock()

        await bot._post_init(SimpleNamespace())
        await bot._post_shutdown(SimpleNamespace())

        bot.stellar_client.start.assert_awaited_once_with()
        bot.stellar_client.close.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()
