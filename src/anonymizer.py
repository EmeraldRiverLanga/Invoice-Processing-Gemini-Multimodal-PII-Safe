"""
Lightweight PII anonymization for text data sent to external AI models.

This module detects personal identifiable information (PII) in text strings
and replaces it with placeholder tokens (e.g. <EMAIL_1>, <PHONE_1>). The
original values are stored in an in-memory mapping table so the placeholders
can be replaced back ("re-identified") in the AI's response.

LIMITATIONS — read carefully before relying on this module:
- Uses regex patterns only. False negatives are likely for non-standard PII
  formats. For production use, replace with Microsoft Presidio or a
  comparable NER-based detector.
- Does NOT anonymize images. The invoice image is sent to Gemini as-is.
  Production systems should OCR + mask sensitive regions before transmission.
- Does NOT detect person names. Names require NER models, not regex.
- Mapping table lives in-memory only. Long-running processes should use a
  secure persistent store (encrypted DB, vault) with proper access controls.

This module is suitable for demo and educational purposes. It is NOT a
substitute for a full DLP (Data Loss Prevention) solution.
"""

import re
from typing import Any

# Compiled regex patterns. Each entry: (pattern, token_prefix)
PII_PATTERNS = [
    # Email addresses (RFC 5322 simplified)
    (
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "EMAIL",
    ),
    # Phone numbers — international format with required '+' country code
    # OR US-style with parentheses around area code
    # Matches: +1 (555) 123-4567, +371 12345678, (555) 123-4567
    # Does NOT match: dates like 2024-11-15, plain number sequences
    (
        re.compile(
            r"(?:"
            r"\+\d{1,3}[\s.-]?\(?\d{2,4}\)?[\s.-]?\d{2,4}[\s.-]?\d{2,4}"  # international with +
            r"|"
            r"\(\d{3}\)[\s.-]?\d{3}[\s.-]?\d{4}"                          # US (555) 123-4567
            r")\b"
        ),
        "PHONE",
    ),
]


class Anonymizer:
    """Anonymizes PII in text and tracks mappings for later re-identification.

    Each Anonymizer instance maintains its own mapping table. Create a new
    instance per request/document to keep mappings isolated.
    """

    def __init__(self) -> None:
        self._mapping: dict[str, str] = {}  # token -> original value
        self._reverse: dict[str, str] = {}  # original value -> token (to dedupe)
        self._counters: dict[str, int] = {}  # token_prefix -> next index

    def anonymize(self, text: str) -> str:
        """Replace PII in the text with placeholder tokens.

        The same original value always maps to the same token within one
        Anonymizer instance (e.g. if 'alice@x.com' appears twice, both
        occurrences become <EMAIL_1>).
        """
        result = text
        for pattern, prefix in PII_PATTERNS:
            result = pattern.sub(
                lambda m: self._get_or_create_token(m.group(), prefix), result
            )
        return result

    def anonymize_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Recursively anonymize all string values in a dict.

        Non-string values (numbers, booleans, None) pass through unchanged.
        Nested dicts and lists are traversed.
        """
        return self._walk(data)

    def deanonymize(self, text: str) -> str:
        """Replace tokens in the text with their original values."""
        result = text
        for token, original in self._mapping.items():
            result = result.replace(token, original)
        return result

    def deanonymize_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Recursively replace tokens with original values in a dict."""
        return self._walk(data, reverse=True)

    @property
    def mapping(self) -> dict[str, str]:
        """Return a copy of the token-to-original mapping (for inspection/audit)."""
        return dict(self._mapping)

    # ---- private helpers ----

    def _get_or_create_token(self, value: str, prefix: str) -> str:
        """Return an existing token for this value, or create a new one."""
        if value in self._reverse:
            return self._reverse[value]
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        token = f"<{prefix}_{self._counters[prefix]}>"
        self._mapping[token] = value
        self._reverse[value] = token
        return token

    def _walk(self, data: Any, reverse: bool = False) -> Any:
        """Recursively transform strings in nested data structures."""
        if isinstance(data, str):
            return self.deanonymize(data) if reverse else self.anonymize(data)
        if isinstance(data, dict):
            return {k: self._walk(v, reverse) for k, v in data.items()}
        if isinstance(data, list):
            return [self._walk(item, reverse) for item in data]
        return data
