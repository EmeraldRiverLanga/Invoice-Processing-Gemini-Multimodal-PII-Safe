# Invoice Processing — Gemini Multimodal with PII Anonymization

## Overview

A production-style invoice processing pipeline that combines three data
sources (email metadata, webhook payload, supplier database) with an
invoice image, sends them through the Gemini multimodal AI model for fact
extraction, and then validates the extracted facts **independently** in
Python against the same data sources to produce an auditable
`APPROVE` / `REVIEW` / `REJECT` decision.

Before any data leaves the local system, personally identifiable
information (PII) in text fields is replaced with placeholder tokens.
The mapping table stays in memory and is used to re-identify the model's
response after it returns. The external AI never sees the original
email addresses, phone numbers, or other PII.

![Both scenarios running in the terminal — approve produces APPROVE, reject produces REVIEW](screenshots/terminal_both_scenarios.jpg)

The project demonstrates that an AI-driven document pipeline can be
*both* useful and privacy-respecting — and that the AI is treated as one
component in a larger system, not as the decision-maker.

## Technologies Used

- **Python 3.11** — core language
- **Requests** — HTTP calls to the OpenRouter API
- **Pandas** — supplier database loading and lookups
- **python-dotenv** — environment variable management for API keys
- **Gemini 2.5 Flash** (via OpenRouter) — multimodal LLM for image + text extraction
- **argparse** — command-line interface
- **pathlib** — location-independent file paths
- **VS Code** — development environment

## Setup

### Requirements

- Python 3.11 or newer
- An OpenRouter API key (free key available at openrouter.ai)

### Install dependencies

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows PowerShell
pip install -r requirements.txt
```

### Add your API key

Create a `.env` file in the project root:

```
OPENROUTER_API_KEY=your-openrouter-api-key-here
```

The `.env` file is ignored by Git, so the key never reaches the repository.

### Run a scenario

Two test scenarios are included:

```bash
python -m src.main --scenario approve
python -m src.main --scenario reject
```

The result is printed to the console and saved as a timestamped JSON file
in `output/`.

## Project Structure

```
invoice-processing-gemini/
├── src/
│   ├── __init__.py
│   ├── sources.py          # Data source loaders (email, webhook, suppliers, image)
│   ├── anonymizer.py       # PII detection and pseudonymization
│   ├── gemini_client.py    # Gemini API client (multimodal request building)
│   ├── validation.py       # Independent validation against sources
│   └── main.py             # Pipeline entry point with argparse CLI
├── data/
│   ├── invoice.png         # Invoice image (shared across scenarios)
│   ├── suppliers.csv       # Supplier database (shared)
│   └── scenarios/
│       ├── approve/        # Email + webhook that match the invoice
│       │   ├── email.json
│       │   └── webhook.json
│       └── reject/         # Email + webhook that do NOT match
│           ├── email.json
│           └── webhook.json
├── output/                 # Timestamped result files (auto-created)
├── .env                    # API key (gitignored)
├── .gitignore
├── requirements.txt
└── README.md
```

## How the Pipeline Works

```
┌──────────────────┐
│  Three sources   │
│  - email.json    │
│  - webhook.json  │
│  - suppliers.csv │
│  - invoice.png   │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Anonymize PII   │   ← replaces emails / phones with <EMAIL_1> tokens
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Gemini 2.5      │   ← receives ANONYMIZED text + the image
│  Flash           │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Re-identify PII  │   ← tokens replaced back with originals
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Validate        │   ← Python checks against ORIGINAL data:
│  independently   │     - invoice ID match
└────────┬─────────┘     - amount match (with tolerance)
         │               - supplier in DB and trusted
         ▼
┌──────────────────┐
│  Save + summary  │
│  APPROVE/REVIEW/ │
│  REJECT          │
└──────────────────┘
```

## Key Design Decisions

### 1. Gemini extracts facts, Python makes decisions

The model is asked **only** to extract structured data from the invoice
image. It is *not* asked whether the invoice should be approved.
Approval logic lives entirely in `validation.py` as deterministic Python
code that can be unit-tested, debugged, and audited.

This is the most important design choice in the project. A common
anti-pattern in AI demos is letting the model decide its own
trustworthiness (e.g. asking it "should this be approved?"). That
collapses extraction and decision-making into one untraceable step.
Separating them gives every decision a clear, inspectable reason.

### 2. PII is anonymized before the AI call

All text fields sent to the external AI go through `Anonymizer` first.
Email addresses are replaced with `<EMAIL_1>`, phone numbers with
`<PHONE_1>`, and so on. The mapping is kept in a per-request in-memory
table. After the AI responds, tokens are replaced back with the original
values for internal use.

The audit log records *how many* PII items were anonymized and *which
tokens* were used — but never the original values. This pattern follows
the pseudonymization model used in regulated industries (banking,
healthcare, legal).

### 3. Three independent validation checks

| Check | What it verifies |
|---|---|
| `invoice_id_match` | Image invoice ID equals webhook invoice ID (whitespace and `#` are stripped) |
| `amount_match` | Image total equals webhook expected amount, within a 0.01 tolerance |
| `supplier_trusted` | Image supplier name maps to a row in the suppliers DB and that row is `trusted=True` |

A `REVIEW` recommendation is produced when some — but not all — checks
pass. This third zone is what makes the system useful in practice:
real invoices are rarely cleanly good or bad.

### 4. Currency normalization

Gemini returns currency inconsistently — sometimes as `USD`, sometimes
as `$`. A normalization step maps symbols and variants to ISO 4217 codes
before validation, so downstream code can rely on a canonical format.

### 5. Configuration via `.env`, not hard-coded keys

The API key is never in the source code. It is loaded from `.env` via
`python-dotenv` and accessed through `os.environ`. The `.env` file is
listed in `.gitignore` from the first commit, so the key never reaches
the repository.

## Limitations

This section is deliberate. The project demonstrates the **technical
core** of a PII-safe AI pipeline. A production deployment needs much more
around it.

| Limitation | What is missing | What production would need |
|---|---|---|
| **Image PII** | The invoice image is sent to Gemini as-is | OCR + bounding-box masking of sensitive regions |
| **Name detection** | Regex finds emails and phones, not person names | NER-based detection (e.g. Microsoft Presidio, spaCy) |
| **False positives** | Telephone regex was initially matching dates (now fixed); other edge cases possible | Battle-tested PII libraries handle these |
| **In-memory mapping** | Token-to-value mapping lives in memory only | Encrypted persistent store with access controls |
| **Audit logging** | Audit data is bundled in the result JSON | Separate, append-only, access-controlled log |
| **Human-in-the-loop** | `REVIEW` decisions are flagged but not routed | UI / workflow for human reviewers |
| **Legal compliance** | No GDPR DPA, DPIA, SOC 2 / ISO 27001, DPO involvement | All of the above, plus jurisdictional analysis |
| **Scale** | Single invoice per run | Queue-based ingestion, retry logic, rate limiting |

The project is suitable for portfolio and educational use. It is *not*
a drop-in production tool.

## Sample Output

`APPROVE` scenario (all three checks pass):

```
============================================================
Scenario:      approve
Invoice:       #INV02081
Supplier:      Stanford Plumbing & Heating
Total:         2844.8 USD
------------------------------------------------------------
PII anonymized before AI call: 2 item(s)
  <EMAIL_1> -> billing@stanfordplumbing.com
  <EMAIL_2> -> accounting@homeowner.com
------------------------------------------------------------
Validation checks:
  [PASS] invoice_id_match: image='INV02081' vs webhook='INV02081'
  [PASS] amount_match: image=2844.8 vs expected=2844.8 (diff=0.00)
  [PASS] supplier_trusted: supplier='Stanford Plumbing & Heating' trusted=True
------------------------------------------------------------
Recommendation: APPROVE
============================================================
```

`REJECT`/`REVIEW` scenario (mismatching webhook data):

```
============================================================
Scenario:      reject
Invoice:       #INV02081
Supplier:      Stanford Plumbing & Heating
Total:         2844.8 USD
------------------------------------------------------------
PII anonymized before AI call: 2 item(s)
  <EMAIL_1> -> client@techcorp.com
  <EMAIL_2> -> accounting@devsolutions.com
------------------------------------------------------------
Validation checks:
  [FAIL] invoice_id_match: image='INV02081' vs webhook='INV-2024-047'
  [FAIL] amount_match: image=2844.8 vs expected=4365.68 (diff=1520.88)
  [PASS] supplier_trusted: supplier='Stanford Plumbing & Heating' trusted=True
------------------------------------------------------------
Recommendation: REVIEW
============================================================
```

The `details` field on each check is what makes the output auditable —
every decision has a reason that can be inspected without re-running the
model.

## Challenges & Solutions

| Problem | Solution |
|---|---|
| Earlier Colab version had Gemini making approval decisions | Split into extraction (Gemini) + validation (Python) so decisions are deterministic and auditable |
| API failures produced cryptic `KeyError` exceptions | Wrapped API calls in `try/except` with `response.raise_for_status()` and structured `RuntimeError` re-raises |
| Phone regex was matching ISO dates like `2024-11-15` as phone numbers | Tightened the pattern to require either a `+` country code prefix or US-style parentheses around the area code |
| Gemini returned currency inconsistently (`$` vs `USD`) | Added a normalization map to ISO 4217 codes before validation |
| Moving the project folder broke the virtual environment | `requirements.txt` allowed the venv to be recreated from scratch in the new location |
| Original Gemini 2.0 model was retired by OpenRouter | Diagnosed via a model-list endpoint, switched to `google/gemini-2.5-flash` |
| Floating-point comparison of amounts gave false mismatches | Compared with a 0.01 tolerance instead of `==` |

## Key Concepts Demonstrated

- **Multimodal AI integration** — sending image + text in a single API request
- **PII pseudonymization** — pre-call anonymization with post-call re-identification
- **Separation of concerns** — extraction, validation, anonymization, and orchestration each in their own module
- **Independent validation** — Python decides, the AI only extracts
- **Structured error handling** — typed exceptions at each pipeline stage
- **Configuration via environment variables** — no secrets in source code
- **Auditable output** — every decision includes the reason in the result file
- **Reproducible setup** — pinned dependencies, virtual environment, location-independent paths

## Dataset

The invoice image is a sample template from
[InvoiceSimple.com](https://www.invoicesimple.com/), used for demonstration
purposes only. All names and amounts in the image are fictional.
The email and webhook JSON files are hand-crafted to produce two distinct
test scenarios (`approve` and `reject`).

## Possible Improvements

- Add a third scenario with an unknown supplier for a clean `REJECT` decision
- Replace regex-based PII detection with Microsoft Presidio for production-grade accuracy
- Add image PII masking via OCR + bounding boxes
- Implement a proper append-only audit log with access controls
- Add unit tests for `validation.py` and `anonymizer.py`
- Containerize the pipeline with Docker for portable deployment
- Add a Streamlit UI that lets a reviewer approve `REVIEW` decisions manually
