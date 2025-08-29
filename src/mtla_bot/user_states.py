from enum import Enum
from dataclasses import dataclass
from typing import Optional
from .database import DatabaseManager

class UserState(Enum):
    """Состояния пользователя в процессе проверки"""
    CHECKING_USERNAME = "checking_username"
    AGREEMENT = "agreement"
    ENTERING_ADDRESS = "entering_address"
    CHECKING_ADDRESS = "checking_address"
    COMPLETED = "completed"

@dataclass
class UserData:
    """Данные пользователя"""
    user_id: int
    username: str
    language: str = 'ru'
    state: str = 'checking_username'
    stellar_address: Optional[str] = None
    has_username: bool = False
    agreed_to_terms: bool = False
    has_trustline: bool = False
    has_recommendation: bool = False
    recommender_username: Optional[str] = None
    created_at: Optional[str] = None
    last_activity: Optional[str] = None
    progress: Optional[dict] = None

class UserStateManager:
    """Менеджер состояний пользователей с MongoDB"""
    
    def __init__(self):
        self.db = DatabaseManager()
    
    def get_user(self, user_id: int) -> Optional[UserData]:
        """Получает пользователя из базы данных"""
        user_doc = self.db.get_user(user_id)
        if user_doc:
            # Фильтруем MongoDB-специфичные поля
            filtered_doc = {k: v for k, v in user_doc.items() if not k.startswith('_')}
            return UserData(**filtered_doc)
        return None
    
    def create_user(self, user_id: int, username: str, language: str = 'ru') -> bool:
        """Создает нового пользователя в базе данных"""
        return self.db.create_user(user_id, username, language)
    
    def update_user(self, user_id: int, update_data: dict) -> bool:
        """Обновляет данные пользователя"""
        return self.db.update_user(user_id, update_data)
    
    def update_state(self, user_id: int, state: UserState):
        """Обновляет состояние пользователя"""
        self.db.update_user_state(user_id, state.value)
    
    def update_language(self, user_id: int, language: str):
        """Обновляет язык пользователя"""
        self.db.update_user(user_id, {"language": language})
    
    def set_stellar_address(self, user_id: int, address: str):
        """Устанавливает Стеллар адрес пользователя"""
        self.db.set_stellar_address(user_id, address)
    
    def set_username_status(self, user_id: int, has_username: bool):
        """Устанавливает статус наличия юзернейма"""
        self.db.set_username_status(user_id, has_username)
    
    def set_agreement_status(self, user_id: int, agreed: bool):
        """Устанавливает статус согласия с условиями"""
        self.db.set_agreement_status(user_id, agreed)
    
    def set_trustline_status(self, user_id: int, has_trustline: bool):
        """Устанавливает статус линии доверия"""
        self.db.set_trustline_status(user_id, has_trustline)
    
    def set_recommendation_status(self, user_id: int, has_recommendation: bool):
        """Устанавливает статус рекомендации"""
        self.db.update_user(user_id, {"has_recommendation": has_recommendation})
    
    def set_recommender(self, user_id: int, recommender_username: str):
        """Устанавливает рекомендателя"""
        self.db.set_recommendation(user_id, recommender_username)
    
    def reset_user(self, user_id: int):
        """Сбрасывает данные пользователя"""
        self.db.reset_user(user_id)
    
    def reset_user_progress(self, user_id: int):
        """Сбрасывает прогресс пользователя, но сохраняет базовую информацию"""
        self.db.update_user(user_id, {
            "state": "checking_username",
            "has_username": False,
            "agreed_to_terms": False,
            "stellar_address": None,
            "has_trustline": False,
            "has_recommendation": False,
            "recommender_username": None,
            "progress": {
                "username_check": False,
                "agreement": False,
                "address_entered": False,
                "trustline_check": False,
                "recommendation": False
            }
        })
    
    def get_user_progress(self, user_id: int) -> dict:
        """Получает прогресс пользователя"""
        user = self.get_user(user_id)
        if user and user.progress:
            return user.progress
        return {}
    
    def get_users_by_state(self, state: str) -> list:
        """Получает всех пользователей с определенным состоянием"""
        return self.db.get_users_by_state(state)
    
    def get_incomplete_users(self) -> list:
        """Получает пользователей, которые не завершили процесс"""
        return self.db.get_incomplete_users()
    
    def get_users_for_reminder(self, days_inactive: int = 7) -> list:
        """Получает пользователей для напоминания"""
        return self.db.get_users_for_reminder(days_inactive)
    
    def get_user_statistics(self) -> dict:
        """Получает статистику по пользователям"""
        return self.db.get_user_statistics()
    
    def close_connection(self):
        """Закрывает соединение с базой данных"""
        self.db.close()
