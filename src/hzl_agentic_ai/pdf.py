from pathlib import Path
from typing import BinaryIO

from pypdf import PdfReader


def extract_text_from_pdf(source: str | Path | BinaryIO) -> str:
    reader = PdfReader(source)
    return "\n".join(page.extract_text() or "" for page in reader.pages)
