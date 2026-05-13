import os
import time
import json
import requests
import pandas as pd
import pdfplumber
import streamlit as st

# Настройки Selenium
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

DOWNLOAD_DIR = "declarations"
RESULT_EXCEL = "dom_rf_data.xlsx"

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

def get_house_list_via_selenium(limit=3):
    """Открывает скрытый браузер, используя локальный драйвер"""
    url = f"https://наш.дом.рф/api/ext/v1/objects?offset=0&limit={limit}&sortField=objId&sortType=desc"
    
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Скрытый режим
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    driver = None
    try:
        st.write("🤖 Запуск локального Chrome...")
        # ИСПРАВЛЕНО: Убрали webdriver-manager, используем встроенный локальный поиск Chrome
        driver = webdriver.Chrome(options=chrome_options)
        
        st.write("🌍 Обходим проверку сайта наш.дом.рф...")
        driver.get(url)
        
        time.sleep(5)
        page_source = driver.find_element("xpath", "//body").text
        
        try:
            json_data = json.loads(page_source)
            st.success("🔒 Защита успешно пройдена!")
            return json_data.get('data', {}).get('list', [])
        except json.JSONDecodeError:
            st.error("Не удалось десериализовать JSON. Получен текст:")
            st.code(page_source[:400])
            
    except Exception as e:
        st.error(f"Ошибка работы браузера Selenium: {e}")
    finally:
        if driver:
            driver.quit()
            
    return []

def download_declaration(obj_id, pd_id):
    """Скачивает оригинальный файл проектной декларации"""
    if not pd_id:
        return None
        
    download_url = f"xn--d1aqf.xn--p1ai{pd_id}"
    file_path = os.path.join(DOWNLOAD_DIR, f"declaration_{obj_id}.pdf")
    
    if os.path.exists(file_path):
        return file_path
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    try:
        # Для скачивания файлов прямые запросы часто работают, если сессия не привязана жестко
        res = requests.get(download_url, headers=headers, verify=False, timeout=20)
        if res.status_code == 200:
            with open(file_path, "wb") as f:
                f.write(res.content)
            return file_path
    except Exception as e:
        st.warning(f"Не удалось скачать PDF для объекта {obj_id}: {e}")
    return None

def parse_pdf(file_path):
    """Извлекает текст из первой страницы декларации"""
    if not file_path:
        return "Файл не скачан"
    try:
        with pdfplumber.open(file_path) as pdf:
            if pdf.pages:
                first_page = pdf.pages[0]
                text = first_page.extract_text()
                return text[:150].replace("\n", " ") if text else "Текст пуст"
    except Exception as e:
        return f"Ошибка чтения PDF: {e}"
    return "Нет данных"

# --- Интерфейс Streamlit ---
st.title("🏭 Парсер ДОМ.РФ через эмуляцию браузера")
st.write("Использует Selenium для безопасного прохождения антибот-систем сайта.")

limit_input = st.number_input("Количество объектов для проверки:", min_value=1, max_value=10, value=3)

if st.button("Запустить процесс через Selenium", type="primary"):
    st.info("Шаг 1: Запуск скрытого браузера Chrome...")
    houses = get_house_list_via_selenium(limit=limit_input)
    
    if not houses:
        st.warning("Список домов пуст. Не удалось собрать данные.")
    else:
        st.info(f"Найдено объектов: {len(houses)}. Начинаем обработку...")
        data_for_excel = []
        
        for house in houses:
            obj_id = house.get('objId')
            addr = house.get('objAddr', 'Адрес не указан')
            dev_name = house.get('developer', {}).get('shortName', 'Не указан')
            pd_id = house.get('objPdId')
            
            st.write(f"⏳ Загрузка ID {obj_id}: {addr}")
            
            pdf_path = download_declaration(obj_id, pd_id)
            pdf_snippet = parse_pdf(pdf_path)
            
            data_for_excel.append({
                "ID объекта": obj_id,
                "Застройщик": dev_name,
                "Адрес": addr,
                "ID Декларации": pd_id if pd_id else "Нет",
                "Путь к файлу на ПК": pdf_path if pdf_path else "Ошибка",
                "Выдержка из декларации": pdf_snippet
            })
            time.sleep(1)
            
        df = pd.DataFrame(data_for_excel)
        df.to_excel(RESULT_EXCEL, index=False)
        
        st.success(f"🎉 Процесс завершен! Данные сохранены.")
        st.dataframe(df)

        with open(RESULT_EXCEL, "rb") as f:
            st.download_button(
                label="📥 Скачать готовый Excel файл", 
                data=f, 
                file_name=RESULT_EXCEL,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )