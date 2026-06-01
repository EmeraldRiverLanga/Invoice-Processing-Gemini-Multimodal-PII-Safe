"""
Data source loaders for the invoice processing pipeline.

This module loads data from three different sources:
- Email metadata (JSON file, scenario-specific)
- Webhook payload (JSON file, scenario-specific)
- Suppliers database (CSV file, shared)
- Invoice image (PNG file, shared)
"""
import json
from pathlib import Path

import pandas as pd


# Project root is one level up from this file (src/sources.py -> project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SCENARIOS_DIR = DATA_DIR / "scenarios"


def _scenario_dir(scenario: str) -> Path:
    """Return the path to a scenario directory. Raises if it does not exist."""
    path = SCENARIOS_DIR / scenario
    if not path.is_dir():
        available = [d.name for d in SCENARIOS_DIR.iterdir() if d.is_dir()]
        raise FileNotFoundError(
            f"Scenario '{scenario}' not found in {SCENARIOS_DIR}. "
            f"Available scenarios: {available}"
        )
    return path


def load_email(scenario: str) -> dict:
    """Load email metadata for the given scenario."""
    email_path = _scenario_dir(scenario) / "email.json"
    with open(email_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_webhook(scenario: str) -> dict:
    """Load webhook payload for the given scenario."""
    webhook_path = _scenario_dir(scenario) / "webhook.json"
    with open(webhook_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_suppliers() -> pd.DataFrame:
    """Load suppliers database (shared across scenarios)."""
    return pd.read_csv(DATA_DIR / "suppliers.csv")


def load_invoice_image_path() -> Path:
    """Return the path to the invoice image (shared across scenarios)."""
    return DATA_DIR / "invoice.png"