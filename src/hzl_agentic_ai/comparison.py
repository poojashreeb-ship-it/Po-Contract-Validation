"""Agentic validation steps (spec sections 3.3 and 3.4).

These produce a full field-by-field comparison ledger rather than a
discrepancies-only diff — every comparable field gets a "match" / "minor" /
"major" rating so a reviewer can see everything that was checked, not just
what differed. "30 days payment terms" vs. "net 30" should rate "match", a
price or date mismatch should rate "major". The system only extracts,
compares, and summarizes; it never approves or resolves discrepancies —
that decision is handed off to VIM downstream.
"""
import json
from typing import Literal

from pydantic import BaseModel

from .agents import run_structured_agent
from .retry import llm_retry
from .schemas import (
    ComparisonResult,
    ContractFields,
    DiscrepancySummary,
    FieldComparison,
    PurchaseOrderFields,
)


def _overall_status(
    discrepancies: list[FieldComparison],
) -> Literal["PASS", "PASS_WITH_WARNINGS", "FAIL"]:
    severities = {d.severity for d in discrepancies}
    if "major" in severities:
        return "FAIL"
    if "minor" in severities:
        return "PASS_WITH_WARNINGS"
    return "PASS"


_METADATA_FIELDS = frozenset({"extraction_confidence", "low_confidence_fields"})


def _allowed_field_names(*sources: BaseModel | dict) -> list[str]:
    """Real field names a comparison ledger entry is allowed to use.

    Passing the model/schemas doesn't stop a weaker LLM from hallucinating
    a field name (or, as observed, echoing a stray literal like "field: ")
    unless it's given a closed, explicit list to pick from instead of being
    asked to freely name fields itself.
    """
    names: set[str] = set()
    for source in sources:
        keys = type(source).model_fields.keys() if isinstance(source, BaseModel) else source.keys()
        names.update(k for k in keys if k not in _METADATA_FIELDS)
    return sorted(names)


def _ledger_instructions(allowed_fields: list[str]) -> str:
    return (
        "Produce an entry for every field that has a genuine semantic counterpart "
        "in both documents, rating each 'match', 'minor', or 'major', with a note "
        "explaining the rating.\n\n"
        "Scope rules — read carefully before comparing:\n"
        "- Never include 'extraction_confidence' or 'low_confidence_fields' in the "
        "ledger. These are metadata about the extraction process, not document "
        "content, and must never be compared.\n"
        "- Two fields are only a genuine counterpart if they represent the same "
        "real-world fact. Document identifiers of different kinds are NOT "
        "counterparts of each other — e.g. a PO number and a contract agreement "
        "number are two different documents' own reference numbers, not the same "
        "fact, so never compare them against each other. Likewise, a PO's contact "
        "person and a contract's owner/service-provider party names serve "
        "different purposes and are not counterparts.\n"
        "- If a field exists in only one document with no genuine counterpart in "
        "the other, leave it out of the ledger entirely rather than pairing it "
        "with an unrelated field.\n\n"
        "For each entry you do include:\n"
        f"- 'field' MUST be copied verbatim from this exact list of real field "
        f"names — never invent, translate, relabel, or abbreviate one, and never "
        f"output the literal word 'field' or a fragment like 'field: ': "
        f"{allowed_fields}\n"
        "- 'source_a' must be the literal value of that field from the first "
        "document (never the string 'PO' or a document name — the actual value, "
        "e.g. 'INR 12,50,000', or null if the field is absent).\n"
        "- 'source_b' must be the literal value of that field from the second "
        "document, under the same rule.\n\n"
        "Example of a correct entry:\n"
        '{"field": "contract_price", "source_a": "INR 12,50,000", '
        '"source_b": "INR 15,00,000", "severity": "major", '
        '"note": "Values differ by INR 2,50,000."}'
    )


@llm_retry
async def compare_po_vs_sap(
    po_fields: PurchaseOrderFields, sap_po_record: dict
) -> DiscrepancySummary:
    instructions = _ledger_instructions(_allowed_field_names(po_fields, sap_po_record))
    prompt = (
        f"Compare the extracted PO fields against the SAP PO record. {instructions}\n\n"
        f"Extracted PO fields:\n{po_fields.model_dump_json(indent=2)}\n\n"
        f"SAP PO record:\n{json.dumps(sap_po_record, indent=2)}"
    )
    result = await run_structured_agent("po_sap_validator", prompt, ComparisonResult)
    return DiscrepancySummary(
        validation_type="PO_vs_SAP",
        summary=result.summary,
        discrepancies=result.discrepancies,
        overall_status=_overall_status(result.discrepancies),
    )


@llm_retry
async def compare_po_vs_contract(
    po_fields: PurchaseOrderFields, contract_fields: ContractFields
) -> DiscrepancySummary:
    instructions = _ledger_instructions(_allowed_field_names(po_fields, contract_fields))
    prompt = (
        f"Compare the extracted PO fields against the extracted contract fields. {instructions}\n\n"
        f"Extracted PO fields:\n{po_fields.model_dump_json(indent=2)}\n\n"
        f"Extracted contract fields:\n{contract_fields.model_dump_json(indent=2)}"
    )
    result = await run_structured_agent("po_contract_validator", prompt, ComparisonResult)
    return DiscrepancySummary(
        validation_type="PO_vs_Contract",
        summary=result.summary,
        discrepancies=result.discrepancies,
        overall_status=_overall_status(result.discrepancies),
    )
