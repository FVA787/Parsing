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
                    
                    # 1. Поиск Застройщика
                    if "Фирменное наименование застройщика" in line or "Организационно-правовая forma" in line:
                        if i + 1 < len(lines):
                            data["Застройщик"] = lines[i+1].strip()
                    
                    # 2. Поиск ИНН
                    if "Идентификационный номер налогоплательщика" in line or "ИНН" in line:
                        inn_match = re.search(r'\b\d{10}\b', line)
                        if inn_match:
                            data["ИНН застройщика"] = inn_match.group(0)
                        elif i + 1 < len(lines):
                            inn_match_next = re.search(r'\b\d{10}\b', lines[i+1])
                            if inn_match_next:
                                data["ИНН застройщика"] = inn_match_next.group(0)
                    
                    # 3. Поиск региона
                    if "Местоположение объекта" in line or "Регион" in line:
                        if i + 1 < len(lines):
                            data["Регион строительства"] = lines[i+1].strip()

                    # 4. Поиск этажности
                    if "Количество этажей" in line:
                        floors = re.findall(r'\d+', line)
                        if floors:
                            data["Количество этажей"] = floors

                    # 5. Площадь
                    if "Общая площадь объекта" in line:
                        area_match = re.search(r'\d+[\.,]\d+|\d+', line)
                        if area_match:
                            data["Жилая площадь (кв.м)"] = area_match.group(0)

    except Exception as e:
        data["Застройщик"] = f"Ошибка чтения файла: {str(e)}"
        
    return data

# --- Настройка боковой панели (Sidebar) интерфейса Streamlit ---
st.set_page_config(page_title="Парсер деклараций", layout="wide")
st.title("📊 Локальный парсер проектных деклараций ДОМ.РФ")

st.sidebar.header("⚙️ Настройки объема")

# Проверяем файлы в папке
if os.path.exists(PDF_FOLDER_PATH):
    all_pdf_files = [f for f in os.listdir(PDF_FOLDER_PATH) if f.endswith('.pdf')]
    total_found = len(all_pdf_files)
else:
    all_pdf_files = []
    total_found = 0

# ИСПРАВЛЕНО: Безопасный расчет параметров, если файлы не найдены
if total_found == 0:
    st.sidebar.warning("⚠️ PDF-файлы не найдены по указанному пути!")
    max_files = st.sidebar.number_input(
        "Сколько файлов обработать?",
        min_value=0,
        max_value=0,
        value=0
    )
else:
    max_files = st.sidebar.number_input(
        f"Сколько файлов обработать? (Всего найдено: {total_found})", 
        min_value=1, 
        max_value=total_found, 
        value=min(total_found, 5)
    )

st.write(f"Текущая конфигурация: будет обработано максимум **{max_files} файлов**. Каждый файл сканируется **полностью**.")

# --- Логика запуска ---
if st.button("Начать сбор данных", type="primary"):
    if not os.path.exists(PDF_FOLDER_PATH):
        st.error(f"Указанная папка не найдена! Проверьте путь: {PDF_FOLDER_PATH}")
    elif total_found == 0:
        st.warning("В указанной папке нет .pdf файлов.")
    else:
        # Ограничиваем список файлов на основе ввода пользователя
        selected_files = all_pdf_files[:max_files]
        total_selected = len(selected_files)
        
        st.info(f"Запуск обработки {total_selected} файлов...")
        
        all_extracted_data = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for idx, file_name in enumerate(selected_files):
            full_path = os.path.join(PDF_FOLDER_PATH, file_name)
            status_text.text(f"Обработка ({idx + 1}/{total_selected}): {file_name}")
            
            # Парсим файл без ограничения по страницам
            file_data = extract_fields_from_pdf(full_path)
            all_extracted_data.append(file_data)
            
            progress_bar.progress((idx + 1) / total_selected)
        
        # Создание таблицы и экспорт
        df = pd.DataFrame(all_extracted_data)
        df.to_excel(RESULT_EXCEL, index=False)
        
        status_text.text("✅ Выбранные файлы полностью обработаны!")
        st.success(f"Данные сохранены в файл: {RESULT_EXCEL}")
        st.dataframe(df)
        
        with open(RESULT_EXCEL, "rb") as f:
            st.download_button(
                label="📥 Скачать готовый Excel файл",
                data=f,
                file_name=RESULT_EXCEL,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )