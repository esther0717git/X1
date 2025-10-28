import streamlit as st
import fitz  # PyMuPDF
import re
from io import BytesIO
from datetime import datetime
import zipfile

# Optional OCR dependencies
try:
    from pdf2image import convert_from_bytes
    import pytesseract
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False


# ---------------------- PAGE SETUP ----------------------
st.set_page_config(page_title="PDF Rename Tool", page_icon="📄", layout="wide")

# --- Custom CSS for a polished UI ---
st.markdown(
    """
    <style>
      .main-title {text-align:center; font-size:2.2rem; font-weight:700; margin-bottom:0.3rem;}
      .subtitle {text-align:center; color:#6c757d; margin-bottom:1.8rem;}
      .section-header {font-size:1.25rem; font-weight:600; margin-top:1.6rem; margin-bottom:0.5rem; color:#2e7dba;}
      .info-card {
          border:1px solid rgba(0,0,0,0.08);
          background-color:#f8f9fa;
          border-radius:12px;
          padding:1rem 1.5rem;
          margin-bottom:1.2rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------- HEADER ----------------------
st.markdown("<div class='main-title'>📄 PDF Rename Tool</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='subtitle'>Automatically rename PDF(s) using detected <b>Order No</b>, <b>Name</b>, <b>Start Date</b>, and <b>End Date</b>.</div>",
    unsafe_allow_html=True,
)

# ---------------------- CONSTANTS ----------------------
START_REGEX = r"Start\s*Date\s*:\s*([0-9]{2}-[A-Za-z]{3}-[0-9]{4}|[0-9]{2}/[0-9]{2}/[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})"
END_REGEX = r"End\s*Date\s*:\s*([0-9]{2}-[A-Za-z]{3}-[0-9]{4}|[0-9]{2}/[0-9]{2}/[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})"
SPLIT_ANCHOR = r"Start\s*Date"
ORDER_PATTERNS = [
    r"Order\s*(?:No\.?|Number|#|ID)\s*[:\-]?\s*([A-Z0-9\-]{5,})",
    r"\bPO\s*[:\-]?\s*([A-Z0-9\-]{5,})",
    r"\bSO\s*[:\-]?\s*([A-Z0-9\-]{5,})",
]
DATE_FORMATS = ["%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"]


# ---------------------- HELPER FUNCTIONS ----------------------
def safe_slug(s: str | None) -> str:
    s = s or ""
    s = re.sub(r"[^\w\s\-\.]+", "", s)
    s = re.sub(r"\s+", "_", s.strip())
    return s or "Unknown"


def extract_text_pages(pdf_bytes: bytes) -> list[str]:
    """Extract text from each page, fallback to OCR if no text found."""
    try:
        texts = []
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page in doc:
                texts.append(page.get_text() or "")
        if any(t.strip() for t in texts):
            return texts
    except Exception:
        pass

    if OCR_AVAILABLE:
        try:
            images = convert_from_bytes(pdf_bytes)
            return [pytesseract.image_to_string(img) for img in images]
        except Exception:
            pass
    return [""]


def extract_order_number(text: str) -> str | None:
    for pat in ORDER_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = re.sub(r"[^A-Za-z0-9\-]", "", m.group(1))
            if not re.match(r"\d{4}-\d{2}-\d{2}", val):  # avoid reading dates
                return val
    return None


def guess_name_from_text(text: str) -> str:
    m = re.search(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})\b", text)
    return m.group(1) if m else "Unknown_Name"


def find_date_strings(text: str) -> tuple[str, str]:
    sm = re.search(START_REGEX, text, re.IGNORECASE)
    em = re.search(END_REGEX, text, re.IGNORECASE)
    return (sm.group(1) if sm else ""), (em.group(1) if em else "")


def parse_date(s: str) -> datetime | None:
    s = (s or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return None


def build_filename(order, name, s_dt, e_dt) -> str:
    name_slug = safe_slug(name)
    order_slug = safe_slug(order) if order else None
    if s_dt and e_dt:
        fname = f"{order_slug+'_' if order_slug else ''}{name_slug}_{s_dt.strftime('%Y.%m.%d')}-{e_dt.strftime('%m.%d')}.pdf"
    else:
        fname = f"{order_slug+'_' if order_slug else ''}{name_slug}_UnknownDate.pdf"
    return fname


def split_pdf(pdf_bytes):
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        texts = extract_text_pages(pdf_bytes)
        marks = [i for i, t in enumerate(texts) if re.search(SPLIT_ANCHOR, t, re.IGNORECASE)]
        if not marks:
            return [{"from": 0, "to": len(doc) - 1, "text": "\n".join(texts)}]
        marks.append(len(doc))
        return [{"from": marks[i], "to": marks[i+1]-1, "text": "\n".join(texts[marks[i]:marks[i+1]])} for i in range(len(marks)-1)]


def export_pages(pdf_bytes, from_page, to_page):
    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    new = fitz.open()
    new.insert_pdf(src, from_page=from_page, to_page=to_page)
    buf = BytesIO()
    new.save(buf)
    new.close()
    src.close()
    buf.seek(0)
    return buf.read()


# ---------------------- UPLOAD SECTION ----------------------
st.markdown("<div class='section-header'>📂 Upload Your PDF Files</div>", unsafe_allow_html=True)
st.markdown("<div class='info-card'>Upload single or merged PDFs. The app will extract info and rename automatically based on detected fields.</div>", unsafe_allow_html=True)

uploaded = st.file_uploader("Upload PDF(s)", type="pdf", accept_multiple_files=True)

# ---------------------- MAIN LOGIC ----------------------
if uploaded:
    for file in uploaded:
        st.markdown(f"<div class='section-header'>📘 Processing: {file.name}</div>", unsafe_allow_html=True)
        pdf_bytes = file.read()
        parts = split_pdf(pdf_bytes)

        if len(parts) == 1:
            text = parts[0]["text"]
            name = guess_name_from_text(text)
            order = extract_order_number(text)
            s_str, e_str = find_date_strings(text)
            s_dt, e_dt = parse_date(s_str), parse_date(e_str)
            filename = build_filename(order, name, s_dt, e_dt)

            st.success("✅ Renamed to:")
            st.code(filename)
            st.download_button("⬇️ Download Renamed PDF", pdf_bytes, file_name=filename, mime="application/pdf")

        else:
            st.info(f"Detected {len(parts)} sections (split by 'Start Date').")
            zip_buf = BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, p in enumerate(parts, 1):
                    text = p["text"]
                    name = guess_name_from_text(text)
                    order = extract_order_number(text)
                    s_str, e_str = find_date_strings(text)
                    s_dt, e_dt = parse_date(s_str), parse_date(e_str)
                    fname = build_filename(order, name, s_dt, e_dt)
                    zf.writestr(fname, export_pages(pdf_bytes, p["from"], p["to"]))
                    st.write(f"📄 Part {i}: pages {p['from']+1}-{p['to']+1} → **{fname}**")

            zip_buf.seek(0)
            st.download_button("📦 Download All as ZIP", zip_buf, file_name="renamed_parts.zip", mime="application/zip")
else:
    st.markdown("<div class='info-card'>👋 Start by uploading a PDF to begin renaming. Everything runs locally in your browser session.</div>", unsafe_allow_html=True)
