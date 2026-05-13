import os
import time
import json
import requests
import pandas as pd
import pdfplumber
import streamlit as st
import re

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
    """Открывает страницу и извлекает ID объектов из кода"""
    url = "https://наш.дом.рф/сервисы/каталог-новостроек/список-объектов"
    
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    driver = None
    try:
        st.write("🤖 Запуск локального Chrome...")
        driver = webdriver.Chrome(options=chrome_options)
        driver.get(url)
        time.sleep(7)
        
        st.write("📊 Извлекаем ID домов...")
        page_html = driver.page_source
        
        # Ищем ID объектов в коде страницы
        found_ids = re.findall(r'(?:/объект/|objId=)(\d{3,7})', page_html)
        if not found_ids:
            found_ids = re.findall(r'\b\d{5}\b', page_html)
            
        unique_ids = list(set(found_ids))
        
        if not unique_ids:
            return []
            
        houses_list = []
        for obj_id in unique_ids[:limit]:
            houses_list.append({
                'objId': obj_id,
                'objAddr': f"Дом из каталога (ID {obj_id})",
                'developer': {'shortName': 'Застройщик (информация внутри PDF)'},
                'objPdId': "Определится при скачивании"  # Больше не генерируем фейковый путь
            })
            
        st.success(f"🔒 ID успешно собраны! Найдено уникальных объектов: {len(houses_list)}")
        return houses_list
            
    except Exception as e:
        st.error(f"Ошибка работы браузера Selenium: {e}")
    finally:
        if driver:
            driver.quit()
    return []

def download_declaration(obj_id, pd_id):
    """Находит кнопку скачивания декларации прямо на странице объекта"""
    # Заходим на страницу карточки конкретного дома
    object_url = f"https://наш.дом.рф/сервисы/каталог-новостроек/объект/{obj_id}"
    
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    prefs = {
        "download.default_directory": os.path.abspath(DOWNLOAD_DIR),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True
    }
    chrome_options.add_experimental_option("prefs", prefs)
    
    driver = None
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.get(object_url)
        time.sleep(5)  # Ждем загрузку карточки дома
        
        # Запоминаем список файлов в папке до нажатия на кнопку
        files_before = set(os.listdir(DOWNLOAD_DIR))
        
        st.write(f"🔎 Ищем ссылку на декларацию на странице объекта {obj_id}...")
        
        # Находим элемент ссылки, который содержит скачивание проектной декларации
        # Кнопка на сайте обычно содержит текст "Проектная декларация" или ссылку со словом 'file'
        download_buttons = driver.find_elements("xpath", "//a[contains(text(), 'декларация') or contains(@href, 'file')]")
        
        if download_buttons:
            # Кликаем по первой найденной кнопке документа
            driver.execute_script("arguments[0].click();", download_buttons[0])
            time.sleep(7)  # Ожидаем скачивание файла
            
            # Проверяем, какой новый файл появился в папке
            files_after = set(os.listdir(DOWNLOAD_DIR))
            new_files = files_after - files_before
            
            if new_files:
                downloaded_name = list(new_files)[0]
                old_path = os.path.join(DOWNLOAD_DIR, downloaded_name)
                new_path = os.path.join(DOWNLOAD_DIR, f"declaration_{obj_id}.pdf")
                
                # Переименовываем для унификации
                if not os.path.exists(new_path) and downloaded_name.endswith('.pdf'):
                    os.rename(old_path, new_path)
                    return new_path
                return old_path
        else:
            print(f"Кнопка декларации не найдена для объекта {obj_id}")
            
    except Exception as e:
        print(f"Ошибка при поиске кнопки скачивания: {e}")
    finally:
        if driver:
            driver.quit()
            
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