import streamlit as st
import fitz  # PyMuPDF
import re
from io import BytesIO
from datetime import datetime
import zipfile

# Optional deps (guarded): pdf2image + pytesseract used for OCR fallback
try:
    from pdf2image import convert_from_bytes
    import pytesseract
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

# ---------------------- Page Setup ----------------------
st.set_page_config(page_title="PDF Rename", page_icon="📄", layout="wide")

st.markdown(
    """
    <style>
      .hero {padding: 1.25rem 1.25rem 0.5rem; border-radius: 16px;}
      .muted {color: var(--text-color-secondary);}
      .card {
        border: 1px solid rgba(49,51,63,0.2);
        padding: 1rem 1rem 0.75rem;
        border-radius: 12px;
        margin-bottom: 0.75rem;
        background: rgba(49,51,63,0.03);
      }
      .kpi {display:flex; gap:1rem; flex-wrap: wrap; margin:.5rem 0 0.75rem;}
      .kpi > div {padding:.5rem .75rem; background: rgba(49,51,63,0.06); border-radius: 10px; font-size: 0.9rem;}
      .filename {font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------- Header ----------------------
st.markdown(
    """
    <div class="hero">
      <h1 style="margin-bottom:0.25rem;">📄 PDF Rename</h1>
      <p class="muted">Automatically rename PDF(s) using the <b>name, order number, start date, and end date</b> found inside.  
      If a file contains multiple <i>Start Date</i> sections, we’ll split it and name each part for you.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------- Sidebar (simplified) ----------------------
with st.sidebar:
    st.header("Settings")
    st.caption("Tweak behavior without touching the code.")
    use_ocr = st.checkbox(
        "Enable OCR fallback (slower)",
        value=False,
        help="If text extraction fails, convert pages to images and run OCR."
    )
    if use_ocr and not OCR_AVAILABLE:
        st.warning("OCR dependencies not detected. Install `pdf2image` and `pytesseract` to enable.", icon="⚠️")

    date_input_style = st.selectbox(
        "Expected date format (for parsing)",
        [
            "DD-MMM-YYYY  (e.g., 05-Oct-2025)",
            "DD/MM/YYYY    (e.g., 05/10/2025)",
            "YYYY-MM-DD    (e.g., 2025-10-05)",
            "Auto (try common patterns)"
        ],
        index=0
    )

    filename_style = st.selectbox(
        "Filename style",
        [
            "{Order}_{Name}_{YYYY.MM.DD}-{MM.DD}.pdf",
            "{Order}_{YYYY.MM.DD}-{MM.DD}_{Name}.pdf",
            "{Name}_{YYYY.MM.DD}-{MM.DD}.pdf  (no order)",
            "{Name}_{YYYYMMDD}-{MMDD}.pdf  (compact, no order)"
        ],
        index=0
    )

# ---------------------- Helpers ----------------------
START_REGEX = r"Start\s*Date\s*:\s*([0-9]{2}-[A-Za-z]{3}-[0-9]{4}|[0-9]{2}/[0-9]{2}/[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})"
END_REGEX   = r"End\s*Date\s*:\s*([0-9]{2}-[A-Za-z]{3}-[0-9]{4}|[0-9]{2}/[0-9]{2}/[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})"
SPLIT_ANCHOR = r"Start\s*Date"

ORDER_PATTERNS = [
    r"Order\s*(?:No\.?|Number|#|ID)\s*[:\-]?\s*([A-Z0-9\-]{5,})",
    r"\bPO\s*[:\-]?\s*([A-Z0-9\-]{5,})",
    r"\bSO\s*[:\-]?\s*([A-Z0-9\-]{5,})",
]

def safe_slug(s: str) -> str:
    s = re.sub(r"[^\w\s\-\.]+", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "_", s.strip())
    return s or "Unknown"

def extract_text_pages(pdf_bytes: bytes, allow_ocr: bool) -> list[str]:
    try:
        page_texts = []
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page in doc:
                page_texts.append(page.get_text() or "")
        if any(t.strip() for t in page_texts):
            return page_texts
    except Exception:
        pass

    if allow_ocr and OCR_AVAILABLE:
        try:
            images = convert_from_bytes(pdf_bytes)
            return [pytesseract.image_to_string(img) for img in images]
        except Exception:
            pass

    return [""]

def guess_name_from_text(text: str) -> str:
    # Simple 2–4 capitalized words heuristic
    m = re.search(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})\b", text)
    return m.group(1) if m else "Unknown Name"

def extract_order_number(text: str) -> str | None:
    for pat in ORDER_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            # sanitize to keep typical PO formats (alnum + dash)
            order = re.sub(r"[^A-Za-z0-9\-]", "", m.group(1))
            # avoid accidentally capturing dates like 2024-10-05
            if not re.match(r"\d{4}-\d{2}-\d{2}", order):
                return order
    return None

INPUT_FORMATS = ["%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"]

def parse_date(date_str: str, style: str) -> datetime | None:
    date_str = (date_str or "").strip()
    if not date_str:
        return None
    if "DD-MMM-YYYY" in style:
        fmts = ["%d-%b-%Y"]
    elif "DD/MM/YYYY" in style:
        fmts = ["%d/%m/%Y"]
    elif "YYYY-MM-DD" in style:
        fmts = ["%Y-%m-%d"]
    else:
        fmts = INPUT_FORMATS
    for fmt in fmts:
        try:
            return datetime.strptime(date_str, fmt)
        except Exception:
            continue
    return None

def build_filenames(name: str, s_dt: datetime | None, e_dt: datetime | None, style: str,_
