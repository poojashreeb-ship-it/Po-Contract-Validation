# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Agentic AI layer for the Hindustan Zinc Limited PO/Contract validation automation. The RPA shell (UiPath) owns document download, filenames, audit logging, the VIM hand-off, and notifications/retries. This service only handles the steps that need LLM judgment rather than deterministic rules:

- Extract structured fields from a PO document (`POST /extract/purchase-order`)
- Extract structured fields from a contract document (`POST /extract/contract`)
- Validate PO fields against the SAP PO record (`POST /validate/po-vs-sap`)
- Validate PO fields against contract fields (`POST /validate/po-vs-contract`)
- Run both validations at once and bundle them, given already-extracted fields (`POST /validate/full-report`)
- Run the whole thing in one call — extract PO, extract contract, run both validations, bundle the report — given just the two file paths and the SAP record (`POST /process/full-report`)

The first four are each invoked independently — there's no fixed sequential pipeline, since UiPath decides the calling order and what happens between calls. `validate/full-report` and `process/full-report` each compose steps internally (see Architecture below); the difference is `validate/full-report` takes pre-extracted `po_fields`/`contract_fields`, while `process/full-report` takes raw document file paths and does the extraction itself — this is the one-URL integration point for UiPath: give it `po_file_path`, `contract_file_path`, and `sap_po_record`, get the finished JSON report back.

**Extraction endpoints take a file path, not an uploaded file.** `POST /extract/purchase-order` and `POST /extract/contract` accept `{"file_path": "..."}` and read the PDF directly off disk rather than a multipart upload — this assumes the API process can see the same filesystem UiPath downloaded the document into (same machine or a reachable share).

**Every endpoint requires an `X-API-Key` header**, checked in `auth.py` against `API_KEY` in `.env` via `secrets.compare_digest` (timing-safe comparison, not `==`). This is a single shared secret, not per-user auth — the only caller is the UiPath robot on a trusted internal network, so a full OAuth/JWT setup would be solving a problem this service doesn't have. Wired in globally via `FastAPI(dependencies=[Depends(verify_api_key)])` in `api.py` rather than per-route, so a new endpoint is protected by default without remembering to add the dependency.

## Commands

```
uv sync          # install dependencies
uv run serve     # start the API on http://localhost:8000 (docs at /docs), auto-reload on file change
```

There is no test suite in this repo — verification has been done by hand: run the server, POST the sample PDFs in `input/` through the endpoints via curl/PowerShell, and inspect the JSON response.

No lint/format tooling is configured either; match the existing style in a file when editing it.

## Architecture

**LLM execution is centralized in `agents.py` behind one function**: `run_structured_agent(agent_key, prompt, response_format)`. It's backed by a single reusable LangGraph graph (one node, `run_llm`) — not four separate agents or a multi-step workflow. `agent_key` is just a string key into `config/agents.yaml` (`po_extraction_specialist`, `contract_extraction_specialist`, `po_sap_validator`, `po_contract_validator`), which supplies the role/goal/backstory that becomes the system prompt. `extraction.py` and `comparison.py` are thin callers of this one function — they don't touch LangGraph or the LLM client directly.

**LLM provider is hardcoded to OpenRouter**, not a generic "any OpenAI-compatible provider" setup: `agents.py`'s `_llm()` builds a `ChatOpenAI` with `base_url="https://openrouter.ai/api/v1"` and reads the key from `OPENROUTER_API_KEY`. The `MODEL` env var is expected in `openrouter/vendor/model` form (e.g. `openrouter/nvidia/nemotron-3-ultra-550b-a55b:free`); the `openrouter/` prefix is stripped before being passed to `ChatOpenAI`. Switching to plain OpenAI or another provider means editing `_llm()`, not just `.env`.

**Structured output uses `method="json_schema"`** (not the langchain default `function_calling`) — this was a deliberate choice because the free-tier model's confirmed capability is JSON schema / structured-outputs, not necessarily tool-calling.

**Validation produces a full field-by-field ledger, not a discrepancies-only diff.** Every comparable field gets an entry rated `match` / `minor` / `major` (see `FieldComparison` in `schemas.py`), including fields that match exactly — this was a deliberate format match to an external report shape (`generated_at` + `reports[]`, `source_a`/`source_b`/`severity`/`note` per field). Two schemas are involved in `comparison.py`:
- `ComparisonResult` — what the LLM actually returns (`summary` + `discrepancies`).
- `DiscrepancySummary` — the API response shape, which adds `validation_type` and `overall_status`. **`overall_status` is computed in code** (`_overall_status()`: any `major` → `FAIL`, else any `minor` → `PASS_WITH_WARNINGS`, else `PASS`) — it is deliberately never asked of the LLM, to keep the pass/fail rollup deterministic.

**Field names in the ledger are constrained, not inferred.** The weaker free-tier model would otherwise hallucinate or mislabel `field` values (observed: it once echoed the literal string `"field: "` instead of a real key). `comparison.py`'s `_allowed_field_names()` computes the real field names straight from the Pydantic schemas (`PurchaseOrderFields`/`ContractFields`, or the raw SAP dict's keys) and the prompt requires the model to copy one of those verbatim — it's given a closed vocabulary, not asked to name fields itself. `extraction_confidence` and `low_confidence_fields` are explicitly excluded (they're extraction metadata, not document content) and must never appear in a ledger.

**Retries live in one decorator** (`retry.py`'s `llm_retry`, applied to every function in `extraction.py`/`comparison.py`): 5 attempts, exponential backoff up to 20s, on `RateLimitError`, `APIConnectionError`, `APITimeoutError`, and bare `TypeError`. The `TypeError` case is not generic defensive coding — it's the specific, observed failure mode of the OpenRouter free-tier model returning a malformed/empty completion (`choices: null`), which crashes the OpenAI SDK's response parser with `TypeError: 'NoneType' object is not iterable`. This is a real, recurring failure on the free tier, not hypothetical.

**`api.py` is a thin FastAPI layer** — six routes, each just extracting PDF text (`pdf.py`) or delegating to `extraction.py`/`comparison.py`. `validate_full_report_endpoint` and `process_full_report_endpoint` are the two places with actual orchestration logic: both run their two validation calls concurrently via `asyncio.gather` and wrap the results in a `ValidationReportBundle` with a `generated_at` timestamp; `process_full_report_endpoint` additionally runs the two extraction calls concurrently first.

## Known constraints

- **The configured model is free-tier** (OpenRouter `:free` model). Expect: daily/rate-limit exhaustion (`insufficient_quota`/`429` errors that even retries can't fix if the whole day's quota is gone), occasional malformed responses (see the `TypeError` note above), and non-deterministic judgment calls on borderline severity ratings (the same input has flipped between `match` and `minor` across runs on things like payment-terms conditionality). None of this indicates a code bug on its own — check the actual error/response before assuming something broke.
- `input/` and `output/` at the repo root are working folders for manual testing (sample PO/contract PDFs and saved JSON results) — not part of the package, not referenced by any code.
- This is a Windows/PowerShell dev environment. PowerShell's `-Command` has a hard length limit (~965 bytes) — multi-field JSON test payloads need to be written to a `.ps1` file and run via `powershell.exe -File <path>` rather than passed inline.
