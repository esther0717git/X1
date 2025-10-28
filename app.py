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
END_REGEX = r"End\s*Date\s*:\s*([0-9]{2}-[A-Za-z]{3}-[0-9]{4}|[0-9]{2}/[0-9]{2}/[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})"
SPLIT_ANCHOR = r"Start\s*Date"

ORDER_PATTERNS = [
    r"Order\s*(?:No\.?|Number|#|ID)\s*[:\-]?\s*([A-Z0-9\-]{5,})",
    r"\bPO\s*[:\-]?\s*([A-Z0-9\-]{5,})",
    r"\bSO\s*[:\-]?\s*([A-Z0-9\-]{5,})",
]

def safe_slug(s: str | None) -> str:
    s = s or ""
    s = re.sub(r"[^\w\s\-\.]+", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "_", s.strip())
    return s or "Unknown"

def extract_text_pages(pdf_bytes: bytes, allow_ocr: bool) -> list[str]:
    # Try native text extraction first
    try:
        page_texts = []
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page in doc:
                page_texts.append(page.get_text() or "")
        if any(t.strip() for t in page_texts):
            return page_texts
    except Exception:
        pass

    # OCR fallback
    if allow_ocr and OCR_AVAILABLE:
        try:
            images = convert_from_bytes(pdf_bytes)
            return [pytesseract.image_to_string(img) for img in images]
        except Exception:
            pass

    # Final fallback
    return [""]

def guess_name_from_text(text: str) -> str:
    # Simple 2–4 capitalized words heuristic
    m = re.search(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})\b", text)
    return m.group(1) if m else "Unknown Name"

def extract_order_number(text: str) -> str | None:
    for pat in ORDER_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            order = re.sub(r"[^A-Za-z0-9\-]", "", m.group(1))
            # Avoid capturing dates like 2024-10-05 as an order number
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

def build_filenames(name: str, s_dt: datetime | None, e_dt: datetime | None, style: str, order: str | None) -> tuple[str, str]:
    name_slug = safe_slug(name)
    order_slug = safe_slug(order) if order else None

    if s_dt and e_dt:
        ymd_dot = s_dt.strftime("%Y.%m.%d")
        md_dot = e_dt.strftime("%m.%d")
        ymd_comp = s_dt.strftime("%Y%m%d")
        md_comp = e_dt.strftime("%m%d")

        if style.startswith("{Order}_{Name}_{YYYY.MM.DD}-{MM.DD}"):
            base = f"{name_slug}_{ymd_dot}-{md_dot}.pdf"
            pdf_name = f"{order_slug}_{base}" if order_slug else base
            zip_name = f"{ymd_dot}-{md_dot}.zip"
        elif style.startswith("{Order}_{YYYY.MM.DD}-{MM.DD}_{Name}"):
            base = f"{ymd_dot}-{md_dot}_{name_slug}.pdf"
            pdf_name = f"{order_slug}_{base}" if order_slug else base
            zip_name = f"{ymd_dot}-{md_dot}.zip"
        elif style.startswith("{Name}_{YYYY.MM.DD}-{MM.DD}"):
            pdf_name = f"{name_slug}_{ymd_dot}-{md_dot}.pdf"
            zip_name = f"{ymd_dot}-{md_dot}.zip"
        else:
            pdf_name = f"{name_slug}_{ymd_comp}-{md_comp}.pdf"
            zip_name = f"{ymd_comp}-{md_comp}.zip"
    else:
        prefix = f"{order_slug}_" if order_slug else ""
        pdf_name = f"{prefix}{name_slug}_UnknownDate.pdf"
        zip_name = "UnknownDate.zip"

    return pdf_name, zip_name

def find_date_strings(text: str) -> tuple[str, str]:
    sm = re.search(START_REGEX, text, re.IGNORECASE)
    em = re.search(END_REGEX, text, re.IGNORECASE)
    return (sm.group(1) if sm else ""), (em.group(1) if em else "")

def split_pdf(pdf_bytes: bytes) -> list[dict]:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        texts = extract_text_pages(pdf_bytes, allow_ocr=use_ocr)
        boundaries = [i for i, t in enumerate(texts) if re.search(SPLIT_ANCHOR, t, re.IGNORECASE)]
        if not boundaries:
            return [{"from": 0, "to": len(doc) - 1, "text": "\n".join(texts)}]
        boundaries.append(len(doc))
        parts = []
        for i in range(len(boundaries) - 1):
            start = boundaries[i]
            end = boundaries[i + 1] - 1
            parts.append({"from": start, "to": end, "text": "\n".join(texts[start:end + 1])})
        return parts

def export_pages(pdf_bytes: bytes, from_page: int, to_page: int) -> bytes:
    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    new_pdf = fitz.open()
    new_pdf.insert_pdf(src, from_page=from_page, to_page=to_page)
    buf = BytesIO()
    new_pdf.save(buf)
    new_pdf.close()
    src.close()
    buf.seek(0)
    return buf.read()

# ---------------------- Uploader ----------------------
st.subheader("Upload")
st.caption("Files you upload stay local to your session.")
uploaded_files = st.file_uploader("Drag & drop PDF(s) here or browse", type="pdf", accept_multiple_files=True)

# ---------------------- App Logic ----------------------
if uploaded_files:
    total_files = len(uploaded_files)
    st.markdown(f"**{total_files}** file{'s' if total_files > 1 else ''} queued.")
    st.write("")

    for uploaded in uploaded_files:
        st.markdown(f"### {uploaded.name}")
        with st.container():
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.write("Processing...")

            uploaded.seek(0)
            pdf_bytes = uploaded.read()
            parts = split_pdf(pdf_bytes)

            # Single part → rename
            if len(parts) == 1:
                text = parts[0]["text"]

                name = guess_name_from_text(text)
                order = extract_order_number(text)
                start_s, end_s = find_date_strings(text)
                s_dt = parse_date(start_s, date_input_style)
                e_dt = parse_date(end_s, date_input_style)

                filename, _zipname = build_filenames(name, s_dt, e_dt, filename_style, order)

                # KPIs
                kpi = st.columns(5)
                with kpi[0]:
                    st.metric("Pages", "Single")
                with kpi[1]:
                    st.metric("Order", order or "—")
                with kpi[2]:
                    st.metric("Name", name if name != "Unknown Name" else "—")
                with kpi[3]:
                    st.metric("Start Date", start_s or "—")
                with kpi[4]:
                    st.metric("End Date", end_s or "—")

                st.success(f"Renamed to:\n<span class='filename'>{filename}</span>", icon="✅", unsafe_allow_html=True)
                st.download_button(
                    label="🔽 Download Renamed PDF",
                    data=pdf_bytes,
                    file_name=filename,
                    mime="application/pdf",
                    use_container_width=True
                )

            # Multiple parts → ZIP
            else:
                st.info("Detected multiple parts (by 'Start Date').", icon="🪄")
                zip_buffer = BytesIO()

                with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
                    for idx, part in enumerate(parts, 1):
                        text = part["text"]

                        name = guess_name_from_text(text)
                        order = extract_order_number(text)
                        start_s, end_s = find_date_strings(text)
                        s_dt = parse_date(start_s, date_input_style)
                        e_dt = parse_date(end_s, date_input_style)
                        filename, zipname = build_filenames(name, s_dt, e_dt, filename_style, order)

                        part_bytes = export_pages(pdf_bytes, part["from"], part["to"])
                        zipf.writestr(filename, part_bytes)

                        st.markdown(
                            f"- Part **{idx}**: pages **{part['from'] + 1}–{part['to'] + 1}** → "
                            f"<span class='filename'>{filename}</span>",
                            unsafe_allow_html=True
                        )

                zip_buffer.seek(0)
                st.download_button(
                    label="📦 Download All as ZIP",
                    data=zip_buffer,
                    file_name="renamed_parts.zip",
                    mime="application/zip",
                    use_container_width=True
                )

            st.markdown("</div>", unsafe_allow_html=True)

else:
    st.info(
        "Upload one or more PDFs to begin. We'll extract text, find **Order #**, **Name**, **Start Date**, and **End Date**, "
        "then rename the file(s). If a PDF includes multiple **Start Date** sections, each section becomes a separate file.",
        icon="💡"
    )
    st.caption("Tip: Toggle OCR fallback in the sidebar if your PDFs are scans.")
