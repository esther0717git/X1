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
st.set_page_config(
    page_title="PDF Rename",
    page_icon="📄",
    layout="wide"
)

# --- Minimal CSS polish (keeps Streamlit theme) ---
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
      <p class="muted">Automatically rename PDF(s) using the <b>name, start date, and end date</b> found inside.  
      If a file contains multiple <i>Start Date</i> sections, we’ll split it and name each part for you.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------- Sidebar Controls ----------------------
with st.sidebar:
    st.header("Settings")
    st.caption("Tweak behavior without touching the code.")

    use_ocr = st.checkbox(
        "Enable OCR fallback (slower)",
        value=True if OCR_AVAILABLE else False,
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
            "{Name}_{YYYY.MM.DD}-{MM.DD}.pdf (Original)",
            "{YYYY.MM.DD}-{MM.DD}_{Name}.pdf",
            "{Name}_{YYYYMMDD}-{MMDD}.pdf"
        ],
        index=0
    )

    st.divider()
    with st.expander("Advanced (optional)"):
        name_hints = st.text_input(
            "Name field hints (comma-separated)",
            value="Name,Employee,Staff",
            help="We’ll prioritize lines containing these hints when extracting the person’s name."
        )
        start_regex = st.text_input(
            "Start Date regex",
            value=r"Start\s*Date\s*:\s*([0-9]{2}-[A-Za-z]{3}-[0-9]{4}|[0-9]{2}/[0-9]{2}/[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})",
        )
        end_regex = st.text_input(
            "End Date regex",
            value=r"End\s*Date\s*:\s*([0-9]{2}-[A-Za-z]{3}-[0-9]{4}|[0-9]{2}/[0-9]{2}/[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})",
        )
        split_anchor = st.text_input(
            "Split anchor regex",
            value=r"Start\s*Date",
            help="Each occurrence starts a new part."
        )

# ---------------------- Helpers ----------------------
def safe_slug(s: str) -> str:
    s = re.sub(r"[^\w\s\-\.]+", "", s, flags=re.UNICODE)  # keep word chars, spaces, dash, dot
    s = re.sub(r"\s+", "_", s.strip())
    return s or "Unknown"

def extract_text_pages(pdf_bytes: bytes, allow_ocr: bool) -> list[str]:
    """Extract text per page; optionally fall back to OCR."""
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
    return [""]  # at least one page so downstream doesn't break

def guess_name_from_text(text: str, hints: list[str]) -> str:
    """
    Try to extract a person name:
    1) Prefer lines that contain provided hints (e.g., 'Name', 'Employee')
    2) Then fallback to 2–4 capitalized words
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # prioritize hinted lines
    if hints:
        pat = re.compile("|".join([re.escape(h) for h in hints]), re.IGNORECASE)
        for ln in lines:
            if pat.search(ln):
                # try after colon first
                m = re.search(r":\s*([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})\b", ln)
                if m:
                    return m.group(1)

    # general fallback: 2–4 capitalized words (avoid month names etc by proximity to dates later if needed)
    m = re.search(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})\b", text)
    return m.group(1) if m else "Unknown Name"

def find_date_strings(text: str, start_pat: str, end_pat: str) -> tuple[str, str]:
    sm = re.search(start_pat, text, re.IGNORECASE)
    em = re.search(end_pat, text, re.IGNORECASE)
    start = sm.group(1) if sm else ""
    end = em.group(1) if em else ""
    return start, end

# Supported input formats → (strftime output for yyyy.mm.dd, mm.dd)
INPUT_FORMATS = [
    "%d-%b-%Y",   # 05-Oct-2025
    "%d/%m/%Y",   # 05/10/2025
    "%Y-%m-%d",   # 2025-10-05
]

def parse_date(date_str: str, style: str) -> datetime | None:
    date_str = date_str.strip()
    if not date_str:
        return None

    # forced style
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

def build_filenames(name: str, s_dt: datetime | None, e_dt: datetime | None, style: str) -> tuple[str, str]:
    """
    Returns (pdf_filename, zip_filename).
    zip_filename ignores name to group parts by date range.
    """
    name_slug = safe_slug(name)
    if s_dt and e_dt:
        if style.startswith("{Name}_{YYYY.MM.DD}-{MM.DD}"):
            pdf_name = f"{name_slug}_{s_dt.strftime('%Y.%m.%d')}-{e_dt.strftime('%m.%d')}.pdf"
            zip_name = f"{s_dt.strftime('%Y.%m.%d')}-{e_dt.strftime('%m.%d')}.zip"
        elif style.startswith("{YYYY.MM.DD}-{MM.DD}_{Name}"):
            pdf_name = f"{s_dt.strftime('%Y.%m.%d')}-{e_dt.strftime('%m.%d')}_{name_slug}.pdf"
            zip_name = f"{s_dt.strftime('%Y.%m.%d')}-{e_dt.strftime('%m.%d')}.zip"
        else:  # {Name}_{YYYYMMDD}-{MMDD}.pdf
            pdf_name = f"{name_slug}_{s_dt.strftime('%Y%m%d')}-{e_dt.strftime('%m%d')}.pdf"
            zip_name = f"{s_dt.strftime('%Y%m%d')}-{e_dt.strftime('%m%d')}.zip"
    else:
        pdf_name = f"{name_slug}_UnknownDate.pdf"
        zip_name = "UnknownDate.zip"
    return pdf_name, zip_name

def split_pdf(pdf_bytes: bytes, anchor_regex: str, allow_ocr: bool) -> list[dict]:
    """Split PDF into parts based on the anchor regex (default: 'Start Date')."""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        texts = extract_text_pages(pdf_bytes, allow_ocr=allow_ocr)
        boundaries = [i for i, t in enumerate(texts) if re.search(anchor_regex, t, re.IGNORECASE)]
        if not boundaries:
            # single chunk
            return [{"from": 0, "to": len(doc) - 1, "text": "\n".join(texts)}]

        boundaries.append(len(doc))
        parts = []
        for i in range(len(boundaries) - 1):
            start = boundaries[i]
            end = boundaries[i + 1] - 1
            part_text = "\n".join(texts[start:end + 1])
            parts.append({"from": start, "to": end, "text": part_text})
        return parts

def export_pages(pdf_bytes: bytes, from_page: int, to_page: int) -> bytes:
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

# ---------------------- Uploader ----------------------
st.subheader("Upload")
st.caption("Files you upload stay local to your session.")
uploaded_files = st.file_uploader(
    "Drag & drop PDF(s) here or browse",
    type="pdf",
    accept_multiple_files=True
)

# ---------------------- App Logic ----------------------
if uploaded_files:
    total_files = len(uploaded_files)
    st.markdown(f"**{total_files}** file{'s' if total_files>1 else ''} queued.")
    st.write("")

    for uploaded in uploaded_files:
        st.markdown(f"### {uploaded.name}")
        card = st.container()
        with card:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.write("Processing…")

            uploaded.seek(0)
            pdf_bytes = uploaded.read()

            parts = split_pdf(pdf_bytes, anchor_regex=split_anchor, allow_ocr=use_ocr)

            # Single part → rename
            if len(parts) == 1:
                text = parts[0]["text"]

                # Extract fields
                hints = [h.strip() for h in name_hints.split(",") if h.strip()]
                name = guess_name_from_text(text, hints=hints)
                start_s, end_s = find_date_strings(text, start_regex, end_regex)

                s_dt = parse_date(start_s, date_input_style)
                e_dt = parse_date(end_s, date_input_style)
                filename, _zipname = build_filenames(name, s_dt, e_dt, filename_style)

                # KPIs
                kpi = st.columns(4)
                with kpi[0]: st.metric("Pages", "Single")
                with kpi[1]: st.metric("Name", name if name != "Unknown Name" else "—")
                with kpi[2]: st.metric("Start Date", start_s or "—")
                with kpi[3]: st.metric("End Date", end_s or "—")

                st.success(f"Renamed to:  \n<span class='filename'>{filename}</span>", icon="✅", unsafe_allow_html=True)
                st.download_button(
                    label="🔽 Download Renamed PDF",
                    data=pdf_bytes,
                    file_name=filename,
                    mime="application/pdf",
                    use_container_width=True
                )

            # Multiple parts → ZIP
            else:
                st.info(f"Detected **{len(parts)}** parts (by '{split_anchor}').", icon="🪄")
                zip_buffer = BytesIO()
                manifest = []

                with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
                    for idx, part in enumerate(parts, 1):
                        text = part["text"]

                        hints = [h.strip() for h in name_hints.split(",") if h.strip()]
                        name = guess_name_from_text(text, hints=hints)
                        start_s, end_s = find_date_strings(text, start_regex, end_regex)

                        s_dt = parse_date(start_s, date_input_style)
                        e_dt = parse_date(end_s, date_input_style)
                        filename, zipname = build_filenames(name, s_dt, e_dt, filename_style)

                        part_bytes = export_pages(pdf_bytes, part["from"], part["to"])
                        zipf.writestr(filename, part_bytes)

                        st.markdown(
                            f"- Part **{idx}**: pages **{part['from']+1}–{part['to']+1}** → "
                            f"<span class='filename'>{filename}</span>",
                            unsafe_allow_html=True
                        )
                        manifest.append({
                            "idx": idx,
                            "pages": f"{part['from']+1}-{part['to']+1}",
                            "name": name,
                            "start": start_s or "",
                            "end": end_s or "",
                            "filename": filename
                        })

                zip_buffer.seek(0)
                st.download_button(
                    label="📦 Download All as ZIP",
                    data=zip_buffer,
                    file_name="renamed_parts.zip",
                    mime="application/zip",
                    use_container_width=True
                )

            st.markdown('</div>', unsafe_allow_html=True)

else:
    st.info(
        "Upload one or more PDFs to begin. We’ll extract text, find **Name**, **Start Date**, and **End Date**, "
        "then rename the file(s). If a PDF includes multiple **Start Date** sections, each section becomes a separate file.",
        icon="💡"
    )
    st.caption("Tip: Toggle OCR fallback in the sidebar if your PDFs are scans.")
