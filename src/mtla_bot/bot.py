import asyncio
import logging
import re
import signal
import sys
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode

from . import config
from . import messages
from .stellar_client import StellarClient
from .user_states import UserStateManager, UserState
from .admin_tools import AdminTools
from .admin_config import ADMIN_IDS

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class MTLAJoinBot:
    def __init__(self):
        self.state_manager = UserStateManager()
        self.stellar_client = StellarClient()
        self.admin_tools = AdminTools()
        self.application = None
        
    def is_admin(self, user_id: int) -> bool:
        """Проверяет, является ли пользователь администратором"""
        return user_id in ADMIN_IDS
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user_id = update.effective_user.id
        user = update.effective_user
        
        # Определяем язык пользователя
        language = 'ru' if user.language_code == 'ru' else 'en'
        
        try:
            # Проверяем, есть ли пользователь в базе
            existing_user = self.state_manager.get_user(user_id)
            if not existing_user:
                # Создаем нового пользователя
                username = user.username or f"user_{user_id}"
                if self.state_manager.create_user(user_id, username, language):
                    logger.info(f"Created new user: {user_id}")
                    # Проверяем, что пользователь действительно создался
                    existing_user = self.state_manager.get_user(user_id)
                    if not existing_user:
                        logger.error(f"User was not created properly: {user_id}")
                        await update.message.reply_text("Произошла ошибка при создании пользователя. Попробуйте позже.")
                        return
                else:
                    logger.error(f"Failed to create user: {user_id}")
                    await update.message.reply_text("Произошла ошибка. Попробуйте позже.")
                    return
            else:
                # Обновляем базовую информацию существующего пользователя
                username = user.username or f"user_{user_id}"
                self.state_manager.update_user(user_id, {
                    "username": username,
                    "language": language
                })
                # Сбрасываем прогресс
                self.state_manager.reset_user_progress(user_id)
            
            # Отправляем приветственное сообщение
            await update.message.reply_text(get_message(language, 'welcome'))
            
            # Ждем 1 секунду и начинаем проверку с первого шага
            await asyncio.sleep(1)
            await self.check_username_step(update, context)
            
        except Exception as e:
            logger.error(f"Error in start method: {e}")
            await update.message.reply_text("Произошла ошибка. Попробуйте позже.")
    
    async def restart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /restart"""
        user_id = update.effective_user.id
        
        try:
            # Проверяем, есть ли пользователь в базе
            existing_user = self.state_manager.get_user(user_id)
            if not existing_user:
                # Если пользователя нет, создаем нового
                await self.start(update, context)
                return
            
            # Сбрасываем прогресс существующего пользователя
            self.state_manager.reset_user_progress(user_id)
            
            # Отправляем приветственное сообщение
            user = self.state_manager.get_user(user_id)
            await update.message.reply_text(get_message(user.language, 'welcome'))
            
            # Ждем 1 секунду и начинаем проверку с первого шага
            await asyncio.sleep(1)
            await self.check_username_step(update, context)
            
        except Exception as e:
            logger.error(f"Error in restart method: {e}")
            await update.message.reply_text("Произошла ошибка. Попробуйте позже.")
    
    async def language(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /language"""
        user_id = update.effective_user.id
        user = self.state_manager.get_user(user_id)
        
        if not user:
            await update.message.reply_text("Пользователь не найден. Используйте /start")
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
            stats_text = self.admin_tools.get_user_statistics()
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
            incomplete_text = self.admin_tools.get_incomplete_users_report()
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
            
            reminders_text = self.admin_tools.get_reminder_candidates(days)
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
            user_details = self.admin_tools.get_user_details(target_user_id)
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
    
    async def check_username_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Первый шаг - проверка юзернейма"""
        user_id = update.effective_user.id
        user = self.state_manager.get_user(user_id)
        
        if not user:
            await update.message.reply_text("Пользователь не найден. Используйте /start")
            return
        
        self.state_manager.update_state(user_id, UserState.CHECKING_USERNAME)
        
        # Проверяем наличие юзернейма
        has_username = bool(update.effective_user.username)
        self.state_manager.set_username_status(user_id, has_username)
        
        if has_username:
            logger.info(f"User {user_id} has username, proceeding to agreement step")
            await self.agreement_step(update, context)
        else:
            keyboard = [
                [InlineKeyboardButton(
                    get_message(user.language, 'username_installed'),
                    callback_data="username_installed"
                )]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            text = get_message(user.language, 'no_username')
            await update.message.reply_text(text, reply_markup=reply_markup)
    
    async def agreement_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Второй шаг - согласие с условиями"""
        user_id = update.effective_user.id
        user = self.state_manager.get_user(user_id)
        
        if not user:
            await update.effective_message.reply_text("Пользователь не найден. Используйте /start")
            return
        
        self.state_manager.update_state(user_id, UserState.AGREEMENT)
        logger.info(f"User {user_id} state updated to AGREEMENT")
        
        keyboard = [
            [KeyboardButton(get_message(user.language, 'agree'))],
            [KeyboardButton(get_message(user.language, 'disagree'))]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        
        text = f"{get_message(user.language, 'agreement_text')}\n{config.LINKS[user.language]['agreement_link']}"
        
        # Используем effective_message для автоматического выбора правильного объекта
        await update.effective_message.reply_text(text, reply_markup=reply_markup, disable_web_page_preview=True)
    
    async def enter_address_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Третий шаг - ввод Стеллар адреса"""
        user_id = update.effective_user.id
        user = self.state_manager.get_user(user_id)
        
        if not user:
            await update.effective_message.reply_text("Пользователь не найден. Используйте /start")
            return
        
        self.state_manager.update_state(user_id, UserState.ENTERING_ADDRESS)
        logger.info(f"User {user_id} state updated to ENTERING_ADDRESS")
        
        # Создаем клавиатуру с кнопкой "Что за стеллар адрес?"
        keyboard = [[KeyboardButton("Что за стеллар адрес?")]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        
        text = get_message(user.language, 'enter_stellar_address')
        
        # Используем effective_message для автоматического выбора правильного объекта
        await update.effective_message.reply_text(text, reply_markup=reply_markup)
    
    async def validate_address_basic(self, address: str, user_language: str):
        """Базовая валидация Стеллар адреса"""
        try:
            # Проверяем адрес на Stellar
            account_info = await self.stellar_client.get_account_info(address)
            
            if not account_info['exists']:
                return False, get_message(user_language, 'invalid_address'), None
            
            # Проверяем, не является ли адрес уже участником
            if account_info['has_trustline'] and account_info['mtlap_balance'] > 0:
                text = get_message(user_language, 'address_already_member')
                return False, text, account_info
            
            return True, None, account_info
            
        except Exception as e:
            logger.error(f"Error in validate_address_basic for {address}: {e}")
            return False, get_message(user_language, 'invalid_address'), None
    
    async def check_address_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Четвёртый шаг - проверка Стеллар адреса"""
        user_id = update.effective_user.id
        user = self.state_manager.get_user(user_id)
        
        logger.info(f"check_address_step called for user {user_id}")
        
        if not user:
            await update.effective_message.reply_text("Пользователь не найден. Используйте /start")
            return
        
        # Логируем текущее состояние пользователя
        logger.info(f"User {user_id} is in CHECKING_ADDRESS state, proceeding with address verification")
        
        # Отправляем сообщение о начале проверки только если это callback
        # (если пользователь ввел адрес, сообщение уже отправлено в handle_address_input)
        if hasattr(update, 'callback_query') and update.callback_query:
            # Убираем клавиатурные кнопки при начале проверки
            await update.effective_message.reply_text(get_message(user.language, 'checking_address'), reply_markup=ReplyKeyboardRemove())
        
        # Проверяем адрес
        address = user.stellar_address
        logger.info(f"Checking address {address} for user {user_id}")
        
        account_info = await self.stellar_client.get_account_info(address)
        logger.info(f"Account info for {address}: exists={account_info['exists']}, trustline={account_info['has_trustline']}, recommendation={account_info.get('recommendation', {}).get('has_recommendation', False)}")
        
        if not account_info['exists']:
            text = get_message(user.language, 'invalid_address')
            await update.effective_message.reply_text(text)
            return
        
        # Устанавливаем статус линии доверия
        self.state_manager.set_trustline_status(user_id, account_info['has_trustline'])
        logger.info(f"Trustline status set for user {user_id}: {account_info['has_trustline']}")
        
        # Проверяем все условия включая рекомендации
        has_recommendation = account_info.get('recommendation', {}).get('has_recommendation', False)
        
        if (user.has_username and user.agreed_to_terms and 
            user.stellar_address and account_info['has_trustline'] and has_recommendation):
            logger.info(f"All checks passed for user {user_id}, proceeding to completion")
            await self.completion_step(update, context)
        else:
            logger.info(f"Some checks failed for user {user_id}, showing issues")
            await self.show_issues(update, context, account_info)
    
    async def show_issues(self, update: Update, context: ContextTypes.DEFAULT_TYPE, account_info: dict):
        """Показывает проблемы, которые нужно исправить"""
        user_id = update.effective_user.id
        user = self.state_manager.get_user(user_id)
        
        if not user:
            await update.effective_message.reply_text("Пользователь не найден. Используйте /start")
            return
        
        # Используем effective_message для автоматического выбора правильного объекта
        base_message = update.effective_message
        
        # Проверяем и отправляем каждую проблему отдельным сообщением
        
        # 1. Проблема с юзернеймом
        if not user.has_username:
            username_keyboard = [[InlineKeyboardButton(
                get_message(user.language, 'username_installed'),
                callback_data="username_installed"
            )]]
            username_markup = InlineKeyboardMarkup(username_keyboard)
            await base_message.reply_text(
                get_message(user.language, 'no_username'),
                reply_markup=username_markup
            )
        
        # 2. Проблема с согласием
        if not user.agreed_to_terms:
            agree_keyboard = [[KeyboardButton(get_message(user.language, 'agree'))]]
            agree_markup = ReplyKeyboardMarkup(agree_keyboard, one_time_keyboard=True, resize_keyboard=True)
            await base_message.reply_text(
                get_message(user.language, 'agreement_required'),
                reply_markup=agree_markup
            )
        
        # 3. Проблема с линией доверия
        if not account_info['has_trustline']:
            # Формируем текст с ссылками внутри
            trustline_text = f"{get_message(user.language, 'no_trustline')}\n{get_message(user.language, 'trustline_help')}\n\nОткрыть линию доверия: {config.LINKS[user.language]['mtlap_trustline']}"
            
            # Добавляем обычную кнопку "Повторить проверку"
            repeat_keyboard = [[KeyboardButton(get_message(user.language, 'repeat_check'))]]
            repeat_markup = ReplyKeyboardMarkup(repeat_keyboard, one_time_keyboard=True, resize_keyboard=True)
            
            # Отправляем сообщение с текстом и обычной кнопкой
            await base_message.reply_text(trustline_text, reply_markup=repeat_markup, disable_web_page_preview=True)
        
        # 4. Проблема с рекомендациями
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
            recommendation_text = f"{get_message(user.language, 'recommendation_help')}\n\nЧат Площадь: {config.LINKS[user.language]['square_chat']}"
            
            # Добавляем обычную кнопку "Повторить проверку"
            repeat_keyboard = [[KeyboardButton(get_message(user.language, 'repeat_check'))]]
            repeat_markup = ReplyKeyboardMarkup(repeat_keyboard, one_time_keyboard=True, resize_keyboard=True)
            
            # Отправляем сообщение с текстом и обычной кнопкой
            await base_message.reply_text(recommendation_text, reply_markup=repeat_markup, disable_web_page_preview=True)
        
        # Кнопка повторной проверки теперь добавляется к каждому сообщению с проблемами
    
    async def completion_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Финальный шаг - все проверки пройдены"""
        user_id = update.effective_user.id
        user = self.state_manager.get_user(user_id)
        
        if not user:
            await update.effective_message.reply_text("Пользователь не найден. Используйте /start")
            return
        
        self.state_manager.update_state(user_id, UserState.COMPLETED)
        
        # Формируем текст заявки в формате для копирования
        application_text = get_message(user.language, 'application_text').format(address=user.stellar_address)
        
        # Используем Markdown для оформления копируемого текста
        # Экранируем подчеркивания в имени бота, чтобы Telegram не интерпретировал их как курсив
        feedback_bot_escaped = config.LINKS[user.language]['feedback_bot'].replace('_', '\\_')
        text = get_message(user.language, 'all_checks_passed').format(application_text=application_text, feedback_bot=feedback_bot_escaped)
        
        # Используем effective_message для автоматического выбора правильного объекта
        await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    
    async def handle_address_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик ввода Стеллар адреса и ответов на соглашение"""
        user_id = update.effective_user.id
        user = self.state_manager.get_user(user_id)
        
        logger.info(f"handle_address_input called for user {user_id}, text: {update.message.text}")
        
        if not user:
            logger.warning(f"User {user_id} not found in handle_address_input")
            await update.message.reply_text("Пользователь не найден. Используйте /start")
            return
        
        # Проверяем, если пользователь отвечает на соглашение
        if user.state == UserState.AGREEMENT.value:
            user_text = update.message.text.strip()
            agree_text = get_message(user.language, 'agree')
            disagree_text = get_message(user.language, 'disagree')
            
            if user_text == agree_text:
                logger.info(f"User {user_id} agreed to terms, setting agreement status and proceeding to address step")
                self.state_manager.set_agreement_status(user_id, True)
                # Кнопки сами исчезнут после следующего сообщения
                await self.enter_address_step(update, context)
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
                await update.message.reply_text("Пожалуйста, выберите один из предложенных вариантов.")
                return
        
        # Проверяем, если пользователь нажал "Повторить проверку"
        repeat_check_text = get_message(user.language, 'repeat_check')
        if update.message.text.strip() == repeat_check_text:
            logger.info(f"User {user_id} requested repeat check")
            # Запускаем повторную проверку адреса
            await self.check_address_step(update, context)
            return
        
        # Проверяем, если пользователь нажал "Что за стеллар адрес?"
        if update.message.text.strip() == "Что за стеллар адрес?":
            logger.info(f"User {user_id} asked about Stellar address")
            # Отправляем информацию о лёгком способе и убираем клавиатурные кнопки
            text = f"{get_message(user.language, 'stellar_address_explanation')} {config.LINKS[user.language]['light_entry_article']}"
            await update.message.reply_text(text, reply_markup=ReplyKeyboardRemove())
            return
        
        logger.info(f"User {user_id} state: {user.state}, expected: {UserState.ENTERING_ADDRESS.value}")
        
        if user.state not in [UserState.ENTERING_ADDRESS.value, UserState.CHECKING_ADDRESS.value]:
            logger.info(f"User {user_id} is not in ENTERING_ADDRESS or CHECKING_ADDRESS state, current state: {user.state}")
            return
        
        # Если пользователь уже в процессе проверки, разрешаем повторный ввод адреса
        if user.state == UserState.CHECKING_ADDRESS.value:
            logger.info(f"User {user_id} is already checking address, allowing new address input")
        
        address = update.message.text.strip()
        
        # Простая проверка формата Стеллар адреса
        if not re.match(r'^G[A-Z0-9]{55}$', address):
            text = get_message(user.language, 'invalid_address')
            await update.message.reply_text(text)
            return
        
        logger.info(f"Address {address} is valid, setting it for user {user_id}")
        self.state_manager.set_stellar_address(user_id, address)

        # Отправляем сообщение о начале проверки и убираем клавиатурные кнопки
        await update.message.reply_text(get_message(user.language, 'checking_address'), reply_markup=ReplyKeyboardRemove())

        # Используем общую функцию валидации
        success, error_text, account_info = await self.validate_address_basic(address, user.language)
        
        if not success:
            await update.message.reply_text(error_text)
            return
        
        # Если адрес подходит, обновляем состояние и начинаем проверку
        self.state_manager.update_state(user_id, UserState.CHECKING_ADDRESS)
        
        # Начинаем проверку адреса
        await self.check_address_step(update, context)
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик callback кнопок"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        user = self.state_manager.get_user(user_id)
        
        if not user:
            await query.message.reply_text("Пользователь не найден. Используйте /start")
            return
        
        if query.data == "username_installed":
            # Убираем кнопки из старого сообщения
            await query.edit_message_reply_markup(reply_markup=None)
            await self.check_username_step(update, context)
        elif query.data == "agree":
            logger.info(f"User {user_id} agreed to terms, setting agreement status and proceeding to address step")
            self.state_manager.set_agreement_status(user_id, True)
            
            # Убираем кнопки из старого сообщения
            await query.edit_message_reply_markup(reply_markup=None)
            await self.enter_address_step(update, context)
        elif query.data == "disagree":
            text = get_message(user.language, 'agreement_required')
            # Убираем кнопки из старого сообщения
            await query.edit_message_reply_markup(reply_markup=None)
            # Создаем клавиатуру с кнопкой согласия
            keyboard = [
                [KeyboardButton(get_message(user.language, 'agree'))]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            # Создаем новое сообщение с требованием согласия и кнопкой
            await query.message.reply_text(text, reply_markup=reply_markup)
        elif query.data == "repeat_check":
            # Убираем кнопки из старого сообщения
            await query.edit_message_reply_markup(reply_markup=None)
            await self.check_address_step(update, context)
        elif query.data == "restart":
            # Убираем кнопки из старого сообщения
            await query.edit_message_reply_markup(reply_markup=None)
            await self.restart(update, context)
        elif query.data.startswith("lang_"):
            lang = query.data.split("_")[1]
            self.state_manager.update_language(user_id, lang)
            text = get_message(lang, 'language_changed')
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text(text)
    
    def run(self):
        """Запуск бота"""
        self.application = Application.builder().token(config.TELEGRAM_TOKEN).build()
        
        # Обработчики команд
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("restart", self.restart))
        self.application.add_handler(CommandHandler("language", self.language))
        
        # Административные команды
        self.application.add_handler(CommandHandler("stats", self.stats))
        self.application.add_handler(CommandHandler("incomplete", self.incomplete))
        self.application.add_handler(CommandHandler("reminders", self.reminders))
        self.application.add_handler(CommandHandler("user_info", self.user_info))
        self.application.add_handler(CommandHandler("help_admin", self.help_admin))
        
        # Обработчики сообщений
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_address_input))
        
        # Обработчики сообщений уже настроены выше
        
        # Обработчики callback
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        
        # Запуск бота с явным сбросом webhook и дополнительными параметрами
        self.application.run_polling(
            drop_pending_updates=True,  # Игнорируем старые обновления
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
    
    def stop(self):
        """Корректная остановка бота"""
        try:
            if self.application:
                logger.info("Stopping bot...")
                # Останавливаем бота
                self.application.stop()
                logger.info("Bot stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping bot: {e}")
        finally:
            self.cleanup()
    
    def signal_handler(self, signum, frame):
        """Обработчик сигналов для корректного завершения"""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.stop()
        sys.exit(0)

def get_message(lang: str, key: str) -> str:
    """Получает сообщение на указанном языке"""
    return messages.get_message(lang, key)

# Этот блок выполняется только при прямом запуске bot.py
# При импорте через main.py он не выполняется
if __name__ == '__main__':
    bot = MTLAJoinBot()
    
    # Настраиваем обработчики сигналов для корректного завершения
    signal.signal(signal.SIGINT, bot.signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, bot.signal_handler)  # Сигнал завершения
    
    try:
        logger.info("Starting MTLA Join Bot...")
        bot.run()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (Ctrl+C)")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        logger.info("Shutting down bot...")
        bot.cleanup()
        logger.info("Bot shutdown complete")
