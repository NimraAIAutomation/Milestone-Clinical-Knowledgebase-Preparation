"""Group typed blocks into a logical section hierarchy."""
import re

from .vocab import classify_heading, looks_like_boilerplate, normalise_heading

ACRONYMS = {
    "WHO", "NCD", "NCDS", "HIV", "AIDS", "BMI", "GDM", "TB", "US", "USA", "UK", "UN", "EU", "IGT",
    "IFG", "HBA1C", "A1C", "ECG", "CVD", "ICD", "DALY", "DALYS", "OGTT", "FPG", "LDL", "HDL", "NICE",
    "ADA", "IDF", "COVID", "COVID-19", "ICU", "ER", "CT", "MRI", "COPD", "CKD", "ESRD", "II", "III", "IV",
}
SMALL_WORDS = {"a", "an", "and", "or", "of", "in", "on", "for", "to", "the", "with", "by", "from", "at", "as", "vs"}


def smart_title(s: str) -> str:
    """Title-case ALL-CAPS headings while keeping clinical acronyms."""
    out = []
    for i, w in enumerate(s.split()):
        core = re.sub(r"^\W+|\W+$", "", w)
        if core.upper() in ACRONYMS or re.search(r"\d", core) and core.isupper() and len(core) <= 6 and not core.isdigit():
            out.append(w)
        elif i > 0 and core.lower() in SMALL_WORDS:
            out.append(w.lower())
        else:
            out.append("-".join(p[:1].upper() + p[1:].lower() for p in w.split("-")))
    return " ".join(out)


def display_title(raw: str) -> str:
    raw = raw.strip().rstrip(":").strip()
    letters = [c for c in raw if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) >= 0.95:
        return smart_title(raw)
    return raw


CIT_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
CIT_SIGNAL = re.compile(
    r"\b[A-Z][a-zA-Z'’-]+\s[A-Z]{1,3}\b[,.]|\bet al\b|\bdoi\b|Available (?:from|at)|https?://|"
    r"\b[A-Z][a-z]+:\s[A-Z][A-Za-z ]+;|\b(?:19|20)\d{2};\s*\(?\d+|\bpp?\.\s*\d")
CIT_PARA = re.compile(r"\b(?:19|20)\d{2}\s*;\s*\(?\d+|\b(?:19|20)\d{2};\d+\(\d+\)")


def is_citation(text):
    return bool(CIT_YEAR.search(text) and CIT_SIGNAL.search(text))


def is_numeric_noise(text):
    """Chart axis labels and similar figure residue: mostly numbers / percentages."""
    toks = text.split()
    if len(toks) < 4 or len(text) > 300:
        return False
    numeric = sum(1 for t in toks if re.fullmatch(r"[\d.,%–\-:/()]+", t))
    return numeric / len(toks) >= 0.55


def _tag_ignorable(b):
    """Mark reference lists and figure residue so they are kept for traceability but never chunked."""
    if b["type"] == "list" and len(b["items"]) >= 2:
        if sum(1 for i in b["items"] if is_citation(i)) / len(b["items"]) >= 0.6:
            b["type"] = "references"
    elif b["type"] == "list" and len(b["items"]) == 1 and is_citation(b["items"][0]):
        b["type"] = "references"
    elif b["type"] == "paragraph":
        if is_numeric_noise(b["text"]):
            b["type"] = "noise"
        elif len(CIT_PARA.findall(b["text"])) >= 3:
            b["type"] = "references"
    return b


def _clean_blocks(blocks):
    """Drop duplicate / implausible headings; keep a stable block_index."""
    out = []
    for b in blocks:
        b = dict(b)
        if b["type"] == "heading":
            words = b["text"].split()
            if len(words) > 14 or len(b["text"]) > 110:          # table/figure captions in caps
                b = {"type": "paragraph", "text": b["text"], "page_start": b.get("page_start"),
                     "page_end": b.get("page_end")}
            else:
                prev = out[-1] if out else None
                if prev and prev["type"] == "heading" and \
                        normalise_heading(prev["text"]) == normalise_heading(b["text"]):
                    if prev["text"].isupper() or prev["text"].islower():
                        prev["text"] = b["text"] if not (b["text"].isupper() or b["text"].islower()) else prev["text"]
                    prev["level"] = min(prev["level"], b["level"])
                    prev["page_end"] = b.get("page_end", prev.get("page_end"))
                    continue
        out.append(b)
    for i, b in enumerate(out):
        _tag_ignorable(b)
        b["block_index"] = i
    return out


def _dense_levels(blocks):
    levels = sorted({b["level"] for b in blocks if b["type"] == "heading"})
    mapping = {lv: i + 1 for i, lv in enumerate(levels)}
    for b in blocks:
        if b["type"] == "heading":
            b["level"] = mapping[b["level"]]


def build_sections(blocks, doc_title: str, paged: bool = False):
    blocks = _clean_blocks(blocks)
    _dense_levels(blocks)

    sections, stack = [], []

    def new_section(title, level, raw_title=None):
        path = [s["title"] for s in stack] + [title]
        sec = {
            "section_index": len(sections), "title": title, "raw_title": raw_title or title,
            "level": level, "path": path if title != "Preamble" else [],
            "blocks": [], "parent_index": stack[-1]["section_index"] if stack else None,
        }
        sections.append(sec)
        return sec

    current = None
    for b in blocks:
        if b["type"] == "heading":
            title = display_title(b["text"])
            while stack and stack[-1]["level"] >= b["level"]:
                stack.pop()
            current = new_section(title, b["level"], b["text"])
            current["heading_kind"] = b.get("kind")
            if b.get("kind") != "toc":          # "Contents" is a leaf, never a parent
                stack.append(current)
        else:
            if current is None:
                current = new_section("Preamble", 0)
                current["heading_kind"] = "preamble"
            current["blocks"].append(b)

    heading_count = sum(1 for s in sections if s.get("heading_kind") != "preamble")
    # ---- typing: own heading -> inherited from ancestor -> default ----------------
    for sec in sections:
        own = classify_heading(sec["raw_title"]) if sec.get("heading_kind") != "preamble" else None
        body_text = "\n".join(bl["text"] for bl in sec["blocks"])
        sec["section_type"], sec["type_source"] = None, None
        kinds = {bl["type"] for bl in sec["blocks"]}
        if kinds and kinds <= {"references", "noise"} and "references" in kinds:
            sec["section_type"], sec["type_source"] = "references", "content"
        elif sec["blocks"] and all(bl["type"] == "toc" for bl in sec["blocks"]):
            sec["section_type"], sec["type_source"] = "toc", "content"
        elif sec.get("heading_kind") == "toc":
            sec["section_type"], sec["type_source"] = "toc", "heading"
        elif looks_like_boilerplate(body_text):
            sec["section_type"], sec["type_source"] = "front_matter", "content"
        elif own:
            sec["section_type"], sec["type_source"] = own, "heading"
        elif sec.get("heading_kind") == "preamble":
            sec["section_type"] = "front_matter" if (paged and heading_count >= 3) else "preamble"
            sec["type_source"] = "position"
    by_index = {s["section_index"]: s for s in sections}
    for sec in sections:
        if sec["section_type"] is None:
            p = by_index.get(sec["parent_index"])
            while p is not None and p["section_type"] in (None, "general"):
                p = by_index.get(p["parent_index"])
            if p is not None:
                sec["section_type"], sec["type_source"] = p["section_type"], "inherited"
            else:
                sec["section_type"], sec["type_source"] = "general", "default"

    # ---- ranges / ids ------------------------------------------------------------
    for sec in sections:
        bl = sec["blocks"]
        pages = [p for b in bl for p in (b.get("page_start"), b.get("page_end")) if p is not None]
        sec["page_start"] = min(pages) if pages else None
        sec["page_end"] = max(pages) if pages else None
        sec["block_start"] = bl[0]["block_index"] if bl else None
        sec["block_end"] = bl[-1]["block_index"] if bl else None
        sec["char_count"] = sum(len(b["text"]) for b in bl)
        sec["is_container"] = not bl
        sec["ignored_blocks"] = sum(1 for b in bl if b["type"] in ("references", "noise"))
    return sections
