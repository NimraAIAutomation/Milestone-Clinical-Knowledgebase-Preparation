"""Format-specific parsing of extracted content into typed blocks.

A block is a dict:
    {"type": "heading"|"paragraph"|"list"|"table"|"toc",
     "text": str,                      # heading / paragraph text, or rendered list/table
     "level": int,                     # headings only (1 = top)
     "items": [str], "ordered": bool,  # lists only
     "rows": [[str]],                  # tables only
     "page_start": int|None, "page_end": int|None}

Every parser returns (blocks, hints) where hints may carry {"title_hint": str}.
"""
import re
import unicodedata
from collections import Counter

# ----------------------------------------------------------------------------
# Text normalisation
# ----------------------------------------------------------------------------
_LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"}


def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFC", s)
    for k, v in _LIGATURES.items():
        s = s.replace(k, v)
    s = s.replace("\u00ad", "")
    s = re.sub(r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]", " ", s)   # NBSP, thin/narrow spaces, ...
    s = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", s)
    s = s.replace("\t", " ")
    return re.sub(r"[ ]{2,}", " ", s).strip()


# ----------------------------------------------------------------------------
# Line classification helpers
# ----------------------------------------------------------------------------
# "yy" is how PyMuPDF renders Wingdings-style bullet glyphs in many PDFs
# (seen in the WHO Global Report on Diabetes).
BULLET_RE = re.compile(r"^(?:[•▪●■◦‣·►➢*–—-]|yy|ÿÿ)\s+(?=\S)")
NUM_ITEM_RE = re.compile(r"^(?:\(?\d{1,2}[.)]|\(?[a-z][.)])\s+(?=\S)")
LONE_BULLET_RE = re.compile(r"^[•▪●■◦‣·►➢]$")
PART_RE = re.compile(
    r"^(?P<label>(?:part|chapter|section|appendix|annex|module|unit)\s+(?:\d+|[ivxlc]+|[A-Z])\b)"
    r"\s*[:.\-–—]?\s*(?P<rest>.*)$", re.I)
NUMBERED_RE = re.compile(r"^(?P<num>\d+(?:\.\d+){0,3})[.)]?\s+(?P<title>[A-Z][^\n]*)$")
BOX_RE = re.compile(r"^BOX\s+\d+\b", re.I)
QUESTION_START = re.compile(r"^(?:what|how|why|when|who|where|which|can|could|does|do|is|are|should|will)\b", re.I)
TERMINAL = ".;,"
SENTENCE_END = ".!?:)\"”'"
DOT_LEADER_RE = re.compile(r"\.{4,}\s*\d+\s*$")
TOC_LINE_RE = re.compile(
    r"^(?:part\s+\d+[:.]?\s*|\d+(?:\.\d+)+\s*)\t|\.{4,}\s*\d+\s*$|^.{3,}\t\s*\d{1,4}\s*$", re.I)


def _words(s):
    return s.split()


def capital_ratio(s: str) -> float:
    ws = [w for w in re.findall(r"[A-Za-z][A-Za-z'’-]*", s) if len(w) > 3]
    if not ws:
        return 1.0 if s[:1].isupper() else 0.0
    return sum(1 for w in ws if w[0].isupper()) / len(ws)


def is_all_caps(s: str) -> bool:
    letters = [c for c in s if c.isalpha()]
    if len(letters) < 4:
        return False
    if re.search(r"https?://|www\.|@", s):
        return False
    return sum(1 for c in letters if c.isupper()) / len(letters) >= 0.95


def looks_like_title(s: str) -> bool:
    """Weak heading rule (Title Case or a question), only used where one line == one paragraph."""
    ws = _words(s)
    if not (1 <= len(ws) <= 10) or len(s) > 90:
        return False
    if s[-1] in TERMINAL + ":" or not (s[0].isupper() or s[0].isdigit()):
        return False
    if s.endswith("?"):
        return bool(QUESTION_START.match(s))
    return capital_ratio(s) >= 0.6


def known_exact(s: str) -> bool:
    from .vocab import EXACT_HEADINGS, normalise_heading
    return normalise_heading(s) in EXACT_HEADINGS and len(s) <= 60


def strong_heading(s: str, prev_closed: bool = True):
    """Typography-independent heading rules.

    Returns {"kind", "level", "title", "rest"} or None.
    `prev_closed` is False when the previous text line ended mid-sentence; the
    numbered/part patterns are then suppressed so wrapped lines are not misread.
    """
    from .vocab import INLINE_HEADING_RE
    s = s.strip()
    if not s or len(s) > 140:
        return None

    m = INLINE_HEADING_RE.match(s)           # "Assessment: Type 2 diabetes..."
    if m and prev_closed:
        return {"kind": "inline", "level": 2, "title": m.group("term").strip().title(),
                "rest": m.group("rest").strip()}

    if BOX_RE.match(s) and is_all_caps(s) and s[-1] not in TERMINAL:
        return {"kind": "box", "level": 3, "title": s, "rest": ""}

    nw = len(_words(s))
    if nw > 12 or s[-1] in TERMINAL:
        return None

    if prev_closed:
        m = PART_RE.match(s)
        if m:
            rest = m.group("rest")
            if not rest or (rest[0].isupper() or rest[0].isdigit()):
                return {"kind": "part", "level": 1, "title": s, "rest": ""}
        m = NUMBERED_RE.match(s)
        if m:
            dots = m.group("num").count(".")
            title = m.group("title")
            sentence_inside = re.search(r"[.!?]\s+[A-Z]", title)      # reference-list entries etc.
            if not sentence_inside:
                if dots >= 1:
                    return {"kind": "numbered", "level": min(dots + 1, 4), "title": s, "rest": ""}
                if int(m.group("num")) <= 15 and (is_all_caps(title) or (nw <= 8 and capital_ratio(title) >= 0.6)):
                    return {"kind": "numbered", "level": 2 if is_all_caps(title) else 1, "title": s, "rest": ""}

    if is_all_caps(s) and nw <= 10:
        return {"kind": "allcaps", "level": 2, "title": s, "rest": ""}

    # vocabulary headings must start with a capital (lower-case hits are figure/table labels)
    if s[:1].isupper():
        if s[-1] != "?" and known_exact(s):
            return {"kind": "vocab", "level": 2, "title": s.rstrip(":").strip(), "rest": ""}
        if s.endswith(":") and known_exact(s.rstrip(":")):
            return {"kind": "vocab", "level": 2, "title": s.rstrip(":").strip(), "rest": ""}
    return None


def list_marker(s: str):
    """Return (ordered, text-without-marker) if the line starts a list item."""
    m = BULLET_RE.match(s)
    if m:
        return False, s[m.end():].strip()
    m = NUM_ITEM_RE.match(s)
    if m:
        return True, s[m.end():].strip()
    return None


# ----------------------------------------------------------------------------
# Joining wrapped lines
# ----------------------------------------------------------------------------
def collapse_repeats(s: str) -> str:
    """'ACKNOWLEDGEMENTS ACKNOWLEDGEMENTS' -> 'ACKNOWLEDGEMENTS' (duplicated display text)."""
    ws = s.split()
    n = len(ws)
    if n >= 2 and n % 2 == 0 and ws[: n // 2] == ws[n // 2:]:
        return " ".join(ws[: n // 2])
    return s


def build_vocab(texts):
    c = Counter()
    for t in texts:
        c.update(w.lower() for w in re.findall(r"[A-Za-z]{3,}", t))
    return c


def join_lines(lines, vocab=None):
    """Join hard-wrapped lines; repair line-end hyphenation only when the merged
    word is attested elsewhere in the document (keeps real compounds like long-term)."""
    out = ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if not out:
            out = ln
            continue
        if out.endswith("-") and ln[:1].islower():
            frag = re.search(r"([A-Za-z]+)-$", out)
            nxt = re.match(r"[a-z]+", ln)
            merged = (frag.group(1) + nxt.group(0)).lower() if frag and nxt else ""
            if vocab is not None and merged and vocab.get(merged, 0) >= 1 and len(frag.group(1)) >= 2:
                out = out[:-1] + ln
            else:
                out = out + ln
        else:
            out = out + " " + ln
    return out


def render_table(rows):
    """Markdown pipe table (first row = header)."""
    rows = [[c.replace("\n", " ").replace("|", "/").strip() for c in r] for r in rows if any(c.strip() for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def render_list(items, ordered, start=1):
    return "\n".join(f"{i}. {t}" if ordered else f"- {t}" for i, t in enumerate(items, start))


# ----------------------------------------------------------------------------
# Block accumulator shared by the text-based parsers
# ----------------------------------------------------------------------------
class _Builder:
    def __init__(self, vocab=None):
        self.blocks = []
        self.vocab = vocab
        self.cur = None            # open paragraph: {"lines": [], "ps": , "pe": }
        self.item = None           # open list item: {"lines": [], "ordered": bool, "ps":, "pe":}
        self.last_heading_kind = None

    # -- state helpers -------------------------------------------------------
    def cur_text(self):
        src = self.item or self.cur
        return join_lines(src["lines"], self.vocab) if src else ""

    def prev_closed(self):
        t = self.cur_text()
        return (not t) or t[-1] in SENTENCE_END

    def flush(self):
        if self.cur:
            text = join_lines(self.cur["lines"], self.vocab)
            if text:
                self.blocks.append({"type": "paragraph", "text": text,
                                    "page_start": self.cur["ps"], "page_end": self.cur["pe"]})
            self.cur = None
        if self.item:
            self._close_item()

    def _close_item(self):
        it = self.item
        self.item = None
        text = join_lines(it["lines"], self.vocab)
        if not text:
            return
        last = self.blocks[-1] if self.blocks else None
        if last and last["type"] == "list" and last["ordered"] == it["ordered"] and not it.get("force_new"):
            last["items"].append(text)
            last["text"] = render_list(last["items"], last["ordered"], last.get("start", 1))
            last["page_end"] = it["pe"]
        else:
            start = it.get("num") or 1
            self.blocks.append({"type": "list", "items": [text], "ordered": it["ordered"], "start": start,
                                "text": render_list([text], it["ordered"], start),
                                "page_start": it["ps"], "page_end": it["pe"]})

    def _continues(self, prev, info):
        """Does `info` continue the wrapped heading `prev`?

        Wrapped headings are adjacent ALL-CAPS lines on one page. Merge once, only when
        the result stays short and neither line is a standalone section word
        (e.g. "KEY MESSAGES" or "SUMMARY" must remain their own heading).
        """
        if prev.get("_merged") or info["kind"] != "allcaps":
            return False
        if self.last_heading_kind not in ("allcaps", "numbered"):
            return False
        if prev.get("page_end") != info.get("page"):
            return False
        combined = prev["text"] + " " + info["title"]
        if len(combined) > 90:
            return False
        for t in (prev["text"], info["title"]):
            if known_exact(re.sub(r"^\d+(?:\.\d+)*\s*", "", t)):
                return False
        return True

    def heading(self, info, page):
        self.flush()
        title = collapse_repeats(info["title"])
        prev = self.blocks[-1] if self.blocks else None
        info = dict(info, page=page)
        if prev and prev["type"] == "heading" and self.last_heading_kind and self._continues(prev, info):
            prev["text"] = collapse_repeats((prev["text"] + " " + title).strip())
            prev["page_end"] = page
            prev["_merged"] = True
        else:
            self.blocks.append({"type": "heading", "text": title, "level": info["level"],
                                "kind": info["kind"], "page_start": page, "page_end": page})
        self.last_heading_kind = info["kind"]

    def line(self, s, page):
        """Add a body line (not a heading)."""
        self.last_heading_kind = None
        lm = list_marker(s)
        if lm:
            ordered, txt = lm
            self.flush()
            mnum = re.match(r"\(?(\d{1,3})[.)]", s) if ordered else None
            self.item = {"lines": [txt], "ordered": ordered, "ps": page, "pe": page,
                         "num": int(mnum.group(1)) if mnum else None}
            return
        if self.item:                                   # continuation of a list item
            self.item["lines"].append(s)
            self.item["pe"] = page
            return
        if self.cur:
            self.cur["lines"].append(s)
            self.cur["pe"] = page
        else:
            self.cur = {"lines": [s], "ps": page, "pe": page}

    def blank(self):
        self.last_heading_kind = None
        self.flush()

    def table(self, rows, page=None):
        self.flush()
        text = render_table(rows)
        if text:
            self.blocks.append({"type": "table", "rows": rows, "text": text,
                                "page_start": page, "page_end": page})


# ----------------------------------------------------------------------------
# PDF / scanned PDF / image (OCR): list of {"page_number", "text"}
# ----------------------------------------------------------------------------
def _header_key(line):
    return re.sub(r"[\d\W_]+", " ", line.lower()).strip()


def _is_page_number(line):
    return bool(re.fullmatch(r"(?:page\s+)?\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?", line.strip(), re.I))


def _is_toc_page(lines):
    ne = [l for l in lines if l.strip()]
    if not ne:
        return False
    if any(re.fullmatch(r"(?:table of )?contents", l.strip(), re.I) for l in ne[:3]):
        return True
    if len(ne) >= 6:
        hits = sum(1 for l in ne if TOC_LINE_RE.search(l))
        return hits / len(ne) >= 0.55
    return False


def parse_paged_text(pages, cfg):
    n = len(pages)
    raw = []
    for p in pages:
        lines = [normalize_text(l) if l.strip() else "" for l in (p.get("text") or "").splitlines()]
        raw.append((p.get("page_number") or len(raw) + 1, lines))

    # --- running headers / footers ------------------------------------------
    counter, where = Counter(), {}
    for pi, (_, lines) in enumerate(raw):
        ne = [l for l in lines if l]
        cand = ne[:3] + ne[-2:]
        for k in {k for k in (_header_key(l) for l in cand if len(l) <= 100) if k}:
            counter[k] += 1
            where.setdefault(k, []).append(pi)

    def _is_running(k):
        # A running header recurs on neighbouring pages. A section heading that merely repeats
        # once per part (e.g. "REFERENCES") does not, and must stay a heading.
        pages_ = where[k]
        near = sum(1 for p in pages_ if any(0 < abs(p - q) <= 2 for q in pages_))
        return counter[k] >= cfg.min_header_pages and near / len(pages_) >= 0.5

    headers = set()
    if n >= cfg.min_pages_for_headers:
        headers = {k for k in counter if _is_running(k)}
    docwide = {k for k in headers if counter[k] / n >= 0.8}

    vocab = build_vocab(l for _, lines in raw for l in lines)
    b = _Builder(vocab)
    last_running = None
    title_hint = None
    prev_toc = False

    for idx, (pno, lines) in enumerate(raw):
        ne_idx = [i for i, l in enumerate(lines) if l]
        drop = set()
        # page numbers (first / last non-blank line)
        for i in ne_idx[:1] + ne_idx[-1:]:
            if _is_page_number(lines[i]):
                drop.add(i)
        running = None
        top_zone = [i for i in ne_idx[:3]] + [i for i in ne_idx[-2:]]
        for i in top_zone:
            if i in drop:
                continue
            k = _header_key(lines[i])
            if k and k in headers:
                drop.add(i)
                if k not in docwide and i in ne_idx[:3] and running is None:
                    running = lines[i]
        body = [(i, l) for i, l in enumerate(lines) if i not in drop]

        # table of contents pages are kept as 'toc' blocks and never chunked
        if _is_toc_page([l for _, l in body]):
            b.flush()
            if not prev_toc:
                b.blocks.append({"type": "heading", "text": "Contents", "level": 1, "kind": "toc",
                                 "page_start": pno, "page_end": pno})
            b.blocks.append({"type": "toc", "text": "\n".join(l for _, l in body if l),
                             "page_start": pno, "page_end": pno})
            prev_toc = True
            continue
        prev_toc = False

        if running and running != last_running:          # section opener from running header
            b.heading({"kind": "running_header", "level": 1, "title": running}, pno)
            last_running = running
        elif running:
            last_running = running

        for i, line in body:
            if not line:
                b.blank()
                continue
            if DOT_LEADER_RE.search(line):
                continue
            if LONE_BULLET_RE.match(line):               # bullet glyph on its own line
                b.flush()
                b.item = {"lines": [], "ordered": False, "ps": pno, "pe": pno}
                continue
            if b.item is not None and not b.item["lines"]:
                b.item["lines"].append(line)
                b.item["pe"] = pno
                continue
            info = strong_heading(line, prev_closed=b.prev_closed())
            if info:
                if info["kind"] == "inline":
                    b.heading(info, pno)
                    b.line(info["rest"], pno)
                else:
                    b.heading(info, pno)
                continue
            b.line(line, pno)
        # keep a paragraph open across a page break only if it stopped mid-sentence
        if b.item is not None and b.item["lines"] and b.item["lines"][-1].rstrip()[-1:] not in ",-–":
            b.flush()
        elif b.cur_text() and b.prev_closed():
            b.flush()

    b.flush()
    if title_hint is None:
        first = next((bl for bl in b.blocks if bl["type"] == "heading" and bl.get("page_start") == 1
                      and bl.get("kind") == "allcaps"), None)
        title_hint = first["text"] if first else None
    if title_hint:
        title_hint = title_hint.title() if title_hint.isupper() else title_hint
    return b.blocks, {"title_hint": title_hint}


# ----------------------------------------------------------------------------
# Plain text (TXT) and un-styled paragraph streams (DOCX without heading styles)
# ----------------------------------------------------------------------------
def _split_units(text):
    units, cur = [], []
    for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if ln.strip():
            cur.append(normalize_text(ln))
        elif cur:
            units.append(cur)
            cur = []
    if cur:
        units.append(cur)
    return units


def parse_text(text, cfg):
    units = _split_units(text)
    return _units_to_blocks([{"lines": u} for u in units], cfg, weak=True)


def _units_to_blocks(units, cfg, weak=True):
    """units: [{"lines": [..]} or {"table": rows} or {"style_heading": level, "lines": [..]}]"""
    vocab = build_vocab(l for u in units for l in u.get("lines", []))
    b = _Builder(vocab)
    title_hint = None
    n = len(units)

    def unit_len(j):
        u = units[j]
        return len(" ".join(u.get("lines", []))) if "lines" in u else 10 ** 6

    def weak_heading(j):
        u = units[j]
        if "lines" not in u or len(u["lines"]) != 1:
            return False
        s = u["lines"][0]
        if not looks_like_title(s):
            return False
        return j + 1 >= n or unit_len(j + 1) > len(s)

    for j, u in enumerate(units):
        if "table" in u:
            b.table(u["table"])
            continue
        if "style_heading" in u:
            b.heading({"kind": "style", "level": u["style_heading"], "title": " ".join(u["lines"])}, None)
            continue
        if "style_list" in u:
            b.flush()
            b.item = {"lines": [" ".join(u["lines"])], "ordered": u["style_list"] == "ordered",
                      "ps": None, "pe": None}
            b.flush()
            continue
        lines = u["lines"]
        # document title: first unit, short, heading-like, followed by another short/heading-like unit
        if j == 0 and weak and len(lines) == 1 and len(lines[0].split()) <= 10 \
                and lines[0][-1:] not in TERMINAL + "?:" and (looks_like_title(lines[0]) or is_all_caps(lines[0])) \
                and (n == 1 or unit_len(1) < 40 or "lines" not in units[1] or weak_heading(1)
                     or (strong_heading(units[1]["lines"][0]) is not None)):
            title_hint = lines[0].title() if lines[0].isupper() else lines[0]
            continue
        if len(lines) == 1:
            info = strong_heading(lines[0], prev_closed=True)
            if info and info["kind"] != "inline":
                b.heading(info, None)
                continue
        if weak and weak_heading(j):
            b.heading({"kind": "weak", "level": 2, "title": lines[0]}, None)
            continue
        for ln in lines:
            info = strong_heading(ln, prev_closed=b.prev_closed())
            if info:
                b.heading(info, None)
                if info["kind"] == "inline":
                    b.line(info["rest"], None)
            else:
                b.line(ln, None)
        b.flush()
    b.flush()
    return b.blocks, {"title_hint": title_hint}


# ----------------------------------------------------------------------------
# DOCX (structural re-read: styles + tables in document order)
# ----------------------------------------------------------------------------
def parse_docx(path, cfg):
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(path)
    items = []
    has_heading_styles = False
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, doc)
            text = normalize_text(p.text)
            if not text:
                continue
            try:
                style = (p.style.name or "") if p.style is not None else ""
            except Exception:
                style = ""
            sl = style.lower()
            m = re.match(r"heading\s*(\d)", sl)
            numpr = child.find(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr")
            if sl == "title":
                items.append({"lines": [text], "style_title": True})
            elif m:
                has_heading_styles = True
                items.append({"lines": [text], "style_heading": int(m.group(1))})
            elif sl.startswith("list") or numpr is not None:
                ordered = "number" in sl
                items.append({"lines": [text], "style_list": "ordered" if ordered else "bullet"})
            else:
                items.append({"lines": [text]})
        elif tag == "tbl" and cfg.include_tables:
            t = Table(child, doc)
            rows = []
            for row in t.rows:
                cells, seen = [], set()
                for c in row.cells:                      # merged cells repeat the same _tc
                    if id(c._tc) in seen:
                        continue
                    seen.add(id(c._tc))
                    cells.append(normalize_text(c.text))
                rows.append(cells)
            if any(any(c for c in r) for r in rows):
                items.append({"table": rows})

    title_hint = None
    if items and items[0].get("style_title"):
        title_hint = items[0]["lines"][0]
        items = items[1:]
    # style hints can be ignored in documents that use none -> heuristics take over
    blocks, hints = _units_to_blocks(items, cfg, weak=not has_heading_styles)
    hints["title_hint"] = title_hint or hints.get("title_hint")
    return blocks, hints


# ----------------------------------------------------------------------------
# HTML (structural re-read: h1-h6, p, ul/ol, table in document order)
# ----------------------------------------------------------------------------
def parse_html(path, cfg):
    from bs4 import BeautifulSoup
    from pathlib import Path

    soup = BeautifulSoup(Path(path).read_text(encoding="utf-8", errors="replace"), "html.parser")
    for el in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
        el.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    b = _Builder()
    root = soup.body or soup

    def walk(node):
        for ch in node.children:
            name = getattr(ch, "name", None)
            if not name:
                continue
            if re.fullmatch(r"h[1-6]", name):
                txt = normalize_text(ch.get_text(" ", strip=True))
                if txt:
                    b.heading({"kind": "html", "level": int(name[1]), "title": txt}, None)
            elif name in ("p", "pre", "blockquote"):
                txt = normalize_text(ch.get_text(" ", strip=True))
                if txt:
                    b.flush()
                    b.blocks.append({"type": "paragraph", "text": txt, "page_start": None, "page_end": None})
            elif name in ("ul", "ol"):
                items = [normalize_text(li.get_text(" ", strip=True)) for li in ch.find_all("li", recursive=False)]
                items = [i for i in items if i]
                if items:
                    b.flush()
                    ordered = name == "ol"
                    b.blocks.append({"type": "list", "items": items, "ordered": ordered,
                                     "text": render_list(items, ordered), "page_start": None, "page_end": None})
            elif name == "table" and cfg.include_tables:
                rows = []
                for tr in ch.find_all("tr"):
                    cells = [normalize_text(c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
                    if any(cells):
                        rows.append(cells)
                b.table(rows)
            else:
                walk(ch)

    walk(root)
    b.flush()
    h1s = [bl for bl in b.blocks if bl["type"] == "heading" and bl["level"] == 1]
    return b.blocks, {"title_hint": title or (h1s[0]["text"] if h1s else None)}
