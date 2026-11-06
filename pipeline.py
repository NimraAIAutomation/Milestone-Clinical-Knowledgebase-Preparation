from pathlib import Path
from extractors.pdf_extractor import extract_pdf
from extractors.docx_extractor import extract_docx
from extractors.txt_extractor import extract_txt
from extractors.html_extractor import extract_html
from processing.schema import create_document_schema
from extractors.ocr_extractor import (
    extract_image_ocr,
    extract_scanned_pdf
)

SUPPORTED_FORMATS = {
    ".pdf",
    ".docx",
    ".txt",
    ".html",
    ".htm",
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".bmp"
}


def is_scanned_pdf(pdf_result, min_chars=30):

    pages = pdf_result["pages"]

    if not pages:
        return True

    pages_with_text = sum(
        1 for page in pages
        if len(page["text"].strip()) >= min_chars
    )

    text_page_ratio = pages_with_text / len(pages)

    return text_page_ratio < 0.5

def extract_document(file_path):

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(
            f"File not found: {file_path}"
        )

    extension = path.suffix.lower()

    if extension not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported file format: {extension}"
        )

    if extension == ".pdf":

        result = extract_pdf(file_path)

        if is_scanned_pdf(result):
            return extract_scanned_pdf(file_path)

        return result
    
    elif extension == ".docx":
        return extract_docx(file_path)

    elif extension == ".txt":
        return extract_txt(file_path)

    elif extension in [".html", ".htm"]:
        return extract_html(file_path)

    elif extension in [
        ".png", ".jpg", ".jpeg", ".tiff", ".bmp"
    ]:
        return extract_image_ocr(file_path)

def standardize_document(result):
    metadata = result.get("metadata", {})
    source_format = metadata.get("format", "UNKNOWN")

    content = {
        key: value
        for key, value in result.items()
        if key != "metadata"
    }

    return create_document_schema(
        metadata=metadata,
        content=content,
        source_format=source_format
    )    