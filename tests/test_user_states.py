import unittest
from unittest.mock import Mock

from mtla_bot.user_states import UserStateManager


class UserStateCompatibilityTest(unittest.TestCase):
    def test_legacy_unknown_fields_do_not_break_user_loading(self) -> None:
        manager = UserStateManager.__new__(UserStateManager)
        manager.db = Mock()
        manager.db.get_user.return_value = {
            "_id": "mongo-id",
            "user_id": 42,
            "username": None,
            "state": "checking_address",
            "has_any_recommendation": True,
            "recommendation_details": {"legacy": True},
            "future_field": "ignored",
        }

        loaded = manager.get_user(42)

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.user_id, 42)
        self.assertEqual(loaded.state, "checking_address")

    def test_legacy_document_without_username_uses_null(self) -> None:
        manager = UserStateManager.__new__(UserStateManager)
        manager.db = Mock()
        manager.db.get_user.return_value = {"user_id": 42}

        loaded = manager.get_user(42)

        self.assertIsNone(loaded.username)

    def test_finalizing_batch_uses_same_legacy_safe_loader(self) -> None:
        manager = UserStateManager.__new__(UserStateManager)
        manager.db = Mock()
        manager.db.get_finalizing_users.return_value = [
            {
                "_id": "mongo-id",
                "user_id": 42,
                "state": "finalizing",
                "future_field": "ignored",
            }
        ]

        loaded = manager.get_finalizing_users(20, 3)

        self.assertEqual(len(loaded), 1)
        self.assertIsNone(loaded[0].username)
        self.assertEqual(loaded[0].state, "finalizing")
        manager.db.get_finalizing_users.assert_called_once_with(20, 3)


if __name__ == "__main__":
    unittest.main()
