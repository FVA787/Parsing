import os
import requests
import pandas as pd
import pdfplumber
import streamlit as st

# 1. Настройки
BASE_URL = "https://xn--d1aqf.xn--p1ai" # API наш.дом.рф
DOWNLOAD_DIR = "declarations"
RESULT_EXCEL = "dom_rf_data.xlsx"

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

def get_house_list(limit=5):
    """Получает список объектов с сайта через API"""
    params = {
        "offset": 0,
        "limit": limit,
        "sortField": "objId",
        "sortType": "asc"
    }
    response = requests.get(BASE_URL, params=params)
    if response.status_code == 200:
        return response.json().get('data', {}).get('list', [])
    return []

def download_declaration(obj_id):
    """Скачивает проектную декларацию по ID объекта"""
    # Ссылка на декларацию обычно формируется через ID объекта
    url = f"https://наш.дом.рф/сервисы/каталог-объектов/объект/{obj_id}"
    # Примечание: В реальном API прямая ссылка на PDF лежит в карточке объекта
    # Для примера имитируем путь к файлу, если мы нашли прямую ссылку
    file_path = os.path.join(DOWNLOAD_DIR, f"decl_{obj_id}.pdf")
    
    # Это упрощенный пример. В реальности нужно извлечь 'pdId' из данных объекта
    # и скачать по ссылке: https://наш.дом.рф/api/ext/file/ID_ФАЙЛА
    return file_path

def parse_pdf(file_path):
    """Базовый пример извлечения текста из PDF"""
    try:
        with pdfplumber.open(file_path) as pdf:
            first_page = pdf.pages[0]
            text = first_page.extract_text()
            # Здесь должна быть логика поиска конкретных полей (ИНН, Площадь и т.д.)
            return {"Файл": file_path, "Краткий текст": text[:100] if text else "Пусто"}
    except Exception as e:
        return {"Файл": file_path, "Ошибка": str(e)}

# --- Интерфейс Streamlit ---
st.title("Парсер деклараций ДОМ.РФ")

if st.button("Запустить процесс"):
    st.info("Шаг 1: Получаем список домов...")
    houses = get_house_list(limit=3) # Берем 3 для теста
    
    data_for_excel = []
    
    for house in houses:
        obj_id = house.get('objId')
        addr = house.get('address')
        st.write(f"Обработка объекта ID {obj_id}: {addr}")
        
        # В реальном API ссылка на файл лежит здесь:
        # house.get('objPdId') -> это ID файла декларации
        
        # Имитация сбора данных
        data_for_excel.append({
            "ID объекта": obj_id,
            "Адрес": addr,
            "Застройщик": house.get('developer', {}).get('shortName')
        })
    
    # Сохранение в Excel
    df = pd.DataFrame(data_for_excel)
    df.to_excel(RESULT_EXCEL, index=False)
    
    st.success(f"Готово! Данные сохранены в {RESULT_EXCEL}")
    st.dataframe(df)

    with open(RESULT_EXCEL, "rb") as f:
        st.download_button("Скачать Excel файл", f, file_name=RESULT_EXCEL)