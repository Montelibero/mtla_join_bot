import unittest
from unittest.mock import Mock

from mtla_bot.admin_tools import AdminTools
from mtla_bot.database import DatabaseOperationError


class AdminFailureSemanticsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.admin = AdminTools.__new__(AdminTools)
        self.admin.state_manager = Mock()

    def test_incomplete_outage_is_not_reported_as_everyone_completed(self) -> None:
        self.admin.state_manager.get_incomplete_users.side_effect = (
            DatabaseOperationError("database_read_failed")
        )

        result = self.admin.get_incomplete_users_report()

        self.assertIn("временно недоступен", result)
        self.assertNotIn("Все пользователи завершили", result)

    def test_reminder_outage_is_not_reported_as_empty(self) -> None:
        self.admin.state_manager.get_users_for_reminder.side_effect = (
            DatabaseOperationError("database_read_failed")
        )

        result = self.admin.get_reminder_candidates()

        self.assertIn("временно недоступен", result)
        self.assertNotIn("Нет пользователей", result)


if __name__ == "__main__":
    unittest.main()
