"""
ingest.py - Convert PDF to structured markdown using Docling.
"""

from pathlib import Path


def ingest_pdf(pdf_path: str) -> str:
    """
    Convert a PDF file to structured markdown using Docling.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        Markdown string extracted from the PDF.
    """
    from docling.document_converter import DocumentConverter

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    print(f"[ingest] Converting PDF: {pdf_path.name}")

    converter = DocumentConverter()
    result = converter.convert(str(pdf_path))

    markdown = result.document.export_to_markdown()

    print(f"[ingest] Extracted {len(markdown)} characters of markdown")
    return markdown
