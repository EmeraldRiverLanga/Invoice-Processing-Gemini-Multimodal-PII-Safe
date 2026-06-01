"""
Main entry point for the invoice processing pipeline.

Usage:
    python -m src.main --scenario approve
    python -m src.main --scenario reject

This script:
1. Loads data from three sources (email, webhook, suppliers CSV)
2. Anonymizes PII in text data before sending to external AI
3. Extracts invoice facts from the image using Gemini (multimodal)
4. Re-identifies anonymized fields in the result
5. Validates the extracted facts against the other sources
6. Saves the result as a timestamped JSON file in output/
7. Prints a short summary to the console
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from src.anonymizer import Anonymizer
from src.gemini_client import extract_invoice_facts
from src.sources import (
    PROJECT_ROOT,
    load_email,
    load_invoice_image_path,
    load_suppliers,
    load_webhook,
)
from src.validation import validate_invoice

OUTPUT_DIR = PROJECT_ROOT / "output"


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Process an invoice image using Gemini multimodal AI."
    )
    parser.add_argument(
        "--scenario",
        required=True,
        help="Name of the scenario directory under data/scenarios/ "
        "(e.g. 'approve' or 'reject').",
    )
    return parser.parse_args()


def _print_summary(result: dict, scenario: str, mapping: dict) -> None:
    """Print a short human-readable summary of the validation result."""
    facts = result["facts_enriched"]
    print()
    print("=" * 60)
    print(f"Scenario:      {scenario}")
    print(f"Invoice:       {facts.get('invoice_id')}")
    print(f"Supplier:      {facts.get('supplier_name')}")
    print(f"Total:         {facts.get('total')} {facts.get('currency')}")
    print("-" * 60)
    print(f"PII anonymized before AI call: {len(mapping)} item(s)")
    for token, original in mapping.items():
        print(f"  {token} -> {original}")
    print("-" * 60)
    print("Validation checks:")
    for check in result["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        print(f"  [{status}] {check['name']}: {check['details']}")
    print("-" * 60)
    print(f"Recommendation: {result['recommendation']}")
    print("=" * 60)


def _save_result(result: dict, scenario: str, mapping: dict) -> Path:
    """Save the result to output/ with a timestamped filename. Returns the path."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"{scenario}_{timestamp}.json"

    # Include the PII mapping in the audit trail. In production this would
    # go to a separate, access-controlled audit log — not into the regular
    # result file.
    result_with_audit = {
        **result,
        "audit": {
            "pii_items_anonymized": len(mapping),
            "pii_tokens": list(mapping.keys()),  # tokens only, not values
        },
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result_with_audit, f, indent=2, ensure_ascii=False, default=str)
    return output_path


def main() -> int:
    """Run the full invoice processing pipeline. Returns an exit code."""
    args = _parse_args()
    scenario = args.scenario

    print(f"Loading data sources for scenario '{scenario}'...")
    try:
        email = load_email(scenario)
        webhook = load_webhook(scenario)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    suppliers = load_suppliers()
    image_path = load_invoice_image_path()

    print("Anonymizing PII before sending to external AI...")
    anonymizer = Anonymizer()
    email_anon = anonymizer.anonymize_dict(email)
    webhook_anon = anonymizer.anonymize_dict(webhook)
    print(f"  {len(anonymizer.mapping)} PII item(s) anonymized")

    print("Extracting invoice facts with Gemini (this takes a few seconds)...")
    try:
        # Send ANONYMIZED data to Gemini, not the originals
        facts = extract_invoice_facts(image_path, email_anon, webhook_anon, suppliers)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print("Re-identifying anonymized fields in Gemini's response...")
    facts = anonymizer.deanonymize_dict(facts)

    print("Validating extracted facts...")
    # Validate against ORIGINAL data (not anonymized), since validation is
    # internal and operates on real values
    result = validate_invoice(facts, email, webhook, suppliers)

    output_path = _save_result(result, scenario, anonymizer.mapping)
    _print_summary(result, scenario, anonymizer.mapping)
    print(f"\nFull result saved to: {output_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
