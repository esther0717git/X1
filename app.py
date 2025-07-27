import streamlit as st
import fitz  # PyMuPDF
import re
from io import BytesIO
from datetime import datetime
from pdf2image import convert_from_bytes
import pytesseract
from PIL import Image
import zipfile

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


# Function to extract text from PDF or fallback to OCR
def extract_text_from_pdf(pdf_file):
    try:
        with fitz.open(stream=pdf_file.read(), filetype="pdf") as doc:
            text = "\n".join([page.get_text() for page in doc])
        return text
    except Exception:
        pdf_file.seek(0)
        images = convert_from_bytes(pdf_file.read())
        text = "\n".join([pytesseract.image_to_string(img) for img in images])
        return text

# Function to extract name and dates and create filename + zipname
def extract_info_from_text(text):
    # Extract Name (First Last)
    name_match = re.search(r"([A-Z][a-z]+ [A-Z][a-z]+)", text)
    name = name_match.group(1).replace(" ", "_") if name_match else "Unknown_Name"

    # Extract Start Date
    start_match = re.search(r"Start Date\s*:\s*(\d{2}-\w{3}-\d{4})", text)
    start_date = start_match.group(1) if start_match else "UnknownStart"

    # Extract End Date
    end_match = re.search(r"End Date\s*:\s*(\d{2}-\w{3}-\d{4})", text)
    end_date = end_match.group(1) if end_match else "UnknownEnd"

    # Format output
    try:
        start_dt = datetime.strptime(start_date, "%d-%b-%Y")
        end_dt = datetime.strptime(end_date, "%d-%b-%Y")
        file_label = f"{name}_{start_dt.strftime('%Y.%m.%d')}-{end_dt.strftime('%m.%d')}.pdf"
        zip_label = f"{start_dt.strftime('%Y.%m.%d')}-{end_dt.strftime('%m.%d')}.zip"
    except:
        file_label = f"{name}_UnknownDate.pdf"
        zip_label = "UnknownDate.zip"

    return file_label, zip_label

# File upload
uploaded_files = st.file_uploader("Upload PDF(s)", type="pdf", accept_multiple_files=True)

renamed_files = []
zip_filename = "renamed_pdfs.zip"

if uploaded_files:
    for uploaded_file in uploaded_files:
        st.write(f"Processing: {uploaded_file.name}")
        try:
            text = extract_text_from_pdf(uploaded_file)
            new_name, zip_filename = extract_info_from_text(text)
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
