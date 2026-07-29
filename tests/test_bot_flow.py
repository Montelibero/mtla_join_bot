import asyncio
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import ANY, AsyncMock, Mock

from mtla_bot.bot import MTLAJoinBot, encode_flow_callback
from mtla_bot.messages import get_message
from mtla_bot.user_states import UserState


ADDRESS = "GBACH65OTKJL5VZCYCI4F4FTTODPEORFQQZVNF4PUK7X4AMGFXNP2KZZ"


def user(**overrides):
    values = {
        "user_id": 42,
        "username": None,
        "attempt_id": "attempt-current",
        "language": "ru",
        "state": UserState.CHECKING_ADDRESS.value,
        "stellar_address": ADDRESS,
        "has_username": False,
        "username_warning_acknowledged": True,
        "agreed_to_terms": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def account_snapshot(**overrides):
    values = {
        "exists": True,
        "has_trustline": True,
        "mtlap_balance": "0",
        "recommendation": {
            "has_recommendation": True,
            "has_any_recommendation": True,
        },
    }
    values.update(overrides)
    return values


def update_for(*, telegram_user=None, text=None, callback_query=None):
    telegram_user = telegram_user or SimpleNamespace(id=42, username=None)
    message = (
        callback_query.message
        if callback_query is not None
        else SimpleNamespace(text=text, reply_text=AsyncMock())
    )
    if not hasattr(message, "text"):
        message.text = text
    return SimpleNamespace(
        effective_user=telegram_user,
        effective_message=message,
        message=message,
        callback_query=callback_query,
    )


class BotFlowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.bot = MTLAJoinBot.__new__(MTLAJoinBot)
        self.bot.state_manager = Mock()
        self.bot.state_manager.record_eligibility_snapshot.return_value = True
        self.bot.state_manager.complete_attempt.return_value = True
        self.bot.state_manager.claim_final_delivery.return_value = True
        self.bot.state_manager.defer_final_delivery.return_value = True
        self.bot.state_manager.update_attempt_fields.return_value = True
        self.bot.state_manager.transition_attempt.return_value = True
        self.bot.state_manager.update_language.return_value = True
        self.bot.stellar_client = SimpleNamespace(get_account_info=AsyncMock())
        self.bot._user_locks = {}
        self.bot._active_user_tasks = {}
        self.context = SimpleNamespace()

    async def test_busy_user_is_rejected_without_blocking_another_user(self) -> None:
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        events = []

        async def handler(update, _context):
            marker = update.effective_user.username
            events.append(f"start:{marker}")
            if marker == "first-a":
                first_started.set()
                await release_first.wait()
            events.append(f"end:{marker}")

        wrapped = self.bot._serialized(handler)
        first_a = update_for(
            telegram_user=SimpleNamespace(id=42, username="first-a")
        )
        second_a = update_for(
            telegram_user=SimpleNamespace(id=42, username="second-a")
        )
        user_b = update_for(
            telegram_user=SimpleNamespace(id=43, username="user-b")
        )

        task_a1 = asyncio.create_task(wrapped(first_a, self.context))
        await first_started.wait()
        task_a2 = asyncio.create_task(wrapped(second_a, self.context))
        task_b = asyncio.create_task(wrapped(user_b, self.context))
        await task_b

        self.assertIn("end:user-b", events)
        self.assertNotIn("start:second-a", events)

        release_first.set()
        await asyncio.gather(task_a1, task_a2)
        self.assertNotIn("start:second-a", events)
        second_a.effective_message.reply_text.assert_awaited_once_with(
            get_message("en", "request_in_progress")
        )

    async def test_start_wrapper_cancels_active_user_work(self) -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()
        reset_ran = asyncio.Event()

        async def slow_handler(_update, _context):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        async def reset_handler(_update, _context):
            reset_ran.set()

        update = update_for()
        active = asyncio.create_task(
            self.bot._serialized(slow_handler)(update, self.context)
        )
        await started.wait()

        await self.bot._reset_serialized(reset_handler)(update, self.context)

        self.assertTrue(active.cancelled())
        self.assertTrue(cancelled.is_set())
        self.assertTrue(reset_ran.is_set())

    async def test_state_calls_do_not_block_the_event_loop(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def blocking_get_user(_user_id):
            started.set()
            release.wait(timeout=1)
            return "done"

        self.bot.state_manager.get_user.side_effect = blocking_get_user
        call = asyncio.create_task(self.bot._state_call("get_user", 42))
        while not started.is_set():
            await asyncio.sleep(0)

        # Reaching this line while the database stand-in is blocked proves the
        # synchronous call is running outside the event-loop thread.
        release.set()
        self.assertEqual(await call, "done")

    async def test_cancelled_state_call_waits_for_mongo_thread_to_finish(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def blocking_update(*_args):
            started.set()
            release.wait(timeout=1)
            return True

        self.bot.state_manager.begin_new_attempt.side_effect = blocking_update
        call = asyncio.create_task(
            self.bot._state_call(
                "begin_new_attempt",
                42,
                None,
                "ru",
                "attempt-old",
            )
        )
        while not started.is_set():
            await asyncio.sleep(0)

        call.cancel()
        await asyncio.sleep(0)
        self.assertFalse(call.done())

        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await call

    async def test_no_username_prompt_offers_explicit_continue(self) -> None:
        candidate = user(state=UserState.CHECKING_USERNAME.value)
        self.bot.state_manager.get_user.return_value = candidate
        update = update_for()

        await self.bot.check_username_step(update, self.context)

        reply_markup = update.effective_message.reply_text.await_args.kwargs[
            "reply_markup"
        ]
        callback_data = [
            row[0].callback_data for row in reply_markup.inline_keyboard
        ]
        self.assertEqual(
            callback_data,
            [
                encode_flow_callback("username_installed", "attempt-current"),
                encode_flow_callback(
                    "continue_without_username",
                    "attempt-current",
                ),
            ],
        )
        self.bot.state_manager.update_attempt_fields.assert_called_once_with(
            42,
            "attempt-current",
            UserState.CHECKING_USERNAME.value,
            {
                "username": None,
                "has_username": False,
                "progress.username_check": False,
            },
        )

    async def test_start_stores_missing_username_as_null(self) -> None:
        telegram_user = SimpleNamespace(
            id=42,
            username=None,
            language_code="ru",
        )
        update = update_for(telegram_user=telegram_user)
        self.bot.state_manager.get_user.side_effect = [None, user()]
        self.bot.state_manager.create_user.return_value = True
        self.bot.check_username_step = AsyncMock()

        await self.bot.start(update, self.context)

        self.bot.state_manager.create_user.assert_called_once_with(
            42,
            None,
            "ru",
            ANY,
        )
        self.assertTrue(self.bot.state_manager.create_user.call_args.args[3])
        self.bot.check_username_step.assert_awaited_once_with(
            update,
            self.context,
            expected_attempt_id=self.bot.state_manager.create_user.call_args.args[3],
        )

    async def test_start_resets_existing_process(self) -> None:
        telegram_user = SimpleNamespace(
            id=42,
            username=None,
            language_code="en",
        )
        update = update_for(telegram_user=telegram_user)
        self.bot.state_manager.get_user.return_value = user(state="completed")
        self.bot.check_username_step = AsyncMock()

        await self.bot.start(update, self.context)

        self.bot.state_manager.begin_new_attempt.assert_called_once_with(
            42,
            None,
            "en",
            ANY,
        )
        self.assertNotEqual(
            self.bot.state_manager.begin_new_attempt.call_args.args[3],
            "attempt-current",
        )
        self.bot.check_username_step.assert_awaited_once_with(
            update,
            self.context,
            expected_attempt_id=(
                self.bot.state_manager.begin_new_attempt.call_args.args[3]
            ),
        )

    async def test_start_stops_if_new_attempt_cannot_be_persisted(self) -> None:
        telegram_user = SimpleNamespace(
            id=42,
            username=None,
            language_code="ru",
        )
        update = update_for(telegram_user=telegram_user)
        self.bot.state_manager.get_user.return_value = user(state="completed")
        self.bot.state_manager.begin_new_attempt.return_value = False
        self.bot.check_username_step = AsyncMock()

        await self.bot.start(update, self.context)

        self.bot.check_username_step.assert_not_awaited()
        update.message.reply_text.assert_awaited_once_with(
            get_message("ru", "temporary_error")
        )

    async def test_unhandled_handler_error_gets_visible_safe_response(self) -> None:
        telegram_user = SimpleNamespace(
            id=42,
            username=None,
            language_code="en",
        )
        update = update_for(telegram_user=telegram_user)
        context = SimpleNamespace(error=RuntimeError("database down"))

        await self.bot.handle_error(update, context)

        update.effective_message.reply_text.assert_awaited_once_with(
            get_message("en", "temporary_error")
        )

    async def test_continue_without_username_advances_to_agreement(self) -> None:
        query = SimpleNamespace(
            data=encode_flow_callback(
                "continue_without_username",
                "attempt-current",
            ),
            from_user=SimpleNamespace(id=42),
            answer=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        update = update_for(callback_query=query)
        self.bot.state_manager.get_user.return_value = user(
            state=UserState.CHECKING_USERNAME.value,
        )
        self.bot.agreement_step = AsyncMock()

        await self.bot.handle_callback(update, self.context)

        self.bot.agreement_step.assert_awaited_once_with(
            update,
            self.context,
            expected_attempt_id="attempt-current",
            acknowledge_without_username=True,
        )

    async def test_continue_stops_when_warning_ack_cannot_be_persisted(self) -> None:
        query = SimpleNamespace(
            data=encode_flow_callback(
                "continue_without_username",
                "attempt-current",
            ),
            from_user=SimpleNamespace(id=42),
            answer=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        update = update_for(callback_query=query)
        self.bot.state_manager.get_user.return_value = user(
            state=UserState.CHECKING_USERNAME.value,
        )
        self.bot.state_manager.transition_attempt.return_value = False

        await self.bot.handle_callback(update, self.context)

        self.bot.state_manager.transition_attempt.assert_called_once()
        query.message.reply_text.assert_awaited_once_with(
            get_message("ru", "temporary_error")
        )

    async def test_stale_callback_cannot_reopen_process(self) -> None:
        query = SimpleNamespace(
            data=encode_flow_callback(
                "continue_without_username",
                "attempt-old",
            ),
            from_user=SimpleNamespace(id=42),
            answer=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        update = update_for(callback_query=query)
        self.bot.state_manager.get_user.return_value = user(
            state=UserState.COMPLETED.value,
        )
        self.bot.agreement_step = AsyncMock()

        await self.bot.handle_callback(update, self.context)

        self.bot.state_manager.transition_attempt.assert_not_called()
        self.bot.agreement_step.assert_not_awaited()
        query.message.reply_text.assert_awaited_once_with(
            get_message("ru", "action_outdated")
        )

    async def test_legacy_callback_without_attempt_id_is_rejected(self) -> None:
        query = SimpleNamespace(
            data="continue_without_username",
            from_user=SimpleNamespace(id=42),
            answer=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        update = update_for(callback_query=query)
        self.bot.state_manager.get_user.return_value = user(
            state=UserState.CHECKING_USERNAME.value,
        )
        self.bot.agreement_step = AsyncMock()

        await self.bot.handle_callback(update, self.context)

        self.bot.state_manager.transition_attempt.assert_not_called()
        self.bot.agreement_step.assert_not_awaited()
        query.message.reply_text.assert_awaited_once_with(
            get_message("ru", "action_outdated")
        )

    async def test_current_attempt_callback_is_rejected_in_wrong_phase(self) -> None:
        query = SimpleNamespace(
            data=encode_flow_callback(
                "continue_without_username",
                "attempt-current",
            ),
            from_user=SimpleNamespace(id=42),
            answer=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        update = update_for(callback_query=query)
        self.bot.state_manager.get_user.return_value = user(
            state=UserState.COMPLETED.value,
        )
        self.bot.agreement_step = AsyncMock()

        await self.bot.handle_callback(update, self.context)

        self.bot.state_manager.transition_attempt.assert_not_called()
        self.bot.agreement_step.assert_not_awaited()

    async def test_language_change_redraws_agreement_keyboard(self) -> None:
        query = SimpleNamespace(
            data="lang_en",
            from_user=SimpleNamespace(id=42),
            answer=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
            edit_message_text=AsyncMock(),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        update = update_for(callback_query=query)
        self.bot.state_manager.get_user.side_effect = [
            user(state=UserState.AGREEMENT.value, language="ru"),
            user(state=UserState.AGREEMENT.value, language="en"),
        ]

        await self.bot.handle_callback(update, self.context)

        prompt_call = query.message.reply_text.await_args
        keyboard = prompt_call.kwargs["reply_markup"].keyboard
        self.assertEqual(keyboard[0][0].text, get_message("en", "agree"))
        self.assertEqual(keyboard[1][0].text, get_message("en", "disagree"))

    async def test_username_is_not_an_eligibility_blocker(self) -> None:
        self.bot.state_manager.get_user.return_value = user(has_username=False)
        self.bot.completion_step = AsyncMock()
        self.bot.show_issues = AsyncMock()
        update = update_for()
        snapshot = account_snapshot()

        await self.bot.check_address_step(
            update,
            self.context,
            account_info=snapshot,
        )

        self.bot.completion_step.assert_awaited_once_with(
            update,
            self.context,
            address=ADDRESS,
            attempt_id="attempt-current",
        )
        self.bot.show_issues.assert_not_awaited()

    async def test_repeat_check_cannot_bypass_already_member_guard(self) -> None:
        self.bot.state_manager.get_user.return_value = user()
        self.bot.completion_step = AsyncMock()
        self.bot.show_issues = AsyncMock()
        update = update_for(text=get_message("ru", "repeat_check"))
        self.bot.stellar_client.get_account_info.return_value = account_snapshot(
            mtlap_balance="0.0000001"
        )

        await self.bot.handle_address_input(update, self.context)

        self.bot.completion_step.assert_not_awaited()
        self.bot.show_issues.assert_not_awaited()
        sent_texts = [
            call.args[0] for call in update.message.reply_text.await_args_list
        ]
        self.assertIn(get_message("ru", "address_already_member"), sent_texts)
        self.bot.state_manager.update_state.assert_not_called()

    async def test_repeat_check_does_not_reopen_completed_process(self) -> None:
        self.bot.state_manager.get_user.return_value = user(
            state=UserState.COMPLETED.value,
        )
        self.bot.check_address_step = AsyncMock()
        update = update_for(text=get_message("ru", "repeat_check"))

        await self.bot.handle_address_input(update, self.context)

        self.bot.check_address_step.assert_not_awaited()
        update.message.reply_text.assert_awaited_once_with(
            get_message("ru", "process_already_finished")
        )

    async def test_repeat_in_finalizing_redelivers_without_external_lookup(self) -> None:
        self.bot.state_manager.get_user.return_value = user(
            state=UserState.FINALIZING.value,
        )
        self.bot.completion_step = AsyncMock()
        update = update_for(text=get_message("ru", "repeat_check"))

        await self.bot.handle_address_input(update, self.context)

        self.bot.completion_step.assert_awaited_once_with(
            update,
            self.context,
            address=ADDRESS,
            attempt_id="attempt-current",
        )
        self.bot.stellar_client.get_account_info.assert_not_awaited()

    async def test_unexpected_text_never_disappears_silently(self) -> None:
        self.bot.state_manager.get_user.return_value = user(
            state=UserState.CHECKING_USERNAME.value,
        )
        update = update_for(text="hello")

        await self.bot.handle_address_input(update, self.context)

        update.message.reply_text.assert_awaited_once_with(
            get_message("ru", "action_outdated")
        )

    async def test_one_address_input_uses_one_external_snapshot(self) -> None:
        self.bot.state_manager.get_user.return_value = user(
            state=UserState.ENTERING_ADDRESS.value,
            stellar_address=None,
        )
        update = update_for(text=ADDRESS)
        snapshot = account_snapshot()
        self.bot.stellar_client.get_account_info.return_value = snapshot
        self.bot.check_address_step = AsyncMock()

        await self.bot.handle_address_input(update, self.context)

        self.bot.stellar_client.get_account_info.assert_awaited_once_with(ADDRESS)
        self.bot.check_address_step.assert_awaited_once_with(
            update,
            self.context,
            address=ADDRESS,
            account_info=snapshot,
            attempt_id="attempt-current",
            expected_state=UserState.ENTERING_ADDRESS.value,
        )

    async def test_checksum_invalid_address_is_rejected_before_horizon(self) -> None:
        self.bot.state_manager.get_user.return_value = user(
            state=UserState.ENTERING_ADDRESS.value,
            stellar_address=None,
        )
        update = update_for(text="G" + "A" * 55)

        await self.bot.handle_address_input(update, self.context)

        self.bot.stellar_client.get_account_info.assert_not_awaited()
        update.message.reply_text.assert_awaited_once_with(
            get_message("ru", "invalid_address")
        )

    async def test_unknown_agreement_reply_uses_candidate_language(self) -> None:
        self.bot.state_manager.get_user.return_value = user(
            state=UserState.AGREEMENT.value,
            language="en",
        )
        update = update_for(text="something else")

        await self.bot.handle_address_input(update, self.context)

        update.message.reply_text.assert_awaited_once_with(
            get_message("en", "choose_one_option")
        )

    async def test_issue_links_use_candidate_language(self) -> None:
        self.bot.state_manager.get_user.return_value = user(language="en")
        update = update_for()

        await self.bot.show_issues(
            update,
            self.context,
            account_snapshot(
                has_trustline=False,
                recommendation={
                    "has_recommendation": False,
                    "has_any_recommendation": False,
                },
            ),
        )

        texts = [call.args[0] for call in update.effective_message.reply_text.await_args_list]
        self.assertTrue(any("Open trustline:" in text for text in texts))
        self.assertTrue(any("Agora chat:" in text for text in texts))

    async def test_temporary_error_does_not_overwrite_business_facts(self) -> None:
        self.bot.state_manager.get_user.return_value = user()
        update = update_for()

        await self.bot.check_address_step(
            update,
            self.context,
            account_info=account_snapshot(
                exists=False,
                has_trustline=False,
                error="horizon_unavailable",
            ),
        )

        self.bot.state_manager.record_eligibility_snapshot.assert_not_called()
        update.effective_message.reply_text.assert_awaited_once_with(
            get_message("ru", "temporary_error")
        )

    async def test_bsn_error_does_not_accept_new_address_or_advance_state(self) -> None:
        self.bot.state_manager.get_user.return_value = user(stellar_address=None)
        update = update_for()

        await self.bot.check_address_step(
            update,
            self.context,
            address=ADDRESS,
            account_info=account_snapshot(
                recommendation={
                    "has_recommendation": False,
                    "error": "bsn_unavailable",
                }
            ),
        )

        self.bot.state_manager.set_stellar_address.assert_not_called()
        self.bot.state_manager.update_state.assert_not_called()
        self.bot.state_manager.record_eligibility_snapshot.assert_not_called()

    async def test_old_attempt_snapshot_cannot_be_bound_to_new_attempt(self) -> None:
        self.bot.state_manager.get_user.return_value = user(
            attempt_id="attempt-new",
            state=UserState.ENTERING_ADDRESS.value,
            stellar_address=None,
        )
        update = update_for()

        await self.bot.check_address_step(
            update,
            self.context,
            address=ADDRESS,
            account_info=account_snapshot(),
            attempt_id="attempt-old",
            expected_state=UserState.ENTERING_ADDRESS.value,
        )

        self.bot.state_manager.record_eligibility_snapshot.assert_not_called()
        update.effective_message.reply_text.assert_awaited_once_with(
            get_message("ru", "action_outdated")
        )

    async def test_eligible_snapshot_must_be_persisted_before_final_message(self) -> None:
        self.bot.state_manager.get_user.return_value = user()
        self.bot.state_manager.record_eligibility_snapshot.return_value = False
        self.bot.completion_step = AsyncMock()
        update = update_for()

        await self.bot.check_address_step(
            update,
            self.context,
            account_info=account_snapshot(),
        )

        self.bot.completion_step.assert_not_awaited()
        update.effective_message.reply_text.assert_awaited_once_with(
            get_message("ru", "temporary_error")
        )

    async def test_final_message_is_delivered_before_terminal_state(self) -> None:
        events = []
        self.bot.state_manager.get_user.return_value = user(
            state=UserState.FINALIZING.value,
        )

        def record_state(*_args):
            events.append("state")
            return True

        self.bot.state_manager.complete_attempt.side_effect = record_state
        update = update_for()

        async def record_delivery(*_args, **_kwargs):
            events.append("delivery")
            return SimpleNamespace(message_id=777)

        update.effective_message.reply_text.side_effect = record_delivery

        await self.bot.completion_step(
            update,
            self.context,
            address=ADDRESS,
        )

        self.assertEqual(events, ["delivery", "state"])
        self.bot.state_manager.claim_final_delivery.assert_called_once_with(
            42,
            "attempt-current",
            ANY,
            lease_seconds=300,
            automatic=False,
            max_attempts=3,
        )
        self.bot.state_manager.complete_attempt.assert_called_once_with(
            42,
            "attempt-current",
            ANY,
            777,
        )

    async def test_final_delivery_failure_does_not_set_terminal_state(self) -> None:
        self.bot.state_manager.get_user.return_value = user(
            state=UserState.FINALIZING.value,
        )
        update = update_for()
        update.effective_message.reply_text.side_effect = [
            RuntimeError("telegram unavailable"),
            None,
        ]

        await self.bot.completion_step(
            update,
            self.context,
            address=ADDRESS,
        )

        self.bot.state_manager.complete_attempt.assert_not_called()
        self.bot.state_manager.defer_final_delivery.assert_called_once()
        self.assertEqual(update.effective_message.reply_text.await_count, 2)

    async def test_unavailable_final_delivery_claim_does_not_promise_retry(self) -> None:
        self.bot.state_manager.get_user.return_value = user(
            state=UserState.FINALIZING.value,
        )
        self.bot.state_manager.claim_final_delivery.return_value = False
        update = update_for()

        await self.bot.completion_step(
            update,
            self.context,
            address=ADDRESS,
        )

        update.effective_message.reply_text.assert_awaited_once()
        pending_call = update.effective_message.reply_text.await_args
        self.assertEqual(
            pending_call.args[0],
            get_message("ru", "final_delivery_pending"),
        )
        self.assertIn("reply_markup", pending_call.kwargs)
        self.bot.state_manager.complete_attempt.assert_not_called()

    async def test_finalizing_free_text_explains_delivery_without_resetting(self) -> None:
        self.bot.state_manager.get_user.return_value = user(
            state=UserState.FINALIZING.value,
        )
        self.bot.completion_step = AsyncMock()
        update = update_for(text="Что происходит?")

        await self.bot.handle_address_input(update, self.context)

        update.message.reply_text.assert_awaited_once()
        self.assertEqual(
            update.message.reply_text.await_args.args[0],
            get_message("ru", "final_delivery_pending"),
        )
        self.bot.completion_step.assert_not_awaited()

    async def test_terminal_state_write_failure_keeps_durable_finalizing(self) -> None:
        self.bot.state_manager.get_user.return_value = user(
            state=UserState.FINALIZING.value,
        )
        self.bot.state_manager.complete_attempt.return_value = False
        update = update_for()

        await self.bot.completion_step(
            update,
            self.context,
            address=ADDRESS,
        )

        update.effective_message.reply_text.assert_awaited_once()

    async def test_background_worker_redelivers_finalizing_attempt(self) -> None:
        pending = user(state=UserState.FINALIZING.value)
        self.bot.state_manager.get_finalizing_users.return_value = [pending]
        self.bot.state_manager.get_user.return_value = pending
        application = SimpleNamespace(
            bot=SimpleNamespace(
                send_message=AsyncMock(
                    return_value=SimpleNamespace(message_id=888)
                )
            )
        )

        await self.bot._redeliver_finalizations_once(application)

        application.bot.send_message.assert_awaited_once()
        self.bot.state_manager.claim_final_delivery.assert_called_once_with(
            42,
            "attempt-current",
            ANY,
            lease_seconds=300,
            automatic=True,
            max_attempts=3,
        )
        self.bot.state_manager.complete_attempt.assert_called_once_with(
            42,
            "attempt-current",
            ANY,
            888,
        )


if __name__ == "__main__":
    unittest.main()
