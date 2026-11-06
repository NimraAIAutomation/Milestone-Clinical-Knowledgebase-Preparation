import re


def clean_text(text):
    if not isinstance(text, str):
        return text

    # Normalize line endings
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # Remove excessive spaces and tabs
    text = re.sub(r"[ \t]+", " ", text)

    # Remove excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()

def clean_document(data):
    if isinstance(data, str):
        return clean_text(data)

    if isinstance(data, list):
        return [clean_document(item) for item in data]

    if isinstance(data, dict):
        return {
            key: clean_document(value)
            for key, value in data.items()
        }

    return data    