
import streamlit as st
import tempfile
import json
import os
from pathlib import Path

from processing.pipeline import (
    extract_document,
    standardize_document
)
from processing.cleaning import clean_document
from processing.chunking import chunk_document


st.set_page_config(
    page_title="Clinical Document Ingestion",
    page_icon="📄",
    layout="wide"
)

st.title("Clinical Document Ingestion Pipeline")
st.write(
    "Upload clinical documents to extract, clean, "
    "standardize and prepare text chunks for RAG."
)

st.sidebar.header("Chunking Settings")

chunk_size = st.sidebar.slider(
    "Chunk Size (characters)",
    min_value=200,
    max_value=5000,
    value=1000,
    step=100
)

overlap = st.sidebar.slider(
    "Chunk Overlap (characters)",
    min_value=0,
    max_value=1000,
    value=200,
    step=50
)

max_chunks = st.sidebar.number_input(
    "Maximum Number of Chunks",
    min_value=1,
    max_value=5000,
    value=100,
    step=10
)

uploaded_files = st.file_uploader(
    "Upload clinical documents",
    type=[
        "pdf", "docx", "txt", "html",
        "htm", "png", "jpg", "jpeg",
        "tiff", "bmp"
    ],
    accept_multiple_files=True
)

if st.button("Process Documents", type="primary"):
    if not uploaded_files:
        st.warning("Please upload at least one document.")

    else:
        for uploaded_file in uploaded_files:
            st.divider()
            st.subheader(uploaded_file.name)

            temp_path = None

            try:
                suffix = Path(uploaded_file.name).suffix

                with tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=suffix
                ) as temp_file:
                    temp_file.write(uploaded_file.getvalue())
                    temp_path = temp_file.name

                with st.spinner(
                    f"Processing {uploaded_file.name}..."
                ):
                    extracted = extract_document(temp_path)

                    # Restore the original uploaded filename
                    extracted["metadata"]["source"] = (
                        uploaded_file.name
                    )

                    document = standardize_document(extracted)
                    document = clean_document(document)

                    all_chunks = chunk_document(
                    document,
                    chunk_size=chunk_size,
                    overlap=overlap
                    )

                    total_chunks = len(all_chunks)

                    chunks = all_chunks[:max_chunks]
                    

                col1, col2, col3, col4 = st.columns(4)

                col1.metric("Format", document["source_format"])
                col2.metric("Total Available", total_chunks)
                col3.metric("Generated Chunks", len(chunks))
                col4.metric("Chunk Size", chunk_size)

                if total_chunks > max_chunks:
                    st.warning(
                        f"Showing {max_chunks} of {total_chunks} chunks. "
                        "Some document content is excluded from the output."
                    )

                with st.expander("Document Metadata"):
                    st.json(document["metadata"])

                with st.expander("Extracted Content"):
                    st.json(document["content"])

                with st.expander("Chunk Preview"):
                    for chunk in chunks[:5]:
                        st.markdown(
                            f"**Chunk {chunk['chunk_id']}**"
                        )
                        st.caption(chunk["metadata"])
                        st.write(chunk["text"])

                output = {
                    "document": document,
                    "chunks": chunks
                }

                st.download_button(
                    label="Download JSON",
                    data=json.dumps(
                        output,
                        indent=2,
                        ensure_ascii=False
                    ),
                    file_name=(
                        Path(uploaded_file.name).stem
                        + "_processed.json"
                    ),
                    mime="application/json"
                )

                st.success(
                    f"Successfully processed {uploaded_file.name}"
                )

            except Exception as error:
                st.error(f"Processing failed: {error}")

            finally:
                if temp_path and os.path.exists(temp_path):
                    os.unlink(temp_path)
