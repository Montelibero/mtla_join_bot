#!/usr/bin/env python3
"""
Главный файл для запуска MTLA Join Bot
"""

import sys
import os

# Добавляем src в путь для импорта
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from mtla_bot.bot import MTLAJoinBot

if __name__ == '__main__':
    bot = MTLAJoinBot()
    
    try:
        print("🚀 Запуск MTLA Join Bot...")
        bot.run()
    except KeyboardInterrupt:
        print("\n⏹️ Бот остановлен пользователем (Ctrl+C)")
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
    finally:
        print("🔄 Завершение работы бота...")
        bot.cleanup()
        print("✅ Бот завершил работу")
