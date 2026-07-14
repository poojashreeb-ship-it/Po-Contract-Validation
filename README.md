# HZL Agentic AI

Agentic AI layer for the Hindustan Zinc Limited PO/Contract validation automation.
The RPA shell (UiPath) owns document download, filenames, audit logging, the VIM
hand-off, and notifications/retries. This service only handles the steps that
need LLM judgment rather than deterministic rules:

- Extract structured fields from a PO document (`POST /extract/purchase-order`)
- Extract structured fields from a contract document (`POST /extract/contract`)
- Validate PO fields against the SAP PO record (`POST /validate/po-vs-sap`)
- Validate PO fields against contract fields (`POST /validate/po-vs-contract`)
- Run both validations at once and bundle the results, given already-extracted
  fields (`POST /validate/full-report`)
- Run the whole pipeline in one call — extract PO, extract contract, run both
  validations, bundle the report — given just the two file paths and the SAP
  record (`POST /process/full-report`)

The first four are each invoked independently via a single-node LangGraph graph
with structured output — there's no fixed sequential pipeline, since UiPath decides
the calling order and what happens between calls. `validate/full-report` and
`process/full-report` each compose steps internally, running them concurrently;
`process/full-report` is the single-call option when UiPath just wants to hand
over document file paths and get a finished report back.

The two extraction endpoints take a **file path**, not a file upload — they
expect `{"file_path": "..."}` and read the PDF directly, since the API process
is expected to see the same filesystem UiPath downloaded the document into.

Validation results are a full field-by-field comparison ledger (every comparable
field rated `match` / `minor` / `major`), not just a list of discrepancies — see
`schemas.py`'s `FieldComparison` and `DiscrepancySummary`.

## Setup

1. Add `MODEL`, `OPENROUTER_API_KEY`, and `API_KEY` to `.env`. `MODEL` must be
   an OpenRouter-style `openrouter/vendor/model` string, e.g.
   `openrouter/nvidia/nemotron-3-ultra-550b-a55b:free`. `API_KEY` is a shared
   secret of your choosing (e.g. `python -c "import secrets;
   print(secrets.token_urlsafe(32))"`) that callers must send back as an
   `X-API-Key` header — this is a single internal secret, not per-user auth,
   since the only caller is meant to be the UiPath robot on a trusted network.
2. `uv sync`

## Running

```
uv run serve
```

Starts the API on `http://localhost:8000` (interactive docs at `/docs`). Every
endpoint requires the `X-API-Key` header set to `.env`'s `API_KEY`; requests
without it get a `401`.

## Layout

- `config/agents.yaml` — role/goal/backstory for the four agentic steps
- `agents.py` — builds the LangGraph graph and runs an agentic step against it
- `extraction.py` — PO and contract extraction
- `comparison.py` — PO-vs-SAP and PO-vs-contract validation (full ledger, not
  just discrepancies)
- `schemas.py` — Pydantic models the agents return (schema-validated, so
  downstream deterministic steps never parse free-form agent text)
- `retry.py` — retry policy for transient LLM/provider failures
- `auth.py` — shared-secret `X-API-Key` check applied to every endpoint
- `pdf.py` — PDF-to-text helper
- `api.py` — FastAPI endpoints UiPath calls into

See `CLAUDE.md` for a deeper look at the architecture and known constraints
(the model is a free tier and has real reliability caveats).
