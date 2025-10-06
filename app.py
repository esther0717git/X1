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
BAD_DATE_CTX = re.compile(rf"start\s*date|end\s*date|{MONTHS}", re.IGNORECASE)

# Phrases that strongly indicate a company, not a person
COMPANY_HINTS = re.compile(
    r"(?:\bcompany\b|\bco\b\.?|private\s+limited|pte\s+ltd|limited|ltd|inc|corp(?:oration)?|"
    r"technology|technologies|solutions?|holdings?|group|plc|llc|llp)",
    re.IGNORECASE
)

def clean_name(raw: str) -> str:
    """Normalize spacing/casing for names, keep hyphens/apostrophes."""
    name = re.sub(r"\s+", " ", raw).strip(" \t:-")
    parts = []
    for token in name.split(" "):
        t = "-".join(p.capitalize() if p else p for p in token.split("-"))
        t = "'".join(p.capitalize() if p else p for p in t.split("'"))
        parts.append(t)
    return " ".join(parts)

def looks_like_company(text: str) -> bool:
    return bool(COMPANY_HINTS.search(text))

def find_full_name(text: str) -> str | None:
    """
    Extract the *first person name*:
      1) First labeled name line (Name:, Employee Name:, etc.)
      2) Otherwise, the first multi-word capitalized phrase (2–5 tokens) that does NOT look like a company.
      3) ALL-CAPS fallback (also excluding company-looking phrases)
    """
    # 1) Labeled line first
    labeled_pat = re.compile(
        r"^(?:customer\s+name|employee\s+name|full\s*name|name)\s*:?\s*(.+)$",
        re.IGNORECASE
    )
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        if BAD_DATE_CTX.search(ln):
            continue
        m = labeled_pat.search(ln)
        if m:
            cand = re.sub(r"[^A-Za-z\s\-']", " ", m.group(1))
            cand = re.sub(r"\s+", " ", cand).strip()
            if 2 <= len(cand.split()) <= 5 and not looks_like_company(cand):
                return clean_name(cand)

    # 2) First mixed-case multiword name (2–5 tokens), skipping company-looking phrases
    token = r"(?:[A-Z][a-z]+(?:[-'][A-Za-z]+)?)"
    patt_mixed = re.compile(rf"\b({token}(?:\s+{token}){{1,4}})\b")
    for m in patt_mixed.finditer(text):
        span_text = m.group(1)
        if BAD_DATE_CTX.search(span_text):
            continue
        if not looks_like_company(span_text):
            return clean_name(span_text)

    # 3) ALL-CAPS fallback (e.g., OCR or forms), still avoiding company-ish phrases
    token_caps = r"(?:[A-Z]+(?:[-'][A-Z]+)?)"
    patt_caps = re.compile(rf"\b(({token_caps})(?:\s+{token_caps}){{1,4}})\b")
    for m in patt_caps.finditer(text):
        span_text = m.group(1)
        if BAD_DATE_CTX.search(span_text):
            continue
        if not looks_like_company(span_text):
            return clean_name(span_text)

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
    # --- Name (person) ---
    name = find_full_name(text)
    name_slug = name.replace(" ", "_") if name else "Unknown_Name"

    # --- Dates ---
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

            # Re-read bytes for download
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
