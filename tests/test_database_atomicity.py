from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from mtla_bot.database import DatabaseManager, DatabaseOperationError


class DatabaseAtomicityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.database = DatabaseManager.__new__(DatabaseManager)
        self.database.collection = Mock()

    def test_unchanged_but_matched_update_is_successful(self) -> None:
        self.database.collection.update_one.return_value = SimpleNamespace(
            matched_count=1,
            modified_count=0,
        )

        self.assertTrue(self.database.update_user(42, {"state": "agreement"}))

    def test_new_attempt_is_one_atomic_update(self) -> None:
        self.database.collection.update_one.return_value = SimpleNamespace(
            matched_count=1,
        )

        result = self.database.begin_new_attempt(
            42,
            None,
            "ru",
            "attempt-new",
        )

        self.assertTrue(result)
        query, update = self.database.collection.update_one.call_args.args
        self.assertEqual(query, {"user_id": 42})
        persisted = update["$set"]
        self.assertEqual(persisted["attempt_id"], "attempt-new")
        self.assertEqual(persisted["state"], "checking_username")
        self.assertIsNone(persisted["stellar_address"])
        self.assertFalse(persisted["agreed_to_terms"])
        self.assertIsNone(persisted["final_delivery_message_id"])
        self.assertIsNone(persisted["final_delivered_at"])
        self.assertIsNone(persisted["final_delivery_last_attempt_at"])

    def test_snapshot_is_conditional_on_attempt_and_phase(self) -> None:
        self.database.collection.update_one.return_value = SimpleNamespace(
            matched_count=1,
        )

        result = self.database.record_eligibility_snapshot(
            42,
            "attempt-current",
            "entering_address",
            "G" + "A" * 55,
            True,
            "0",
            True,
            "checking_address",
        )

        self.assertTrue(result)
        query, update = self.database.collection.update_one.call_args.args
        self.assertEqual(
            query,
            {
                "user_id": 42,
                "attempt_id": "attempt-current",
                "state": "entering_address",
            },
        )
        persisted = update["$set"]
        self.assertEqual(persisted["state"], "checking_address")
        self.assertTrue(persisted["has_trustline"])
        self.assertEqual(persisted["candidate_mtlap_balance"], "0")
        self.assertTrue(persisted["has_recommendation"])

    def test_phase_transition_is_conditional_on_attempt_and_state(self) -> None:
        self.database.collection.update_one.return_value = SimpleNamespace(
            matched_count=1,
        )

        result = self.database.transition_attempt(
            42,
            "attempt-current",
            "agreement",
            "entering_address",
            {"agreed_to_terms": True},
        )

        self.assertTrue(result)
        query, update = self.database.collection.update_one.call_args.args
        self.assertEqual(
            query,
            {
                "user_id": 42,
                "attempt_id": "attempt-current",
                "state": "agreement",
            },
        )
        self.assertEqual(update["$set"]["state"], "entering_address")
        self.assertTrue(update["$set"]["agreed_to_terms"])

    def test_stale_snapshot_is_rejected(self) -> None:
        self.database.collection.update_one.return_value = SimpleNamespace(
            matched_count=0,
        )

        result = self.database.record_eligibility_snapshot(
            42,
            "attempt-old",
            "checking_address",
            "G" + "A" * 55,
            True,
            "0",
            True,
            "checking_address",
        )

        self.assertFalse(result)

    def test_completion_requires_same_attempt_and_all_persisted_facts(self) -> None:
        self.database.collection.update_one.return_value = SimpleNamespace(
            matched_count=1,
        )

        self.assertTrue(
            self.database.complete_attempt(
                42,
                "attempt-current",
                "lease-current",
            )
        )

        query, update = self.database.collection.update_one.call_args.args
        self.assertEqual(query["attempt_id"], "attempt-current")
        self.assertEqual(query["state"], "finalizing")
        self.assertEqual(query["final_delivery_lease_id"], "lease-current")
        self.assertTrue(query["agreed_to_terms"])
        self.assertTrue(query["has_trustline"])
        self.assertEqual(query["candidate_mtlap_balance"], "0")
        self.assertTrue(query["has_recommendation"])
        self.assertEqual(update["$set"]["state"], "completed")

    def test_automatic_final_delivery_claim_is_bounded_and_checks_all_invariants(self) -> None:
        self.database.collection.update_one.return_value = SimpleNamespace(
            matched_count=1,
        )

        claimed = self.database.claim_final_delivery(
            42,
            "attempt-current",
            "lease-current",
            lease_seconds=300,
            automatic=True,
            max_attempts=3,
        )

        self.assertTrue(claimed)
        query, update = self.database.collection.update_one.call_args.args
        self.assertEqual(query["state"], "finalizing")
        self.assertTrue(query["agreed_to_terms"])
        self.assertTrue(query["has_trustline"])
        self.assertEqual(query["candidate_mtlap_balance"], "0")
        self.assertTrue(query["has_recommendation"])
        self.assertEqual(update["$inc"], {"final_delivery_attempts": 1})
        self.assertIn("final_delivery_attempts", str(query["$and"]))
        self.assertEqual(
            update["$set"]["final_delivery_lease_id"],
            "lease-current",
        )

    def test_manual_final_delivery_claim_remains_available_after_auto_limit(self) -> None:
        self.database.collection.update_one.return_value = SimpleNamespace(
            matched_count=1,
        )

        claimed = self.database.claim_final_delivery(
            42,
            "attempt-current",
            "lease-manual",
            lease_seconds=300,
            automatic=False,
            max_attempts=3,
        )

        self.assertTrue(claimed)
        query, update = self.database.collection.update_one.call_args.args
        self.assertNotIn("final_delivery_attempts", str(query["$and"]))
        self.assertEqual(update["$inc"], {"final_delivery_attempts": 1})

    def test_failed_delivery_is_deferred_under_the_same_lease(self) -> None:
        self.database.collection.update_one.return_value = SimpleNamespace(
            matched_count=1,
        )

        deferred = self.database.defer_final_delivery(
            42,
            "attempt-current",
            "lease-current",
            retry_seconds=300,
            error_code="telegram_send_failed",
        )

        self.assertTrue(deferred)
        query, update = self.database.collection.update_one.call_args.args
        self.assertEqual(query["final_delivery_lease_id"], "lease-current")
        self.assertIsNone(update["$set"]["final_delivery_lease_id"])
        self.assertEqual(
            update["$set"]["final_delivery_last_error"],
            "telegram_send_failed",
        )

    def test_database_read_failure_is_not_reported_as_missing_user(self) -> None:
        self.database.collection.find_one.side_effect = RuntimeError("mongo down")

        with self.assertRaisesRegex(
            DatabaseOperationError,
            "database_read_failed",
        ):
            self.database.get_user(42)

    def test_finalization_redelivery_query_is_bounded_and_oldest_first(self) -> None:
        cursor = Mock()
        cursor.sort.return_value = cursor
        cursor.limit.return_value = [{"user_id": 42}]
        self.database.collection.find.return_value = cursor

        result = self.database.get_finalizing_users(20, 3)

        self.assertEqual(result, [{"user_id": 42}])
        query = self.database.collection.find.call_args.args[0]
        self.assertEqual(query["state"], "finalizing")
        self.assertTrue(query["agreed_to_terms"])
        self.assertIn("$and", query)
        self.assertIn("final_delivery_attempts", str(query["$and"]))
        cursor.sort.assert_called_once_with("last_activity", 1)
        cursor.limit.assert_called_once_with(20)


if __name__ == "__main__":
    unittest.main()
