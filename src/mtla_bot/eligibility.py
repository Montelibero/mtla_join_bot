"""Pure business rules for deciding whether a candidate may proceed."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping

from stellar_sdk import Keypair


class EligibilityStatus(str, Enum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    ALREADY_MEMBER = "already_member"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"


class EligibilityBlocker(str, Enum):
    ACCOUNT_NOT_FOUND = "account_not_found"
    AGREEMENT_REQUIRED = "agreement_required"
    ADDRESS_REQUIRED = "address_required"
    TRUSTLINE_REQUIRED = "trustline_required"
    RECOMMENDATION_REQUIRED = "recommendation_required"


@dataclass(frozen=True)
class EligibilityDecision:
    status: EligibilityStatus
    blockers: tuple[EligibilityBlocker, ...] = ()
    technical_error: str | None = None


def is_valid_stellar_address(value: object) -> bool:
    """Validate the checksum and type of an ordinary Stellar G-address."""

    if not isinstance(value, str):
        return False
    try:
        Keypair.from_public_key(value)
    except (TypeError, ValueError):
        return False
    return True


def _parse_balance(value: Any) -> Decimal:
    try:
        balance = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("invalid_mtlap_balance") from exc

    if not balance.is_finite() or balance < Decimal("0"):
        raise ValueError("invalid_mtlap_balance")
    return balance


def evaluate_eligibility(
    *,
    agreed_to_terms: bool,
    stellar_address: str | None,
    account_info: Mapping[str, Any],
) -> EligibilityDecision:
    """Evaluate one immutable account snapshot against the approved rules.

    Telegram username is deliberately absent: it is a strong recommendation,
    not an eligibility requirement.
    """

    account_error = account_info.get("error")
    if account_error:
        return EligibilityDecision(
            EligibilityStatus.TEMPORARILY_UNAVAILABLE,
            technical_error=str(account_error),
        )

    if not account_info.get("exists", False):
        return EligibilityDecision(
            EligibilityStatus.INELIGIBLE,
            (EligibilityBlocker.ACCOUNT_NOT_FOUND,),
        )

    try:
        mtlap_balance = _parse_balance(account_info.get("mtlap_balance", "0"))
    except ValueError as exc:
        return EligibilityDecision(
            EligibilityStatus.TEMPORARILY_UNAVAILABLE,
            technical_error=str(exc),
        )

    if mtlap_balance > Decimal("0"):
        return EligibilityDecision(EligibilityStatus.ALREADY_MEMBER)

    # Recommendation availability cannot mask the stronger fact that the
    # candidate address is already a member, so it is evaluated afterwards.
    recommendation = account_info.get("recommendation") or {}
    if not isinstance(recommendation, Mapping):
        return EligibilityDecision(
            EligibilityStatus.TEMPORARILY_UNAVAILABLE,
            technical_error="invalid_recommendation_data",
        )
    recommendation_error = recommendation.get("error")
    if recommendation_error:
        return EligibilityDecision(
            EligibilityStatus.TEMPORARILY_UNAVAILABLE,
            technical_error=str(recommendation_error),
        )

    blockers: list[EligibilityBlocker] = []
    if not agreed_to_terms:
        blockers.append(EligibilityBlocker.AGREEMENT_REQUIRED)
    if not stellar_address:
        blockers.append(EligibilityBlocker.ADDRESS_REQUIRED)
    if not account_info.get("has_trustline", False):
        blockers.append(EligibilityBlocker.TRUSTLINE_REQUIRED)
    if not recommendation.get("has_recommendation", False):
        blockers.append(EligibilityBlocker.RECOMMENDATION_REQUIRED)

    if blockers:
        return EligibilityDecision(EligibilityStatus.INELIGIBLE, tuple(blockers))

    return EligibilityDecision(EligibilityStatus.ELIGIBLE)
