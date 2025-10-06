import streamlit as st
import fitz  # PyMuPDF
import re
from io import BytesIO
from datetime import datetime
from pdf2image import convert_from_bytes
import pytesseract
import zipfile

st.set_page_config(page_title="PDF Rename", page_icon="📄")
st.title("PDF Rename")

st.write("""
Automatically rename PDF(s) based on the **name, start date, and end date** found inside.

**Smart features:**
- 📄 Single PDF → renamed directly  
- 📚 Merged PDF (multiple “Start Date” sections) → split, rename each part, and download as ZIP  

**Note:** Files uploaded here are only visible to you.
""")


# ---------------------- Helpers ----------------------
def extract_text_pages(pdf_bytes):
    """Extract text per page; fall back to OCR if needed."""
    try:
        page_texts = []
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page in doc:
                page_texts.append(page.get_text())
        if any(t.strip() for t in page_texts):
            return page_texts
    except Exception:
        pass

    # fallback to OCR
    from pdf2image import convert_from_bytes
    images = convert_from_bytes(pdf_bytes)
    return [pytesseract.image_to_string(img) for img in images]


def extract_name(text):
    """Extract a person name (2–4 capitalized words)."""
    m = re.search(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})\b", text)
    return m.group(1) if m else "Unknown_Name"


def extract_dates(text):
    """Extract start and end date strings."""
    sm = re.search(r"Start\s*Date\s*:\s*(\d{2}-[A-Za-z]{3}-\d{4})", text, re.IGNORECASE)
    em = re.search(r"End\s*Date\s*:\s*(\d{2}-[A-Za-z]{3}-\d{4})", text, re.IGNORECASE)
    start = sm.group(1) if sm else "UnknownStart"
    end = em.group(1) if em else "UnknownEnd"
    return start, end


def format_filename(name, start, end):
    """Format output file name and zip name."""
    name_slug = name.replace(" ", "_")
    try:
        s_dt = datetime.strptime(start, "%d-%b-%Y")
        e_dt = datetime.strptime(end, "%d-%b-%Y")
        fname = f"{name_slug}_{s_dt.strftime('%Y.%m.%d')}-{e_dt.strftime('%m.%d')}.pdf"
        zipname = f"{s_dt.strftime('%Y.%m.%d')}-{e_dt.strftime('%m.%d')}.zip"
    except Exception:
        fname = f"{name_slug}_UnknownDate.pdf"
        zipname = "UnknownDate.zip"
    return fname, zipname


def split_pdf(pdf_bytes):
    """Split PDF into parts based on 'Start Date'."""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        texts = extract_text_pages(pdf_bytes)
        boundaries = [i for i, t in enumerate(texts) if re.search(r"Start\s*Date", t, re.IGNORECASE)]
        if not boundaries:
            return [{"from": 0, "to": len(doc) - 1, "text": "\n".join(texts)}]

        boundaries.append(len(doc))
        parts = []
        for i in range(len(boundaries) - 1):
            start = boundaries[i]
            end = boundaries[i + 1] - 1
            part_text = "\n".join(texts[start:end + 1])
            parts.append({"from": start, "to": end, "text": part_text})
        return parts


def export_pages(pdf_bytes, from_page, to_page):
    """Export selected pages as bytes."""
    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    new_pdf = fitz.open()
    new_pdf.insert_pdf(src, from_page=from_page, to_page=to_page)
    buf = BytesIO()
    new_pdf.save(buf)
    new_pdf.close()
    src.close()
    buf.seek(0)
    return buf.read()


# ---------------------- App Logic ----------------------
uploaded_files = st.file_uploader("Upload PDF(s)", type="pdf", accept_multiple_files=True)

if uploaded_files:
    for uploaded in uploaded_files:
        st.write(f"Processing: **{uploaded.name}**")
        uploaded.seek(0)
        pdf_bytes = uploaded.read()

        # Split into parts
        parts = split_pdf(pdf_bytes)

        if len(parts) == 1:
            # Single file (rename + direct download)
            text = parts[0]["text"]
            name = extract_name(text)
            start, end = extract_dates(text)
            filename, _ = format_filename(name, start, end)

            st.success(f"Renamed to: {filename}")
            st.download_button(
                label="🔽 Download Renamed PDF",
                data=pdf_bytes,
                file_name=filename,
                mime="application/pdf"
            )
        else:
            # Merged file (multiple parts → ZIP)
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
                for idx, part in enumerate(parts, 1):
                    text = part["text"]
                    name = extract_name(text)
                    start, end = extract_dates(text)
                    filename, zipname = format_filename(name, start, end)
                    part_bytes = export_pages(pdf_bytes, part["from"], part["to"])
                    zipf.writestr(filename, part_bytes)
                    st.success(f"Part {idx}: pages {part['from']+1}-{part['to']+1} → {filename}")

            zip_buffer.seek(0)
            st.download_button(
                label="📦 Download All as ZIP",
                data=zip_buffer,
                file_name="renamed_parts.zip",
                mime="application/zip"
            )
