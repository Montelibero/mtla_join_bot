from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
import logging
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from . import config

logger = logging.getLogger(__name__)

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
            self.client = MongoClient(config.MONGODB_URI)
            # Проверяем подключение
            self.client.admin.command('ping')
            self.db = self.client[config.MONGODB_DB]
            self.collection = self.db[config.MONGODB_COLLECTION]
            
            # Создаем индексы
            self.collection.create_index("user_id", unique=True)
            self.collection.create_index("state")
            self.collection.create_index("created_at")
            self.collection.create_index("last_activity")
            
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
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None
    
    def create_user(self, user_id: int, username: str, language: str = 'ru') -> bool:
        """Создает нового пользователя"""
        try:
            user_data = {
                "user_id": user_id,
                "username": username,
                "language": language,
                "state": "checking_username",
                "has_username": False,
                "agreed_to_terms": False,
                "stellar_address": None,
                "has_trustline": False,
                "has_recommendation": False,
                "recommender_username": None,
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
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error updating user {user_id}: {e}")
            return False
    
    def update_user_state(self, user_id: int, state: str) -> bool:
        """Обновляет состояние пользователя"""
        return self.update_user(user_id, {"state": state})
    
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
        except Exception as e:
            logger.error(f"Error getting users by state {state}: {e}")
            return []
    
    def get_incomplete_users(self) -> List[Dict]:
        """Получает пользователей, которые не завершили процесс"""
        try:
            return list(self.collection.find({
                "state": {"$ne": "completed"}
            }))
        except Exception as e:
            logger.error(f"Error getting incomplete users: {e}")
            return []
    
    def get_users_for_reminder(self, days_inactive: int = 7) -> List[Dict]:
        """Получает пользователей для напоминания (неактивных N дней)"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_inactive)
            
            return list(self.collection.find({
                "state": {"$ne": "completed"},
                "last_activity": {"$lt": cutoff_date}
            }))
        except Exception as e:
            logger.error(f"Error getting users for reminder: {e}")
            return []
    
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
        except Exception as e:
            logger.error(f"Error getting user statistics: {e}")
            return {}
