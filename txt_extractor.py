from pathlib import Path

def extract_txt(file_path):

    path = Path(file_path)

    text = path.read_text(encoding="utf-8")

    result = {
        "metadata": {
            "title": path.stem,
            "author": None,
            "source": str(path.resolve()),
            "format": "TXT",
            "character_count": len(text)
        },
        "text": text
    }

    return result
