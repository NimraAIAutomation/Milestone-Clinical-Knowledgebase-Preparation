"""Command-line entry point for knowledge base preparation.

Examples
  python build_kb.py ./clinical_docs
  python build_kb.py ./clinical_docs --out output/kb --max-chars 1000 --overlap 120
  python build_kb.py ./clinical_docs --query "diagnostic criteria for diabetes" --type diagnosis
"""
import argparse
import json
import sys

from knowledgebase import KBConfig, KBSearcher, build_knowledge_base


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a retrieval-ready clinical knowledge base.")
    ap.add_argument("input", nargs="+", help="directory and/or files to process")
    ap.add_argument("--out", default="output/knowledge_base")
    ap.add_argument("--max-chars", type=int, default=1200)
    ap.add_argument("--min-chars", type=int, default=250)
    ap.add_argument("--overlap", type=int, default=150, help="sentence-aligned overlap inside split paragraphs")
    ap.add_argument("--include-types", nargs="*", default=[],
                    help="section types to index even though excluded by default (toc front_matter references)")
    ap.add_argument("--no-recursive", action="store_true")
    ap.add_argument("--no-dedupe", action="store_true", help="keep duplicate documents and chunks")
    ap.add_argument("--tesseract", default=None, help="path to the tesseract executable (overrides the OCR default)")
    ap.add_argument("--query", help="run a test search on the finished dataset")
    ap.add_argument("--type", help="restrict --query to one section_type")
    a = ap.parse_args(argv)

    default_excl = KBConfig().exclude_section_types
    cfg = KBConfig(max_chars=a.max_chars, min_chars=a.min_chars, overlap_chars=a.overlap,
                   exclude_section_types=tuple(t for t in default_excl if t not in a.include_types),
                   recursive=not a.no_recursive, dedupe_documents=not a.no_dedupe,
                   dedupe_chunks=not a.no_dedupe, tesseract_cmd=a.tesseract)

    def progress(i, n, name):
        if name:
            print(f"[{i + 1}/{n}] {name}", file=sys.stderr)

    m = build_knowledge_base(a.input, a.out, cfg, progress=progress)
    c = m["counts"]
    print(f"\nDocuments: {c['documents_processed']} processed, {c['documents_failed']} failed, "
          f"{c['documents_skipped_duplicate']} duplicate")
    print(f"Sections : {c['sections']} ({c['sections_chunked']} indexed)")
    print(f"Chunks   : {c['chunks']}  (median {m['chunk_char_stats'].get('median')} chars, "
          f"{c['chunks_dropped_duplicate']} duplicates dropped)")
    v = m["validation"]
    print(f"Validation: {'OK' if v['ok'] else 'ERRORS'} ({v['errors']} errors, {v['warnings']} warnings)")
    for f in m["failures"]:
        print(f"  FAILED {f['file']}: {f['error']}")
    print(f"Output   : {a.out}/")
    if a.query:
        filt = {"section_type": a.type} if a.type else {}
        for score, ch in KBSearcher(m["files"]["chunks"]).search(a.query, k=5, **filt):
            print(f"\n{score:.2f}  {ch['doc_title']} | {ch['section_path_str']} | p{ch['page_start']}")
            print("   " + ch["text"][:200].replace("\n", " "))
    return 0 if v["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
