from enum import Enum
from dataclasses import dataclass, fields
from typing import Optional
from .database import DatabaseManager

class UserState(Enum):
    """Состояния пользователя в процессе проверки"""
    CHECKING_USERNAME = "checking_username"
    AGREEMENT = "agreement"
    ENTERING_ADDRESS = "entering_address"
    CHECKING_ADDRESS = "checking_address"
    FINALIZING = "finalizing"
    COMPLETED = "completed"

@dataclass
class UserData:
    """Данные пользователя"""
    user_id: int
    username: Optional[str]
    attempt_id: Optional[str] = None
    language: str = 'ru'
    state: str = 'checking_username'
    stellar_address: Optional[str] = None
    has_username: bool = False
    username_warning_acknowledged: bool = False
    agreed_to_terms: bool = False
    has_trustline: bool = False
    candidate_mtlap_balance: Optional[str] = None
    has_recommendation: bool = False
    recommender_username: Optional[str] = None
    final_delivery_attempts: int = 0
    final_delivery_lease_id: Optional[str] = None
    final_delivery_lease_until: Optional[object] = None
    final_delivery_last_error: Optional[str] = None
    final_delivery_last_attempt_at: Optional[object] = None
    final_delivery_message_id: Optional[int] = None
    final_delivered_at: Optional[object] = None
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
            return self._from_document(user_doc)
        return None

    @staticmethod
    def _from_document(user_doc: dict) -> UserData:
        """Load current and legacy MongoDB documents into the stable model."""

        allowed_fields = {field.name for field in fields(UserData)}
        filtered_doc = {
            key: value
            for key, value in user_doc.items()
            if key in allowed_fields
        }
        filtered_doc.setdefault("username", None)
        return UserData(**filtered_doc)
    
    def create_user(
        self,
        user_id: int,
        username: Optional[str],
        language: str = 'ru',
        attempt_id: Optional[str] = None,
    ) -> bool:
        """Создает нового пользователя в базе данных"""
        return self.db.create_user(user_id, username, language, attempt_id)
    
    def update_user(self, user_id: int, update_data: dict) -> bool:
        """Обновляет данные пользователя"""
        return self.db.update_user(user_id, update_data)
    
    def update_state(self, user_id: int, state: UserState):
        """Обновляет состояние пользователя"""
        return self.db.update_user_state(user_id, state.value)

    def begin_new_attempt(
        self,
        user_id: int,
        username: Optional[str],
        language: str,
        attempt_id: str,
    ) -> bool:
        """Atomically begin a fresh flow for an existing user."""

        return self.db.begin_new_attempt(
            user_id,
            username,
            language,
            attempt_id,
        )

    def record_eligibility_snapshot(
        self,
        user_id: int,
        attempt_id: str,
        expected_state: str,
        address: str,
        has_trustline: bool,
        candidate_mtlap_balance: str,
        has_recommendation: bool,
        next_state: str,
    ) -> bool:
        """Persist eligibility facts only for the active attempt and phase."""

        return self.db.record_eligibility_snapshot(
            user_id,
            attempt_id,
            expected_state,
            address,
            has_trustline,
            candidate_mtlap_balance,
            has_recommendation,
            next_state,
        )

    def update_attempt_fields(
        self,
        user_id: int,
        attempt_id: str,
        expected_state: str,
        update_data: dict,
    ) -> bool:
        return self.db.update_attempt_fields(
            user_id,
            attempt_id,
            expected_state,
            update_data,
        )

    def transition_attempt(
        self,
        user_id: int,
        attempt_id: str,
        expected_state: str,
        next_state: str,
        update_data: Optional[dict] = None,
    ) -> bool:
        return self.db.transition_attempt(
            user_id,
            attempt_id,
            expected_state,
            next_state,
            update_data,
        )

    def complete_attempt(
        self,
        user_id: int,
        attempt_id: str,
        delivery_lease_id: str,
        delivery_message_id: Optional[int] = None,
    ) -> bool:
        """Complete only an active attempt with persisted eligibility facts."""

        return self.db.complete_attempt(
            user_id,
            attempt_id,
            delivery_lease_id,
            delivery_message_id,
        )

    def claim_final_delivery(
        self,
        user_id: int,
        attempt_id: str,
        delivery_lease_id: str,
        *,
        lease_seconds: int,
        automatic: bool,
        max_attempts: int,
    ) -> bool:
        return self.db.claim_final_delivery(
            user_id,
            attempt_id,
            delivery_lease_id,
            lease_seconds=lease_seconds,
            automatic=automatic,
            max_attempts=max_attempts,
        )

    def defer_final_delivery(
        self,
        user_id: int,
        attempt_id: str,
        delivery_lease_id: str,
        *,
        retry_seconds: int,
        error_code: str,
    ) -> bool:
        return self.db.defer_final_delivery(
            user_id,
            attempt_id,
            delivery_lease_id,
            retry_seconds=retry_seconds,
            error_code=error_code,
        )
    
    def update_language(self, user_id: int, language: str):
        """Обновляет язык пользователя"""
        return self.db.update_user(user_id, {"language": language})
    
    def set_stellar_address(self, user_id: int, address: str):
        """Устанавливает Стеллар адрес пользователя"""
        return self.db.set_stellar_address(user_id, address)
    
    def set_username_status(self, user_id: int, has_username: bool):
        """Устанавливает статус наличия юзернейма"""
        return self.db.set_username_status(user_id, has_username)

    def acknowledge_username_warning(self, user_id: int):
        """Фиксирует явное решение продолжить без Telegram username."""
        return self.db.update_user(user_id, {"username_warning_acknowledged": True})
    
    def set_agreement_status(self, user_id: int, agreed: bool):
        """Устанавливает статус согласия с условиями"""
        return self.db.set_agreement_status(user_id, agreed)
    
    def set_trustline_status(self, user_id: int, has_trustline: bool):
        """Устанавливает статус линии доверия"""
        return self.db.set_trustline_status(user_id, has_trustline)
    
    def set_recommendation_status(self, user_id: int, has_recommendation: bool):
        """Устанавливает статус рекомендации"""
        return self.db.update_user(user_id, {
            "has_recommendation": has_recommendation,
            "progress.recommendation": has_recommendation,
        })
    
    def set_recommender(self, user_id: int, recommender_username: str):
        """Устанавливает рекомендателя"""
        self.db.set_recommendation(user_id, recommender_username)
    
    def reset_user(self, user_id: int):
        """Сбрасывает данные пользователя"""
        self.db.reset_user(user_id)
    
    def reset_user_progress(self, user_id: int, attempt_id: str):
        """Сбрасывает прогресс пользователя, но сохраняет базовую информацию"""
        return self.db.update_user(user_id, {
            "attempt_id": attempt_id,
            "state": "checking_username",
            "has_username": False,
            "username_warning_acknowledged": False,
            "agreed_to_terms": False,
            "stellar_address": None,
            "has_trustline": False,
            "candidate_mtlap_balance": None,
            "has_recommendation": False,
            "recommender_username": None,
            "final_delivery_attempts": 0,
            "final_delivery_lease_id": None,
            "final_delivery_lease_until": None,
            "final_delivery_last_error": None,
            "final_delivery_last_attempt_at": None,
            "final_delivery_message_id": None,
            "final_delivered_at": None,
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

    def get_finalizing_users(
        self,
        limit: int = 20,
        max_attempts: int = 3,
    ) -> list[UserData]:
        """Return a bounded batch for autonomous final-message redelivery."""

        return [
            self._from_document(document)
            for document in self.db.get_finalizing_users(limit, max_attempts)
        ]
    
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
