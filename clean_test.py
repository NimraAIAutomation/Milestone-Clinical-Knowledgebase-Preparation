from processing.pipeline import (
    extract_document,
    standardize_document
)
from processing.cleaning import clean_document

files = [
    "diabetes.pdf",
    "Clinical Assessment.docx",
    "sample_clinical.txt",
    "sample_clinical.html"
]

for file_path in files:
    extracted = extract_document(file_path)
    document = standardize_document(extracted)

    cleaned = clean_document(document)

    print("\n" + "=" * 40)
    print("File:", file_path)
    print("Format:", cleaned["source_format"])
    print("Cleaning successful:", isinstance(cleaned, dict))
    print("Metadata preserved:", "metadata" in cleaned)