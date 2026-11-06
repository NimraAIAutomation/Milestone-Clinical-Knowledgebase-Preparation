"""Integrity checks on the generated dataset."""
from collections import Counter

REQUIRED_CHUNK_FIELDS = ("chunk_id", "doc_id", "section_id", "text", "embedding_text", "doc_title",
                         "section_path", "section_type", "chunk_type", "char_count", "doc_metadata")


def validate_dataset(documents, sections, chunks, cfg):
    issues = []

    def add(level, code, msg, ref=None):
        issues.append({"level": level, "code": code, "message": msg, "ref": ref})

    doc_ids = {d["doc_id"] for d in documents}
    sec_ids = {s["section_id"] for s in sections}
    ids = Counter(c["chunk_id"] for c in chunks)
    for cid, n in ids.items():
        if n > 1:
            add("error", "duplicate_chunk_id", f"chunk_id appears {n} times", cid)
    by_id = {c["chunk_id"]: c for c in chunks}
    for c in chunks:
        for f in REQUIRED_CHUNK_FIELDS:
            if f not in c or c[f] in (None, ""):
                if f == "section_path" and c.get(f) == []:
                    continue
                add("error", "missing_field", f"chunk missing '{f}'", c.get("chunk_id"))
        if not str(c.get("text", "")).strip():
            add("error", "empty_chunk", "chunk text is empty", c["chunk_id"])
        if c["doc_id"] not in doc_ids:
            add("error", "orphan_chunk", "chunk references unknown doc_id", c["chunk_id"])
        if c["section_id"] not in sec_ids:
            add("error", "orphan_chunk", "chunk references unknown section_id", c["chunk_id"])
        for link in ("prev_chunk_id", "next_chunk_id"):
            tgt = c.get(link)
            if tgt and (tgt not in by_id or by_id[tgt]["doc_id"] != c["doc_id"]):
                add("error", "broken_link", f"{link} does not resolve inside the same document", c["chunk_id"])
        if c["char_count"] > cfg.max_chars * 1.5:
            code = "oversize_table" if c["chunk_type"] == "table" else "oversize_chunk"
            add("warning", code, f"{c['char_count']} chars (limit {cfg.max_chars})", c["chunk_id"])
    per_doc = Counter(c["doc_id"] for c in chunks)
    for d in documents:
        if per_doc.get(d["doc_id"], 0) == 0:
            add("warning", "document_without_chunks", "no retrievable content produced", d["doc_id"])
    tiny = sum(1 for c in chunks if c["char_count"] < 60)
    if chunks and tiny / len(chunks) > 0.10:
        add("warning", "many_tiny_chunks", f"{tiny}/{len(chunks)} chunks are under 60 characters")
    errors = sum(1 for i in issues if i["level"] == "error")
    return {"ok": errors == 0, "errors": errors,
            "warnings": sum(1 for i in issues if i["level"] == "warning"), "issues": issues[:200]}
