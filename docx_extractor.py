from docx import Document

def extract_docx(file_path):

    doc = Document(file_path)

    paragraphs = []

    for index, paragraph in enumerate(doc.paragraphs, start=1):

        text = paragraph.text.strip()

        if text:
            paragraphs.append({
                "paragraph_number": index,
                "text": text
            })

    tables = []

    for table_index, table in enumerate(doc.tables, start=1):

        table_data = []

        for row in table.rows:
            table_data.append([
                cell.text.strip()
                for cell in row.cells
            ])

        tables.append({
            "table_number": table_index,
            "data": table_data
        })

    result = {
        "metadata": {
            "title": doc.core_properties.title,
            "author": doc.core_properties.author,
            "subject": doc.core_properties.subject,
            "source": file_path,
            "format": "DOCX",
            "paragraph_count": len(paragraphs),
            "table_count": len(tables)
        },
        "paragraphs": paragraphs,
        "tables": tables
    }

    return result
