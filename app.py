import streamlit as st
import fitz  # PyMuPDF
import re
from io import BytesIO
from datetime import datetime
from pdf2image import convert_from_bytes
import pytesseract
from PIL import Image
import zipfile

# ---------------- UI ----------------
st.set_page_config(page_title="PDF Rename", page_icon="📄")
st.title("PDF Rename")

st.write("""
The file will be renamed based on the name, start date, and end date in the PDF.

**Supports:**
- Individual upload and download as a single file  
- Batch upload and download as a zipped file

**🔒 Note:**  
Files uploaded here are only visible to you. Other users cannot access your files or downloads.
""")

# ---------------- Helpers ----------------
MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|June|July|August|September|October|November|December)"
BAD_CTX = re.compile(rf"start\s*date|end\s*date|{MONTHS}", re.IGNORECASE)

def clean_name(raw: str) -> str:
    """Normalize spacing/casing for names, keep hyphens/apostrophes."""
    name = re.sub(r"\s+", " ", raw).strip(" \t:-")
    # Title-case tokens, preserving - and '
    parts = []
    for token in name.split(" "):
        t = "-".join(p.capitalize() if p else p for p in token.split("-"))
        t = "'".join(p.capitalize() if p else p for p in t.split("'"))
        parts.append(t)
    return " ".join(parts)

def find_full_name(text: str) -> str | None:
    """
    Extract a likely full name:
      1) Labeled line: 'Name:', 'Full Name:', 'Customer Name:' etc.
      2) Multi-word capitalized phrase (2–5 tokens, supports - and ')
      3) ALL-CAPS variant (then title-cased)
    Avoids lines with dates/months/labels.
    """
    # 1) Labeled line
    labeled_pat = re.compile(
        r"^(?:customer\s+name|employee\s+name|full\s*name|name)\s*:?\s*(.+)$",
        re.IGNORECASE
    )
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        if BAD_CTX.search(ln):
            continue
        m = labeled_pat.search(ln)
        if m:
            cand = re.sub(r"[^A-Za-z\s\-']", " ", m.group(1))
            cand = re.sub(r"\s+", " ", cand).strip()
            if 2 <= len(cand.split()) <= 5:
                return clean_name(cand)

    # Common name token: Zhang / Jian / Liang / O'Connor / Jean-Luc
    token = r"(?:[A-Z][a-z]+(?:[-'][A-Za-z]+)?)"

    # 2) Mixed-case multiword names (2–5 tokens)
    patt_mixed = re.compile(rf"\b({token}(?:\s+{token}){{1,4}})\b")
    candidates = [m.group(1) for m in patt_mixed.finditer(text) if not BAD_CTX.search(m.group(1))]
    if candidates:
        # Prefer the longest (e.g., 'Zhang Jian Liang' over 'Zhang Jian')
        return clean_name(max(candidates, key=lambda s: (len(s.split()), len(s))))

    # 3) ALL-CAPS multiword names (2–5 tokens)
    token_caps = r"(?:[A-Z]+(?:[-'][A-Z]+)?)"
    patt_caps = re.compile(rf"\b(({token_caps})(?:\s+{token_caps}){{1,4}})\b")
    candidates = [m.group(1) for m in patt_caps.finditer(text) if not BAD_CTX.search(m.group(1))]
    if candidates:
        return clean_name(max(candidates, key=lambda s: (len(s.split()), len(s))))

    return None

def extract_text_from_pdf(uploaded) -> str:
    """
    Extract text via PyMuPDF; fall back to OCR if needed.
    Reads the file once to bytes so we can reuse it.
    """
    uploaded.seek(0)
    pdf_bytes = uploaded.read()
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            text = "\n".join(page.get_text() for page in doc)
            if text and text.strip():
                return text
    except Exception:
        pass
    # Fallback OCR
    try:
        images = convert_from_bytes(pdf_bytes)
        text = "\n".join(pytesseract.image_to_string(img) for img in images)
        return text
    except Exception:
        return ""

def extract_info_from_text(text: str):
    # --- Name ---
    name = find_full_name(text)
    name_slug = name.replace(" ", "_") if name else "Unknown_Name"

    # --- Dates (supports 'Start Date: 01-Jan-2025' style) ---
    start_match = re.search(r"Start\s*Date\s*:\s*(\d{2}-[A-Za-z]{3}-\d{4})", text, re.IGNORECASE)
    end_match   = re.search(r"End\s*Date\s*:\s*(\d{2}-[A-Za-z]{3}-\d{4})",   text, re.IGNORECASE)
    start_date = start_match.group(1) if start_match else "UnknownStart"
    end_date   = end_match.group(1)   if end_match   else "UnknownEnd"

    # --- Labels ---
    try:
        start_dt = datetime.strptime(start_date, "%d-%b-%Y")
        end_dt   = datetime.strptime(end_date,   "%d-%b-%Y")
        file_label = f"{name_slug}_{start_dt.strftime('%Y.%m.%d')}-{end_dt.strftime('%m.%d')}.pdf"
        zip_label  = f"{start_dt.strftime('%Y.%m.%d')}-{end_dt.strftime('%m.%d')}.zip"
    except Exception:
        file_label = f"{name_slug}_UnknownDate.pdf"
        zip_label  = "UnknownDate.zip"

    return file_label, zip_label

# ---------------- App Logic ----------------
uploaded_files = st.file_uploader("Upload PDF(s)", type="pdf", accept_multiple_files=True)

renamed_files = []
zip_filename = "renamed_pdfs.zip"

if uploaded_files:
    for uploaded_file in uploaded_files:
        st.write(f"Processing: {uploaded_file.name}")
        try:
            text = extract_text_from_pdf(uploaded_file)
            new_name, zip_filename = extract_info_from_text(text)

            # Re-read bytes for download since we consumed earlier
            uploaded_file.seek(0)
            file_bytes = uploaded_file.read()
            renamed_files.append((new_name, file_bytes))

            st.success(f"Renamed to: {new_name}")
            st.download_button(
                label="🔀 Download Renamed PDF",
                data=file_bytes,
                file_name=new_name,
                mime="application/pdf"
            )
        except Exception as e:
            st.error(f"Failed to process {uploaded_file.name}: {e}")

    if renamed_files:
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zipf:
            for filename, content in renamed_files:
                zipf.writestr(filename, content)
        zip_buffer.seek(0)

        st.download_button(
            label="📁 Download All as ZIP",
            data=zip_buffer,
            file_name=zip_filename,
            mime="application/zip"
        )
