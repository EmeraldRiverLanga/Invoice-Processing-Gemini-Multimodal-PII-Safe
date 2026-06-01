"""
Gemini multimodal API client.

This module is responsible for ONE thing: extracting structured facts from an
invoice image using the Gemini model via OpenRouter. It does NOT make business
decisions (approve/reject) — that is the responsibility of validation.py.

The model receives both the image AND text context from other data sources,
because some extracted fields (e.g. invoice_id) can be cross-referenced with
the email subject or webhook payload to improve accuracy.
"""
import base64
import json
import os
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv


# Load environment variables once when the module is imported
load_dotenv()

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "google/gemini-2.5-flash"


def _encode_image(image_path: Path) -> str:
    """Read an image file and return it as a base64-encoded string."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _build_context(
    email: dict,
    webhook: dict,
    suppliers: pd.DataFrame,
) -> str:
    """Build a text context block combining data from all three sources.

    This context is sent alongside the image to help Gemini correlate fields
    (e.g. match the invoice_id from the image with the one in the webhook).
    """
    return f"""EMAIL CONTEXT:
- From: {email['from']}
- Subject: {email['subject']}
- Body: {email['body']}

WEBHOOK DATA:
- Invoice ID: {webhook['invoice_id']}
- Sender: {webhook['sender']}
- Amount Expected: {webhook['amount_expected']} {webhook['currency']}

SUPPLIER DATABASE:
{suppliers.to_string(index=False)}
"""


def _build_prompt(context: str) -> str:
    """Build the extraction prompt. Asks Gemini for FACTS only, no decisions."""
    return f"""You are an invoice data extraction assistant.

Analyze the attached invoice image. Use the following context only as a hint
to disambiguate unclear fields — do NOT copy values from the context.

{context}

Extract the following information from the IMAGE and return it as a JSON
object with this exact structure:
{{
    "invoice_id": "string from image",
    "supplier_name": "string from image",
    "invoice_date": "string from image",
    "due_date": "string from image or null",
    "line_items": [
        {{"description": "string", "quantity": number, "unit_price": number, "amount": number}}
    ],
    "subtotal": number,
    "tax_rate": number (as decimal, e.g. 0.12 for 12%),
    "tax_amount": number,
    "total": number,
    "currency": "string (e.g. USD, EUR)"
}}

Return ONLY the JSON object, no extra text, no markdown code fences.
"""


def extract_invoice_facts(
    image_path: Path,
    email: dict,
    webhook: dict,
    suppliers: pd.DataFrame,
) -> dict:
    """Extract structured facts from an invoice image using Gemini.

    Args:
        image_path: Path to the invoice image file.
        email: Email metadata dict.
        webhook: Webhook payload dict.
        suppliers: Suppliers database as a DataFrame.

    Returns:
        Dict with the extracted invoice fields.

    Raises:
        RuntimeError: If the API call fails or the response cannot be parsed.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not found in environment")

    image_b64 = _encode_image(image_path)
    context = _build_context(email, webhook, suppliers)
    prompt = _build_prompt(context)

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"OpenRouter API request failed: {e}") from e

    try:
        data = response.json()
        raw_text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as e:
        raise RuntimeError(f"Unexpected API response structure: {e}") from e

    # Strip markdown code fences if Gemini added them despite our instructions
    clean = raw_text.strip()
    if clean.startswith("```"):
        clean = clean.split("```json")[-1].split("```")[0].strip()

    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Gemini returned invalid JSON: {e}\nRaw response: {raw_text[:500]}"
        ) from e