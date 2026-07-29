#!/usr/bin/env python3
"""
Главный файл для запуска MTLA Join Bot
"""

import sys
import os
import logging

# Добавляем src в путь для импорта
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from mtla_bot.bot import MTLAJoinBot
from mtla_bot.config import ConfigurationError

logger = logging.getLogger(__name__)

def main() -> int:
    """Run the bot while keeping startup failures inside protected logging."""

    bot = None
    exit_code = 0
    try:
        bot = MTLAJoinBot()
        print("🚀 Запуск MTLA Join Bot...")
        bot.run()
    except KeyboardInterrupt:
        print("\n⏹️ Бот остановлен пользователем (Ctrl+C)")
    except ConfigurationError as error:
        logger.error("Configuration error: %s", error)
        exit_code = 2
    except Exception:
        logger.exception("Unexpected error while running the bot")
        exit_code = 1
    finally:
        print("🔄 Завершение работы бота...")
        if bot is not None:
            bot.cleanup()
        if exit_code:
            print("❌ Бот остановлен из-за ошибки")
        else:
            print("✅ Бот завершил работу")

    return exit_code


if __name__ == '__main__':
    sys.exit(main())
