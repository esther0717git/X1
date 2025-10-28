import streamlit as st
import fitz  # PyMuPDF
import re
from io import BytesIO
from datetime import datetime
import zipfile
from collections import Counter

# Optional OCR dependencies (fallback only if needed)
try:
    from pdf2image import convert_from_bytes
    import pytesseract
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False


# ---------------------- PAGE SETUP ----------------------
st.set_page_config(page_title="Auto Name AI", page_icon="📄", layout="wide")

# --- Minimal CSS polish ---
st.markdown(
    """
    <style>
      .main-title {text-align:center; font-size:2.2rem; font-weight:700; margin-bottom:0.3rem;}
      .subtitle {text-align:center; color:#6c757d; margin-bottom:1.2rem;}
      .section-header {font-size:1.25rem; font-weight:600; margin-top:1.2rem; margin-bottom:0.5rem; color:#2e7dba;}
      .info-card {
          border:1px solid rgba(0,0,0,0.08);
          background-color:#f8f9fa;
          border-radius:12px;
          padding:1rem 1.5rem;
          margin-bottom:1.0rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------- HEADER ----------------------
st.markdown("<div class='main-title'>📄 Auto Name AI</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='subtitle'>Rename using detected <b>Start Date</b>, <b>End Date</b>, <b>Name</b>, and <b>Order No</b>.</div>",
    unsafe_allow_html=True,
)

# ---------------------- CONSTANTS & REGEX ----------------------
START_REGEX = r"Start\s*Date\s*:\s*([0-9]{2}-[A-Za-z]{3}-[0-9]{4}|[0-9]{2}/[0-9]{2}/[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})(?:\s+\d{2}:\d{2}:\d{2}\s*(?:AM|PM)?)?"
END_REGEX   = r"End\s*Date\s*:\s*([0-9]{2}-[A-Za-z]{3}-[0-9]{4}|[0-9]{2}/[0-9]{2}/[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})(?:\s+\d{2}:\d{2}:\d{2}\s*(?:AM|PM)?)?"
SPLIT_ANCHOR = r"Start\s*Date"
ORDER_PATTERNS = [
    r"Order\s*(?:No\.?|Number|#|ID)\s*[:\-]?\s*([A-Z0-9\-]{5,})",
    r"\bPO\s*[:\-]?\s*([A-Z0-9\-]{5,})",
    r"\bSO\s*[:\-]?\s*([A-Z0-9\-]{5,})",
]
DATE_FORMATS = ["%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"]
CODE_STRICT = re.compile(r"^[A-Z]{2}\d{1,3}$")  # e.g., DA11, SG5


# ---------------------- HELPERS ----------------------
def safe_slug(s: str | None) -> str:
    s = s or ""
    s = re.sub(r"[^\w\s\-\.]+", "", s)
    s = re.sub(r"\s+", "_", s.strip())
    return s or "Unknown"


def extract_text_pages(pdf_bytes: bytes) -> list[str]:
    """Extract text per page; fallback to OCR if needed."""
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
            if not re.match(r"\d{4}-\d{2}-\d{2}", val):  # avoid capturing dates
                return val
    return None


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
            continue
    return None


def guess_name_from_text(text: str) -> str:
    m = re.search(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})\b", text)
    return m.group(1) if m else "Unknown_Name"


def extract_candidate_codes_before_order(text: str) -> list[str]:
    """Return all code-like tokens (AA9..AA999) that appear BEFORE the 'Order' line."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    candidates = []
    for ln in lines:
        if re.match(r"^Order\b", ln, re.IGNORECASE):
            break
        for tok in re.findall(r"[A-Z0-9\-]+", ln.upper()):
            if CODE_STRICT.match(tok):
                candidates.append(tok)
    return candidates


def extract_site_code(text: str) -> str | None:
    """Pick the most plausible code before 'Order' (closest to it). Fallback to any strict match."""
    cands = extract_candidate_codes_before_order(text)
    if cands:
        return cands[-1]
    for tok in re.findall(r"[A-Z0-9\-]+", text.upper()):
        if CODE_STRICT.match(tok):
            return tok
    return None


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


# ---------- filename builders ----------
def fname_dates_code_name_order(s_dt, e_dt, code, name, order) -> str:
    """Split mode: StartDate-EndDate_Code_Name_OrderNo.pdf (omit missing parts)."""
    parts = []
    if s_dt and e_dt:
        parts.append(f"{s_dt.strftime('%Y.%m.%d')}-{e_dt.strftime('%m.%d')}")
    else:
        parts.append("UnknownDate")
    if code:
        parts.append(safe_slug(code))
    if name:
        parts.append(safe_slug(name))
    if order:
        parts.append(safe_slug(order))
    return "_".join(parts) + ".pdf"


def fname_dates_code_order(s_dt, e_dt, code, order) -> str:
    """No-split mode: StartDate-EndDate_Code_OrderNo.pdf."""
    parts = []
    if s_dt and e_dt:
        parts.append(f"{s_dt.strftime('%Y.%m.%d')}-{e_dt.strftime('%m.%d')}")
    else:
        parts.append("UnknownDate")
    if code:
        parts.append(safe_slug(code))
    if order:
        parts.append(safe_slug(order))
    return "_".join(parts) + ".pdf"


# ---------- split logic ----------
def split_pdf(pdf_bytes):
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        texts = extract_text_pages(pdf_bytes)
        marks = [i for i, t in enumerate(texts) if re.search(SPLIT_ANCHOR, t, re.IGNORECASE)]
        if not marks:
            return [{"from": 0, "to": len(doc) - 1, "text": "\n".join(texts)}]
        marks.append(len(doc))
        return [{"from": marks[i], "to": marks[i+1]-1, "text": "\n".join(texts[marks[i]:marks[i+1]])} for i in range(len(marks)-1)]


# ---------- no-split extract ----------
def extract_overall_fields(pdf_bytes):
    texts = extract_text_pages(pdf_bytes)
    all_text = "\n".join(texts)
    s_str, e_str = find_date_strings(all_text)
    order = extract_order_number(all_text)
    code = extract_site_code(all_text)
    s_dt, e_dt = parse_date(s_str), parse_date(e_str)
    return s_dt, e_dt, order, code


# ---------------------- MODE PICKER ----------------------
st.markdown("<div class='section-header'>🔧 Mode</div>", unsafe_allow_html=True)
mode = st.radio(
    "Choose how you want to process files:",
    ["Individual PDF", "Merged PDFs"],
    index=0,
    help=(
        "Select *Individual PDF*split pdf and renamed individually. "
        "Choose *Merged PDFs* Rename merged pdf"
    ),
)

# ---------------------- UPLOAD SECTION ----------------------
st.markdown("<div class='section-header'>📂 Upload Your PDF Files</div>", unsafe_allow_html=True)
if mode == "Individual PDF":
    st.markdown(
        "<div class='info-card'>Upload merged PDF"
        "Output: <i>\"StartDate-EndDate_Code_Name_OrderNo\"</i>.</div>",
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        "<div class='info-card'><b>Merged PDF</b><br>"
        "Upload merged PDF | Output: <i>StartDate-EndDate_Code_OrderNo.pdf</i></div>",
        unsafe_allow_html=True,
    )

uploaded = st.file_uploader("Upload PDF(s)", type="pdf", accept_multiple_files=True)


# ---------------------- MAIN LOGIC ----------------------
if uploaded:
    for file in uploaded:
        st.markdown(f"<div class='section-header'>📘 Processing: {file.name}</div>", unsafe_allow_html=True)
        pdf_bytes = file.read()

        if mode == "Individual PDFs":
            parts = split_pdf(pdf_bytes)

            # Majority vote site code across parts (for consistency)
            all_codes = []
            for p in parts:
                code_p = extract_site_code(p["text"])
                if code_p:
                    all_codes.append(code_p)
            majority_code = Counter(all_codes).most_common(1)[0][0] if all_codes else None
            if majority_code and len(set(all_codes)) > 1:
                st.caption(f"Note: multiple site codes detected {sorted(set(all_codes))}. Using majority code: {majority_code}.")

            if len(parts) == 1:
                text = parts[0]["text"]
                s_str, e_str = find_date_strings(text)
                s_dt, e_dt = parse_date(s_str), parse_date(e_str)
                name = guess_name_from_text(text)
                order = extract_order_number(text)
                code = extract_site_code(text) or majority_code
                filename = fname_dates_code_name_order(s_dt, e_dt, code, name, order)

                st.success("✅ Renamed to:")
                st.code(filename)
                st.download_button("⬇️ Download Renamed PDF", pdf_bytes, file_name=filename, mime="application/pdf")

            else:
                st.info(f"Detected {len(parts)} sections (split by 'Start Date').")
                zip_buf = BytesIO()
                with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for i, p in enumerate(parts, 1):
                        text = p["text"]
                        s_str, e_str = find_date_strings(text)
                        s_dt, e_dt = parse_date(s_str), parse_date(e_str)
                        name = guess_name_from_text(text)
                        order = extract_order_number(text)
                        code = majority_code or extract_site_code(text)

                        fname = fname_dates_code_name_order(s_dt, e_dt, code, name, order)
                        zf.writestr(fname, export_pages(pdf_bytes, p["from"], p["to"]))
                        st.write(f"📄 Part {i}: pages {p['from']+1}-{p['to']+1} → **{fname}**")
                zip_buf.seek(0)
                st.download_button("📦 Download All as ZIP", zip_buf, file_name="renamed_parts.zip", mime="application/zip")

        else:  # Merged PDFs (no splitting, rename only)
            s_dt, e_dt, order, code = extract_overall_fields(pdf_bytes)
            filename = fname_dates_code_order(s_dt, e_dt, code, order)

            st.success("✅ Renamed to:")
            st.code(filename)
            st.download_button("⬇️ Download Renamed PDF", pdf_bytes, file_name=filename, mime="application/pdf")
else:
    st.markdown(
        "<div class='info-card'>👋 Start by uploading a PDF to begin renaming. "
        "Everything runs locally within your session.</div>",
        unsafe_allow_html=True,
    )
