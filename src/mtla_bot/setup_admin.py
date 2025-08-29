#!/usr/bin/env python3
"""
Скрипт для настройки администраторов бота
"""

import os
import sys
from dotenv import load_dotenv

def get_user_id():
    """Получает ID пользователя от пользователя"""
    print("🔍 Для получения вашего Telegram ID:")
    print("1. Напишите боту @userinfobot")
    print("2. Скопируйте ваш ID (число)")
    print("3. Введите его ниже")
    
    while True:
        try:
            user_id = input("Введите ваш Telegram ID: ").strip()
            if user_id.isdigit():
                return int(user_id)
            else:
                print("❌ ID должен быть числом. Попробуйте снова.")
        except KeyboardInterrupt:
            print("\n\n❌ Отменено пользователем")
            sys.exit(1)

def update_admin_config(user_id):
    """Обновляет конфигурацию администраторов"""
    config_content = f"""# Конфигурация администраторов бота
# Замените ID на реальные ID администраторов

# Список ID администраторов (получить можно у @userinfobot)
ADMIN_IDS = [
    {user_id},  # Ваш ID
    # 987654321,  # Добавьте других администраторов
]

# Настройки для автоматических напоминаний
REMINDER_SETTINGS = {{
    'default_days_inactive': 7,  # По умолчанию напоминать через 7 дней
    'max_users_per_reminder': 50,  # Максимум пользователей в одном напоминании
    'reminder_cooldown_hours': 24,  # Минимум часов между напоминаниями одному пользователю
}}

# Настройки для статистики
STATS_SETTINGS = {{
    'max_users_in_report': 20,  # Максимум пользователей в отчете
    'date_format': '%Y-%m-%d %H:%M:%S',  # Формат даты в отчетах
}}

# Настройки для логирования
LOGGING_SETTINGS = {{
    'log_admin_actions': True,  # Логировать действия администраторов
    'log_user_queries': False,  # Логировать запросы пользователей
    'log_level': 'INFO',  # Уровень логирования
}}
"""
    
    try:
        with open('admin_config.py', 'w', encoding='utf-8') as f:
            f.write(config_content)
        print("✅ Конфигурация администраторов обновлена!")
        return True
    except Exception as e:
        print(f"❌ Ошибка при обновлении конфигурации: {e}")
        return False

def main():
    """Основная функция"""
    print("🔧 Настройка администраторов MTLA Join Bot")
    print("=" * 50)
    
    # Проверяем, существует ли файл конфигурации
    if os.path.exists('admin_config.py'):
        print("📁 Файл admin_config.py уже существует")
        response = input("Хотите перезаписать его? (y/N): ").strip().lower()
        if response != 'y':
            print("❌ Отменено пользователем")
            return
    
    # Получаем ID пользователя
    user_id = get_user_id()
    
    # Обновляем конфигурацию
    if update_admin_config(user_id):
        print(f"\n🎉 Вы успешно добавлены как администратор!")
        print(f"🆔 Ваш ID: {user_id}")
        print("\n📋 Теперь вы можете использовать административные команды:")
        print("  /stats - Статистика по пользователям")
        print("  /incomplete - Незавершенные пользователи")
        print("  /reminders - Кандидаты для напоминания")
        print("  /user_info - Детали пользователя")
        print("  /help_admin - Справка по командам")
        print("\n⚠️  Не забудьте перезапустить бота после изменения конфигурации!")

if __name__ == "__main__":
    main()
