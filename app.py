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
st.set_page_config(page_title="PDF Rename Tool", page_icon="📄", layout="wide")

# --- Custom CSS ---
st.markdown(
    """
    <style>
      .main-title {
          text-align:center;
          font-size:2.2rem !important;
          font-weight:700;
          margin-bottom:0.5rem;
      }
      .subtitle {
          text-align:center;
          color: #6c757d;
          margin-bottom:1.5rem;
      }
      .section-header {
          font-size:1.3rem;
          font-weight:600;
          margin-top:1.8rem;
          margin-bottom:0.3rem;
          color:#2e7dba;
      }
      .info-card {
          border:1px solid rgba(0,0,0,0.08);
          background-color:#f8f9fa;
          border-radius:12px;
          padding:1rem 1.5rem;
          margin-bottom:1.2rem;
      }
      .filename {
          font-family:ui-monospace, monospace;
          background:rgba(0,0,0,0.04);
          padding:0.1rem 0.4rem;
          border-radius:4px;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------- Header ----------------------
st.markdown("<div class='main-title'>📄 PDF Rename Tool</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='subtitle'>Automatically extract <b>Order No</b>, <b>Name</b>, <b>Start Date</b>, and <b>End Date</b> — then rename or split PDFs intelligently.</div>",
    unsafe_allow_html=True,
)

# ---------------------- Sidebar ----------------------
with st.sidebar:
    st.header("⚙️ Settings")
    use_ocr = st.checkbox("Enable OCR fallback (slower)", value=False)
    if use_ocr and not OCR_AVAILABLE:
        st.warning("OCR dependencies not installed. Install `pdf2image` + `pytesseract` to enable.", icon="⚠️")

    date_input_style = st.selectbox(
        "Expected date format",
        ["DD-MMM-YYYY  (e.g., 05-Oct-2025)", "DD/MM/YYYY  (e.g., 05/10/2025)", "YYYY-MM-DD  (e.g., 2025-10-05)", "Auto (try all)"],
        index=0,
    )

    filename_style = st.selectbox(
        "Filename style",
        [
            "{Order}_{Name}_{YYYY.MM.DD}-{MM.DD}.pdf",
            "{Order}_{YYYY.MM.DD}-{MM.DD}_{Name}.pdf",
            "{Name}_{YYYY.MM.DD}-{MM.DD}.pdf (no order)",
            "{Name}_{YYYYMMDD}-{MMDD}.pdf (compact, no order)",
        ],
        index=0,
    )


# ---------------------- Regex Patterns ----------------------
START_REGEX = r"Start\s*Date\s*:\s*([0-9]{2}-[A-Za-z]{3}-[0-9]{4}|[0-9]{2}/[0-9]{2}/[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})"
END_REGEX = r"End\s*Date\s*:\s*([0-9]{2}-[A-Za-z]{3}-[0-9]{4}|[0-9]{2}/[0-9]{2}/[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})"
SPLIT_ANCHOR = r"Start\s*Date"
ORDER_PATTERNS = [
    r"Order\s*(?:No\.?|Number|#|ID)\s*[:\-]?\s*([A-Z0-9\-]{5,})",
    r"\bPO\s*[:\-]?\s*([A-Z0-9\-]{5,})",
    r"\bSO\s*[:\-]?\s*([A-Z0-9\-]{5,})",
]

# ---------------------- Helpers ----------------------
def safe_slug(s: str | None) -> str:
    s = s or ""
    s = re.sub(r"[^\w\s\-\.]+", "", s)
    s = re.sub(r"\s+", "_", s.strip())
    return s or "Unknown"

def extract_text_pages(pdf_bytes: bytes, allow_ocr: bool) -> list[str]:
    try:
        texts = []
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page in doc:
                texts.append(page.get_text() or "")
        if any(t.strip() for t in texts):
            return texts
    except Exception:
        pass

    if allow_ocr and OCR_AVAILABLE:
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
            if not re.match(r"\d{4}-\d{2}-\d{2}", val):
                return val
    return None

def guess_name_from_text(text: str) -> str:
    m = re.search(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})\b", text)
    return m.group(1) if m else "Unknown Name"

def find_date_strings(text: str):
    sm = re.search(START_REGEX, text, re.IGNORECASE)
    em = re.search(END_REGEX, text, re.IGNORECASE)
    return (sm.group(1) if sm else ""), (em.group(1) if em else "")

def parse_date(s: str, style: str):
    s = s.strip()
    if not s:
        return None
    fmts = {
        "DD-MMM-YYYY": ["%d-%b-%Y"],
        "DD/MM/YYYY": ["%d/%m/%Y"],
        "YYYY-MM-DD": ["%Y-%m-%d"],
        "Auto": ["%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"],
    }
    for fmt in fmts.get("Auto" if "Auto" in style else style.split()[0], []):
        try:
            return datetime.strptime(s, fmt)
        except:
            pass
    return None

def build_filename(name, s_dt, e_dt, style, order):
    name_slug = safe_slug(name)
    order_slug = safe_slug(order) if order else None
    if s_dt and e_dt:
        ymd_dot, md_dot = s_dt.strftime("%Y.%m.%d"), e_dt.strftime("%m.%d")
        ymd_comp, md_comp = s_dt.strftime("%Y%m%d"), e_dt.strftime("%m%d")
        if style.startswith("{Order}_{Name}_{YYYY.MM.DD}-{MM.DD}"):
            base = f"{name_slug}_{ymd_dot}-{md_dot}.pdf"
            fname = f"{order_slug}_{base}" if order_slug else base
        elif style.startswith("{Order}_{YYYY.MM.DD}-{MM.DD}_{Name}"):
            base = f"{ymd_dot}-{md_dot}_{name_slug}.pdf"
            fname = f"{order_slug}_{base}" if order_slug else base
        elif style.startswith("{Name}_{YYYY.MM.DD}-{MM.DD}"):
            fname = f"{name_slug}_{ymd_dot}-{md_dot}.pdf"
        else:
            fname = f"{name_slug}_{ymd_comp}-{md_comp}.pdf"
    else:
        prefix = f"{order_slug}_" if order_slug else ""
        fname = f"{prefix}{name_slug}_UnknownDate.pdf"
    return fname

def split_pdf(pdf_bytes):
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        texts = extract_text_pages(pdf_bytes, allow_ocr=use_ocr)
        marks = [i for i, t in enumerate(texts) if re.search(SPLIT_ANCHOR, t, re.IGNORECASE)]
        if not marks:
            return [{"from": 0, "to": len(doc)-1, "text": "\n".join(texts)}]
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


# ---------------------- Upload Section ----------------------
st.markdown("<div class='section-header'>📂 Upload Your PDF Files</div>", unsafe_allow_html=True)
st.markdown("<div class='info-card'>You can upload single or merged PDFs. The tool will extract information and rename automatically.</div>", unsafe_allow_html=True)

uploaded = st.file_uploader("Upload PDF(s)", type="pdf", accept_multiple_files=True)

# ---------------------- Main Logic ----------------------
if uploaded:
    for file in uploaded:
        st.markdown(f"<div class='section-header'>📘 Processing: {file.name}</div>", unsafe_allow_html=True)
        with st.container():
            pdf_bytes = file.read()
            parts = split_pdf(pdf_bytes)

            if len(parts) == 1:
                text = parts[0]["text"]
                name = guess_name_from_text(text)
                order = extract_order_number(text)
                s_str, e_str = find_date_strings(text)
                s_dt, e_dt = parse_date(s_str, date_input_style), parse_date(e_str, date_input_style)
                filename = build_filename(name, s_dt, e_dt, filename_style, order)

                st.success(f"✅ Renamed to: <span class='filename'>{filename}</span>", unsafe_allow_html=True)
                st.download_button("⬇️ Download Renamed PDF", pdf_bytes, file_name=filename, mime="application/pdf")
            else:
                st.info(f"Detected {len(parts)} sections by 'Start Date'. Splitting...")
                zip_buf = BytesIO()
                with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for i, p in enumerate(parts, 1):
                        text = p["text"]
                        name = guess_name_from_text(text)
                        order = extract_order_number(text)
                        s_str, e_str = find_date_strings(text)
                        s_dt, e_dt = parse_date(s_str, date_input_style), parse_date(e_str, date_input_style)
                        fname = build_filename(name, s_dt, e_dt, filename_style, order)
                        zf.writestr(fname, export_pages(pdf_bytes, p["from"], p["to"]))
                        st.write(f"📄 Part {i}: {p['from']+1}-{p['to']+1} → **{fname}**")

                zip_buf.seek(0)
                st.download_button("📦 Download All as ZIP", zip_buf, file_name="renamed_parts.zip", mime="application/zip")
else:
    st.markdown("<div class='info-card'>👋 Start by uploading a PDF to begin the renaming process. This tool works entirely locally within your session.</div>", unsafe_allow_html=True)
