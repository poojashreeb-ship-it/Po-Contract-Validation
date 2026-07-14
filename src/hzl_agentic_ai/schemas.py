"""Pydantic schemas for the agentic extraction/comparison outputs.

Kept schema-validated so downstream deterministic steps (VIM hand-off,
notifications, which live in the UiPath/RPA shell, not here) never have to
parse free-form LLM text.
"""
from typing import Literal

from pydantic import BaseModel, Field


class DocumentFileRequest(BaseModel):
    file_path: str


class FullReportRequest(BaseModel):
    po_file_path: str
    contract_file_path: str
    sap_po_record: dict


class ContactInfo(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None


class PurchaseOrderFields(BaseModel):
    po_number: str
    po_date: str | None = None
    contract_period_start: str | None = None
    contract_period_end: str | None = None
    contract_price: str | None = None
    payment_terms: str | None = None
    liquidated_damage_details: str | None = None
    pricing_information: str | None = None
    contact_information: ContactInfo | None = None
    extraction_confidence: float = Field(ge=0, le=1)
    low_confidence_fields: list[str] = Field(default_factory=list)


class ContractFields(BaseModel):
    contract_agreement_number: str
    contract_validity_start: str | None = None
    contract_validity_end: str | None = None
    liquidated_damage_details: str | None = None
    pricing_information: str | None = None
    owner_party: str | None = None
    service_provider_party: str | None = None
    payment_terms: str | None = None
    bank_guarantee_details: str | None = None
    penalty_information: str | None = None
    extraction_confidence: float = Field(ge=0, le=1)
    low_confidence_fields: list[str] = Field(default_factory=list)


class FieldComparison(BaseModel):
    field: str
    source_a: str | None = Field(
        default=None,
        description="The actual value of this field from the first document being compared (e.g. the extracted PO). Never a label like 'PO' — the real value, or null if absent.",
    )
    source_b: str | None = Field(
        default=None,
        description="The actual value of this field from the second document being compared (e.g. the SAP record or extracted contract). Never a label like 'Contract' — the real value, or null if absent.",
    )
    severity: Literal["match", "minor", "major"]
    note: str


class ComparisonResult(BaseModel):
    """What the validation agent produces directly.

    `overall_status` is deliberately not part of this — it's a deterministic
    rollup of `discrepancies[].severity` computed in code (see
    `comparison.py`), not left to the LLM to compute from its own output.
    """

    summary: str
    discrepancies: list[FieldComparison]


class DiscrepancySummary(BaseModel):
    validation_type: Literal["PO_vs_SAP", "PO_vs_Contract"]
    summary: str
    discrepancies: list[FieldComparison]
    overall_status: Literal["PASS", "PASS_WITH_WARNINGS", "FAIL"]


class ValidationReportBundle(BaseModel):
    generated_at: str
    reports: list[DiscrepancySummary]


class FullReportWithPdf(BaseModel):
    """Response shape for the browser frontend's upload flow (see api.py's
    /ui/process-full-report and frontend.py). The PDF rendition is delivered
    inline as base64 rather than via a separate download endpoint, since a
    serverless deployment has no persistent filesystem to hand it back from
    on a later request."""

    report: ValidationReportBundle
    pdf_base64: str
