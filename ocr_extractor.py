import pytesseract

pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

import pymupdf
import pytesseract
from PIL import Image
from pathlib import Path
import io

pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

def extract_image_ocr(file_path):

    image = Image.open(file_path)

    text = pytesseract.image_to_string(
        image,
        lang="eng"
    )

    return {
        "metadata": {
            "source": str(Path(file_path).resolve()),
            "format": "IMAGE",
            "page_count": 1
        },
        "pages": [
            {
                "page_number": 1,
                "text": text
            }
        ]
    }

def extract_scanned_pdf(file_path):

    doc = pymupdf.open(file_path)

    pages = []

    for page_number, page in enumerate(doc, start=1):

        pix = page.get_pixmap(
            matrix=pymupdf.Matrix(2, 2),
            alpha=False
        )

        image_bytes = pix.tobytes("png")

        image = Image.open(
            io.BytesIO(image_bytes)
        )

        text = pytesseract.image_to_string(
            image,
            lang="eng"
        )

        pages.append({
            "page_number": page_number,
            "text": text
        })

    result = {
        "metadata": {
            "source": str(Path(file_path).resolve()),
            "format": "SCANNED_PDF",
            "page_count": len(doc)
        },
        "pages": pages
    }

    doc.close()

    return result
