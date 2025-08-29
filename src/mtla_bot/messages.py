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
        'no_username': 'You don\'t have a username. Although the Association rules don\'t prohibit accounts without usernames, we don\'t know how to work with participants who don\'t have them.',
        'username_guide_text': 'Username setup guide:',
        'username_installed': '✅ I installed username',
        
        # Agreement
        'agreement_text': 'To join the Montelibero Association, you must express your agreement with the current text of the Agreement.\n\nPlease read it:',
        'agree': '✅ Agree',
        'disagree': '❌ Disagree',
        'agreement_required': 'To join the Montelibero Association, you must agree to the Agreement. Without this, joining is impossible.',
        
        # Address input and validation
        'enter_stellar_address': 'Enter your Stellar address:',
        'invalid_address': 'Invalid Stellar address format.',
        'stellar_address_explanation': 'A Stellar address is your unique identifier in the Stellar blockchain. It\'s like a bank account number, but for cryptocurrencies.\n\nI recommend reading the article "Easy entry into tokenomics", the result of which is an airdrop:',
        'checking_address': '👀 So, let\'s see...',
        
        # Trustline check
        'no_trustline': 'You don\'t have a trustline to MTLAP token. MTLAP is a membership token, and without your permission, it cannot be sent to you.',
        'trustline_help': 'If you have questions, contact the Square chat.',
        
        # Recommendation check
        'no_recommendation': 'To join the Montelibero Association, you need a recommendation from a verified member (at least 2 MTLAP tokens).',
        'recommendation_unverified': 'You have a recommendation, but it\'s not from a verified member of the Montelibero Association (at least 2 MTLAP tokens required).',
        'recommendation_help': 'You can get a recommendation from verified member acquaintances or contact the Agora chat.',
        
        # User actions
        'repeat_check': '🔄 Repeat check',
        'back_to_start': 'Back to start',
        
        # Successful completion
        'all_checks_passed': 'Great! All checks passed successfully.',
        'feedback_instruction': 'Now write to the feedback bot:',
        'feedback_text': 'Ready text for copying:',
        'application_text': 'I want to join the Montelibero Association.\nI have read the Agreement and express my full agreement with it.\nMy address: {address}',
        
        # System messages
        'language_changed': 'Language changed to English.',
        'address_already_member': 'This address is already a member of the Montelibero Association!',
        'mtlap_balance_info': 'Balance: {balance} MTLAP',
        'try_different_address': 'Please try a different address'
    },
    'ru': {
        # Приветственное сообщение
        'welcome': 'Этот бот поможет оформить вам заявку на вступление в Ассоциацию Монтелиберо (@MTL_Association). Всего несколько шагов и несколько проверок!',
        
        # Проверка юзернейма
        'no_username': 'У вас нет юзернейма :-(\n\nХотя правила Ассоциации не запрещают аккаунты без юзернеймов, мы не знаем, как работать с участниками без них.',
        'username_guide_text': 'Инструкция по установке юзернейма:',
        'username_installed': '✅ Я установил юзернейм',
        
        # Согласие с условиями
        'agreement_text': 'Чтобы вступить в Ассоциацию Монтелиберо, необходимо выразить согласие с актуальным текстом Соглашения.\n\nПожалуйста, ознакомьтесь с ним:',
        'agree': '✅ Согласен',
        'disagree': '❌ Не согласен',
        'agreement_required': 'Для вступления в Ассоциацию необходимо выразить согласие с Соглашением. Без этого вступление невозможно.',
        
        # Ввод и проверка адреса
        'enter_stellar_address': 'Укажите ваш Stellar-адрес:',
        'invalid_address': 'Неверный формат Stellar-адреса.',
        'stellar_address_explanation': 'Stellar-адрес - это ваш уникальный идентификатор в блокчейне Stellar. Это как номер банковского счета, но для криптовалют.\n\nРекомендую прочитать статью «Лёгкий вход в токеномику», по итогам корой можно получить аирдроп:',
        'checking_address': '👀 Так, сейчас посмотрим...',
        
        # Проверка линии доверия
        'no_trustline': 'У вас нет линии доверия к токену MTLAP. Это наш токен участия, и без вашего разрешения его нельзя будет вам прислать.',
        'trustline_help': 'Если у вас возникли вопросы, обратитесь в чат Площади.',
        
        # Проверка рекомендаций
        'no_recommendation': 'Для вступления в Ассоциацию нужна рекомендация от верифицированного участника (у которого есть как минимум 2 токена MTLAP).',
        'recommendation_unverified': 'У вас есть рекомендация, но она не от верифицированного участника Ассоциации (у которого есть как минимум 2 токена MTLAP).',
        'recommendation_help': 'Рекомендацию можно получить от знакомых верифицированных участников Ассоциации или спросить в чате Площадь.',
        
        # Действия пользователя
        'repeat_check': '🔄 Повторить проверку',
        'back_to_start': 'Вернуться к началу',
        
        # Успешное завершение
        'all_checks_passed': '✅ Отлично! Все проверки пройдены успешно.',
        'feedback_instruction': 'Теперь напишите в бота обратной связи:',
        'feedback_text': 'Готовый текст для копирования:',
        'application_text': 'Хочу вступить в Ассоциацию Монтелиберо.\nСоглашение прочитано и выражаю полное согласие с ним.\nМой адрес: {address}',
        
        # Системные сообщения
        'language_changed': 'Язык изменён на русский.',
        'address_already_member': 'Этот адрес уже является участником Ассоциации!',
        'mtlap_balance_info': 'На счету: {balance} MTLAP',
        'try_different_address': 'Попробуйте указать другой адрес'
    },
}

def get_message(lang: str, key: str) -> str:
    """Получает сообщение на указанном языке"""
    return MESSAGES.get(lang, MESSAGES['en']).get(key, key)
