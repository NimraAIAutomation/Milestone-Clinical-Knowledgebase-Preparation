"""Document-level metadata."""
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from .config import SCHEMA_VERSION

OCR_FORMATS = {"SCANNED_PDF", "IMAGE"}


def file_sha256(path, block=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(block), b""):
            h.update(chunk)
    return h.hexdigest()


def _usable_title(t, stem):
    if not t or not str(t).strip():
        return None
    t = re.sub(r"\s+", " ", str(t)).strip()
    low = t.lower()
    if low in {"untitled", "title", stem.lower()} or low.startswith("microsoft word -"):
        return None
    if re.search(r"\.(docx?|pdf|txt|html?)$", low):
        return None
    return t


def infer_title(meta_title, title_hint, stem):
    # The v1 TXT extractor uses the file stem as "title"; treat that as "no title".
    return (_usable_title(meta_title, stem) or _usable_title(title_hint, stem)
            or re.sub(r"[_\-]+", " ", stem).strip().title())


def build_document_record(path, root, standardized, title_hint, sha, cfg, text):
    path = Path(path)
    md = standardized.get("metadata", {})
    fmt = standardized.get("source_format", md.get("format", "UNKNOWN"))
    try:
        rel = path.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        rel = path.name
    stat = path.stat()
    return {
        "doc_id": "doc_" + sha[:16],
        "title": infer_title(md.get("title"), title_hint, path.stem),
        "source_file": rel,
        "file_name": path.name,
        "file_extension": path.suffix.lower(),
        "source_format": fmt,
        "extraction_method": "ocr" if fmt in OCR_FORMATS else "native_text",
        "author": (md.get("author") or None),
        "subject": (md.get("subject") or None),
        "creator": (md.get("creator") or None),
        "page_count": md.get("page_count"),
        "word_count": len(text.split()),
        "char_count": len(text),
        "file_size_bytes": stat.st_size,
        "file_modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
        "content_hash": sha,
        "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kb_schema_version": SCHEMA_VERSION,
        "quality_notes": (["OCR text may contain recognition errors, especially in clinical terms and numbers."]
                          if fmt in OCR_FORMATS else []),
    }


# metadata copied into every chunk so each record is self-contained for a vector store
CHUNK_DOC_FIELDS = ("source_file", "file_name", "source_format", "extraction_method", "doc_type",
                    "author", "subject", "page_count", "content_hash", "ingested_at")
