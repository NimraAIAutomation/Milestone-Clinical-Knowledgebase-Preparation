# Clinical Document Ingestion & Knowledge Base Preparation

A Python/Streamlit project that turns clinical documents in many formats into a **retrieval-ready knowledge base** for Retrieval-Augmented Generation (RAG).

| Milestone | Scope |
|---|---|
| 1. Multi-Format Ingestion | Extract, standardize, clean and chunk PDF, DOCX, TXT, HTML and scanned documents |
| 2. Clinical Knowledge Base Preparation | Sections, structure-aware chunking, preserved metadata and a unified dataset |

```
files -> extract -> standardize -> clean                      (milestone 1)
      -> typed blocks (heading / paragraph / list / table)
      -> section hierarchy + clinical section types
      -> structure-aware chunks (never cross sections)
      -> dedupe, prev/next links, validation
      -> documents.jsonl | sections.jsonl | chunks.jsonl | chunks.csv | manifest.json   (milestone 2)
```

## Features

**Ingestion (milestone 1)**
- Formats: PDF (PyMuPDF), DOCX (python-docx), HTML (BeautifulSoup), TXT, scanned PDF and images (Tesseract OCR)
- Automatic format detection and scanned-PDF detection
- Common standardized schema and whitespace cleaning
- Streamlit interface with JSON download

**Knowledge base (milestone 2)**
- **Logical sections** with hierarchy (`Managing diabetes > Blood Glucose Control`) and clinical section types (`diagnosis`, `management`, `risk_factors`, `chief_complaint`, `plan`, ...)
- **Structure-aware chunking**: chunks never cross section boundaries; paragraphs stay whole; lists keep their lead-in; tables become their own chunks (header repeated when split)
- **Noise control**: table of contents, front matter, reference lists, running headers, page numbers and chart residue are kept out of the index but stay traceable in `sections.jsonl`
- **Metadata preserved** on every chunk: source file, format, document type, author, page range, extraction method, content hash, ingestion time
- **Retrieval-ready**: `embedding_text` (section path + text), deterministic chunk IDs, prev/next links, de-duplication across documents
- Built-in validation report and a BM25 search baseline to sanity-check the dataset
- CLI, Python API and a Streamlit page

## Project structure

```
clinical_document_ingestion/
├── app.py                        Milestone 1 Streamlit app
├── build_kb.py                   Milestone 2 CLI
├── requirements.txt
├── README.md
├── AI_USAGE.md
├── README_KB.md                  Detailed knowledge base notes
├── test_*.py                     Milestone 1 tests
├── test_knowledgebase.py         Milestone 2 tests (33)
│
├── extractors/                   pdf, docx, txt, html, ocr extractors
├── processing/                   pipeline, schema, cleaning, chunking
├── knowledgebase/                Milestone 2 package
│   ├── config.py                 KBConfig (chunk size, overlap, exclusions)
│   ├── vocab.py                  clinical heading vocabulary, section/document typing
│   ├── blocks.py                 format parsers -> typed blocks
│   ├── sectioning.py             hierarchy, section types, reference/noise tagging
│   ├── chunker.py                structure-aware chunking
│   ├── metadata.py               document metadata
│   ├── builder.py                corpus orchestration and file output
│   ├── validate.py               dataset integrity checks
│   └── search.py                 BM25 baseline
├── pages/2_Knowledge_Base.py     Streamlit page
└── output/                       generated datasets (git-ignored)
```

## Installation

```bash
python -m venv venv
.\venv\Scripts\Activate.ps1          # Windows PowerShell
pip install -r requirements.txt
pip install pytest                    # for the tests
```

Install **Tesseract OCR** separately for scanned documents. Default Windows path: `C:\Program Files\Tesseract-OCR\tesseract.exe`.

## Usage

**Streamlit**
```bash
streamlit run app.py
```
Open **Knowledge Base** in the sidebar, upload documents (or enter a folder path), adjust chunk size and overlap, click **Build knowledge base**, then explore the Documents, Outline, Chunks and Search tabs and download the dataset.

**Command line**
```bash
python build_kb.py ./clinical_docs --out output/knowledge_base
python build_kb.py ./clinical_docs --max-chars 1000 --overlap 120
python build_kb.py ./clinical_docs --query "diagnostic criteria for diabetes" --type diagnosis
python build_kb.py ./scans --tesseract "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

**Python**
```python
from knowledgebase import build_knowledge_base, KBConfig, KBSearcher

manifest = build_knowledge_base("clinical_docs", "output/kb", KBConfig(max_chars=1000))
hits = KBSearcher(manifest["files"]["chunks"]).search("insulin access", k=3, section_type="management")
```

## Output dataset

| File | Content |
|---|---|
| `chunks.jsonl` | The retrieval dataset: one self-contained record per chunk |
| `documents.jsonl` | Document metadata, type, outline, counts |
| `sections.jsonl` | All sections, including non-indexed ones with `skip_reason` |
| `chunks.csv` | Flat view for spreadsheets and pandas |
| `manifest.json` | Counts, distributions, failures, duplicates, validation, config |

Chunk record (abridged):
```json
{
  "chunk_id": "doc_19775ace59ea27d6-003-01",
  "doc_id": "doc_19775ace59ea27d6",
  "text": "| Type of test | In-range (mg/dL) | ...",
  "embedding_text": "Clinical Assessment > How common is diabetes?\nTable columns: ...",
  "section_path": ["How common is diabetes?"],
  "section_type": "epidemiology",
  "chunk_type": "table",
  "page_start": null, "page_end": null,
  "prev_chunk_id": "...", "next_chunk_id": null,
  "doc_metadata": {"source_file": "Clinical Assessment.docx", "doc_type": "patient_education", "...": "..."}
}
```

## Results on the sample documents

WHO Global Report on Diabetes (88-page PDF), Clinical Assessment (DOCX), sample HTML, sample TXT and a scanned image:

| Metric | Value |
|---|---|
| Documents processed / failed | 5 / 0 |
| Sections (indexed) | 157 (111) |
| Chunks | 194 |
| Median chunk size | 912 characters |
| Validation | 0 errors, 0 warnings |

## Testing

```bash
python -m pytest test_knowledgebase.py -q
```
33 tests cover heading rules, each parser, PDF clean-up, reference and noise filtering, chunking rules (section boundaries, overlap, tables, lists), de-duplication, deterministic output and an end-to-end build with a corrupt file and a duplicate file. Fixtures are generated on the fly.

## Design decisions
- Sections are hard chunk boundaries so a chunk never mixes topics.
- Only paragraphs larger than the size limit are split, on sentence boundaries, with sentence-aligned overlap.
- DOCX and HTML are re-read structurally because the milestone 1 extractors flatten styles, list structure and table position.
- Running headers must recur on neighbouring pages to be removed, so headings that repeat once per chapter (e.g. `REFERENCES`) are kept.
- One failing file never stops a run; failures are reported in the manifest.

## Limitations
- PDF tables are not reconstructed; table cells in PDFs can produce a few stray headings.
- PDF headings are detected by wording and capitalization, not font size.
- Unstyled DOCX and TXT rely on short-line heuristics.
- OCR output may contain errors in clinical terms and numbers.
- Chunk sizes are in characters; `token_estimate` is characters / 4.
- The BM25 search is a baseline, not a substitute for embeddings.
- Documents containing patient-identifiable information need your own privacy review before processing or sharing.

## Roadmap
- Embedding generation for `embedding_text`
- Vector store with `section_type` and `doc_metadata` as filters
- PDF table extraction (`find_tables`)
- Retrieval and RAG question answering with prev/next context expansion

## Technologies
Python · Streamlit · PyMuPDF · python-docx · BeautifulSoup · pytesseract / Tesseract OCR · Pandas · Pillow · pytest
