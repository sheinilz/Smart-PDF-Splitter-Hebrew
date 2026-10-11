from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import fitz  # PyMuPDF
from PyPDF2 import PdfReader, PdfWriter
import pandas as pd
import io
import zipfile
import re
import pytesseract
from PIL import Image
import sys
import os
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# הרשאה לאתר ה-HTML שלנו לתקשר עם השרת
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# הגדרת נתיב Tesseract לווינדוס
if sys.platform.startswith('win'):
    path1 = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    path2 = r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe'
    if os.path.exists(path1):
        pytesseract.pytesseract.tesseract_cmd = path1
    elif os.path.exists(path2):
        pytesseract.pytesseract.tesseract_cmd = path2

# נתיב חדש לחילוץ שמות העמודות מקובץ האקסל
@app.post("/get-columns/")
async def get_excel_columns(excel_file: UploadFile = File(...)):
    excel_bytes = await excel_file.read()
    df = pd.read_csv(io.BytesIO(excel_bytes)) if excel_file.filename.endswith('.csv') else pd.read_excel(io.BytesIO(excel_bytes))
    return {"columns": df.columns.tolist()}


# ----------------- שלב 1: ניתוח ה-PDF וזיהוי שמות -----------------
@app.post("/analyze/")
async def analyze_pdf(
    file: UploadFile = File(...),
    method: str = Form(...),
    anchor: str = Form("לכבוד"),
    pages_per_split: int = Form(1),
    excel_file: UploadFile = File(None),
    column_name: str = Form(None)
):
    pdf_bytes = await file.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)
    extracted_data = []

    if method == "excel" and excel_file and column_name:
        excel_bytes = await excel_file.read()
        df_names = pd.read_csv(io.BytesIO(excel_bytes)) if excel_file.filename.endswith('.csv') else pd.read_excel(io.BytesIO(excel_bytes))
        
        # שימוש בעמודה שהמשתמש בחר
        if column_name in df_names.columns:
            names_list = df_names[column_name].dropna().astype(str).tolist()
        else:
            names_list = df_names.iloc[:, 0].dropna().astype(str).tolist() # גיבוי לעמודה הראשונה
        
        name_index = 0
        for start_page in range(1, total_pages + 1, pages_per_split):
            end_page = min(start_page + pages_per_split - 1, total_pages)
            file_name = names_list[name_index].strip() if name_index < len(names_list) else f"קובץ_{name_index+1}"
            extracted_data.append({"start": start_page, "end": end_page, "name": file_name})
            name_index += 1

    elif method == "ocr":
        safe_anchor = re.escape(anchor.strip()).replace(r'\ ', r'\s*')
        blacklist = ["תיק ניכויים", "מספר זהות", "תעודת זהות", "תלוש שכר", "שם משפחה", "קוד אישי"]
        current_id = None
        start_page = 1
        
        for i in range(total_pages):
            page = doc[i]
            pix = page.get_pixmap(dpi=150)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            extracted_text = pytesseract.image_to_string(img, lang='heb')
            clean_text = " ".join(extracted_text.split())
            
            page_id = f"לא_מזוהה_עמוד_{i+1}"
            pattern = rf'{safe_anchor}\s*[:\-]?\s*([א-ת]+\s+[א-ת]+)'
            matches = re.finditer(pattern, clean_text)
            
            for match in matches:
                potential_name = match.group(1).strip()
                if not any(bad_word in potential_name for bad_word in blacklist):
                    page_id = potential_name
                    break
            
            if page_id == f"לא_מזוהה_עמוד_{i+1}":
                id_match = re.search(r'(?<!\d)(\d{8,9})(?!\d)', clean_text)
                if id_match:
                    page_id = f"עובד_{id_match.group(1)}"
            
            if current_id is None:
                current_id = page_id
                start_page = i + 1
            elif page_id != current_id and "לא_מזוהה" not in page_id:
                extracted_data.append({"start": start_page, "end": i, "name": current_id})
                current_id = page_id
                start_page = i + 1
        
        if current_id is not None or start_page <= total_pages:
            extracted_data.append({"start": start_page, "end": total_pages, "name": current_id})

    return {"total_pages": total_pages, "data": extracted_data}


# ----------------- שלב 2: גזירת ה-PDF ויצירת ה-ZIP -----------------
@app.post("/generate/")
async def generate_zip(
    file: UploadFile = File(...),
    mapping: str = Form(...) # מקבל את הטבלה הערוכה בפורמט JSON
):
    pdf_bytes = await file.read()
    reader = PdfReader(io.BytesIO(pdf_bytes))
    total_pages = len(reader.pages)
    
    data = json.loads(mapping)
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for index, row in enumerate(data):
            try:
                start_page = int(row["start"]) - 1
                end_page = int(row["end"]) - 1
            except:
                continue
            
            if start_page > end_page or start_page < 0 or end_page >= total_pages:
                continue 
            
            safe_name = re.sub(r'[\\/*?:"<>|]', "", str(row['name']))
            if not safe_name.strip():
                safe_name = f"קובץ_{index+1}"
            file_name = f"{safe_name}.pdf"
            
            writer = PdfWriter()
            for p in range(start_page, end_page + 1):
                writer.add_page(reader.pages[p])
            
            pdf_buffer = io.BytesIO()
            writer.write(pdf_buffer)
            zip_file.writestr(file_name, pdf_buffer.getvalue())

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer, 
        media_type="application/zip", 
        headers={"Content-Disposition": "attachment; filename=split_documents.zip"}
    )