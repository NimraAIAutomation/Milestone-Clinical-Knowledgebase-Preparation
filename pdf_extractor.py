import pymupdf

def extract_pdf(file_path):

    doc = pymupdf.open(file_path)

    pages = []

    for page_number, page in enumerate(doc, start=1):

        text = page.get_text("text")

        pages.append({
            "page_number": page_number,
            "text": text
        })

    metadata = doc.metadata

    result = {
        "metadata": {
            "title": metadata.get("title"),
            "author": metadata.get("author"),
            "subject": metadata.get("subject"),
            "creator": metadata.get("creator"),
            "page_count": len(doc),
            "source": file_path,
            "format": "PDF"
        },
        "pages": pages
    }

    doc.close()

    return result
