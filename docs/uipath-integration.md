# UiPath integration guide

How to call this API's 6 endpoints from a UiPath workflow using the built-in
`HTTP Request` activity (`UiPath.WebAPI.Activities`). No API package or custom
connector is needed — this is a plain FastAPI service reachable over HTTP.

## The one URL to use: `POST /process/full-report`

This is the single call UiPath needs for the full flow: give it the PO file
path, the contract file path, and the SAP PO record — get back the finished
extraction + comparison report as JSON.

```
POST http://<host>:8000/process/full-report
Content-Type: application/json
X-API-Key: <the shared secret — see Authentication below>
```

**Request body** — three inputs, two of them file paths:

```json
{
  "po_file_path": "C:\\UiPath\\Downloads\\PO_12345\\po.pdf",
  "contract_file_path": "C:\\UiPath\\Downloads\\Contract_98765\\contract.pdf",
  "sap_po_record": {
    "po_number": "PO-2026-001",
    "po_date": "2026-01-15",
    "contract_price": "INR 12,50,000",
    "payment_terms": "30 days from invoice",
    "validity_start": "2026-02-01",
    "validity_end": "2027-01-31"
  }
}
```

- `po_file_path` / `contract_file_path`: absolute paths to the downloaded PDFs.
  The API process reads these directly off disk, so it must be able to see
  the same filesystem UiPath saved them to (same machine, or a network share
  both can reach by that path).
- `sap_po_record`: whatever fields your SAP read step already pulled — passed
  straight through, not a file, since this data doesn't come from a document.

**Response** — a `ValidationReportBundle`, one report per comparison:

```json
{
  "generated_at": "2026-07-09T07:02:35.969127+00:00",
  "reports": [
    {
      "validation_type": "PO_vs_SAP",
      "summary": "...",
      "discrepancies": [
        { "field": "contract_price", "source_a": "...", "source_b": "...", "severity": "match", "note": "..." }
      ],
      "overall_status": "PASS"
    },
    {
      "validation_type": "PO_vs_Contract",
      "summary": "...",
      "discrepancies": [ /* same shape */ ],
      "overall_status": "PASS_WITH_WARNINGS"
    }
  ]
}
```

Each `discrepancies[]` entry (`FieldComparison`) has `field`, `source_a`,
`source_b`, `severity` (`match`/`minor`/`major`), `note`. `overall_status` is
what you branch your VIM/notification logic on — it's a deterministic rollup
(any `major` → `FAIL`, else any `minor` → `PASS_WITH_WARNINGS`, else `PASS`),
not an LLM judgment call, so it's safe to trust directly in a `Switch`
activity.

## UiPath Studio setup for this call

1. Package: `UiPath.WebAPI.Activities` (ships by default in most templates).
2. Config asset holding the base URL (e.g. `http://<host>:8000`), so it isn't
   hardcoded in the workflow.
3. `HTTP Request` activity:
   - `EndPoint`: `baseUrl + "/process/full-report"`
   - `Method`: `POST`
   - `BodyFormat`: `application/json`
   - `Body`: build a `JObject` with three keys (`po_file_path`,
     `contract_file_path`, `sap_po_record`) and call `.ToString()` — this
     avoids hand-escaping backslashes in Windows paths, which a raw string
     concatenation would get wrong.
   - `Result`: string variable, e.g. `fullReportResponse`
4. `Deserialize JSON` (or `JObject.Parse`) on the result to get `reports[0]`
   (`PO_vs_SAP`) and `reports[1]` (`PO_vs_Contract`), then branch on each
   `overall_status`.

## Authentication

Every endpoint requires a shared-secret header:

```
X-API-Key: <value of API_KEY from the service's .env>
```

Missing or wrong key → `401` with `{"detail": "Not authenticated"}` or
`{"detail": "Invalid API key"}`. This is a single internal secret, not
per-user auth — appropriate here because the only caller is the UiPath robot
on a trusted internal network, not the public internet.

In UiPath Studio: don't hardcode the key in the workflow. Store it as an
Orchestrator asset of type **Credential** (or "Text - Encrypted" if you're
not on Orchestrator), read it at runtime with `Get Credential`/`Get Asset`,
and add it as a header on the `HTTP Request` activity:
`Headers`: a dictionary with key `X-API-Key` → the retrieved secret value.

Rotate the key by changing `API_KEY` in the service's `.env` and restarting
it, then updating the Orchestrator asset to match — both sides need to agree
on the same value.

## Other endpoints (if you need them)

The single call above covers the common case. These exist for when you want
to inspect intermediate results before deciding whether to validate:

| Endpoint | Body | Purpose |
|---|---|---|
| `POST /extract/purchase-order` | `{"file_path": "..."}` | Extract PO fields only |
| `POST /extract/contract` | `{"file_path": "..."}` | Extract contract fields only |
| `POST /validate/po-vs-sap` | `{"po_fields": {...}, "sap_po_record": {...}}` | Compare already-extracted PO fields against SAP |
| `POST /validate/po-vs-contract` | `{"po_fields": {...}, "contract_fields": {...}}` | Compare already-extracted PO fields against contract |
| `POST /validate/full-report` | `{"po_fields": {...}, "sap_po_record": {...}, "contract_fields": {...}}` | Both validations, given fields you already extracted |

E.g. if you want to check `extraction_confidence` and route low-confidence
extractions to human review *before* running any comparison, call
`/extract/purchase-order` and `/extract/contract` separately first, then
either endpoint under `/validate/*`, instead of `/process/full-report`.

## Error handling — wrap the call in a Retry Scope

The model backing this service is a free-tier OpenRouter model (see
`CLAUDE.md`). Expect on occasion:
- `429` — daily/rate-limit quota exhausted (retries won't help if the whole
  day's quota is gone; the service itself already retries 5x with backoff
  before returning, so a `429` reaching UiPath means it's a real, exhausted
  quota, not a blip)
- `500` — either a malformed LLM response the service couldn't recover from
  after its internal retries, a provider-side outage (observed: OpenRouter's
  underlying Nvidia endpoint returning `"DEGRADED function cannot be
  invoked"` — clears on its own after a delay, not fixed by an immediate
  retry), or a bad `file_path` (missing file / wrong path)
- Non-deterministic severity ratings on borderline calls (e.g. conditional
  payment terms flipping between `match`/`minor` across runs) — not an error,
  but don't treat a `minor` on a re-run as a regression if nothing changed.

Recommended: wrap the `HTTP Request` in a `Retry Scope` (2–3 attempts, a few
seconds apart) inside a `Try Catch`. On final failure, route to whatever your
existing UiPath exception/notification handling does for "needs human
attention" — this service intentionally leaves retries/notifications to the
RPA shell rather than duplicating that logic.

## Deployment note

`uv run serve` runs uvicorn with `reload=True`, which is meant for local
development, not a long-running production service — it isn't process-
supervised and will not restart itself if it crashes. Before wiring this into
a production UiPath process on a schedule, decide where and how this stays
running (e.g. a Windows service via NSSM, or a small container) rather than a
terminal window.
