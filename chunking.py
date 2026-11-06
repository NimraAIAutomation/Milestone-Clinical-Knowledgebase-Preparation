

def extract_segments(value, metadata=None):
    metadata = metadata or {}
    segments = []

    if isinstance(value, str):
        if value.strip():
            segments.append({
                "text": value,
                "metadata": metadata.copy()
            })

    elif isinstance(value, list):
        for item in value:
            segments.extend(extract_segments(item, metadata))

    elif isinstance(value, dict):
        location_keys = [
            "page_number",
            "paragraph_number",
            "table_number",
            "tag"
        ]

        current_metadata = metadata.copy()

        for key in location_keys:
            if key in value:
                current_metadata[key] = value[key]

        for key, item in value.items():
            if key not in location_keys:
                segments.extend(
                    extract_segments(item, current_metadata)
                )

    return segments


def chunk_document(document, chunk_size=1000, overlap=200):
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("Invalid chunk size or overlap")

    segments = extract_segments(document["content"])
    chunks = []

    for segment in segments:
        text = segment["text"]
        start = 0

        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end].strip()

            if chunk:
                chunks.append({
                    "chunk_id": len(chunks) + 1,
                    "text": chunk,
                    "metadata": {
                        "source": document["metadata"].get("source"),
                        "source_format": document["source_format"],
                        **segment["metadata"]
                    }
                })

            start += chunk_size - overlap

    return chunks