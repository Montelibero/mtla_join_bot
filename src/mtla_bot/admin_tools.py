import logging
from typing import List, Dict
from .user_states import UserStateManager
from . import messages

logger = logging.getLogger(__name__)

class AdminTools:
    """Инструменты для администраторов бота"""
    
    def __init__(self, state_manager: UserStateManager | None = None):
        self.state_manager = state_manager or UserStateManager()
        self._owns_state_manager = state_manager is None
    
    def get_user_statistics(self) -> str:
        """Получает статистику по пользователям в читаемом виде"""
        try:
            stats = self.state_manager.get_user_statistics()
            
            if not stats:
                return "Не удалось получить статистику"
            
            result = "📊 Статистика пользователей:\n\n"
            result += f"👥 Всего пользователей: {stats.get('total_users', 0)}\n"
            result += f"✅ Завершили процесс: {stats.get('completed_users', 0)}\n"
            result += f"🔄 Активных за 24 часа: {stats.get('active_users', 0)}\n\n"
            
            result += "📈 Распределение по состояниям:\n"
            state_dist = stats.get('state_distribution', {})
            for state, count in state_dist.items():
                state_name = self._get_state_name(state)
                result += f"  {state_name}: {count}\n"
            
            return result
        except Exception:
            logger.exception("Error getting statistics")
            return "Статистика временно недоступна из-за ошибки базы данных"
    
    def get_incomplete_users_report(self) -> str:
        """Получает отчет о незавершенных пользователях"""
        try:
            incomplete_users = self.state_manager.get_incomplete_users()
            
            if not incomplete_users:
                return "Все пользователи завершили процесс! 🎉"
            
            result = f"📋 Незавершенные пользователи ({len(incomplete_users)}):\n\n"
            
            for user in incomplete_users[:20]:  # Показываем только первые 20
                username = user.get('username')
                identity = f"@{username}" if username else f"Telegram ID {user.get('user_id', 'Unknown')}"
                state = user.get('state', 'Unknown')
                state_name = self._get_state_name(state)
                created = user.get('created_at', 'Unknown')
                
                result += f"👤 {identity}\n"
                result += f"   📍 Состояние: {state_name}\n"
                result += f"   📅 Создан: {created}\n\n"
            
            if len(incomplete_users) > 20:
                result += f"... и еще {len(incomplete_users) - 20} пользователей"
            
            return result
        except Exception:
            logger.exception("Error getting incomplete users")
            return "Отчёт временно недоступен из-за ошибки базы данных"
    
    def get_reminder_candidates(self, days_inactive: int = 7) -> str:
        """Получает список пользователей для напоминания"""
        try:
            reminder_users = self.state_manager.get_users_for_reminder(days_inactive)
            
            if not reminder_users:
                return f"Нет пользователей для напоминания (неактивны более {days_inactive} дней)"
            
            result = f"🔔 Пользователи для напоминания ({len(reminder_users)}):\n\n"
            
            for user in reminder_users[:15]:  # Показываем только первые 15
                username = user.get('username')
                identity = f"@{username}" if username else f"Telegram ID {user.get('user_id', 'Unknown')}"
                state = user.get('state', 'Unknown')
                state_name = self._get_state_name(state)
                last_activity = user.get('last_activity', 'Unknown')
                
                result += f"👤 {identity}\n"
                result += f"   📍 Состояние: {state_name}\n"
                result += f"   ⏰ Последняя активность: {last_activity}\n\n"
            
            if len(reminder_users) > 15:
                result += f"... и еще {len(reminder_users) - 15} пользователей"
            
            return result
        except Exception:
            logger.exception("Error getting reminder candidates")
            return "Список временно недоступен из-за ошибки базы данных"
    
    def get_user_details(self, user_id: int) -> str:
        """Получает детальную информацию о пользователе"""
        try:
            user = self.state_manager.get_user(user_id)
            
            if not user:
                return f"Пользователь с ID {user_id} не найден"
            
            identity = f"@{user.username}" if user.username else f"Telegram ID {user.user_id}"
            result = f"👤 Детали пользователя {identity}:\n\n"
            result += f"🆔 ID: {user.user_id}\n"
            result += f"🌐 Язык: {user.language}\n"
            result += f"📍 Состояние: {self._get_state_name(user.state)}\n"
            result += f"📅 Создан: {user.created_at}\n"
            result += f"⏰ Последняя активность: {user.last_activity}\n\n"
            
            result += "📊 Прогресс:\n"
            if user.progress:
                progress = user.progress
                result += f"  ✅ Юзернейм: {'Да' if progress.get('username_check') else 'Нет'}\n"
                result += f"  ✅ Согласие с условиями: {'Да' if progress.get('agreement') else 'Нет'}\n"
                result += f"  ✅ Адрес введен: {'Да' if progress.get('address_entered') else 'Нет'}\n"
                result += f"  ✅ Линия доверия: {'Да' if progress.get('trustline_check') else 'Нет'}\n"
                result += f"  ✅ Рекомендация: {'Да' if progress.get('recommendation') else 'Нет'}\n"
            
            if user.stellar_address:
                result += f"\n💎 Стеллар адрес: {user.stellar_address}"
            
            if user.recommender_username:
                result += f"\n👥 Рекомендатель: @{user.recommender_username}"
            
            return result
        except Exception:
            logger.exception("Error getting user details")
            return "Детали временно недоступны из-за ошибки базы данных"
    
    def _get_state_name(self, state: str) -> str:
        """Преобразует состояние в читаемое название"""
        state_names = {
            'checking_username': 'Проверка юзернейма',
            'agreement': 'Согласие с условиями',
            'entering_address': 'Ввод адреса',
            'checking_address': 'Проверка адреса',
            'finalizing': 'Доставка результата',
            'completed': 'Завершено'
        }
        return state_names.get(state, state)
    
    def close_connection(self):
        """Закрывает соединение с базой данных"""
        if self._owns_state_manager:
            self.state_manager.close_connection()

# Пример использования
if __name__ == "__main__":
    admin = AdminTools()
    
    print("=== Статистика ===")
    print(admin.get_user_statistics())
    
    print("\n=== Незавершенные пользователи ===")
    print(admin.get_incomplete_users_report())
    
    print("\n=== Кандидаты для напоминания ===")
    print(admin.get_reminder_candidates())
    
    admin.close_connection()
