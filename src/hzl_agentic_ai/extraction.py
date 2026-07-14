"""Agentic extraction steps (spec sections 3.1 and 3.2).

PO and contract layouts vary, so these use LLM document understanding
rather than fixed-template OCR. Scope is limited to the known PO/contract
formats in use (English, typed, not handwritten) per the spec's exclusions.
"""
from .agents import run_structured_agent
from .retry import llm_retry
from .schemas import ContractFields, PurchaseOrderFields


@llm_retry
async def extract_purchase_order(document_text: str) -> PurchaseOrderFields:
    return await run_structured_agent(
        "po_extraction_specialist",
        f"Extract the PO fields from this purchase order document:\n\n{document_text}",
        PurchaseOrderFields,
    )


@llm_retry
async def extract_contract(document_text: str) -> ContractFields:
    return await run_structured_agent(
        "contract_extraction_specialist",
        f"Extract the contract fields from this contract document:\n\n{document_text}",
        ContractFields,
    )
