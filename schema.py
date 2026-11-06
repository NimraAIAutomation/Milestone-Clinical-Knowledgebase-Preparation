def create_document_schema(
    metadata,
    content,
    source_format
):
    return {
        "metadata": metadata,
        "source_format": source_format,
        "content": content
    }