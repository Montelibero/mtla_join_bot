from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
import logging
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from . import config

logger = logging.getLogger(__name__)


class DatabaseOperationError(RuntimeError):
    """Stable storage failure that is distinct from a missing record."""

class DatabaseManager:
    """Менеджер базы данных MongoDB"""
    
    def __init__(self):
        self.client = None
        self.db = None
        self.collection = None
        self.connect()
    
    def connect(self):
        """Подключение к MongoDB"""
        try:
            self.client = MongoClient(
                config.MONGODB_URI,
                appname="MTLAJoinBot",
                serverSelectionTimeoutMS=5_000,
                connectTimeoutMS=3_000,
                socketTimeoutMS=5_000,
            )
            # Проверяем подключение
            self.client.admin.command('ping')
            self.db = self.client[config.MONGODB_DB]
            self.collection = self.db[config.MONGODB_COLLECTION]
            
            # Создаем индексы
            self.collection.create_index("user_id", unique=True)
            self.collection.create_index("state")
            self.collection.create_index("created_at")
            self.collection.create_index("last_activity")
            self.collection.create_index([
                ("state", 1),
                ("final_delivery_lease_until", 1),
                ("last_activity", 1),
            ])
            
            logger.info("Successfully connected to MongoDB")
        except ConnectionFailure as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error connecting to MongoDB: {e}")
            raise
    
    def close(self):
        """Закрытие соединения с MongoDB"""
        if self.client:
            self.client.close()
    
    def get_user(self, user_id: int) -> Optional[Dict]:
        """Получает пользователя по ID"""
        try:
            return self.collection.find_one({"user_id": user_id})
        except Exception as exc:
            logger.exception("Error getting user %s", user_id)
            raise DatabaseOperationError("database_read_failed") from exc
    
    def create_user(
        self,
        user_id: int,
        username: Optional[str],
        language: str = 'ru',
        attempt_id: Optional[str] = None,
    ) -> bool:
        """Создает нового пользователя"""
        try:
            user_data = {
                "user_id": user_id,
                "username": username,
                "attempt_id": attempt_id,
                "language": language,
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
                "created_at": datetime.utcnow(),
                "last_activity": datetime.utcnow(),
                "progress": {
                    "username_check": False,
                    "agreement": False,
                    "address_entered": False,
                    "trustline_check": False,
                    "recommendation": False
                }
            }
            
            result = self.collection.insert_one(user_data)
            logger.info(f"Created user {user_id}: {result.inserted_id}")
            return True
        except Exception as e:
            logger.error(f"Error creating user {user_id}: {e}")
            return False
    
    def update_user(self, user_id: int, update_data: Dict) -> bool:
        """Обновляет данные пользователя"""
        try:
            update_data["last_activity"] = datetime.utcnow()
            result = self.collection.update_one(
                {"user_id": user_id},
                {"$set": update_data}
            )
            return result.matched_count == 1
        except Exception as e:
            logger.error(f"Error updating user {user_id}: {e}")
            return False
    
    def update_user_state(self, user_id: int, state: str) -> bool:
        """Обновляет состояние пользователя"""
        return self.update_user(user_id, {"state": state})

    def begin_new_attempt(
        self,
        user_id: int,
        username: Optional[str],
        language: str,
        attempt_id: str,
    ) -> bool:
        """Atomically replace the current candidate flow with a fresh attempt."""

        try:
            result = self.collection.update_one(
                {"user_id": user_id},
                {"$set": {
                    "username": username,
                    "language": language,
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
                    "last_activity": datetime.utcnow(),
                    "progress": {
                        "username_check": False,
                        "agreement": False,
                        "address_entered": False,
                        "trustline_check": False,
                        "recommendation": False,
                    },
                }},
            )
            return result.matched_count == 1
        except Exception:
            logger.exception("Error starting a new attempt for user %s", user_id)
            return False

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
        """Persist one verified snapshot only for the expected active attempt."""

        try:
            result = self.collection.update_one(
                {
                    "user_id": user_id,
                    "attempt_id": attempt_id,
                    "state": expected_state,
                },
                {"$set": {
                    "stellar_address": address,
                    "has_trustline": has_trustline,
                    "candidate_mtlap_balance": candidate_mtlap_balance,
                    "has_recommendation": has_recommendation,
                    "state": next_state,
                    "last_activity": datetime.utcnow(),
                    "progress.address_entered": True,
                    "progress.trustline_check": has_trustline,
                    "progress.recommendation": has_recommendation,
                    "final_delivery_attempts": 0,
                    "final_delivery_lease_id": None,
                    "final_delivery_lease_until": None,
                    "final_delivery_last_error": None,
                    "final_delivery_last_attempt_at": None,
                    "final_delivery_message_id": None,
                    "final_delivered_at": None,
                }},
            )
            return result.matched_count == 1
        except Exception:
            logger.exception(
                "Error recording eligibility snapshot for user %s",
                user_id,
            )
            return False

    def update_attempt_fields(
        self,
        user_id: int,
        attempt_id: str,
        expected_state: str,
        update_data: Dict,
    ) -> bool:
        """Conditionally update facts without changing the active phase."""

        try:
            persisted = dict(update_data)
            persisted["last_activity"] = datetime.utcnow()
            result = self.collection.update_one(
                {
                    "user_id": user_id,
                    "attempt_id": attempt_id,
                    "state": expected_state,
                },
                {"$set": persisted},
            )
            return result.matched_count == 1
        except Exception:
            logger.exception("Error updating active attempt for user %s", user_id)
            return False

    def transition_attempt(
        self,
        user_id: int,
        attempt_id: str,
        expected_state: str,
        next_state: str,
        update_data: Optional[Dict] = None,
    ) -> bool:
        """Atomically move only the expected active attempt to its next phase."""

        persisted = dict(update_data or {})
        persisted["state"] = next_state
        return self.update_attempt_fields(
            user_id,
            attempt_id,
            expected_state,
            persisted,
        )

    def complete_attempt(
        self,
        user_id: int,
        attempt_id: str,
        delivery_lease_id: str,
        delivery_message_id: Optional[int] = None,
    ) -> bool:
        """Mark only the verified active attempt as completed."""

        try:
            result = self.collection.update_one(
                {
                    "user_id": user_id,
                    "attempt_id": attempt_id,
                    "state": "finalizing",
                    "final_delivery_lease_id": delivery_lease_id,
                    "agreed_to_terms": True,
                    "has_trustline": True,
                    "candidate_mtlap_balance": "0",
                    "has_recommendation": True,
                    "stellar_address": {"$type": "string", "$ne": ""},
                },
                {"$set": {
                    "state": "completed",
                    "final_delivery_message_id": delivery_message_id,
                    "final_delivered_at": datetime.utcnow(),
                    "final_delivery_lease_id": None,
                    "final_delivery_lease_until": None,
                    "final_delivery_last_error": None,
                    "last_activity": datetime.utcnow(),
                }},
            )
            return result.matched_count == 1
        except Exception:
            logger.exception("Error completing attempt for user %s", user_id)
            return False

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
        """Atomically reserve one final delivery, bounding autonomous sends."""

        if lease_seconds < 1 or max_attempts < 1:
            raise ValueError("delivery limits must be positive")
        if not isinstance(automatic, bool):
            raise ValueError("automatic must be a boolean")
        now = datetime.utcnow()
        claim_conditions = [
            {"$or": [
                {"final_delivery_lease_until": {"$exists": False}},
                {"final_delivery_lease_until": None},
                {"final_delivery_lease_until": {"$lte": now}},
            ]},
        ]
        increments = {"final_delivery_attempts": 1}
        if automatic:
            claim_conditions.insert(0, {"$or": [
                {"final_delivery_attempts": {"$exists": False}},
                {"final_delivery_attempts": {"$lt": max_attempts}},
            ]})
        try:
            result = self.collection.update_one(
                {
                    "user_id": user_id,
                    "attempt_id": attempt_id,
                    "state": "finalizing",
                    "agreed_to_terms": True,
                    "has_trustline": True,
                    "candidate_mtlap_balance": "0",
                    "has_recommendation": True,
                    "stellar_address": {"$type": "string", "$ne": ""},
                    "$and": claim_conditions,
                },
                {
                    "$inc": increments,
                    "$set": {
                        "final_delivery_lease_id": delivery_lease_id,
                        "final_delivery_lease_until": now + timedelta(
                            seconds=lease_seconds
                        ),
                        "final_delivery_last_attempt_at": now,
                        "final_delivery_last_error": None,
                        "last_activity": now,
                    },
                },
            )
            return result.matched_count == 1
        except Exception:
            logger.exception("Error claiming final delivery for user %s", user_id)
            return False

    def defer_final_delivery(
        self,
        user_id: int,
        attempt_id: str,
        delivery_lease_id: str,
        *,
        retry_seconds: int,
        error_code: str,
    ) -> bool:
        """Release a failed delivery claim with a bounded retry delay."""

        if retry_seconds < 1:
            raise ValueError("retry_seconds must be positive")
        now = datetime.utcnow()
        try:
            result = self.collection.update_one(
                {
                    "user_id": user_id,
                    "attempt_id": attempt_id,
                    "state": "finalizing",
                    "final_delivery_lease_id": delivery_lease_id,
                },
                {"$set": {
                    "final_delivery_lease_id": None,
                    "final_delivery_lease_until": now + timedelta(
                        seconds=retry_seconds
                    ),
                    "final_delivery_last_error": error_code,
                    "last_activity": now,
                }},
            )
            return result.matched_count == 1
        except Exception:
            logger.exception("Error deferring final delivery for user %s", user_id)
            return False
    
    def update_user_progress(self, user_id: int, progress_key: str, value: bool) -> bool:
        """Обновляет прогресс пользователя"""
        return self.update_user(user_id, {
            f"progress.{progress_key}": value
        })
    
    def set_stellar_address(self, user_id: int, address: str) -> bool:
        """Устанавливает Стеллар адрес пользователя"""
        return self.update_user(user_id, {
            "stellar_address": address,
            "progress.address_entered": True
        })
    
    def set_username_status(self, user_id: int, has_username: bool) -> bool:
        """Устанавливает статус наличия юзернейма"""
        return self.update_user(user_id, {
            "has_username": has_username,
            "progress.username_check": has_username
        })
    
    def set_agreement_status(self, user_id: int, agreed: bool) -> bool:
        """Устанавливает статус согласия с условиями"""
        return self.update_user(user_id, {
            "agreed_to_terms": agreed,
            "progress.agreement": agreed
        })
    
    def set_trustline_status(self, user_id: int, has_trustline: bool) -> bool:
        """Устанавливает статус линии доверия"""
        return self.update_user(user_id, {
            "has_trustline": has_trustline,
            "progress.trustline_check": has_trustline
        })
    
    def set_recommendation(self, user_id: int, recommender_username: str) -> bool:
        """Устанавливает рекомендателя"""
        return self.update_user(user_id, {
            "has_recommendation": True,
            "recommender_username": recommender_username,
            "progress.recommendation": True
        })
    
    def reset_user(self, user_id: int) -> bool:
        """Сбрасывает данные пользователя"""
        try:
            result = self.collection.delete_one({"user_id": user_id})
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"Error resetting user {user_id}: {e}")
            return False
    
    def get_users_by_state(self, state: str) -> List[Dict]:
        """Получает всех пользователей с определенным состоянием"""
        try:
            return list(self.collection.find({"state": state}))
        except Exception as exc:
            logger.exception("Error getting users by state %s", state)
            raise DatabaseOperationError("database_read_failed") from exc

    def get_finalizing_users(
        self,
        limit: int = 20,
        max_attempts: int = 3,
    ) -> List[Dict]:
        """Return the oldest pending final deliveries in a bounded batch."""

        if not 1 <= limit <= 100 or max_attempts < 1:
            raise ValueError("invalid finalization batch limits")
        now = datetime.utcnow()
        try:
            cursor = (
                self.collection.find({
                    "state": "finalizing",
                    "agreed_to_terms": True,
                    "has_trustline": True,
                    "candidate_mtlap_balance": "0",
                    "has_recommendation": True,
                    "stellar_address": {"$type": "string", "$ne": ""},
                    "attempt_id": {"$type": "string", "$ne": ""},
                    "$and": [
                        {"$or": [
                            {"final_delivery_attempts": {"$exists": False}},
                            {"final_delivery_attempts": {"$lt": max_attempts}},
                        ]},
                        {"$or": [
                            {"final_delivery_lease_until": {"$exists": False}},
                            {"final_delivery_lease_until": None},
                            {"final_delivery_lease_until": {"$lte": now}},
                        ]},
                    ],
                })
                .sort("last_activity", 1)
                .limit(limit)
            )
            return list(cursor)
        except Exception as exc:
            logger.exception("Error getting finalizing users")
            raise DatabaseOperationError("database_read_failed") from exc
    
    def get_incomplete_users(self) -> List[Dict]:
        """Получает пользователей, которые не завершили процесс"""
        try:
            return list(self.collection.find({
                "state": {"$ne": "completed"}
            }))
        except Exception as exc:
            logger.exception("Error getting incomplete users")
            raise DatabaseOperationError("database_read_failed") from exc
    
    def get_users_for_reminder(self, days_inactive: int = 7) -> List[Dict]:
        """Получает пользователей для напоминания (неактивных N дней)"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_inactive)
            
            return list(self.collection.find({
                "state": {"$ne": "completed"},
                "last_activity": {"$lt": cutoff_date}
            }))
        except Exception as exc:
            logger.exception("Error getting users for reminder")
            raise DatabaseOperationError("database_read_failed") from exc
    
    def get_user_statistics(self) -> Dict:
        """Получает статистику по пользователям"""
        try:
            total_users = self.collection.count_documents({})
            completed_users = self.collection.count_documents({"state": "completed"})
            active_users = self.collection.count_documents({
                "last_activity": {"$gte": datetime.utcnow() - timedelta(days=1)}
            })
            
            state_stats = {}
            pipeline = [
                {"$group": {"_id": "$state", "count": {"$sum": 1}}}
            ]
            
            for doc in self.collection.aggregate(pipeline):
                state_stats[doc["_id"]] = doc["count"]
            
            return {
                "total_users": total_users,
                "completed_users": completed_users,
                "active_users": active_users,
                "state_distribution": state_stats
            }
        except Exception as exc:
            logger.exception("Error getting user statistics")
            raise DatabaseOperationError("database_read_failed") from exc
