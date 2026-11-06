"""Structure-aware chunking.

Rules
  * A chunk never crosses a section boundary.
  * Paragraphs are packed whole; only a paragraph larger than max_chars is split, on
    sentence boundaries, with sentence-aligned overlap between its parts.
  * A list is kept together when it fits; otherwise it is split between items, and a
    lead-in line ending in ':' stays attached to the first item.
  * A table is its own chunk(s); an oversize table is split between rows with the
    header row repeated in every part.
  * A short trailing chunk is merged back into the previous one.
"""
import hashlib
import math
import re

from .blocks import render_table

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[“\"'])")
ABBREV = {"e.g.", "i.e.", "vs.", "fig.", "figs.", "dr.", "no.", "approx.", "etc.", "st.", "mr.", "mrs.",
          "ms.", "prof.", "ca.", "cf.", "al.", "u.s.", "viz.", "eg.", "ie."}


def split_sentences(text):
    parts = SENT_SPLIT.split(text)
    merged = []
    for p in parts:
        if merged:
            last = merged[-1].split()[-1].lower() if merged[-1].split() else ""
            if last in ABBREV or re.fullmatch(r"[A-Z]\.", merged[-1].split()[-1] if merged[-1].split() else ""):
                merged[-1] = merged[-1] + " " + p
                continue
        merged.append(p)
    return [m.strip() for m in merged if m.strip()]


def hard_split(text, limit):
    out, cur = [], ""
    for w in text.split():
        if cur and len(cur) + 1 + len(w) > limit:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        out.append(cur)
    return out


def _unit(text, kind, block, **kw):
    u = {"text": text, "kind": kind, "block_index": block["block_index"],
         "page_start": block.get("page_start"), "page_end": block.get("page_end"),
         "keep_next": False, "overlap": False}
    u.update(kw)
    return u


def section_units(section, cfg):
    units = []
    blocks = section["blocks"]
    for i, b in enumerate(blocks):
        t = b["type"]
        if t == "paragraph":
            text = b["text"]
            lead_in = text.rstrip().endswith(":") and i + 1 < len(blocks) and blocks[i + 1]["type"] in ("list", "table")
            if len(text) <= cfg.max_chars:
                units.append(_unit(text, "para", b, keep_next=lead_in))
            else:
                for s in split_sentences(text):
                    for piece in (hard_split(s, cfg.max_chars) if len(s) > cfg.max_chars else [s]):
                        units.append(_unit(piece, "sentence", b))
        elif t == "list":
            if len(b["text"]) <= cfg.max_chars:
                units.append(_unit(b["text"], "list", b))
            else:
                for n, item in enumerate(b["items"], b.get("start", 1)):
                    txt = f"{n}. {item}" if b.get("ordered") else f"- {item}"
                    for piece in (hard_split(txt, cfg.max_chars) if len(txt) > cfg.max_chars else [txt]):
                        units.append(_unit(piece, "list_item", b))
        elif t == "table":
            rows = [r for r in b["rows"] if any(c.strip() for c in r)]
            cols = [c for c in rows[0] if c] if rows else []
            full = render_table(rows)
            if len(full) <= cfg.max_chars or len(rows) <= 2:
                units.append(_unit(full, "table", b, columns=cols))
            else:
                header, body = rows[0], rows[1:]
                group = []
                for r in body:
                    trial = render_table([header] + group + [r])
                    if group and len(trial) > cfg.max_chars:
                        units.append(_unit(render_table([header] + group), "table", b, columns=cols))
                        group = []
                    group.append(r)
                if group:
                    units.append(_unit(render_table([header] + group), "table", b, columns=cols))
    return units


def _joiner(prev, cur):
    if prev is None:
        return ""
    if prev["kind"] == "sentence" and cur["kind"] == "sentence" and prev["block_index"] == cur["block_index"]:
        return " "
    if prev["kind"] == "list_item" and cur["kind"] == "list_item" and prev["block_index"] == cur["block_index"]:
        return "\n"
    return "\n\n"


def units_text(units):
    out, prev = "", None
    for u in units:
        out += _joiner(prev, u) + u["text"]
        prev = u
    return out


def _overlap_units(prev_units, first, cfg):
    if cfg.overlap_chars <= 0 or first["kind"] != "sentence" or not prev_units:
        return []
    if prev_units[-1]["kind"] != "sentence" or prev_units[-1]["block_index"] != first["block_index"]:
        return []
    picked, total = [], 0
    for u in reversed(prev_units):
        if u["kind"] != "sentence" or u["block_index"] != first["block_index"]:
            break
        if total + len(u["text"]) > cfg.overlap_chars:
            break
        picked.append(dict(u, overlap=True))
        total += len(u["text"]) + 1
    return list(reversed(picked))


def pack_units(units, cfg):
    chunks, buf = [], []

    def length(us):
        return len(units_text(us))

    def flush():
        nonlocal buf
        if buf:
            chunks.append(buf)
        buf = []

    for u in units:
        if u["kind"] == "table":
            carry = []
            while buf and buf[-1]["keep_next"]:
                carry.insert(0, buf.pop())
            flush()
            if carry and length(carry + [u]) > cfg.max_chars * 1.5:
                chunks.append(carry)
                carry = []
            chunks.append(carry + [u])
            continue
        if buf and length(buf + [u]) > cfg.max_chars:
            carry = []
            while len(buf) > 1 and buf[-1]["keep_next"]:
                carry.insert(0, buf.pop())
            prev_units = buf
            flush()
            buf = [] if carry else _overlap_units(prev_units, u, cfg)
            buf = buf + carry
        buf.append(u)
    flush()

    # merge a small trailing chunk into its predecessor
    if len(chunks) > 1:
        last, prev = chunks[-1], chunks[-2]
        is_table = lambda c: all(x["kind"] == "table" for x in c)
        body = [x for x in last if not x["overlap"]]
        if (length(body) < cfg.min_chars and not is_table(last) and not is_table(prev)
                and length(prev + body) <= int(cfg.max_chars * 1.25)):
            chunks[-2] = prev + body
            chunks.pop()
    return chunks


def _norm_hash(text):
    return hashlib.sha1(re.sub(r"[^a-z0-9]+", " ", text.lower()).strip().encode()).hexdigest()


def chunk_type(units):
    kinds = {("table" if u["kind"] == "table" else "list" if u["kind"] in ("list", "list_item") else "text")
             for u in units}
    return kinds.pop() if len(kinds) == 1 else "mixed"


def context_header(doc_title, path):
    parts = [p for p in [doc_title] + list(path) if p]
    return " > ".join(parts)


def chunk_sections(doc_meta, sections, cfg):
    """Return (chunks, section_stats). Chunks are retrieval records (without prev/next links)."""
    chunks = []
    for sec in sections:
        sec["chunk_count"] = 0
        sec["chunked"] = False
        if sec["is_container"]:
            sec["skip_reason"] = "no_content"
            continue
        if sec["section_type"] in cfg.exclude_section_types:
            sec["skip_reason"] = f"excluded_type:{sec['section_type']}"
            continue
        sec["skip_reason"] = None
        units = section_units(sec, cfg)
        if not units:
            sec["skip_reason"] = "only_references_or_noise"
            continue
        packed = pack_units(units, cfg)
        header = context_header(doc_meta["title"], sec["path"])
        for n, us in enumerate(packed):
            text = units_text(us).strip()
            if not text:
                continue
            pages = [p for u in us for p in (u["page_start"], u["page_end"]) if p is not None]
            blocks = [u["block_index"] for u in us]
            ctype = chunk_type(us)
            cols = next((u["columns"] for u in us if u["kind"] == "table" and u.get("columns")), [])
            emb = header + ("\nTable columns: " + "; ".join(cols) if ctype == "table" and cols else "") + "\n\n" + text
            chunks.append({
                "chunk_id": f"{doc_meta['doc_id']}-{sec['section_index']:03d}-{n:02d}",
                "doc_id": doc_meta["doc_id"],
                "section_id": sec["section_id"],
                "section_chunk_index": n,
                "text": text,
                "embedding_text": emb,
                "doc_title": doc_meta["title"],
                "section_title": sec["title"],
                "section_path": sec["path"],
                "section_path_str": " > ".join(sec["path"]),
                "section_type": sec["section_type"],
                "section_level": sec["level"],
                "chunk_type": ctype,
                "page_start": min(pages) if pages else None,
                "page_end": max(pages) if pages else None,
                "block_start": min(blocks), "block_end": max(blocks),
                "char_count": len(text),
                "word_count": len(text.split()),
                "token_estimate": math.ceil(len(text) / 4),
                "has_overlap": any(u["overlap"] for u in us),
                "_norm_hash": _norm_hash(text),
            })
            sec["chunk_count"] += 1
        sec["chunked"] = sec["chunk_count"] > 0
    return chunks
