"""Streamlit page: build and explore the clinical knowledge base."""
import io
import json
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

from knowledgebase import KBConfig, KBSearcher, build_knowledge_base

st.set_page_config(page_title="Clinical Knowledge Base", layout="wide")
st.title("Clinical Knowledge Base Preparation")
st.caption("Upload documents -> sections -> structure-aware chunks -> retrieval-ready dataset")

with st.sidebar:
    st.header("Chunking")
    max_chars = st.slider("Max chunk size (chars)", 400, 3000, 1200, 100)
    min_chars = st.slider("Merge trailing chunks smaller than", 0, 600, 250, 50)
    overlap = st.slider("Overlap inside split paragraphs", 0, 400, 150, 25)
    st.header("Indexing")
    keep_refs = st.checkbox("Also index reference lists", value=False)
    keep_front = st.checkbox("Also index front matter / contents", value=False)
    tess = st.text_input("Tesseract path (optional)", "")

files = st.file_uploader("Clinical documents", accept_multiple_files=True,
                         type=["pdf", "docx", "txt", "html", "htm", "png", "jpg", "jpeg", "tiff", "bmp"])
folder = st.text_input("...or a folder path on this machine", "")

if st.button("Build knowledge base", type="primary"):
    excl = [t for t in ("toc", "front_matter", "references")
            if not ((t == "references" and keep_refs) or (t in ("toc", "front_matter") and keep_front))]
    try:
        cfg = KBConfig(max_chars=max_chars, min_chars=min_chars, overlap_chars=overlap,
                       exclude_section_types=tuple(excl), tesseract_cmd=tess or None).validate()
    except ValueError as e:
        st.error(str(e))
        st.stop()
    work = Path(tempfile.mkdtemp(prefix="kb_"))
    inputs = []
    if folder.strip():
        inputs.append(folder.strip())
    if files:
        up = work / "uploads"
        up.mkdir()
        for f in files:
            (up / Path(f.name).name).write_bytes(f.getbuffer())
        inputs.append(up)
    if not inputs:
        st.warning("Upload files or enter a folder path.")
        st.stop()
    bar = st.progress(0.0, text="Starting...")
    manifest = build_knowledge_base(
        inputs, work / "kb", cfg,
        progress=lambda i, n, name: bar.progress(i / max(n, 1), text=f"Processing {name}" if name else "Finishing"))
    bar.empty()
    st.session_state["kb"] = {"manifest": manifest, "dir": str(work / "kb")}

kb = st.session_state.get("kb")
if kb:
    m, out = kb["manifest"], Path(kb["dir"])
    c = m["counts"]
    cols = st.columns(5)
    for col, (label, val) in zip(cols, [("Documents", c["documents_processed"]), ("Sections", c["sections"]),
                                         ("Indexed sections", c["sections_chunked"]), ("Chunks", c["chunks"]),
                                         ("Failed", c["documents_failed"])]):
        col.metric(label, val)
    v = m["validation"]
    (st.success if v["ok"] else st.error)(f"Validation: {v['errors']} errors, {v['warnings']} warnings")
    for f in m["failures"]:
        st.error(f"{Path(f['file']).name}: {f['error']}")

    t_docs, t_out, t_chunks, t_search, t_dl = st.tabs(["Documents", "Outline", "Chunks", "Search", "Download"])
    docs = [json.loads(l) for l in (out / "documents.jsonl").read_text(encoding="utf-8").splitlines()]
    chunks = [json.loads(l) for l in (out / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
    with t_docs:
        st.dataframe(pd.DataFrame([{k: d.get(k) for k in (
            "title", "file_name", "source_format", "doc_type", "extraction_method", "page_count", "word_count",
            "section_count", "chunk_count", "author")} for d in docs]), width="stretch")
    with t_out:
        sel = st.selectbox("Document", docs, format_func=lambda d: d["title"])
        if sel:
            st.dataframe(pd.DataFrame([{"section": "    " * (o["level"] - 1) + o["title"], "type": o["type"],
                                        "pages": f"{o['pages'][0]}-{o['pages'][1]}" if o["pages"][0] else "",
                                        "chunks": o["chunks"]} for o in sel["outline"]]), width="stretch")
    with t_chunks:
        types = sorted({c_["section_type"] for c_ in chunks})
        pick = st.multiselect("Section type", types)
        view = [c_ for c_ in chunks if not pick or c_["section_type"] in pick]
        st.write(f"{len(view)} chunks")
        for c_ in view[:50]:
            with st.expander(f"{c_['doc_title']} > {c_['section_path_str']} ({c_['char_count']} chars)"):
                st.caption(f"{c_['chunk_id']} | {c_['chunk_type']} | {c_['section_type']} | "
                           f"pages {c_['page_start']}-{c_['page_end']}")
                st.text(c_["text"])
    with t_search:
        q = st.text_input("Test query")
        if q:
            for score, c_ in KBSearcher(chunks=chunks).search(q, k=5):
                st.markdown(f"**{score:.2f}** - {c_['doc_title']} > {c_['section_path_str']} (p{c_['page_start']})")
                st.text(c_["text"][:400])
    with t_dl:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name in ("documents.jsonl", "sections.jsonl", "chunks.jsonl", "chunks.csv", "manifest.json"):
                z.write(out / name, name)
        st.download_button("Download dataset (zip)", buf.getvalue(), "clinical_knowledge_base.zip")
