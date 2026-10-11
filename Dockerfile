# בחירת סביבת פייתון קלה ומהירה
FROM python:3.10-slim

# התקנת תוכנת ה-OCR והשפה העברית ברמת השרת
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-heb \
    && rm -rf /var/lib/apt/lists/*

# הגדרת תיקיית העבודה
WORKDIR /app

# העתקת הקבצים שלך לשרת
COPY . /app

# התקנת כל ספריות הפייתון מקובץ ה-requirements
RUN pip install --no-cache-dir -r requirements.txt

# הפקודה שתפעיל את השרת ברגע שהוא עולה לאוויר
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]