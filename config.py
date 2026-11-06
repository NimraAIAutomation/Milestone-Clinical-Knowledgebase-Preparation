"""Configuration for knowledge base preparation."""
from dataclasses import dataclass, field, asdict

SCHEMA_VERSION = "1.0"


@dataclass
class KBConfig:
    # ---- chunking (characters, consistent with the v1 chunker) -------------
    max_chars: int = 1200        # target upper bound for a chunk
    min_chars: int = 250         # a trailing chunk smaller than this is merged back
    overlap_chars: int = 150     # sentence-aligned overlap, ONLY inside a split paragraph

    # ---- sections ----------------------------------------------------------
    # Sections of these types are kept in sections.jsonl (for traceability) but
    # are not turned into retrieval chunks.
    exclude_section_types: tuple = ("toc", "front_matter", "references")

    # ---- PDF clean-up ------------------------------------------------------
    min_header_pages: int = 3    # a top/bottom line repeated on >= N pages is a running header/footer
    min_pages_for_headers: int = 4

    # ---- corpus handling ---------------------------------------------------
    recursive: bool = True
    dedupe_documents: bool = True   # identical file bytes -> processed once
    dedupe_chunks: bool = True      # identical normalised chunk text across docs -> kept once
    include_tables: bool = True

    # ---- OCR ---------------------------------------------------------------
    # The v1 OCR extractor hard-codes a Windows path. Set this to override it
    # (e.g. "tesseract" on Linux/macOS). None = leave the extractor's default.
    tesseract_cmd: str = None

    def validate(self):
        if self.max_chars < 200:
            raise ValueError("max_chars must be >= 200")
        if not (0 <= self.overlap_chars < self.max_chars // 2):
            raise ValueError("overlap_chars must be >= 0 and < max_chars/2")
        if not (0 <= self.min_chars < self.max_chars):
            raise ValueError("min_chars must be >= 0 and < max_chars")
        return self

    def to_dict(self):
        return asdict(self)
