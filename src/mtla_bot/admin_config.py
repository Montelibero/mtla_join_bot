# Конфигурация администраторов бота
# Администраторы теперь настраиваются в .env файле через переменную ADMIN_IDS
# Пример: ADMIN_IDS=3718221,987654321

# Импортируем ADMIN_IDS из config.py
from .config import ADMIN_IDS

# Настройки для автоматических напоминаний
REMINDER_SETTINGS = {
    'default_days_inactive': 7,  # По умолчанию напоминать через 7 дней
    'max_users_per_reminder': 50,  # Максимум пользователей в одном напоминании
    'reminder_cooldown_hours': 24,  # Минимум часов между напоминаниями одному пользователю
}

# Настройки для статистики
STATS_SETTINGS = {
    'max_users_in_report': 20,  # Максимум пользователей в отчете
    'date_format': '%Y-%m-%d %H:%M:%S',  # Формат даты в отчетах
}

# Настройки для логирования
LOGGING_SETTINGS = {
    'log_admin_actions': True,  # Логировать действия администраторов
    'log_user_queries': False,  # Логировать запросы пользователей
    'log_level': 'INFO',  # Уровень логирования
}
