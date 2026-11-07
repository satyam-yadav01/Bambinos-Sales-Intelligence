# Bambinos Stage 3 — Milestone 3.2 (Corrected)

This package implements LLM-assisted transcript extraction on top of the **approved Milestone 3.1** Pydantic schema and transcript parser. It does not integrate with or modify Stage 2 decisions.

## Contents

- `s3/schemas.py`, `s3/transcript_parser.py`: approved Milestone 3.1 files, retained unchanged.
- `s3/extraction_prompt.py`: conservative extraction instructions and separated metadata/dialogue prompt.
- `s3/llm_client.py`: OpenAI structured-output client, configurable model, timeout, bounded retries.
- `s3/extraction_pipeline.py`: parse → extract → schema/identity/evidence validation → result.
- `run_extraction.py`: command-line runner and JSON persistence.
- `test_milestone3_2.py`: offline tests with mocked provider responses.

## Setup

Python 3.10+ and Pydantic v2 are required.

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set `OPENAI_API_KEY`. The initial provider is OpenAI Chat Completions structured parsing. Default model: `gpt-4o-2024-08-06`; override with `OPENAI_MODEL` only with a model that supports the SDK's Pydantic structured-output parsing. Configure `OPENAI_TIMEOUT` and `OPENAI_MAX_RETRIES` as needed. Never commit `.env`.

## Run offline tests

Run from this directory:

```bash
python -m unittest -v test_milestone3_2.py
python ../milestone3_1_corrected/test_milestone3_1.py
```

The tests mock the provider; they do not require an API key and do not prove model extraction quality.

## Process transcripts with the real provider

Place the six `call_*.txt` files in a directory, then run from this project directory:

```bash
python run_extraction.py --input-dir ../ --output-dir outputs
```

One transcript:

```bash
python run_extraction.py --input-dir ../ --file call_01_LEAD801_aarav_english_spouse_objection.txt --output-dir outputs
```

Each transcript receives a JSON file. `run_summary.json` records success, validation failure, and processing errors. Exit code 2 indicates at least one transcript did not finish with validated success.

## Validation semantics

- `success`: Pydantic output, parser/model lead and call IDs, and all evidence quotations passed checks.
- `validation_failed`: schema-valid model output exists, but identity or evidence checks failed. Do not treat it as validated intelligence.
- `error`: parsing, provider, or schema processing failed.

Evidence quote checking is lexical substring matching after normalization; it does **not** prove semantic entailment, quote context, or factual truth. Speaker attribution can be ambiguous. Human review remains necessary, especially for compliance signals.

## Stage 2 boundary

The extraction pipeline does not accept Stage 2 decisions as writable input and never calculates or changes prices, discounts, payment status, policy compliance, academic review, identity review, or automation dispositions. Stage 2 remains deterministic and authoritative. A Stage 3 conversational concern is not a final policy finding.

## Limitations / Milestone 3.3

- No real-provider call has been made as part of offline tests. Real execution requires the user's API key, provider access, and billing/usage availability.
- Six transcripts are a small sample, not a validated benchmark.
- No ground-truth labels are invented. Milestone 3.3 should include human review of all six outputs, quote/context checks, speaker attribution review, field-level error analysis, and prompt refinements based on observed errors.
- Callback normalization is deliberately conservative; ambiguous relative dates remain unnormalized.
- Evidence validation is string-based, not semantic.
