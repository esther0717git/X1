import streamlit as st
import fitz  # PyMuPDF
import re
from io import BytesIO
from datetime import datetime
from pdf2image import convert_from_bytes
import pytesseract
from PIL import Image
import zipfile

st.set_page_config(page_title="PDF Rename (Merged Support)", page_icon="📄")
st.title("PDF Rename")

st.write("""
Upload one or more PDFs. If a PDF is a **merged file** containing multiple forms,
this app will split it into parts and rename **each** part based on the detected **name** and **dates**.

**How splitting works:** a new sub-document starts on any page that contains the phrase **"Start Date"**.
If that phrase never appears, the entire PDF is treated as a single document.

**Outputs:**
- A single **ZIP** containing all renamed PDFs.
""")

# ---------- Name & Date helpers ----------
def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> list[str]:
    """Return a list of page texts using PyMuPDF; if it fails, OCR each page."""
    try:
        page_texts = []
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for pg in doc:
                page_texts.append(pg.get_text() or "")
        # If we got any non-empty text, use it
        if any(t.strip() for t in page_texts):
            return page_texts
    except Exception:
        pass

    # Fallback to OCR (slower)
    images = convert_from_bytes(pdf_bytes)
    page_texts = [pytesseract.image_to_string(img) for img in images]
    return page_texts

def extract_name(text: str) -> str:
    """
    Capture a person name as 2–4 capitalized words (e.g., 'Zhang Jian Liang').
    """
    m = re.search(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})\b", text)
    if m:
        return m.group(1)
    return "Unknown Name"

def extract_dates(text: str) -> tuple[str, str]:
    """
    Expect 'Start Date: 21-Oct-2025' and 'End Date: 31-Oct-2025'.
    Returns start_str, end_str (or placeholders).
    """
    sm = re.search(r"Start\s*Date\s*:\s*(\d{2}-[A-Za-z]{3}-\d{4})", text, re.IGNORECASE)
    em = re.search(r"End\s*Date\s*:\s*(\d{2}-[A-Za-z]{3}-\d{4})",   text, re.IGNORECASE)
    return (sm.group(1) if sm else "UnknownStart",
            em.group(1) if em else "UnknownEnd")

def label_from(name: str, start_str: str, end_str: str) -> tuple[str, str]:
    """Build file name and zip folder name (kept for consistency)."""
    name_slug = name.replace(" ", "_")
    try:
        start_dt = datetime.strptime(start_str, "%d-%b-%Y")
        end_dt   = datetime.strptime(end_str,   "%d-%b-%Y")
        file_label = f"{name_slug}_{start_dt.strftime('%Y.%m.%d')}-{end_dt.strftime('%m.%d')}.pdf"
        zip_label  = f"{start_dt.strftime('%Y.%m.%d')}-{end_dt.strftime('%m.%d')}.zip"
    except Exception:
        file_label = f"{name_slug}_UnknownDate.pdf"
        zip_label  = "UnknownDate.zip"
    return file_label, zip_label

def split_merged_pdf(pdf_bytes: bytes):
    """
    Split a merged PDF into sub-documents using the 'Start Date' page as a boundary.
    Returns a list of dicts:
      [{'from': a, 'to': b, 'text': '...', 'name': '...', 'start': '...', 'end': '...'}]
    """
    parts = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        page_texts = extract_text_from_pdf_bytes(pdf_bytes)
        n = len(doc)

        # find boundary pages (indexes) – start of each part
        boundaries = []
        for i, t in enumerate(page_texts):
            if re.search(r"Start\s*Date\s*:", t, re.IGNORECASE):
                boundaries.append(i)
        if not boundaries:
            boundaries = [0]  # whole doc as one part

        # ensure last boundary captures to end
        boundaries.append(n)  # sentinel

        for idx in range(len(boundaries) - 1):
            start_pg = boundaries[idx]
            end_pg_exclusive = boundaries[idx + 1]
            end_pg = end_pg_exclusive - 1
            if start_pg > end_pg:
                continue

            # concatenate text for this range
            part_text = "\n".join(page_texts[start_pg:end_pg+1])

            # extract metadata
            name = extract_name(part_text)
            start_str, end_str = extract_dates(part_text)

            parts.append({
                "from": start_pg,
                "to": end_pg,
                "text": part_text,
                "name": name,
                "start": start_str,
                "end": end_str,
            })
    return parts

def export_part_as_pdf_bytes(src_pdf_bytes: bytes, from_page: int, to_page: int) -> bytes:
    """Create a new PDF containing pages [from_page..to_page] from the source."""
    src = fitz.open(stream=src_pdf_bytes, filetype="pdf")
    new_pdf = fitz.open()
    new_pdf.insert_pdf(src, from_page=from_page, to_page=to_page)
    buf = BytesIO()
    new_pdf.save(buf)
    new_pdf.close()
    src.close()
    buf.seek(0)
    return buf.read()

# ---------- Streamlit App Logic ----------
uploaded_files = st.file_uploader("Upload PDF(s)", type="pdf", accept_multiple_files=True)

zip_items = []  # (filename, bytes)
overall_zip_name = "renamed_parts.zip"

if uploaded_files:
    for uploaded in uploaded_files:
        st.write(f"Processing: {uploaded.name}")

        # read once
        uploaded.seek(0)
        pdf_bytes = uploaded.read()

        try:
            parts = split_merged_pdf(pdf_bytes)

            # handle duplicate names by appending a counter when needed
            seen = {}

            for idx, p in enumerate(parts, 1):
                part_pdf = export_part_as_pdf_bytes(pdf_bytes, p["from"], p["to"])

                base_filename, per_file_zipname = label_from(p["name"], p["start"], p["end"])
                # de-dup filenames within the same upload
                key = base_filename.lower()
                if key in seen:
                    seen[key] += 1
                    root, ext = base_filename.rsplit(".pdf", 1)
                    base_filename = f"{root} ({seen[key]}).pdf"
                else:
                    seen[key] = 1

                zip_items.append((base_filename, part_pdf))
                st.success(f"  • Part {idx}: pages {p['from']+1}-{p['to']+1} → {base_filename}")

        except Exception as e:
            st.error(f"Failed to process {uploaded.name}: {e}")

    if zip_items:
        # build one ZIP containing all parts from all uploads
        zip_buf = BytesIO()
        with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
            for fname, content in zip_items:
                zipf.writestr(fname, content)
        zip_buf.seek(0)

        st.download_button(
            label="📁 Download All Renamed Parts (ZIP)",
            data=zip_buf,
            file_name=overall_zip_name,
            mime="application/zip"
        )
