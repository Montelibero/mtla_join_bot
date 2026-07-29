"""
Мультиязычные сообщения для MTLA Join Bot

Этот файл содержит все текстовые сообщения бота на русском и английском языках.
Сообщения организованы по функциональным группам для удобства поддержки и локализации.

Структура:
- Проверка юзернейма
- Согласие с условиями  
- Ввод и проверка адреса
- Проверка линии доверия
- Проверка рекомендаций
- Действия пользователя
- Успешное завершение
- Системные сообщения
"""

MESSAGES = {
    'en': {
        # Welcome message
        'welcome': 'This bot will help you submit an application to join the Montelibero Association (@MTL_Association). Just a few steps and a few checks!',
        
        # Username check
        'no_username': 'You don\'t have a Telegram username. It is not required, but we strongly recommend setting one so Association participants can identify and contact you.\n\nYou can set it in Telegram settings and check again, or explicitly continue without a username.',
        'username_installed': '✅ I installed username',
        'continue_without_username': 'Continue without username',
        
        # Agreement
        'agreement_text': 'To join the Montelibero Association, you must express your agreement with the current text of the Agreement.\n\nThis is our common contract.\nPlease read it:',
        'agree': '✅ Agree',
        'disagree': '❌ Disagree',
        'agreement_required': 'To join the Montelibero Association, you must agree to the Agreement. Without this, joining is impossible.',
        
        # Address input and validation
        'enter_stellar_address': 'Enter your Stellar address (string that starts with G...)',
        'address_help_button': 'What is a Stellar address?',
        'invalid_address': 'Invalid Stellar address. Check that you copied the complete G-address correctly.',
        'stellar_address_explanation': 'A Stellar address is your unique identifier in the Stellar blockchain. It\'s like a bank account number, but for cryptocurrencies.\n\nWe recommend reading the article "Easy entry into tokenomics", the result of which is an airdrop:',
        'checking_address': '👀 Checking Stellar, BSN, and the recommendation. This can take up to about half a minute — the bot is working.',
        
        # Trustline check
        'no_trustline': 'You don\'t have a trustline to MTLAP token. MTLAP is a membership token, and without your permission, it cannot be sent to you.',
        'trustline_help': 'If you have questions, contact the Agora chat.',
        'open_trustline_label': 'Open trustline',
        
        # Recommendation check
        'no_recommendation': 'To join the Montelibero Association, you need a recommendation from a verified member (at least 2 MTLAP tokens).',
        'recommendation_unverified': 'You have a recommendation, but it\'s not from a verified member of the Montelibero Association (at least 2 MTLAP tokens required).',
        'recommendation_help': 'You can get a recommendation from verified member acquaintances or contact the Agora chat.',
        'square_chat_label': 'Agora chat',
        
        # User actions
        'repeat_check': '🔄 Repeat check',
        'repeat_current_check': 'The language has changed. Use the button below to repeat the current check.',
        'back_to_start': 'Back to start',
        
        # Successful completion
        'all_checks_passed': 'Great job! All required checks passed. You can now submit your application.\n\nCopy this text:\n```\n{application_text}\n```\n\nAnd send it to the Montelibero feedback bot: {feedback_bot}\n\nThank you for participating!',
        'application_text': 'I want to join the Montelibero Association.\nI have read the Agreement and express my full agreement with it.\nMy address: {address}',
        
        # System messages
        'language_changed': 'Language changed to English.',
        'request_in_progress': 'Your previous action is still being processed. Wait for its result or use /start to cancel it and begin again.',
        'final_delivery_pending': 'All checks are saved. The final answer is being delivered or needs an administrator\'s attention. If it does not arrive, use “Repeat check”: only delivery will be retried, not the checks.',
        'choose_one_option': 'Please choose one of the available options.',
        'user_not_found': 'Your process was not found. Use /start to begin a new attempt.',
        'temporary_error': 'The check is temporarily unavailable because a technical service did not respond correctly. Please try again later.',
        'action_outdated': 'This button or action belongs to an old step. Use /start to begin a new attempt.',
        'process_already_finished': 'This attempt is already complete. Use /start if you want to begin again.',
        'address_already_member': 'This address is already a member of the Montelibero Association and has MTLAP tokens. Maybe you have already joined the Association before. Or maybe this is not your address? Then try a different address.'
    },
    'ru': {
        # Приветственное сообщение
        'welcome': 'Этот бот поможет оформить вам заявку на вступление в Ассоциацию Монтелиберо (@MTL_Association). Всего несколько шагов и несколько проверок!',
        
        # Проверка юзернейма
        'no_username': 'У вас не установлен Telegram username. Он не обязателен, но мы настоятельно рекомендуем его установить, чтобы участники Ассоциации могли вас опознать и связаться с вами.\n\nУстановите username в настройках Telegram и проверьте снова либо явно продолжите без него.',
        'username_installed': '✅ Я установил юзернейм',
        'continue_without_username': 'Продолжить без username',
        
        # Согласие с условиями
        'agreement_text': 'Чтобы вступить в Ассоциацию Монтелиберо, необходимо выразить согласие с актуальным текстом Соглашения.\n\nЭто наш общий контракт.\nПожалуйста, ознакомьтесь с ним:',
        'agree': '✅ Согласен',
        'disagree': '❌ Не согласен',
        'agreement_required': 'Для вступления в Ассоциацию необходимо выразить согласие с Соглашением. Без этого вступление невозможно.',
        
        # Ввод и проверка адреса
        'enter_stellar_address': 'Напишите ваш Stellar-адрес (строка что начинается с G...)',
        'address_help_button': 'Что за Stellar-адрес?',
        'invalid_address': 'Некорректный Stellar-адрес. Проверьте, что полностью скопировали G-адрес.',
        'stellar_address_explanation': 'Stellar-адрес - это ваш уникальный идентификатор в блокчейне Stellar. Это как номер банковского счета, но для криптовалют.\n\nРекомендем прочитать статью «Лёгкий вход в токеномику», по итогам корой можно получить аирдроп:',
        'checking_address': '👀 Проверяю Stellar, BSN и рекомендацию. Это может занять до половины минуты — бот работает.',
        
        # Проверка линии доверия
        'no_trustline': 'У вас нет линии доверия к токену MTLAP. Это наш токен участия, и без вашего разрешения его нельзя будет вам прислать.',
        'trustline_help': 'Если у вас возникли вопросы, обратитесь в чат Площади.',
        'open_trustline_label': 'Открыть линию доверия',
        
        # Проверка рекомендаций
        'no_recommendation': 'Для вступления в Ассоциацию нужна рекомендация от верифицированного участника (у которого есть как минимум 2 токена MTLAP).',
        'recommendation_unverified': 'У вас есть рекомендация, но она не от верифицированного участника Ассоциации (у которого есть как минимум 2 токена MTLAP).',
        'recommendation_help': 'Рекомендацию можно получить от знакомых верифицированных участников Ассоциации или спросить в чате Площадь.',
        'square_chat_label': 'Чат Площадь',
        
        # Действия пользователя
        'repeat_check': '🔄 Повторить проверку',
        'repeat_current_check': 'Язык изменён. Нажмите кнопку ниже, чтобы повторить текущую проверку.',
        'back_to_start': 'Вернуться к началу',
        
        # Успешное завершение
        'all_checks_passed': '✅ Вы молодец! Все необходимые проверки пройдены, и теперь можно подавать заявление.\n\nСкопируйте этот текст:\n```\n{application_text}\n```\n\nИ отправьте его боту обратной связи Монтелиберо: {feedback_bot}\n\nСпасибо за участие!',
        'application_text': 'Хочу вступить в Ассоциацию Монтелиберо.\nСоглашение прочитано и выражаю полное согласие с ним.\nМой адрес: {address}',
        
        # Системные сообщения
        'language_changed': 'Язык изменён на русский.',
        'request_in_progress': 'Предыдущее действие ещё обрабатывается. Дождитесь результата или используйте /start, чтобы отменить его и начать заново.',
        'final_delivery_pending': 'Все проверки сохранены. Финальный ответ доставляется или требует внимания администратора. Если он не придёт, нажмите «Повторить проверку»: повторится только доставка, а не сами проверки.',
        'choose_one_option': 'Пожалуйста, выберите один из предложенных вариантов.',
        'user_not_found': 'Ваш процесс не найден. Используйте /start, чтобы начать новую попытку.',
        'temporary_error': 'Сейчас проверка временно недоступна: один из технических сервисов ответил с ошибкой. Попробуйте ещё раз позже.',
        'action_outdated': 'Эта кнопка или команда относится к старому шагу. Используйте /start, чтобы начать новую попытку.',
        'process_already_finished': 'Эта попытка уже завершена. Используйте /start, если хотите начать заново.',
        'address_already_member': 'Этот адрес уже является участником Ассоциации и там уже есть токены MTLAP. Возможно, вы вступали в Ассоциацию ранее. А может это не ваш адрес? Тогда попробуйте указать другой.'
    },
}

def get_message(lang: str, key: str) -> str:
    """Получает сообщение на указанном языке"""
    return MESSAGES.get(lang, MESSAGES['en']).get(key, key)
