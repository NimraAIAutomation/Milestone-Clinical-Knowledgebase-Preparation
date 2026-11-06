"""Clinical heading vocabulary, section typing and document typing."""
import re

# ---------------------------------------------------------------------------
# Section types. First match wins, so narrower patterns come first.
# ---------------------------------------------------------------------------
SECTION_TYPE_PATTERNS = [
    ("front_matter", r"acknowledg(?:e)?ments?|copyright|contributors?|abbreviations?|disclaimer|"
                     r"about this (?:document|report|guideline)|table of contents|contents"),
    ("references", r"references?|bibliography|further reading|citations?"),
    ("appendix", r"annex(?:es)?|appendix|appendices"),
    ("chief_complaint", r"chief complaint|presenting complaint|reason for (?:visit|referral|consultation|admission)"),
    ("history_present_illness", r"history of (?:the )?present(?:ing)? illness|hpi"),
    ("past_medical_history", r"(?:past )?(?:medical|surgical|medical and surgical) history|pmh"),
    ("family_history", r"family history"),
    ("social_history", r"social history"),
    ("allergies", r"allerg(?:y|ies)|adverse (?:drug )?reactions?"),
    ("review_of_systems", r"review of systems"),
    ("vitals", r"vital signs?|vitals"),
    ("physical_examination", r"physical exam(?:ination)?|clinical findings|examination findings"),
    ("investigations", r"investigations?|laboratory (?:results|tests|findings)|lab results|"
                       r"test results|imaging"),
    ("medications", r"medications?|medicines?|drug (?:history|therapy)|prescriptions?"),
    ("assessment", r"assessment|clinical impression|impression"),
    ("diagnosis", r"diagnos[ie]s|diagnostic criteria"),
    ("plan", r"(?:treatment |management |care |discharge )?plan"),
    ("screening", r"screening|early detection"),
    ("prevention", r"prevent(?:ion|ing)|prophylaxis"),
    ("risk_factors", r"risk factors?|causes|etiology|aetiology"),
    ("symptoms", r"signs and symptoms|symptoms|clinical (?:features|presentation)|presentation"),
    ("complications", r"complications?"),
    ("treatment", r"treatments?|therap(?:y|ies)|pharmacological"),
    ("management", r"management|managing|manage"),
    ("follow_up", r"follow[- ]?up|monitoring"),
    ("prognosis", r"prognosis|outcomes?"),
    ("epidemiology", r"epidemiology|prevalence|burden|incidence|statistics|how common"),
    ("types_classification", r"types of|kinds of|forms of|classification"),
    ("definition", r"definitions?|what is|what are"),
    ("recommendations", r"recommendations?|key (?:points|messages)"),
    ("summary", r"summary|conclusions?|abstract"),
    ("introduction", r"introduction|background|preface|foreword|purpose|scope|overview"),
    ("methods", r"methods?|methodology"),
    ("results", r"results?|findings"),
    ("discussion", r"discussion"),
]
_SECTION_TYPE_RES = [(t, re.compile(r"\b(?:%s)\b" % p, re.I)) for t, p in SECTION_TYPE_PATTERNS]

# ---------------------------------------------------------------------------
# Headings that are recognised even when typography gives no hint
# (whole line equals the phrase, optionally numbered / followed by a colon).
# ---------------------------------------------------------------------------
EXACT_HEADINGS = {
    "introduction", "background", "summary", "executive summary", "conclusion", "conclusions",
    "references", "bibliography", "abstract", "methods", "methodology", "results", "discussion",
    "overview", "purpose", "scope", "recommendations", "key points", "preface", "foreword",
    "acknowledgements", "acknowledgments", "abbreviations", "glossary", "appendix",
    "chief complaint", "presenting complaint", "history of present illness", "hpi",
    "past medical history", "medical history", "surgical history", "family history",
    "social history", "medications", "current medications", "allergies", "review of systems",
    "vital signs", "vitals", "physical examination", "physical exam", "examination",
    "investigations", "laboratory results", "lab results", "assessment", "impression",
    "diagnosis", "differential diagnosis", "plan", "treatment plan", "management plan",
    "treatment", "management", "follow-up", "follow up", "prognosis", "complications",
    "prevention", "screening", "symptoms", "signs and symptoms", "risk factors", "causes",
    "diagnostic criteria", "monitoring", "epidemiology", "definition", "classification",
    "key messages", "key recommendations", "limitations",
}

# Terms that may appear as "Term: content" on one line in clinical notes.
INLINE_HEADING_TERMS = [
    "history of present illness", "past medical history", "chief complaint",
    "presenting complaint", "review of systems", "physical examination", "physical exam",
    "differential diagnosis", "family history", "social history", "surgical history",
    "current medications", "vital signs", "laboratory results", "lab results",
    "treatment plan", "management plan", "medications", "allergies", "assessment",
    "impression", "diagnosis", "plan", "follow-up", "follow up", "recommendations", "hpi",
]
INLINE_HEADING_RE = re.compile(
    r"^(?P<term>%s)\s*:\s*(?P<rest>\S.*)$"
    % "|".join(re.escape(t) for t in sorted(INLINE_HEADING_TERMS, key=len, reverse=True)),
    re.I,
)

NOTE_SECTION_TYPES = {
    "chief_complaint", "history_present_illness", "past_medical_history", "family_history",
    "social_history", "allergies", "review_of_systems", "vitals", "physical_examination",
    "medications", "assessment", "plan",
}

BOILERPLATE_RES = [re.compile(p, re.I) for p in (
    r"all rights reserved", r"©", r"\bISBN\b", r"cataloguing[- ]in[- ]publication",
    r"printed in", r"suggested citation", r"design and layout", r"permission to reproduce",
    r"licen[cs]e", r"\bWHO Press\b", r"library of congress",
)]


def normalise_heading(text: str) -> str:
    """Lower-case heading text without numbering, part labels or trailing punctuation."""
    t = text.strip().lower()
    t = re.sub(r"^(?:part|chapter|section|appendix|annex)\s+[0-9ivxlc]+\s*[:.\-–—]?\s*", "", t)
    t = re.sub(r"^\(?\d+(?:\.\d+)*[.)]?\s+", "", t)
    t = re.sub(r"\s+", " ", t).strip(" :.-–—")
    return t


def classify_heading(title: str):
    """Return a section type for a heading, or None when nothing matches."""
    norm = normalise_heading(title)
    if not norm:
        return None
    for stype, rx in _SECTION_TYPE_RES:
        if rx.search(norm):
            return stype
    return None


def looks_like_boilerplate(text: str, min_hits: int = 2) -> bool:
    return sum(1 for rx in BOILERPLATE_RES if rx.search(text)) >= min_hits


# ---------------------------------------------------------------------------
# Document typing
# ---------------------------------------------------------------------------
def classify_document(title: str, text: str, section_types) -> str:
    title_l = (title or "").lower()
    if re.search(r"guideline|protocol|standards? of care|consensus", title_l):
        return "guideline"
    if re.search(r"\breport\b|survey|surveillance|annual|statistics", title_l):
        return "report"
    if len(set(section_types) & NOTE_SECTION_TYPES) >= 3:
        return "clinical_note"
    words = max(1, len(text.split()))
    you = len(re.findall(r"\b(?:you|your|yours)\b", text, re.I))
    if you / words * 1000 >= 5:
        return "patient_education"
    head = text[:400].lower()
    if re.search(r"guideline|protocol", head) or len(re.findall(r"guideline|protocol|recommend", text, re.I)) >= 5:
        return "guideline"
    return "clinical_document"
