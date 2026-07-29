import unittest
from pathlib import Path
from unittest.mock import patch

import main
from mtla_bot import config
from mtla_bot.bot import MTLAJoinBot


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALID_TOKEN = "123456:ABC_def-123"
VALID_ASSET = (
    "MTLAP:GCNVDZIHGX473FEI7IXCUAEXUJ4BGCKEMHF36VYP5EMS7PX2QBLAMTLA"
)


class ConfigurationValidationTest(unittest.TestCase):
    def validate(self, *, token=VALID_TOKEN, asset=VALID_ASSET, network="public"):
        with (
            patch.object(config, "TELEGRAM_TOKEN", token),
            patch.object(config, "MTLAP_ASSET", asset),
            patch.object(config, "STELLAR_NETWORK", network),
        ):
            config.validate_config()

    def test_valid_configuration_and_default_asset_are_accepted(self) -> None:
        self.validate()
        with patch.object(config, "MTLAP_ASSET", VALID_ASSET):
            asset = config.get_mtlap_asset()

        self.assertEqual(asset.code, "MTLAP")
        self.assertEqual(
            asset.issuer,
            "GCNVDZIHGX473FEI7IXCUAEXUJ4BGCKEMHF36VYP5EMS7PX2QBLAMTLA",
        )

    def test_missing_or_invalid_tokens_are_rejected_without_echoing_value(self) -> None:
        invalid_tokens = (
            None,
            "",
            " 123456:secret",
            "123456:secret ",
            "not-a-number:secret",
            "123456:",
            "123456:has space",
            "123456:too:many",
        )

        for token in invalid_tokens:
            with self.subTest(token_present=bool(token)):
                with self.assertRaises(config.ConfigurationError) as raised:
                    self.validate(token=token)
                if token:
                    self.assertNotIn(token, str(raised.exception))

    def test_invalid_assets_are_rejected_without_echoing_value(self) -> None:
        invalid_assets = (
            "MTLAP",
            "MTLAP:issuer:extra",
            ":GCNVDZIHGX473FEI7IXCUAEXUJ4BGCKEMHF36VYP5EMS7PX2QBLAMTLA",
            "BAD!:GCNVDZIHGX473FEI7IXCUAEXUJ4BGCKEMHF36VYP5EMS7PX2QBLAMTLA",
            "MTLAP:GAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        )

        for asset in invalid_assets:
            with self.subTest(asset=asset.split(":", 1)[0]):
                with self.assertRaises(config.ConfigurationError) as raised:
                    self.validate(asset=asset)
                self.assertEqual(
                    str(raised.exception),
                    "Invalid MTLAP_ASSET configuration",
                )

    def test_unknown_stellar_network_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            config.ConfigurationError,
            "STELLAR_NETWORK",
        ):
            self.validate(network="mainnet")

    def test_default_agreement_links_follow_interface_language(self) -> None:
        self.assertEqual(
            config.DEFAULT_AGREEMENT_LINK_RU,
            "https://docs.mtla.me/Agreement/Agreement.ru.html",
        )
        self.assertEqual(
            config.DEFAULT_AGREEMENT_LINK_EN,
            "https://docs.mtla.me/Agreement/Agreement.en.html",
        )

    @patch("mtla_bot.bot.StellarClient")
    @patch("mtla_bot.bot.UserStateManager")
    def test_invalid_config_fails_before_database_construction(
        self,
        state_manager,
        stellar_client,
    ) -> None:
        with patch(
            "mtla_bot.bot.config.validate_config",
            side_effect=config.ConfigurationError("TELEGRAM_TOKEN is required"),
        ):
            with self.assertRaises(config.ConfigurationError):
                MTLAJoinBot()

        state_manager.assert_not_called()
        stellar_client.assert_not_called()


class EntrypointTest(unittest.TestCase):
    @patch("builtins.print")
    @patch("main.MTLAJoinBot")
    def test_configuration_error_returns_distinct_exit_code(
        self,
        bot_class,
        _print,
    ) -> None:
        bot_class.side_effect = config.ConfigurationError("TELEGRAM_TOKEN is required")

        with self.assertLogs("main", level="ERROR") as logs:
            exit_code = main.main()

        self.assertEqual(exit_code, 2)
        self.assertIn("TELEGRAM_TOKEN is required", "\n".join(logs.output))

    @patch("builtins.print")
    @patch("main.MTLAJoinBot")
    def test_unexpected_startup_error_returns_one(
        self,
        bot_class,
        _print,
    ) -> None:
        bot_class.side_effect = RuntimeError("startup failed")

        with self.assertLogs("main", level="ERROR"):
            exit_code = main.main()

        self.assertEqual(exit_code, 1)


class TlsAndContainerGuardTest(unittest.TestCase):
    def test_bsn_client_does_not_disable_tls_verification(self) -> None:
        sources = [
            (PROJECT_ROOT / "src/mtla_bot/stellar_client.py").read_text(),
            (PROJECT_ROOT / "src/mtla_bot/recommendation_gateway.py").read_text(),
        ]
        source = "\n".join(sources)

        self.assertNotIn("CERT_NONE", source)
        self.assertNotIn("check_hostname = False", source)
        self.assertNotIn("TCPConnector(ssl=", source)
        self.assertNotIn("ssl=False", source)
        self.assertIn("aiohttp.ClientSession", source)

    def test_container_has_ca_bundle_and_runs_python_as_non_root(self) -> None:
        dockerfile = (PROJECT_ROOT / "Dockerfile").read_text()

        self.assertIn("ca-certificates", dockerfile)
        self.assertIn('USER mtla', dockerfile)
        self.assertIn('CMD ["python", "main.py"]', dockerfile)
        self.assertNotIn("mongod", dockerfile)

    def test_compose_separates_and_health_checks_mongodb(self) -> None:
        compose = (PROJECT_ROOT / "compose.yaml").read_text()

        self.assertIn("mongo:7.0@sha256:", compose)
        self.assertIn("condition: service_healthy", compose)
        self.assertIn("MONGODB_URI: mongodb://mongo:27017/", compose)
        self.assertIn("external: true", compose)
        self.assertIn("name: mtla_join_bot_data", compose)

    def test_portainer_uses_bsn_over_shared_internal_network(self) -> None:
        compose = (PROJECT_ROOT / "deploy/portainer-stack.yml").read_text()

        self.assertIn("BSN_URL: http://bsn_app", compose)
        self.assertIn("- web3", compose)
        self.assertIn("name: web3", compose)

    def test_polling_keeps_updates_received_during_downtime(self) -> None:
        bot_source = (PROJECT_ROOT / "src/mtla_bot/bot.py").read_text()

        self.assertIn("drop_pending_updates=False", bot_source)
        self.assertIn(".post_init(self._post_init)", bot_source)
        self.assertIn(".post_shutdown(self._post_shutdown)", bot_source)
        self.assertIn(".concurrent_updates(8)", bot_source)


if __name__ == "__main__":
    unittest.main()
