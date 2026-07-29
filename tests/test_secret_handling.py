import io
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import mock_open, patch

from mtla_bot import config
from mtla_bot.logging_config import (
    REDACTED_VALUE,
    SecretRedactingFormatter,
    configure_logging,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SecretRedactingFormatterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.token = "123456:TEST_TOKEN_ONLY"
        self.formatter = SecretRedactingFormatter(
            logging.Formatter("%(levelname)s %(message)s"),
            (self.token,),
        )

    def test_redacts_secret_from_formatted_arguments(self) -> None:
        record = logging.LogRecord(
            name="httpx",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="HTTP Request: %s",
            args=(f"https://api.telegram.org/bot{self.token}/getMe",),
            exc_info=None,
        )

        output = self.formatter.format(record)

        self.assertNotIn(self.token, output)
        self.assertIn(REDACTED_VALUE, output)

    def test_redacts_secret_from_exception_traceback(self) -> None:
        try:
            raise RuntimeError(f"request failed for {self.token}")
        except RuntimeError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="mtla_bot",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Unexpected error",
            args=(),
            exc_info=exc_info,
        )

        output = self.formatter.format(record)

        self.assertNotIn(self.token, output)
        self.assertIn(REDACTED_VALUE, output)


class LoggingConfigurationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root_logger = logging.getLogger()
        self.original_handlers = list(self.root_logger.handlers)
        self.original_root_level = self.root_logger.level
        self.httpx_level = logging.getLogger("httpx").level
        self.httpcore_level = logging.getLogger("httpcore").level

        self.output = io.StringIO()
        self.handler = logging.StreamHandler(self.output)
        self.handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        self.root_logger.handlers[:] = [self.handler]

    def tearDown(self) -> None:
        self.root_logger.handlers[:] = self.original_handlers
        self.root_logger.setLevel(self.original_root_level)
        logging.getLogger("httpx").setLevel(self.httpx_level)
        logging.getLogger("httpcore").setLevel(self.httpcore_level)

    def test_configure_logging_redacts_actual_handler_and_reconfiguration(self) -> None:
        first_token = "123456:FIRST_TEST_TOKEN"
        second_token = "123456:SECOND_TEST_TOKEN"

        configure_logging((first_token,))
        configure_logging((second_token,))
        logging.getLogger("mtla_bot.test").error(
            "request URLs: %s %s",
            f"https://api.telegram.org/bot{first_token}/getMe",
            f"https://api.telegram.org/bot{second_token}/getMe",
        )

        output = self.output.getvalue()
        self.assertNotIn(first_token, output)
        self.assertNotIn(second_token, output)
        self.assertEqual(output.count(REDACTED_VALUE), 2)

    def test_configure_logging_redacts_traceback_and_quiets_http_clients(self) -> None:
        token = "123456:TRACEBACK_TEST_TOKEN"
        configure_logging((token,))

        try:
            raise RuntimeError(f"request failed for {token}")
        except RuntimeError:
            logging.getLogger("mtla_bot.test").exception("Unexpected error")

        output = self.output.getvalue()
        self.assertNotIn(token, output)
        self.assertIn(REDACTED_VALUE, output)
        self.assertEqual(logging.getLogger("httpx").getEffectiveLevel(), logging.WARNING)
        self.assertEqual(logging.getLogger("httpcore").getEffectiveLevel(), logging.WARNING)


class SecretSourcePriorityTest(unittest.TestCase):
    @patch.dict(os.environ, {"TELEGRAM_TOKEN": "environment-test-token"})
    @patch("mtla_bot.config.os.path.exists", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data="file-test-token\n")
    def test_docker_secret_file_wins_over_environment(
        self,
        mocked_open,
        mocked_exists,
    ) -> None:
        value = config.get_secret("TELEGRAM_TOKEN")

        self.assertEqual(value, "file-test-token")
        mocked_exists.assert_called_once_with(
            "/run/secrets/MTLA_JOIN_BOT_TELEGRAM_TOKEN"
        )
        mocked_open.assert_called_once_with(
            "/run/secrets/MTLA_JOIN_BOT_TELEGRAM_TOKEN",
            "r",
        )


class DockerSecretHandlingTest(unittest.TestCase):
    def run_management_command(
        self,
        command: str,
        **fake_settings: str,
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        """Run the management script against a deterministic fake Docker CLI."""

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_bin = temp_path / "bin"
            fake_bin.mkdir()
            fake_docker = fake_bin / "docker"
            fake_log = temp_path / "docker.log"
            env_file = temp_path / "runtime.env"
            env_file.write_text("TELEGRAM_TOKEN=123456:FAKE_TEST_TOKEN\n")
            fake_docker.write_text(
                """#!/bin/bash
set -u

command_line="$*"
printf '%s\n' "$command_line" >> "$FAKE_DOCKER_LOG"

case "$command_line" in
    "image inspect mtla-join-bot:local")
        exit "${FAKE_IMAGE_INSPECT_STATUS:-0}"
        ;;
    "image inspect mtla-join-bot:previous")
        exit "${FAKE_PREVIOUS_INSPECT_STATUS:-1}"
        ;;
    "volume inspect mtla_join_bot_data")
        exit "${FAKE_VOLUME_INSPECT_STATUS:-0}"
        ;;
    "container inspect mtla-join-bot")
        exit "${FAKE_LEGACY_INSPECT_STATUS:-1}"
        ;;
    "compose -f compose.yaml up -d --no-build --force-recreate --wait --wait-timeout 90")
        exit "${FAKE_COMPOSE_UP_STATUS:-0}"
        ;;
    "compose -f compose.yaml ps -q bot")
        if [ "${FAKE_COMPOSE_PS_STATUS:-0}" -eq 0 ]; then
            printf '%s\n' "fake-bot-id"
        fi
        exit "${FAKE_COMPOSE_PS_STATUS:-0}"
        ;;
    "inspect -f {{.State.Status}} {{.State.Health.Status}} {{.RestartCount}} fake-bot-id")
        if [ "${FAKE_BOT_INSPECT_STATUS:-0}" -eq 0 ]; then
            printf '%s\n' "${FAKE_BOT_STATE:-running healthy 0}"
        fi
        exit "${FAKE_BOT_INSPECT_STATUS:-0}"
        ;;
    *)
        exit 0
        ;;
esac
"""
            )
            fake_docker.chmod(0o755)

            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
                    "FAKE_DOCKER_LOG": str(fake_log),
                    "MTLA_JOIN_BOT_ENV_FILE": str(env_file),
                    "MTLA_JOIN_BOT_TELEGRAM_TOKEN_FILE": "",
                }
            )
            environment.update(fake_settings)
            result = subprocess.run(
                ["bash", str(PROJECT_ROOT / "docker-simple.sh"), command],
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            docker_calls = fake_log.read_text().splitlines() if fake_log.exists() else []

        return result, docker_calls

    def test_local_environment_files_are_excluded_from_build_context(self) -> None:
        patterns = {
            line.strip()
            for line in (PROJECT_ROOT / ".dockerignore").read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        self.assertIn(".env", patterns)
        self.assertIn(".env.*", patterns)
        self.assertIn("*.env", patterns)

    def test_named_environment_files_are_ignored_by_git(self) -> None:
        patterns = {
            line.strip()
            for line in (PROJECT_ROOT / ".gitignore").read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        self.assertIn(".env", patterns)
        self.assertIn(".env.*", patterns)
        self.assertIn("*.env", patterns)

    def test_run_injects_environment_file_at_runtime(self) -> None:
        script = (PROJECT_ROOT / "docker-simple.sh").read_text()
        compose = (PROJECT_ROOT / "compose.yaml").read_text()

        self.assertIn('ENV_FILE="${MTLA_JOIN_BOT_ENV_FILE:-.env}"', script)
        self.assertIn('MTLA_JOIN_BOT_ENV_FILE="$ENV_FILE"', script)
        self.assertIn("${MTLA_JOIN_BOT_ENV_FILE:-.env}", compose)
        self.assertIn('if [ ! -f "$ENV_FILE" ]', script)

    def test_run_supports_read_only_telegram_token_file(self) -> None:
        script = (PROJECT_ROOT / "docker-simple.sh").read_text()
        dockerfile = (PROJECT_ROOT / "Dockerfile").read_text()
        secret_compose = (PROJECT_ROOT / "compose.secret.yaml").read_text()

        self.assertIn("MTLA_JOIN_BOT_TELEGRAM_TOKEN_FILE", script)
        self.assertIn("telegram_token", secret_compose)
        self.assertIn("target: MTLA_JOIN_BOT_TELEGRAM_TOKEN", secret_compose)
        self.assertIn("${MTLA_JOIN_BOT_TELEGRAM_TOKEN_FILE}", secret_compose)
        self.assertIn("TELEGRAM_TOKEN([[:space:]]*=|[[:space:]]*$)", script)
        self.assertIn("Удалите TELEGRAM_TOKEN", script)
        self.assertIn("/run/secrets", dockerfile)

    def test_file_secret_mode_rejects_host_environment_passthrough(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            env_file = temp_path / "runtime.env"
            token_file = temp_path / "telegram-token"
            env_file.write_text("TELEGRAM_TOKEN\n")
            token_file.write_text("dummy-test-token\n")

            environment = os.environ.copy()
            environment.update(
                {
                    "MTLA_JOIN_BOT_ENV_FILE": str(env_file),
                    "MTLA_JOIN_BOT_TELEGRAM_TOKEN_FILE": str(token_file),
                    "TELEGRAM_TOKEN": "host-test-token",
                }
            )
            result = subprocess.run(
                ["bash", str(PROJECT_ROOT / "docker-simple.sh"), "run"],
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Удалите TELEGRAM_TOKEN", result.stdout)
        self.assertNotIn("host-test-token", result.stdout + result.stderr)

    def test_run_fails_closed_when_external_volume_is_missing(self) -> None:
        result, docker_calls = self.run_management_command(
            "run",
            FAKE_VOLUME_INSPECT_STATUS="1",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MongoDB volume не найден", result.stdout)
        self.assertIn("bootstrap", result.stdout)
        self.assertNotIn("volume create mtla_join_bot_data", docker_calls)
        self.assertFalse(any(" compose " in f" {call} " for call in docker_calls))

    def test_bootstrap_explicitly_creates_missing_empty_volume(self) -> None:
        result, docker_calls = self.run_management_command(
            "bootstrap",
            FAKE_VOLUME_INSPECT_STATUS="1",
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("volume create mtla_join_bot_data", docker_calls)
        self.assertIn("Пустой volume создан", result.stdout)

    def test_build_does_not_replace_last_known_good_rollback_tag(self) -> None:
        result, docker_calls = self.run_management_command("build")

        self.assertEqual(result.returncode, 0)
        self.assertIn("build -t mtla-join-bot:local .", docker_calls)
        self.assertFalse(any(call.startswith("tag ") for call in docker_calls))

    def test_successful_run_refreshes_rollback_tag_after_healthcheck(self) -> None:
        result, docker_calls = self.run_management_command("run")

        self.assertEqual(result.returncode, 0)
        inspect_call = (
            "inspect -f {{.State.Status}} {{.State.Health.Status}} "
            "{{.RestartCount}} fake-bot-id"
        )
        tag_call = "tag mtla-join-bot:local mtla-join-bot:previous"
        self.assertIn(inspect_call, docker_calls)
        self.assertIn(tag_call, docker_calls)
        self.assertLess(docker_calls.index(inspect_call), docker_calls.index(tag_call))

    def test_post_deploy_cli_failures_enter_rollback(self) -> None:
        scenarios = (
            {"FAKE_COMPOSE_PS_STATUS": "17"},
            {"FAKE_BOT_INSPECT_STATUS": "18"},
        )

        for settings in scenarios:
            with self.subTest(settings=settings):
                result, docker_calls = self.run_management_command("run", **settings)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("compose -f compose.yaml down", docker_calls)
                self.assertNotIn(
                    "tag mtla-join-bot:local mtla-join-bot:previous",
                    docker_calls,
                )

    def test_restart_preserves_legacy_container_until_new_stack_is_healthy(self) -> None:
        result, docker_calls = self.run_management_command(
            "restart",
            FAKE_LEGACY_INSPECT_STATUS="0",
        )

        self.assertEqual(result.returncode, 0)
        stop_index = docker_calls.index("stop mtla-join-bot")
        health_index = docker_calls.index(
            "inspect -f {{.State.Status}} {{.State.Health.Status}} "
            "{{.RestartCount}} fake-bot-id"
        )
        remove_index = docker_calls.index("rm mtla-join-bot")
        self.assertLess(stop_index, health_index)
        self.assertLess(health_index, remove_index)
        self.assertNotIn("compose -f compose.yaml down", docker_calls)


if __name__ == "__main__":
    unittest.main()
