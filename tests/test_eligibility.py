import unittest

from mtla_bot.eligibility import (
    EligibilityBlocker,
    EligibilityStatus,
    evaluate_eligibility,
    is_valid_stellar_address,
)


def account_snapshot(**overrides):
    snapshot = {
        "exists": True,
        "has_trustline": True,
        "mtlap_balance": "0",
        "recommendation": {
            "has_recommendation": True,
            "has_any_recommendation": True,
        },
    }
    snapshot.update(overrides)
    return snapshot


class EligibilityRulesTest(unittest.TestCase):
    def test_stellar_address_validation_checks_checksum(self) -> None:
        self.assertTrue(
            is_valid_stellar_address(
                "GBACH65OTKJL5VZCYCI4F4FTTODPEORFQQZVNF4PUK7X4AMGFXNP2KZZ"
            )
        )
        self.assertFalse(is_valid_stellar_address("G" + "A" * 55))

    def test_username_is_not_part_of_eligibility(self) -> None:
        decision = evaluate_eligibility(
            agreed_to_terms=True,
            stellar_address="G" + "A" * 55,
            account_info=account_snapshot(),
        )

        self.assertEqual(decision.status, EligibilityStatus.ELIGIBLE)
        self.assertEqual(decision.blockers, ())

    def test_positive_mtlap_balance_is_already_member(self) -> None:
        decision = evaluate_eligibility(
            agreed_to_terms=True,
            stellar_address="G" + "A" * 55,
            account_info=account_snapshot(mtlap_balance="0.0000001"),
        )

        self.assertEqual(decision.status, EligibilityStatus.ALREADY_MEMBER)

    def test_recommendation_outage_does_not_mask_existing_member(self) -> None:
        decision = evaluate_eligibility(
            agreed_to_terms=True,
            stellar_address="G" + "A" * 55,
            account_info=account_snapshot(
                mtlap_balance="1",
                recommendation={
                    "has_recommendation": False,
                    "error": "bsn_unavailable",
                },
            ),
        )

        self.assertEqual(decision.status, EligibilityStatus.ALREADY_MEMBER)

    def test_missing_account_is_a_business_blocker(self) -> None:
        decision = evaluate_eligibility(
            agreed_to_terms=True,
            stellar_address="G" + "A" * 55,
            account_info=account_snapshot(exists=False),
        )

        self.assertEqual(decision.status, EligibilityStatus.INELIGIBLE)
        self.assertEqual(decision.blockers, (EligibilityBlocker.ACCOUNT_NOT_FOUND,))

    def test_upstream_error_is_not_reported_as_missing_account(self) -> None:
        decision = evaluate_eligibility(
            agreed_to_terms=True,
            stellar_address="G" + "A" * 55,
            account_info=account_snapshot(exists=False, error="horizon timeout"),
        )

        self.assertEqual(
            decision.status,
            EligibilityStatus.TEMPORARILY_UNAVAILABLE,
        )
        self.assertEqual(decision.technical_error, "horizon timeout")

    def test_recommendation_error_is_not_reported_as_absent(self) -> None:
        decision = evaluate_eligibility(
            agreed_to_terms=True,
            stellar_address="G" + "A" * 55,
            account_info=account_snapshot(
                recommendation={
                    "has_recommendation": False,
                    "error": "bsn unavailable",
                }
            ),
        )

        self.assertEqual(
            decision.status,
            EligibilityStatus.TEMPORARILY_UNAVAILABLE,
        )
        self.assertEqual(decision.technical_error, "bsn unavailable")

    def test_malformed_recommendation_is_a_temporary_data_error(self) -> None:
        decision = evaluate_eligibility(
            agreed_to_terms=True,
            stellar_address="G" + "A" * 55,
            account_info=account_snapshot(recommendation=["unexpected"]),
        )

        self.assertEqual(
            decision.status,
            EligibilityStatus.TEMPORARILY_UNAVAILABLE,
        )

    def test_invalid_balance_is_a_temporary_data_error(self) -> None:
        for balance in ("not-a-number", "NaN", "Infinity", "-0.0000001"):
            with self.subTest(balance=balance):
                decision = evaluate_eligibility(
                    agreed_to_terms=True,
                    stellar_address="G" + "A" * 55,
                    account_info=account_snapshot(mtlap_balance=balance),
                )

                self.assertEqual(
                    decision.status,
                    EligibilityStatus.TEMPORARILY_UNAVAILABLE,
                )

    def test_all_missing_requirements_are_reported_together(self) -> None:
        decision = evaluate_eligibility(
            agreed_to_terms=False,
            stellar_address=None,
            account_info=account_snapshot(
                has_trustline=False,
                recommendation={"has_recommendation": False},
            ),
        )

        self.assertEqual(decision.status, EligibilityStatus.INELIGIBLE)
        self.assertEqual(
            decision.blockers,
            (
                EligibilityBlocker.AGREEMENT_REQUIRED,
                EligibilityBlocker.ADDRESS_REQUIRED,
                EligibilityBlocker.TRUSTLINE_REQUIRED,
                EligibilityBlocker.RECOMMENDATION_REQUIRED,
            ),
        )


if __name__ == "__main__":
    unittest.main()
