import streamlit as st
import fitz  # PyMuPDF
import re
from io import BytesIO
from datetime import datetime
from pdf2image import convert_from_bytes
import pytesseract
from PIL import Image

st.set_page_config(page_title="PDF Renamer", page_icon="📄")
st.title("PDF Renamer for Order Slips")
st.write("Upload your PDF(s) below. The file will be renamed based on the name, start date, and end date in the PDF.")


def extract_text_from_pdf(pdf_file):
    try:
        with fitz.open(stream=pdf_file.read(), filetype="pdf") as doc:
            text = "\n".join([page.get_text() for page in doc])
        return text
    except Exception:
        # Fallback to OCR
        pdf_file.seek(0)
        images = convert_from_bytes(pdf_file.read())
        text = "\n".join([pytesseract.image_to_string(img) for img in images])
        return text


def extract_info_from_text(text):
    # Extract Name (first last)
    name_match = re.search(r"([A-Z][a-z]+\s[A-Z][a-z]+)", text)
    name = name_match.group(1).replace(" ", "_") if name_match else "Unknown_Name"

    # Extract Start Date
    start_match = re.search(r"Start Date\s*:\s*(\d{2}-\w{3}-\d{4})", text)
    start_date = start_match.group(1) if start_match else "UnknownStart"

    # Extract End Date
    end_match = re.search(r"End Date\s*:\s*(\d{2}-\w{3}-\d{4})", text)
    end_date = end_match.group(1) if end_match else "UnknownEnd"

    # Format date to YYYY-MM-DD
    try:
        start_date_fmt = datetime.strptime(start_date, "%d-%b-%Y").strftime("%Y-%m-%d")
    except:
        start_date_fmt = start_date

    try:
        end_date_fmt = datetime.strptime(end_date, "%d-%b-%Y").strftime("%Y-%m-%d")
    except:
        end_date_fmt = end_date

    new_filename = f"{name}_{start_date_fmt}_{end_date_fmt}.pdf"
    return new_filename


uploaded_files = st.file_uploader("Upload PDF(s)", type="pdf", accept_multiple_files=True)

if uploaded_files:
    for uploaded_file in uploaded_files:
        st.write(f"Processing: {uploaded_file.name}")
        try:
            text = extract_text_from_pdf(uploaded_file)
            new_name = extract_info_from_text(text)
            uploaded_file.seek(0)  # reset pointer for download
            st.success(f"Renamed to: {new_name}")
            st.download_button(
                label="🔀 Download Renamed PDF",
                data=uploaded_file.read(),
                file_name=new_name,
                mime="application/pdf"
            )
        except Exception as e:
            st.error(f"Failed to process {uploaded_file.name}: {e}")
