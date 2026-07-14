"""HTTP surface for the agentic layer.

The RPA shell (UiPath) owns document download, filenames, audit logging,
the VIM hand-off, and notifications/retries — all deterministic, all out of
scope here. This service only does the four agentic steps: extract PO,
extract contract, validate PO-vs-SAP, validate PO-vs-contract — plus a small
browser frontend for manually running the full pipeline (see frontend.py).
"""
import asyncio
import base64
import io
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, UploadFile
from fastapi.responses import HTMLResponse

from .auth import verify_api_key
from .comparison import compare_po_vs_contract, compare_po_vs_sap
from .extraction import extract_contract, extract_purchase_order
from .frontend import render_page
from .pdf import extract_text_from_pdf
from .report_pdf import render_report_pdf, write_report_pdf
from .schemas import (
    ContractFields,
    DiscrepancySummary,
    DocumentFileRequest,
    FullReportRequest,
    FullReportWithPdf,
    PurchaseOrderFields,
    ValidationReportBundle,
)

_REQUIRED_ENV_VARS = ("MODEL", "OPENROUTER_API_KEY", "API_KEY")


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = [name for name in _REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            "Set them in .env locally, or in your deployment platform's environment "
            "variable settings (e.g. Vercel project -> Settings -> Environment Variables), "
            "then redeploy."
        )
    yield


app = FastAPI(title="HZL Agentic AI", lifespan=lifespan)

# Every data-bearing route requires X-API-Key (see auth.py) except GET / below,
# which serves no PO/contract/SAP data — just the frontend page, which embeds
# the key itself so its own fetch() calls can attach it.
protected = APIRouter(dependencies=[Depends(verify_api_key)])

# Repo-root output/ folder (see CLAUDE.md: manual-testing scratch space, not
# referenced by any other code) — full-report calls best-effort save a JSON +
# PDF rendition here for local manual inspection. Best-effort because this
# also runs on Vercel, where the deployment filesystem is read-only outside
# of /tmp — a failed write here must never fail the actual request.
_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"


async def _build_full_report(
    po_text: str, contract_text: str, sap_po_record: dict
) -> ValidationReportBundle:
    po_fields, contract_fields = await asyncio.gather(
        extract_purchase_order(po_text), extract_contract(contract_text)
    )
    sap_report, contract_report = await asyncio.gather(
        compare_po_vs_sap(po_fields, sap_po_record),
        compare_po_vs_contract(po_fields, contract_fields),
    )
    return ValidationReportBundle(
        generated_at=datetime.now(timezone.utc).isoformat(),
        reports=[sap_report, contract_report],
    )


def _save_report_files(bundle: ValidationReportBundle, name: str) -> None:
    try:
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (_OUTPUT_DIR / f"{name}.json").write_text(bundle.model_dump_json(indent=2))
        write_report_pdf(bundle, _OUTPUT_DIR / f"{name}.pdf")
    except OSError:
        pass  # read-only filesystem (e.g. Vercel) — harmless, purely a dev convenience


@app.get("/", response_class=HTMLResponse)
async def frontend_page() -> str:
    return render_page(os.environ["API_KEY"])


@protected.post("/extract/purchase-order", response_model=PurchaseOrderFields)
async def extract_purchase_order_endpoint(request: DocumentFileRequest) -> PurchaseOrderFields:
    text = extract_text_from_pdf(request.file_path)
    return await extract_purchase_order(text)


@protected.post("/extract/contract", response_model=ContractFields)
async def extract_contract_endpoint(request: DocumentFileRequest) -> ContractFields:
    text = extract_text_from_pdf(request.file_path)
    return await extract_contract(text)


@protected.post("/validate/po-vs-sap", response_model=DiscrepancySummary)
async def validate_po_vs_sap_endpoint(
    po_fields: PurchaseOrderFields, sap_po_record: dict
) -> DiscrepancySummary:
    return await compare_po_vs_sap(po_fields, sap_po_record)


@protected.post("/validate/po-vs-contract", response_model=DiscrepancySummary)
async def validate_po_vs_contract_endpoint(
    po_fields: PurchaseOrderFields, contract_fields: ContractFields
) -> DiscrepancySummary:
    return await compare_po_vs_contract(po_fields, contract_fields)


@protected.post("/validate/full-report", response_model=ValidationReportBundle)
async def validate_full_report_endpoint(
    po_fields: PurchaseOrderFields, sap_po_record: dict, contract_fields: ContractFields
) -> ValidationReportBundle:
    sap_report, contract_report = await asyncio.gather(
        compare_po_vs_sap(po_fields, sap_po_record),
        compare_po_vs_contract(po_fields, contract_fields),
    )
    bundle = ValidationReportBundle(
        generated_at=datetime.now(timezone.utc).isoformat(),
        reports=[sap_report, contract_report],
    )
    _save_report_files(bundle, "validate_full_report")
    return bundle


@protected.post("/process/full-report", response_model=ValidationReportBundle)
async def process_full_report_endpoint(request: FullReportRequest) -> ValidationReportBundle:
    """One call for UiPath: point at the PO file and contract file it
    downloaded, plus the SAP record, and get the finished report back —
    extraction and both validations run here instead of round-tripping
    through the other endpoints. Also best-effort saves a JSON + PDF
    rendition of the same report into output/ for local manual inspection."""
    po_text = extract_text_from_pdf(request.po_file_path)
    contract_text = extract_text_from_pdf(request.contract_file_path)
    bundle = await _build_full_report(po_text, contract_text, request.sap_po_record)
    _save_report_files(bundle, "full_report")
    return bundle


@protected.post("/ui/process-full-report", response_model=FullReportWithPdf)
async def ui_process_full_report_endpoint(
    po_file: UploadFile, contract_file: UploadFile, sap_file: UploadFile
) -> FullReportWithPdf:
    """Same pipeline as /process/full-report, for the browser frontend
    (frontend.py) — takes uploaded file bytes instead of on-disk paths, since
    a browser can't hand the server a local filesystem path. The PDF is
    returned inline as base64 rather than via a separate download endpoint,
    since a serverless deployment (Vercel) has no persistent filesystem to
    serve it back from on a later request — the frontend builds both
    downloadable files straight from this one response."""
    po_text = extract_text_from_pdf(io.BytesIO(await po_file.read()))
    contract_text = extract_text_from_pdf(io.BytesIO(await contract_file.read()))
    sap_po_record = json.loads(await sap_file.read())
    bundle = await _build_full_report(po_text, contract_text, sap_po_record)
    _save_report_files(bundle, "full_report")
    pdf_base64 = base64.b64encode(render_report_pdf(bundle)).decode("ascii")
    return FullReportWithPdf(report=bundle, pdf_base64=pdf_base64)


app.include_router(protected)
