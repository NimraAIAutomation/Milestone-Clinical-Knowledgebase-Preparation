"""Corpus-level orchestration: documents -> sections -> chunks -> dataset files."""
import csv
import json
import statistics
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import blocks as B
from .chunker import chunk_sections
from .config import KBConfig, SCHEMA_VERSION
from .metadata import CHUNK_DOC_FIELDS, build_document_record, file_sha256
from .sectioning import build_sections
from .validate import validate_dataset
from .vocab import classify_document


# ----------------------------------------------------------------------------
def discover_files(inputs, cfg, exclude_dir=None):
    from processing.pipeline import SUPPORTED_FORMATS
    inputs = [inputs] if isinstance(inputs, (str, Path)) else list(inputs)
    files, root = [], None
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            root = root or p
            it = p.rglob("*") if cfg.recursive else p.glob("*")
            files += [f for f in it if f.is_file()]
        elif p.is_file():
            files.append(p)
            root = root or p.parent
    ex = Path(exclude_dir).resolve() if exclude_dir else None
    keep = []
    for f in sorted(set(files), key=lambda x: str(x).lower()):
        if f.suffix.lower() not in SUPPORTED_FORMATS or f.name.startswith(("~$", ".")):
            continue
        if ex and ex in f.resolve().parents:
            continue
        keep.append(f)
    return keep, (root or Path("."))


def _flat_blocks(content, cfg):
    """Fallback when a structural re-read fails: reuse the v1 segment walker on standardized content."""
    from processing.chunking import extract_segments
    text = "\n\n".join(s["text"] for s in extract_segments(content))
    return B.parse_text(text, cfg)


def parse_to_blocks(path, standardized, cfg):
    """Pick the parser for a document. Returns (blocks, hints, paged, warnings)."""
    ext, content, warnings = Path(path).suffix.lower(), standardized["content"], []
    if ext == ".docx":
        try:
            return (*B.parse_docx(path, cfg), False, warnings)
        except Exception as e:                                   # pragma: no cover - defensive
            warnings.append(f"structural DOCX read failed ({e}); used flat text")
    elif ext in (".html", ".htm"):
        try:
            return (*B.parse_html(path, cfg), False, warnings)
        except Exception as e:                                   # pragma: no cover
            warnings.append(f"structural HTML read failed ({e}); used flat text")
    elif "pages" in content:
        return (*B.parse_paged_text(content["pages"], cfg), True, warnings)
    elif ext == ".txt" and "text" in content:
        return (*B.parse_text(content["text"], cfg), False, warnings)
    return (*_flat_blocks(content, cfg), False, warnings)


def process_document(path, root, cfg):
    """v1 pipeline (extract -> standardize -> clean) then structure -> sections -> chunks."""
    from processing.cleaning import clean_document
    from processing.pipeline import extract_document, standardize_document

    sha = file_sha256(path)
    extracted = extract_document(str(path))
    standardized = clean_document(standardize_document(extracted))
    blocks, hints, paged, warnings = parse_to_blocks(path, standardized, cfg)
    full_text = "\n".join(b["text"] for b in blocks if b["type"] != "toc")

    doc = build_document_record(path, root, standardized, hints.get("title_hint"), sha, cfg, full_text)
    sections = build_sections(blocks, doc["title"], paged=paged)
    for s in sections:
        s["section_id"] = f"{doc['doc_id']}-s{s['section_index']:03d}"
        s["doc_id"] = doc["doc_id"]
    doc["doc_type"] = classify_document(doc["title"], full_text, [s["section_type"] for s in sections])
    chunks = chunk_sections(doc, sections, cfg)
    doc["warnings"] = warnings
    return doc, sections, chunks


# ----------------------------------------------------------------------------
def _section_record(s):
    first = next((b["text"] for b in s["blocks"]), "")
    return {
        "section_id": s["section_id"], "doc_id": s["doc_id"], "section_index": s["section_index"],
        "parent_section_id": (s["section_id"].rsplit("-s", 1)[0] + f"-s{s['parent_index']:03d}")
        if s["parent_index"] is not None else None,
        "title": s["title"], "level": s["level"], "path": s["path"], "path_str": " > ".join(s["path"]),
        "section_type": s["section_type"], "type_source": s["type_source"],
        "page_start": s["page_start"], "page_end": s["page_end"],
        "block_count": len(s["blocks"]), "ignored_block_count": s.get("ignored_blocks", 0),
        "char_count": s["char_count"],
        "chunk_count": s["chunk_count"], "chunked": s["chunked"], "skip_reason": s["skip_reason"],
        "text_preview": first[:200],
    }


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _write_csv(path, chunks):
    """Flat view for spreadsheets / pandas (the JSONL is the canonical dataset)."""
    header = ["chunk_id", "doc_id", "doc_title", "source_file", "doc_type", "section_path", "section_type",
              "chunk_type", "page_start", "page_end", "char_count", "word_count", "text"]
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:   # BOM so Excel reads UTF-8
        w = csv.writer(fh)
        w.writerow(header)
        for c in chunks:
            w.writerow([c["chunk_id"], c["doc_id"], c["doc_title"], c["doc_metadata"].get("source_file"),
                        c["doc_metadata"].get("doc_type"), c["section_path_str"], c["section_type"],
                        c["chunk_type"], c["page_start"], c["page_end"], c["char_count"], c["word_count"],
                        c["text"]])


def build_knowledge_base(inputs, output_dir="output/knowledge_base", config=None, progress=None):
    """Process a collection of documents into the retrieval-ready dataset.

    inputs      : directory, file path, or list of either
    output_dir  : where documents/sections/chunks/manifest files are written
    progress    : optional callback(done, total, filename)
    Returns the manifest dict (also written to manifest.json).
    """
    cfg = (config or KBConfig()).validate()
    from processing import pipeline as _pipeline   # noqa: F401  (import first: ocr_extractor sets its
    if cfg.tesseract_cmd:                           # Windows default at import time, so override afterwards)
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = cfg.tesseract_cmd

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    files, root = discover_files(inputs, cfg, exclude_dir=out)

    documents, sections_out, chunks_all = [], [], []
    failures, skipped, seen_hash = [], [], {}
    for i, f in enumerate(files, 1):
        if progress:
            progress(i - 1, len(files), f.name)
        try:
            if cfg.dedupe_documents:
                sha = file_sha256(f)
                if sha in seen_hash:
                    skipped.append({"file": f.name, "reason": "duplicate_document", "duplicate_of": seen_hash[sha]})
                    continue
            doc, sections, chunks = process_document(f, root, cfg)
            seen_hash[doc["content_hash"]] = doc["source_file"]
            doc_meta = {k: doc.get(k) for k in CHUNK_DOC_FIELDS}
            for c in chunks:
                c["doc_metadata"] = doc_meta
            documents.append((doc, sections))
            chunks_all.extend(chunks)
        except Exception as e:
            failures.append({"file": str(f), "error": f"{type(e).__name__}: {e}",
                             "trace": traceback.format_exc(limit=3)})
    if progress:
        progress(len(files), len(files), "")

    # ---- cross-document chunk de-duplication --------------------------------
    dropped = []
    if cfg.dedupe_chunks:
        seen, kept = {}, []
        for c in chunks_all:
            h = c["_norm_hash"]
            if h in seen:
                dropped.append({"chunk_id": c["chunk_id"], "duplicate_of": seen[h]})
                continue
            seen[h] = c["chunk_id"]
            kept.append(c)
        chunks_all = kept
    section_chunks = Counter(c["section_id"] for c in chunks_all)

    # ---- reindex & link per document ------------------------------------------
    by_doc = {}
    for c in chunks_all:
        by_doc.setdefault(c["doc_id"], []).append(c)
    for lst in by_doc.values():
        for i, c in enumerate(lst):
            c["chunk_index"] = i
            c["prev_chunk_id"] = lst[i - 1]["chunk_id"] if i else None
            c["next_chunk_id"] = lst[i + 1]["chunk_id"] if i + 1 < len(lst) else None
    for c in chunks_all:
        c.pop("_norm_hash", None)

    doc_rows = []
    for doc, sections in documents:
        for s in sections:
            s["chunk_count"] = section_chunks.get(s["section_id"], 0)
            s["chunked"] = s["chunk_count"] > 0
            if not s["chunked"] and s["skip_reason"] is None:
                s["skip_reason"] = "duplicate_content"
            sections_out.append(_section_record(s))
        doc["section_count"] = len(sections)
        doc["chunk_count"] = len(by_doc.get(doc["doc_id"], []))
        doc["outline"] = [{"title": s["title"], "level": s["level"], "type": s["section_type"],
                           "pages": [s["page_start"], s["page_end"]], "chunks": s["chunk_count"]}
                          for s in sections][:300]
        doc_rows.append(doc)

    report = validate_dataset(doc_rows, sections_out, chunks_all, cfg)

    # ---- write ---------------------------------------------------------------------
    paths = {"documents": out / "documents.jsonl", "sections": out / "sections.jsonl",
             "chunks": out / "chunks.jsonl", "chunks_csv": out / "chunks.csv", "manifest": out / "manifest.json"}
    for d in doc_rows:   # doc_type is also stamped into each chunk's doc_metadata
        for c in by_doc.get(d["doc_id"], []):
            c["doc_metadata"] = dict(c["doc_metadata"], doc_type=d["doc_type"])
    _write_jsonl(paths["documents"], doc_rows)
    _write_jsonl(paths["sections"], sections_out)
    _write_jsonl(paths["chunks"], chunks_all)
    _write_csv(paths["chunks_csv"], chunks_all)

    sizes = [c["char_count"] for c in chunks_all]
    stats = {}
    if sizes:
        ss = sorted(sizes)
        stats = {"min": ss[0], "median": int(statistics.median(ss)), "mean": int(statistics.mean(ss)),
                 "p95": ss[int(0.95 * (len(ss) - 1))], "max": ss[-1]}
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": cfg.to_dict(),
        "input_root": str(root),
        "counts": {
            "files_found": len(files), "documents_processed": len(doc_rows), "documents_failed": len(failures),
            "documents_skipped_duplicate": len(skipped), "sections": len(sections_out),
            "sections_chunked": sum(1 for s in sections_out if s["chunked"]),
            "chunks": len(chunks_all), "chunks_dropped_duplicate": len(dropped),
        },
        "by_format": dict(Counter(d["source_format"] for d in doc_rows)),
        "by_doc_type": dict(Counter(d["doc_type"] for d in doc_rows)),
        "chunks_by_section_type": dict(Counter(c["section_type"] for c in chunks_all).most_common()),
        "chunks_by_type": dict(Counter(c["chunk_type"] for c in chunks_all)),
        "chunk_char_stats": stats,
        "documents": [{"doc_id": d["doc_id"], "title": d["title"], "file": d["source_file"],
                       "format": d["source_format"], "doc_type": d["doc_type"],
                       "sections": d["section_count"], "chunks": d["chunk_count"]} for d in doc_rows],
        "skipped": skipped, "failures": failures, "dropped_duplicate_chunks": dropped[:100],
        "validation": report,
        "files": {k: str(v) for k, v in paths.items()},
    }
    with open(paths["manifest"], "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    return manifest
