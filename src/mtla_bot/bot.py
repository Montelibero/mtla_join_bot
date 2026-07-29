import asyncio
import logging
import re
import uuid
from decimal import Decimal
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode

from . import config
from . import messages
from .stellar_client import StellarClient
from .user_states import UserStateManager, UserState
from .admin_tools import AdminTools
from .admin_config import ADMIN_IDS
from .eligibility import (
    EligibilityBlocker,
    EligibilityStatus,
    evaluate_eligibility,
    is_valid_stellar_address,
)
from .logging_config import configure_logging

# Настройка логирования
configure_logging((config.TELEGRAM_TOKEN, config.MONGODB_URI))
logger = logging.getLogger(__name__)

FLOW_CALLBACK_PREFIX = "flow"
FINALIZATION_POLL_SECONDS = 60
FINALIZATION_RETRY_SECONDS = 300
FINALIZATION_BATCH_SIZE = 20
FINALIZATION_MAX_ATTEMPTS = 3
FINALIZATION_LEASE_SECONDS = 300


def encode_flow_callback(action: str, attempt_id: str) -> str:
    return f"{FLOW_CALLBACK_PREFIX}:{action}:{attempt_id}"


def decode_flow_callback(data: str) -> tuple[str, str] | None:
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != FLOW_CALLBACK_PREFIX:
        return None
    _, action, attempt_id = parts
    if not action or not attempt_id:
        return None
    return action, attempt_id


def telegram_language(update: Update) -> str:
    """Choose a response language before a stored user is available."""

    return (
        "ru"
        if getattr(update.effective_user, "language_code", None) == "ru"
        else "en"
    )

class MTLAJoinBot:
    def __init__(self):
        config.validate_config()
        self.state_manager = UserStateManager()
        self.stellar_client = StellarClient()
        self.admin_tools = AdminTools(self.state_manager)
        self.application = None
        self._user_locks: dict[int, asyncio.Lock] = {}
        self._active_user_tasks: dict[int, asyncio.Task] = {}
        self._finalization_task: asyncio.Task | None = None

    @staticmethod
    async def _thread_call(method, *args, **kwargs):
        """Run sync work off-loop without abandoning its thread on cancel."""

        worker = asyncio.create_task(asyncio.to_thread(method, *args, **kwargs))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            # asyncio.to_thread cannot stop the underlying function. Waiting
            # here keeps resets ordered and prevents a canceled Mongo write
            # from committing after the replacement attempt.
            try:
                await worker
            except Exception:
                pass
            raise

    async def _state_call(self, method_name: str, *args, **kwargs):
        """Run synchronous PyMongo-backed state operations off the event loop."""

        method = getattr(self.state_manager, method_name)
        return await self._thread_call(method, *args, **kwargs)

    async def _admin_call(self, method_name: str, *args, **kwargs):
        """Run synchronous administrative MongoDB reports off the event loop."""

        method = getattr(self.admin_tools, method_name)
        return await self._thread_call(method, *args, **kwargs)

    async def _run_for_user(self, handler, update, context, lock):
        task = asyncio.current_task()
        user_id = update.effective_user.id
        async with lock:
            if task is not None:
                self._active_user_tasks[user_id] = task
            try:
                return await handler(update, context)
            finally:
                if self._active_user_tasks.get(user_id) is task:
                    self._active_user_tasks.pop(user_id, None)

    async def _reject_busy_update(self, update: Update) -> None:
        """Reject queued duplicate work before it occupies a PTB worker slot."""

        effective_user = update.effective_user
        language = (
            "ru"
            if getattr(effective_user, "language_code", None) == "ru"
            else "en"
        )
        text = get_message(language, "request_in_progress")
        if update.callback_query is not None:
            await update.callback_query.answer(text)
        elif update.effective_message is not None:
            await update.effective_message.reply_text(text)

    def _serialized(self, handler):
        """Allow concurrency across users while serializing one user's flow."""

        async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
            effective_user = update.effective_user
            if effective_user is None:
                return await handler(update, context)
            lock = self._user_locks.setdefault(
                effective_user.id,
                asyncio.Lock(),
            )
            if lock.locked():
                await self._reject_busy_update(update)
                return None
            return await self._run_for_user(handler, update, context, lock)

        return wrapped

    def _reset_serialized(self, handler):
        """Make /start cancel active work, then begin a fresh serialized attempt."""

        async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
            effective_user = update.effective_user
            if effective_user is None:
                return await handler(update, context)
            user_id = effective_user.id
            active = self._active_user_tasks.get(user_id)
            current = asyncio.current_task()
            if active is not None and active is not current and not active.done():
                active.cancel()
                await asyncio.gather(active, return_exceptions=True)
            lock = self._user_locks.setdefault(user_id, asyncio.Lock())
            return await self._run_for_user(handler, update, context, lock)

        return wrapped

    async def _post_init(self, application: Application) -> None:
        """Open reusable external-service resources in the running loop."""

        await self.stellar_client.start()
        self._finalization_task = asyncio.create_task(
            self._finalization_loop(application),
            name="mtla-finalization-redelivery",
        )

    async def _post_shutdown(self, _application: Application) -> None:
        """Close reusable external-service resources on every polling exit."""

        finalization_task = self._finalization_task
        self._finalization_task = None
        if finalization_task is not None:
            finalization_task.cancel()
            await asyncio.gather(finalization_task, return_exceptions=True)
        await self.stellar_client.close()

    def _build_completion_text(self, user, address: str | None = None) -> str:
        application_address = address or user.stellar_address
        application_text = get_message(
            user.language,
            "application_text",
        ).format(address=application_address)
        feedback_bot = config.LINKS[user.language]["feedback_bot"].replace(
            "_",
            "\\_",
        )
        return get_message(user.language, "all_checks_passed").format(
            application_text=application_text,
            feedback_bot=feedback_bot,
        )

    @staticmethod
    def _repeat_markup(language: str) -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            [[KeyboardButton(get_message(language, 'repeat_check'))]],
            one_time_keyboard=True,
            resize_keyboard=True,
        )

    async def _redeliver_finalizations_once(self, application: Application) -> None:
        users = await self._state_call(
            "get_finalizing_users",
            FINALIZATION_BATCH_SIZE,
            FINALIZATION_MAX_ATTEMPTS,
        )
        for pending in users:
            delivery = asyncio.create_task(
                self._redeliver_one_finalization(application, pending)
            )
            try:
                await delivery
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
                # /start canceled this user's delivery, not the worker loop.
                continue

    async def _redeliver_one_finalization(
        self,
        application: Application,
        pending,
    ) -> None:
        if not pending.attempt_id or not pending.stellar_address:
            return
        lock = self._user_locks.setdefault(pending.user_id, asyncio.Lock())
        if lock.locked():
            return
        task = asyncio.current_task()
        async with lock:
            if task is not None:
                self._active_user_tasks[pending.user_id] = task
            try:
                current = await self._state_call("get_user", pending.user_id)
                if (
                    current is None
                    or current.attempt_id != pending.attempt_id
                    or current.state != UserState.FINALIZING.value
                ):
                    return
                lease_id = uuid.uuid4().hex
                claimed = await self._state_call(
                    "claim_final_delivery",
                    current.user_id,
                    current.attempt_id,
                    lease_id,
                    lease_seconds=FINALIZATION_LEASE_SECONDS,
                    automatic=True,
                    max_attempts=FINALIZATION_MAX_ATTEMPTS,
                )
                if not claimed:
                    return
                try:
                    delivered = await application.bot.send_message(
                        chat_id=current.user_id,
                        text=self._build_completion_text(current),
                        parse_mode=ParseMode.MARKDOWN,
                        disable_web_page_preview=True,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Background final response delivery failed for user %s",
                        current.user_id,
                    )
                    await self._state_call(
                        "defer_final_delivery",
                        current.user_id,
                        current.attempt_id,
                        lease_id,
                        retry_seconds=FINALIZATION_RETRY_SECONDS,
                        error_code="telegram_send_failed",
                    )
                    return
                message_id = getattr(delivered, "message_id", None)
                if not isinstance(message_id, int):
                    message_id = None
                if not await self._state_call(
                    "complete_attempt",
                    current.user_id,
                    current.attempt_id,
                    lease_id,
                    message_id,
                ):
                    logger.error(
                        "Background final response was delivered but not persisted for user %s",
                        current.user_id,
                    )
            finally:
                if self._active_user_tasks.get(pending.user_id) is task:
                    self._active_user_tasks.pop(pending.user_id, None)

    async def _finalization_loop(self, application: Application) -> None:
        while True:
            try:
                await self._redeliver_finalizations_once(application)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Finalization redelivery pass failed")
            await asyncio.sleep(FINALIZATION_POLL_SECONDS)
        
    def is_admin(self, user_id: int) -> bool:
        """Проверяет, является ли пользователь администратором"""
        return user_id in ADMIN_IDS
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user_id = update.effective_user.id
        user = update.effective_user
        
        # Определяем язык пользователя
        language = telegram_language(update)
        attempt_id = uuid.uuid4().hex
        
        try:
            # Проверяем, есть ли пользователь в базе
            existing_user = await self._state_call("get_user", user_id)
            if not existing_user:
                # Создаем нового пользователя
                username = user.username
                if await self._state_call(
                    "create_user",
                    user_id,
                    username,
                    language,
                    attempt_id,
                ):
                    logger.info(f"Created new user: {user_id}")
                    # Проверяем, что пользователь действительно создался
                    existing_user = await self._state_call("get_user", user_id)
                    if not existing_user:
                        logger.error(f"User was not created properly: {user_id}")
                        await update.message.reply_text(
                            get_message(language, 'temporary_error')
                        )
                        return
                else:
                    logger.error(f"Failed to create user: {user_id}")
                    await update.message.reply_text(
                        get_message(language, 'temporary_error')
                    )
                    return
            else:
                username = user.username
                if not await self._state_call(
                    "begin_new_attempt",
                    user_id,
                    username,
                    language,
                    attempt_id,
                ):
                    logger.error("Failed to start a new attempt for user %s", user_id)
                    await update.message.reply_text(
                        get_message(language, 'temporary_error')
                    )
                    return
            
            # Отправляем приветственное сообщение
            await update.message.reply_text(get_message(language, 'welcome'))
            
            # Сразу начинаем проверку с первого шага.
            await self.check_username_step(
                update,
                context,
                expected_attempt_id=attempt_id,
            )
            
        except Exception:
            logger.exception("Error in start method")
            await update.message.reply_text(
                get_message(language, 'temporary_error')
            )

    async def handle_error(
        self,
        update: object,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Turn an unhandled handler failure into a visible retryable response."""

        error = getattr(context, "error", None)
        logger.error("Unhandled Telegram handler error", exc_info=error)

        effective_message = getattr(update, "effective_message", None)
        effective_user = getattr(update, "effective_user", None)
        if effective_message is None:
            return
        language = (
            "ru"
            if getattr(effective_user, "language_code", None) == "ru"
            else "en"
        )
        try:
            await effective_message.reply_text(
                get_message(language, 'temporary_error')
            )
        except Exception:
            logger.exception("Failed to deliver the handler error response")
    
    async def restart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Alias for starting a fresh attempt."""
        await self.start(update, context)
    
    async def language(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /language"""
        user_id = update.effective_user.id
        user = await self._state_call("get_user", user_id)
        
        if not user:
            await update.effective_message.reply_text(
                get_message(telegram_language(update), 'user_not_found')
            )
            return
        
        keyboard = [
            [InlineKeyboardButton("English", callback_data="lang_en")],
            [InlineKeyboardButton("Русский", callback_data="lang_ru")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = get_message(user.language, 'language_changed')
        await update.message.reply_text(text, reply_markup=reply_markup)
    
    # АДМИНИСТРАТИВНЫЕ КОМАНДЫ
    
    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /stats - показывает статистику (только для админов)"""
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await update.message.reply_text("❌ У вас нет доступа к этой команде")
            return
        
        try:
            stats_text = await self._admin_call("get_user_statistics")
            await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            await update.message.reply_text(f"❌ Ошибка при получении статистики: {e}")
    
    async def incomplete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /incomplete - показывает незавершенных пользователей (только для админов)"""
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await update.message.reply_text("❌ У вас нет доступа к этой команде")
            return
        
        try:
            incomplete_text = await self._admin_call(
                "get_incomplete_users_report"
            )
            # Разбиваем на части, если текст слишком длинный
            if len(incomplete_text) > 4000:
                parts = [incomplete_text[i:i+4000] for i in range(0, len(incomplete_text), 4000)]
                for i, part in enumerate(parts):
                    await update.message.reply_text(f"Часть {i+1}/{len(parts)}:\n\n{part}")
            else:
                await update.message.reply_text(incomplete_text)
        except Exception as e:
            logger.error(f"Error getting incomplete users: {e}")
            await update.message.reply_text(f"❌ Ошибка при получении отчета: {e}")
    
    async def reminders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /reminders - показывает кандидатов для напоминания (только для админов)"""
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await update.message.reply_text("❌ У вас нет доступа к этой команде")
            return
        
        try:
            # Получаем количество дней из аргументов команды
            days = 7
            if context.args:
                try:
                    days = int(context.args[0])
                except ValueError:
                    days = 7
            
            reminders_text = await self._admin_call(
                "get_reminder_candidates",
                days,
            )
            await update.message.reply_text(reminders_text)
        except Exception as e:
            logger.error(f"Error getting reminders: {e}")
            await update.message.reply_text(f"❌ Ошибка при получении списка: {e}")
    
    async def user_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /user_info <user_id> - показывает детали пользователя (только для админов)"""
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await update.message.reply_text("❌ У вас нет доступа к этой команде")
            return
        
        if not context.args:
            await update.message.reply_text("❌ Укажите ID пользователя: /user_info <user_id>")
            return
        
        try:
            target_user_id = int(context.args[0])
            user_details = await self._admin_call(
                "get_user_details",
                target_user_id,
            )
            await update.message.reply_text(user_details)
        except ValueError:
            await update.message.reply_text("❌ ID пользователя должен быть числом")
        except Exception as e:
            logger.error(f"Error getting user details: {e}")
            await update.message.reply_text(f"❌ Ошибка при получении деталей: {e}")
    
    async def help_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /help_admin - показывает справку по админским командам"""
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await update.message.reply_text("❌ У вас нет доступа к этой команде")
            return
        
        help_text = """
🔧 **Административные команды:**

📊 `/stats` - Статистика по пользователям
📋 `/incomplete` - Незавершенные пользователи  
🔔 `/reminders [дни]` - Кандидаты для напоминания (по умолчанию 7 дней)
👤 `/user_info <user_id>` - Детали конкретного пользователя
❓ `/help_admin` - Эта справка

**Примеры:**
- `/reminders 3` - пользователи неактивные более 3 дней
- `/user_info 123456789` - информация о пользователе с ID 123456789
        """
        
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    
    async def check_username_step(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        expected_attempt_id: str | None = None,
    ):
        """Первый шаг - проверка юзернейма"""
        user_id = update.effective_user.id
        user = await self._state_call("get_user", user_id)
        
        if not user:
            await update.message.reply_text(
                get_message(telegram_language(update), 'user_not_found')
            )
            return
        
        attempt_id = expected_attempt_id or user.attempt_id
        if (
            not attempt_id
            or user.attempt_id != attempt_id
            or user.state != UserState.CHECKING_USERNAME.value
        ):
            await update.effective_message.reply_text(
                get_message(user.language, 'action_outdated')
            )
            return

        # Проверяем наличие юзернейма и сохраняем результат только в той же
        # активной попытке и фазе.
        has_username = bool(update.effective_user.username)
        if not await self._state_call(
            "update_attempt_fields",
            user_id,
            attempt_id,
            UserState.CHECKING_USERNAME.value,
            {
                "username": update.effective_user.username,
                "has_username": has_username,
                "progress.username_check": has_username,
            },
        ):
            await update.effective_message.reply_text(
                get_message(user.language, 'temporary_error')
            )
            return
        
        if has_username:
            logger.info(f"User {user_id} has username, proceeding to agreement step")
            await self.agreement_step(
                update,
                context,
                expected_attempt_id=attempt_id,
            )
        else:
            keyboard = [
                [InlineKeyboardButton(
                    get_message(user.language, 'username_installed'),
                    callback_data=encode_flow_callback(
                        "username_installed",
                        attempt_id,
                    )
                )],
                [InlineKeyboardButton(
                    get_message(user.language, 'continue_without_username'),
                    callback_data=encode_flow_callback(
                        "continue_without_username",
                        attempt_id,
                    )
                )],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            text = get_message(user.language, 'no_username')
            await update.effective_message.reply_text(text, reply_markup=reply_markup)
    
    async def agreement_step(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        expected_attempt_id: str | None = None,
        acknowledge_without_username: bool = False,
    ):
        """Второй шаг - согласие с условиями"""
        user_id = update.effective_user.id
        user = await self._state_call("get_user", user_id)
        
        if not user:
            await update.effective_message.reply_text(
                get_message(telegram_language(update), 'user_not_found')
            )
            return
        
        attempt_id = expected_attempt_id or user.attempt_id
        update_data = (
            {"username_warning_acknowledged": True}
            if acknowledge_without_username
            else None
        )
        if (
            not attempt_id
            or user.attempt_id != attempt_id
            or user.state != UserState.CHECKING_USERNAME.value
        ):
            await update.effective_message.reply_text(
                get_message(user.language, 'action_outdated')
            )
            return
        if not await self._state_call(
            "transition_attempt",
                user_id,
                attempt_id,
                UserState.CHECKING_USERNAME.value,
                UserState.AGREEMENT.value,
                update_data,
        ):
            await update.effective_message.reply_text(
                get_message(user.language, 'temporary_error')
            )
            return
        logger.info(f"User {user_id} state updated to AGREEMENT")

        await self._send_agreement_prompt(update, user.language)

    async def _send_agreement_prompt(self, update: Update, language: str) -> None:
        keyboard = [
            [KeyboardButton(get_message(language, 'agree'))],
            [KeyboardButton(get_message(language, 'disagree'))]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        text = f"{get_message(language, 'agreement_text')}\n{config.LINKS[language]['agreement_link']}"
        await update.effective_message.reply_text(text, reply_markup=reply_markup, disable_web_page_preview=True)

    async def enter_address_step(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        expected_attempt_id: str | None = None,
    ):
        """Третий шаг - ввод Стеллар адреса"""
        user_id = update.effective_user.id
        user = await self._state_call("get_user", user_id)
        
        if not user:
            await update.effective_message.reply_text(
                get_message(telegram_language(update), 'user_not_found')
            )
            return
        
        attempt_id = expected_attempt_id or user.attempt_id
        if (
            not attempt_id
            or user.attempt_id != attempt_id
            or user.state != UserState.AGREEMENT.value
        ):
            await update.effective_message.reply_text(
                get_message(user.language, 'action_outdated')
            )
            return
        if not await self._state_call(
            "transition_attempt",
                user_id,
                attempt_id,
                UserState.AGREEMENT.value,
                UserState.ENTERING_ADDRESS.value,
                {
                    "agreed_to_terms": True,
                    "progress.agreement": True,
                },
        ):
            await update.effective_message.reply_text(
                get_message(user.language, 'temporary_error')
            )
            return
        logger.info(f"User {user_id} state updated to ENTERING_ADDRESS")

        await self._send_address_prompt(update, user.language)

    async def _send_address_prompt(self, update: Update, language: str) -> None:
        keyboard = [[KeyboardButton(get_message(language, 'address_help_button'))]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        text = get_message(language, 'enter_stellar_address')
        await update.effective_message.reply_text(text, reply_markup=reply_markup)

    async def _render_current_prompt(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Redraw the active phase after a language change."""

        user = await self._state_call("get_user", update.effective_user.id)
        if not user:
            await update.effective_message.reply_text(
                "User not found. Use /start"
            )
            return
        if user.state == UserState.CHECKING_USERNAME.value:
            await self.check_username_step(
                update,
                context,
                expected_attempt_id=user.attempt_id,
            )
        elif user.state == UserState.AGREEMENT.value:
            await self._send_agreement_prompt(update, user.language)
        elif user.state == UserState.ENTERING_ADDRESS.value:
            await self._send_address_prompt(update, user.language)
        elif user.state == UserState.CHECKING_ADDRESS.value:
            repeat_markup = ReplyKeyboardMarkup(
                [[KeyboardButton(get_message(user.language, 'repeat_check'))]],
                one_time_keyboard=True,
                resize_keyboard=True,
            )
            await update.effective_message.reply_text(
                get_message(user.language, 'repeat_current_check'),
                reply_markup=repeat_markup,
            )
        elif user.state == UserState.FINALIZING.value:
            await self.completion_step(
                update,
                context,
                address=user.stellar_address,
                attempt_id=user.attempt_id,
            )
        elif user.state == UserState.COMPLETED.value:
            await update.effective_message.reply_text(
                get_message(user.language, 'process_already_finished')
            )
        else:
            await update.effective_message.reply_text(
                get_message(user.language, 'action_outdated')
            )
    
    async def check_address_step(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        address: str | None = None,
        account_info: dict | None = None,
        attempt_id: str | None = None,
        expected_state: str | None = None,
    ):
        """Четвёртый шаг - проверка Стеллар адреса"""
        user_id = update.effective_user.id
        user = await self._state_call("get_user", user_id)
        
        logger.info(f"check_address_step called for user {user_id}")
        
        if not user:
            await update.effective_message.reply_text(
                get_message(telegram_language(update), 'user_not_found')
            )
            return

        active_attempt_id = attempt_id or user.attempt_id
        active_state = expected_state or user.state
        if (
            not active_attempt_id
            or user.attempt_id != active_attempt_id
            or user.state != active_state
            or active_state not in {
                UserState.ENTERING_ADDRESS.value,
                UserState.CHECKING_ADDRESS.value,
            }
        ):
            await update.effective_message.reply_text(
                get_message(user.language, 'action_outdated')
            )
            return
        
        # Логируем текущее состояние пользователя
        logger.info(f"User {user_id} is in CHECKING_ADDRESS state, proceeding with address verification")
        
        # Отправляем сообщение о начале проверки только если это callback
        # (если пользователь ввел адрес, сообщение уже отправлено в handle_address_input)
        if hasattr(update, 'callback_query') and update.callback_query:
            # Убираем клавиатурные кнопки при начале проверки
            await update.effective_message.reply_text(get_message(user.language, 'checking_address'), reply_markup=ReplyKeyboardRemove())
        
        # Проверяем адрес
        address = address or user.stellar_address
        if not address:
            await update.effective_message.reply_text(
                get_message(user.language, 'invalid_address')
            )
            return

        logger.info("Checking candidate account for user %s", user_id)
        
        if account_info is None:
            account_info = await self.stellar_client.get_account_info(address)

        recommendation_data = account_info.get('recommendation')
        logged_recommendation = (
            recommendation_data.get('has_recommendation', False)
            if isinstance(recommendation_data, dict)
            else False
        )
        logger.info(
            "Account info for user %s: exists=%s, trustline=%s, recommendation=%s",
            user_id,
            account_info.get('exists', False),
            account_info.get('has_trustline', False),
            logged_recommendation,
        )

        decision = evaluate_eligibility(
            agreed_to_terms=user.agreed_to_terms,
            stellar_address=address,
            account_info=account_info,
        )
        logger.info(
            "Eligibility decision for user %s: %s",
            user_id,
            decision.status.value,
        )

        if (
            decision.status is EligibilityStatus.INELIGIBLE
            and EligibilityBlocker.ACCOUNT_NOT_FOUND in decision.blockers
        ):
            text = get_message(user.language, 'invalid_address')
            await update.effective_message.reply_text(text)
            return

        if decision.status is EligibilityStatus.ALREADY_MEMBER:
            await update.effective_message.reply_text(
                get_message(user.language, 'address_already_member')
            )
            return

        if decision.status is EligibilityStatus.TEMPORARILY_UNAVAILABLE:
            await update.effective_message.reply_text(
                get_message(user.language, 'temporary_error')
            )
            return

        # Одной условной записью сохраняем все факты snapshot только для той
        # попытки и фазы, на которых началась проверка.
        has_trustline = bool(account_info.get('has_trustline', False))
        has_recommendation = account_info.get('recommendation', {}).get(
            'has_recommendation',
            False,
        )
        candidate_balance = Decimal(str(account_info.get('mtlap_balance', '0')))
        canonical_balance = "0" if candidate_balance == 0 else format(
            candidate_balance,
            "f",
        )
        next_state = (
            UserState.FINALIZING.value
            if decision.status is EligibilityStatus.ELIGIBLE
            else UserState.CHECKING_ADDRESS.value
        )
        if (
            not await self._state_call(
                "record_eligibility_snapshot",
                user_id,
                active_attempt_id,
                active_state,
                address,
                has_trustline,
                canonical_balance,
                has_recommendation,
                next_state,
            )
        ):
            logger.error(
                "Eligibility snapshot was not persisted for user %s",
                user_id,
            )
            await update.effective_message.reply_text(
                get_message(user.language, 'temporary_error')
            )
            return
        logger.info("Eligibility snapshot persisted for user %s", user_id)

        if decision.status is EligibilityStatus.ELIGIBLE:
            logger.info(f"All checks passed for user {user_id}, proceeding to completion")
            await self.completion_step(
                update,
                context,
                address=address,
                attempt_id=active_attempt_id,
            )
        else:
            logger.info(f"Some checks failed for user {user_id}, showing issues")
            await self.show_issues(update, context, account_info)
    
    async def show_issues(self, update: Update, context: ContextTypes.DEFAULT_TYPE, account_info: dict):
        """Показывает проблемы, которые нужно исправить"""
        user_id = update.effective_user.id
        user = await self._state_call("get_user", user_id)
        
        if not user:
            await update.effective_message.reply_text(
                get_message(telegram_language(update), 'user_not_found')
            )
            return
        
        # Используем effective_message для автоматического выбора правильного объекта
        base_message = update.effective_message
        
        # Проверяем и отправляем каждую проблему отдельным сообщением
        
        # 1. Проблема с согласием
        if not user.agreed_to_terms:
            agree_keyboard = [[KeyboardButton(get_message(user.language, 'agree'))]]
            agree_markup = ReplyKeyboardMarkup(agree_keyboard, one_time_keyboard=True, resize_keyboard=True)
            await base_message.reply_text(
                get_message(user.language, 'agreement_required'),
                reply_markup=agree_markup
            )
        
        # 2. Проблема с линией доверия
        if not account_info['has_trustline']:
            # Формируем текст с ссылками внутри
            trustline_text = f"{get_message(user.language, 'no_trustline')}\n{get_message(user.language, 'trustline_help')}\n\n{get_message(user.language, 'open_trustline_label')}: {config.LINKS[user.language]['mtlap_trustline']}"
            
            # Добавляем обычную кнопку "Повторить проверку"
            repeat_keyboard = [[KeyboardButton(get_message(user.language, 'repeat_check'))]]
            repeat_markup = ReplyKeyboardMarkup(repeat_keyboard, one_time_keyboard=True, resize_keyboard=True)
            
            # Отправляем сообщение с текстом и обычной кнопкой
            await base_message.reply_text(trustline_text, reply_markup=repeat_markup, disable_web_page_preview=True)
        
        # 3. Проблема с рекомендациями
        recommendation_info = account_info.get('recommendation', {})
        has_any_recommendation = recommendation_info.get('has_any_recommendation', False)
        has_verified_recommendation = recommendation_info.get('has_recommendation', False)
        
        if not has_verified_recommendation:
            if has_any_recommendation:
                # Есть рекомендация, но не от верифицированного участника
                await base_message.reply_text(get_message(user.language, 'recommendation_unverified'))
            else:
                # Нет рекомендаций вообще
                await base_message.reply_text(get_message(user.language, 'no_recommendation'))
            
            # Помощь по рекомендациям с ссылкой в тексте
            recommendation_text = f"{get_message(user.language, 'recommendation_help')}\n\n{get_message(user.language, 'square_chat_label')}: {config.LINKS[user.language]['square_chat']}"
            
            # Добавляем обычную кнопку "Повторить проверку"
            repeat_keyboard = [[KeyboardButton(get_message(user.language, 'repeat_check'))]]
            repeat_markup = ReplyKeyboardMarkup(repeat_keyboard, one_time_keyboard=True, resize_keyboard=True)
            
            # Отправляем сообщение с текстом и обычной кнопкой
            await base_message.reply_text(recommendation_text, reply_markup=repeat_markup, disable_web_page_preview=True)
        
        # Кнопка повторной проверки теперь добавляется к каждому сообщению с проблемами
    
    async def completion_step(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        address: str | None = None,
        attempt_id: str | None = None,
    ):
        """Финальный шаг - все проверки пройдены"""
        user_id = update.effective_user.id
        user = await self._state_call("get_user", user_id)
        
        if not user:
            await update.effective_message.reply_text(
                get_message(telegram_language(update), 'user_not_found')
            )
            return

        expected_attempt_id = attempt_id or user.attempt_id
        if (
            not expected_attempt_id
            or user.attempt_id != expected_attempt_id
            or user.state != UserState.FINALIZING.value
        ):
            await update.effective_message.reply_text(
                get_message(user.language, 'action_outdated')
            )
            return

        lease_id = uuid.uuid4().hex
        if not await self._state_call(
            "claim_final_delivery",
            user_id,
            expected_attempt_id,
            lease_id,
            lease_seconds=FINALIZATION_LEASE_SECONDS,
            automatic=False,
            max_attempts=FINALIZATION_MAX_ATTEMPTS,
        ):
            await update.effective_message.reply_text(
                get_message(user.language, "final_delivery_pending"),
                reply_markup=self._repeat_markup(user.language),
            )
            return
        
        text = self._build_completion_text(user, address)
        
        # Используем effective_message для автоматического выбора правильного объекта
        try:
            delivered_message = await update.effective_message.reply_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception("Final response delivery failed for user %s", user_id)
            await self._state_call(
                "defer_final_delivery",
                user_id,
                expected_attempt_id,
                lease_id,
                retry_seconds=FINALIZATION_RETRY_SECONDS,
                error_code="telegram_send_failed",
            )
            await update.effective_message.reply_text(
                get_message(user.language, 'temporary_error'),
                reply_markup=self._repeat_markup(user.language),
            )
            return

        # Терминальное состояние фиксируется только после успешной доставки.
        delivery_message_id = getattr(delivered_message, "message_id", None)
        if not isinstance(delivery_message_id, int):
            delivery_message_id = None
        if not await self._state_call(
            "complete_attempt",
            user_id,
            expected_attempt_id,
            lease_id,
            delivery_message_id,
        ):
            # Durable FINALIZING remains available for an at-least-once retry.
            # Do not contradict an already delivered success with an error.
            logger.error(
                "Final response delivered but completion was not persisted for user %s",
                user_id,
            )
    
    async def handle_address_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик ввода Стеллар адреса и ответов на соглашение"""
        user_id = update.effective_user.id
        user = await self._state_call("get_user", user_id)
        
        logger.info("Received flow input for user %s", user_id)
        
        if not user:
            logger.warning(f"User {user_id} not found in handle_address_input")
            await update.message.reply_text(
                get_message(telegram_language(update), 'user_not_found')
            )
            return
        
        # Проверяем, если пользователь отвечает на соглашение
        if user.state == UserState.AGREEMENT.value:
            user_text = update.message.text.strip()
            agree_text = get_message(user.language, 'agree')
            disagree_text = get_message(user.language, 'disagree')
            
            if user_text == agree_text:
                logger.info(f"User {user_id} agreed to terms, setting agreement status and proceeding to address step")
                await self.enter_address_step(
                    update,
                    context,
                    expected_attempt_id=user.attempt_id,
                )
                return
            elif user_text == disagree_text:
                text = get_message(user.language, 'agreement_required')
                # Создаем клавиатуру с кнопкой согласия
                keyboard = [
                    [KeyboardButton(get_message(user.language, 'agree'))]
                ]
                reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
                # Кнопки сами исчезнут после следующего сообщения
                await update.message.reply_text(text, reply_markup=reply_markup)
                return
            else:
                # Неизвестный ответ, просим выбрать из предложенных вариантов
                await update.message.reply_text(
                    get_message(user.language, 'choose_one_option')
                )
                return

        # Legacy/incomplete snapshots may surface the agreement issue while
        # already in the address-check phase. Persist it conditionally and
        # re-evaluate the same address.
        if (
            user.state == UserState.CHECKING_ADDRESS.value
            and update.message.text.strip() == get_message(user.language, 'agree')
        ):
            if (
                not user.attempt_id
                or not await self._state_call(
                    "update_attempt_fields",
                    user_id,
                    user.attempt_id,
                    UserState.CHECKING_ADDRESS.value,
                    {
                        "agreed_to_terms": True,
                        "progress.agreement": True,
                    },
                )
            ):
                await update.message.reply_text(
                    get_message(user.language, 'temporary_error')
                )
                return
            await self.check_address_step(
                update,
                context,
                attempt_id=user.attempt_id,
                expected_state=UserState.CHECKING_ADDRESS.value,
            )
            return
        
        # Проверяем, если пользователь нажал "Повторить проверку"
        repeat_check_text = get_message(user.language, 'repeat_check')
        if update.message.text.strip() == repeat_check_text:
            logger.info(f"User {user_id} requested repeat check")
            if user.state == UserState.COMPLETED.value:
                await update.message.reply_text(
                    get_message(user.language, 'process_already_finished')
                )
                return
            if user.state == UserState.FINALIZING.value:
                await self.completion_step(
                    update,
                    context,
                    address=user.stellar_address,
                    attempt_id=user.attempt_id,
                )
                return
            if (
                user.state != UserState.CHECKING_ADDRESS.value
                or not user.stellar_address
            ):
                await update.message.reply_text(
                    get_message(user.language, 'action_outdated')
                )
                return
            await self.check_address_step(
                update,
                context,
                attempt_id=user.attempt_id,
                expected_state=user.state,
            )
            return

        if user.state == UserState.FINALIZING.value:
            await update.message.reply_text(
                get_message(user.language, 'final_delivery_pending'),
                reply_markup=self._repeat_markup(user.language),
            )
            return
        
        # Проверяем, если пользователь нажал кнопку помощи по адресу.
        if update.message.text.strip() == get_message(
            user.language,
            'address_help_button',
        ):
            logger.info(f"User {user_id} asked about Stellar address")
            # Отправляем информацию о лёгком способе и убираем клавиатурные кнопки
            text = f"{get_message(user.language, 'stellar_address_explanation')} {config.LINKS[user.language]['light_entry_article']}"
            await update.message.reply_text(text, reply_markup=ReplyKeyboardRemove())
            return
        
        logger.info(f"User {user_id} state: {user.state}, expected: {UserState.ENTERING_ADDRESS.value}")
        
        if user.state not in [UserState.ENTERING_ADDRESS.value, UserState.CHECKING_ADDRESS.value]:
            logger.info(f"User {user_id} is not in ENTERING_ADDRESS or CHECKING_ADDRESS state, current state: {user.state}")
            message_key = (
                'process_already_finished'
                if user.state == UserState.COMPLETED.value
                else 'action_outdated'
            )
            await update.message.reply_text(
                get_message(user.language, message_key)
            )
            return
        
        # Если пользователь уже в процессе проверки, разрешаем повторный ввод адреса
        if user.state == UserState.CHECKING_ADDRESS.value:
            logger.info(f"User {user_id} is already checking address, allowing new address input")
        
        address = update.message.text.strip()
        
        # Простая проверка формата Стеллар адреса
        if (
            not re.fullmatch(r'G[A-Z0-9]{55}', address)
            or not is_valid_stellar_address(address)
        ):
            text = get_message(user.language, 'invalid_address')
            await update.message.reply_text(text)
            return
        
        # Отправляем сообщение о начале проверки и убираем клавиатурные кнопки
        await update.message.reply_text(get_message(user.language, 'checking_address'), reply_markup=ReplyKeyboardRemove())

        # Один ввод адреса формирует один snapshot внешних проверок.
        account_info = await self.stellar_client.get_account_info(address)
        await self.check_address_step(
            update,
            context,
            address=address,
            account_info=account_info,
            attempt_id=user.attempt_id,
            expected_state=user.state,
        )
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик callback кнопок"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        user = await self._state_call("get_user", user_id)
        
        if not user:
            await query.message.reply_text(
                get_message(telegram_language(update), 'user_not_found')
            )
            return
        
        if query.data in {"lang_en", "lang_ru"}:
            lang = query.data.removeprefix("lang_")
            if not await self._state_call("update_language", user_id, lang):
                await query.message.reply_text(
                    get_message(user.language, 'temporary_error')
                )
                return
            text = get_message(lang, 'language_changed')
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text(text)
            await self._render_current_prompt(update, context)
            return

        decoded_callback = decode_flow_callback(query.data)
        if (
            decoded_callback is None
            or not user.attempt_id
            or decoded_callback[1] != user.attempt_id
            or user.state != UserState.CHECKING_USERNAME.value
        ):
            await query.message.reply_text(
                get_message(user.language, 'action_outdated')
            )
            return

        action, _attempt_id = decoded_callback
        if action == "username_installed":
            await query.edit_message_reply_markup(reply_markup=None)
            await self.check_username_step(
                update,
                context,
                expected_attempt_id=_attempt_id,
            )
        elif action == "continue_without_username":
            await query.edit_message_reply_markup(reply_markup=None)
            await self.agreement_step(
                update,
                context,
                expected_attempt_id=_attempt_id,
                acknowledge_without_username=True,
            )
        else:
            await query.message.reply_text(
                get_message(user.language, 'action_outdated')
            )
    
    def run(self):
        """Запуск бота"""
        self.application = (
            Application.builder()
            .token(config.TELEGRAM_TOKEN)
            .concurrent_updates(8)
            .post_init(self._post_init)
            .post_shutdown(self._post_shutdown)
            .build()
        )
        
        # Обработчики команд
        self.application.add_handler(CommandHandler("start", self._reset_serialized(self.start)))
        self.application.add_handler(CommandHandler("restart", self._reset_serialized(self.restart)))
        self.application.add_handler(CommandHandler("language", self._serialized(self.language)))
        
        # Административные команды
        self.application.add_handler(CommandHandler("stats", self._serialized(self.stats)))
        self.application.add_handler(CommandHandler("incomplete", self._serialized(self.incomplete)))
        self.application.add_handler(CommandHandler("reminders", self._serialized(self.reminders)))
        self.application.add_handler(CommandHandler("user_info", self._serialized(self.user_info)))
        self.application.add_handler(CommandHandler("help_admin", self._serialized(self.help_admin)))
        
        # Обработчики сообщений
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self._serialized(self.handle_address_input),
        ))
        
        # Обработчики сообщений уже настроены выше
        
        # Обработчики callback
        self.application.add_handler(CallbackQueryHandler(
            self._serialized(self.handle_callback)
        ))
        self.application.add_error_handler(self.handle_error)
        
        # Запуск бота с явным сбросом webhook и дополнительными параметрами
        self.application.run_polling(
            # Не теряем сообщения, отправленные во время короткого downtime.
            drop_pending_updates=False,
            allowed_updates=None,       # Разрешаем все типы обновлений
            close_loop=False           # Не закрываем event loop
        )
    
    def cleanup(self):
        """Очистка ресурсов при завершении"""
        try:
            if self.state_manager:
                self.state_manager.close_connection()
            if self.admin_tools:
                self.admin_tools.close_connection()
            logger.info("Cleanup completed successfully")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
    
def get_message(lang: str, key: str) -> str:
    """Получает сообщение на указанном языке"""
    return messages.get_message(lang, key)
