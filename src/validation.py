"""
Independent validation of invoice facts extracted by Gemini.

This module takes the facts extracted from the invoice image and validates
them against the OTHER data sources (email, webhook, suppliers DB). The
validation logic is pure Python — it does NOT trust Gemini's own judgment
about whether the invoice should be approved.

The output is a structured validation result with individual check outcomes
and a final recommendation (APPROVE, REVIEW, or REJECT).
"""
from typing import Any

import pandas as pd


# Tolerance in monetary units when comparing amounts (handles rounding).
AMOUNT_TOLERANCE = 0.01


def _check_invoice_id_match(facts: dict, webhook: dict) -> dict:
    """Check whether the invoice ID from the image matches the webhook."""
    # Normalize: strip whitespace and leading '#' that often appears on invoices
    image_id = (facts.get("invoice_id") or "").strip().lstrip("#")
    webhook_id = (webhook.get("invoice_id") or "").strip().lstrip("#")

    return {
        "name": "invoice_id_match",
        "passed": image_id == webhook_id and image_id != "",
        "details": f"image='{image_id}' vs webhook='{webhook_id}'",
    }


def _check_amount_match(facts: dict, webhook: dict) -> dict:
    """Check whether the image total matches the webhook expected amount."""
    image_total = facts.get("total")
    expected = webhook.get("amount_expected")

    if image_total is None or expected is None:
        return {
            "name": "amount_match",
            "passed": False,
            "details": "missing amount in image or webhook",
        }

    diff = abs(float(image_total) - float(expected))
    return {
        "name": "amount_match",
        "passed": diff <= AMOUNT_TOLERANCE,
        "details": f"image={image_total} vs expected={expected} (diff={diff:.2f})",
    }


def _check_supplier_trusted(facts: dict, suppliers: pd.DataFrame) -> dict:
    """Check whether the supplier is in the database and marked as trusted."""
    image_supplier = (facts.get("supplier_name") or "").strip().lower()

    if not image_supplier:
        return {
            "name": "supplier_trusted",
            "passed": False,
            "details": "no supplier name in image",
        }

    # Case-insensitive substring match — supplier names may vary slightly
    suppliers_lower = suppliers["name"].str.lower()
    matches = suppliers[suppliers_lower.apply(
        lambda s: s in image_supplier or image_supplier in s
    )]

    if matches.empty:
        return {
            "name": "supplier_trusted",
            "passed": False,
            "details": f"supplier '{facts.get('supplier_name')}' not in database",
        }

    is_trusted = bool(matches.iloc[0]["trusted"])
    return {
        "name": "supplier_trusted",
        "passed": is_trusted,
        "details": f"supplier='{matches.iloc[0]['name']}' trusted={is_trusted}",
    }


# Mapping from common currency symbols and variants to ISO 4217 codes
CURRENCY_SYMBOL_MAP = {
    "$": "USD",
    "US$": "USD",
    "USD": "USD",
    "€": "EUR",
    "EUR": "EUR",
    "£": "GBP",
    "GBP": "GBP",
    "¥": "JPY",
    "JPY": "JPY",
}


def _normalize_currency(facts: dict, webhook: dict) -> dict:
    """Normalize currency to ISO 4217 code and fill from webhook if missing.

    Gemini may return currency as a symbol ($, €) or as a code (USD, EUR).
    We normalize to ISO 4217 codes for consistency. If Gemini did not extract
    any currency, we fall back to the webhook value.
    """
    facts = dict(facts)  # copy so we don't mutate the caller's dict
    raw_currency = facts.get("currency")

    if raw_currency:
        # Normalize symbols and variants to ISO codes
        normalized = CURRENCY_SYMBOL_MAP.get(raw_currency.strip())
        facts["currency"] = normalized or raw_currency
    else:
        # Fall back to webhook value
        facts["currency"] = webhook.get("currency")

    return facts


def _decide(checks: list[dict]) -> str:
    """Decide APPROVE / REVIEW / REJECT based on the check outcomes."""
    passed = [c["passed"] for c in checks]

    if all(passed):
        return "APPROVE"
    if not any(passed):
        return "REJECT"
    return "REVIEW"


def validate_invoice(
    facts: dict,
    email: dict,
    webhook: dict,
    suppliers: pd.DataFrame,
) -> dict[str, Any]:
    """Run independent validation on extracted invoice facts.

    Args:
        facts: Dict of facts extracted from the invoice image by Gemini.
        email: Email metadata (currently unused — reserved for future checks
            like matching the email sender to the supplier).
        webhook: Webhook payload with expected invoice_id and amount.
        suppliers: Suppliers database.

    Returns:
        Dict with:
            - facts_enriched: facts with missing fields filled from other sources
            - checks: list of individual check results
            - recommendation: APPROVE | REVIEW | REJECT
    """
    enriched = _normalize_currency(facts, webhook)

    checks = [
        _check_invoice_id_match(enriched, webhook),
        _check_amount_match(enriched, webhook),
        _check_supplier_trusted(enriched, suppliers),
    ]

    return {
        "facts_enriched": enriched,
        "checks": checks,
        "recommendation": _decide(checks),
    }