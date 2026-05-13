import os
import re
import pandas as pd
import pdfplumber
import streamlit as st

# Путь к вашей папке с декларациями
PDF_FOLDER_PATH = r"C:\Users\fomichevva4\Desktop\Проекты\2026-05-12 Робот ДОМ РФ\pdf"
RESULT_EXCEL = "summary_declarations_data.xlsx"

def extract_fields_from_pdf(file_path):
    """Открывает один PDF-файл и сканирует все его страницы без ограничений"""
    data = {
        "Имя файла": os.path.basename(file_path),
        "Застройщик": "Не найден",
        "ИНН застройщика": "Не найден",
        "Регион строительства": "Не найден",
        "Количество этажей": "Не найдено",
        "Жилая площадь (кв.м)": "Не найдена"
    }
    
    try:
        with pdfplumber.open(file_path) as pdf:
            # Цикл обходит абсолютно все страницы текущего документа
            for page in pdf.pages:
                text = page.extract_text()
                if not text:
                    continue
                
                lines = text.split("\n")
                for i, line in enumerate(lines):
                    print(line)
                    if i > 20
                    break