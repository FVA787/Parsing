Владимир Фомичев
import re
from pathlib import Path

import fitz  # PyMuPDF


# =========================
# НАСТРОЙКИ
# =========================

PDF_PATH = Path(r"C:\Users\fomichevva4\Desktop\Проекты\2026-05-12 Робот ДОМ РФ\pdf\0001_Жилой комплекс_Саларьево парк__94305491_obj68264-pd77-003252.pdf")

# Форматы:
# ""          — все страницы
# "1"         — только 1 страница
# "1,2"       — страницы 1 и 2
# "(1, 2)"    — страницы 1 и 2
# "1-3"       — страницы 1, 2, 3
# "(1-3)"     — страницы 1, 2, 3
# "1,5-8"     — страницы 1 и 5–8
PAGE_SELECTION = "1-3"

# Сколько символов показывать вокруг найденного совпадения
CONTEXT_CHARS = 250


# =========================
# ВЫБОР СТРАНИЦ
# =========================

def parse_page_selection(page_selection: str | None, total_pages: int) -> list[int]:
    if not page_selection or not page_selection.strip():
        return list(range(total_pages))

    text = page_selection.strip()
    text = text.replace("(", "").replace(")", "")
    text = text.replace(" ", "")

    if not text:
        return list(range(total_pages))

    selected_pages = set()

    for part in text.split(","):
        if not part:
            continue

        if "-" in part:
            left, right = part.split("-", 1)

            if not left.isdigit() or not right.isdigit():
                raise ValueError(f"Некорректный диапазон страниц: {part}")

            start_page = int(left)
            end_page = int(right)

            if start_page > end_page:
                start_page, end_page = end_page, start_page

            for page_number in range(start_page, end_page + 1):
                page_index = page_number - 1
                if 0 <= page_index < total_pages:
                    selected_pages.add(page_index)

        else:
            if not part.isdigit():
                raise ValueError(f"Некорректный номер страницы: {part}")

            page_number = int(part)
            page_index = page_number - 1

            if 0 <= page_index < total_pages:
                selected_pages.add(page_index)

    return sorted(selected_pages)


# =========================
# PDF -> TEXT
# =========================

def extract_text_from_pdf(pdf_path: Path, page_selection: str | None = None) -> tuple[str, str]:
    text_parts = []

    with fitz.open(pdf_path) as doc:
        total_pages = len(doc)
        page_indexes = parse_page_selection(page_selection, total_pages)

        if not page_indexes:
            return "", f"Не найдено подходящих страниц. Всего страниц: {total_pages}"

        for page_index in page_indexes:
            page = doc[page_index]
            page_text = page.get_text("text")
            text_parts.append(page_text)

        human_pages = ", ".join(str(i + 1) for i in page_indexes)
        pages_note = f"Обработаны страницы: {human_pages} из {total_pages}"

    return "\n".join(text_parts), pages_note


def normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


# =========================
# REGEX ДЛЯ ПЛОЩАДИ
# =========================

AREA_PATTERNS = [
    {
        "name": "Площадь введенного объекта",
        "pattern": r"(?:Площадь|Общая\s+площадь)\s+введ[её]нного\s+объекта\s*[:\-–—]?\s*([\d\s.,]+(?:кв\.?\s*м|м2|м²)?)",
    },
    {
        "name": "Общая площадь введенного в эксплуатацию объекта",
        "pattern": r"Общая\s+площадь\s+введ[её]нного\s+в\s+эксплуатацию\s+объекта\s*[:\-–—]?\s*([\d\s.,]+(?:кв\.?\s*м|м2|м²)?)",
    },
    {
        "name": "Площадь объекта капитального строительства",
        "pattern": r"(?:Общая\s+)?площадь\s+объекта\s+капитального\s+строительства\s*[:\-–—]?\s*([\d\s.,]+(?:кв\.?\s*м|м2|м²)?)",
    },
    {
        "name": "Общая площадь здания",
        "pattern": r"Общая\s+площадь\s+здания\s*[:\-–—]?\s*([\d\s.,]+(?:кв\.?\s*м|м2|м²)?)",
    },
    {
        "name": "Площадь здания",
        "pattern": r"Площадь\s+здания\s*[:\-–—]?\s*([\d\s.,]+(?:кв\.?\s*м|м2|м²)?)",
    },
    {
        "name": "Общая площадь",
        "pattern": r"Общая\s+площадь\s*[:\-–—]?\s*([\d\s.,]+(?:кв\.?\s*м|м2|м²)?)",
    },
]


def clean_value(value: str) -> str:
    value = value.replace("\n", " ")
    value = re.sub(r"\s+", " ", value)
    value = value.strip(" :-–—;,.")
    return value


def get_context(text: str, start: int, end: int, chars: int = 250) -> str:
    left = max(start - chars, 0)
    right = min(end + chars, len(text))

    fragment = text[left:right]
    fragment = fragment.replace("\n", " ")
    fragment = re.sub(r"\s+", " ", fragment)

    return fragment.strip()


def test_area_regex(text: str):
    found_anything = False

    print()
    print("=" * 100)
    print("ПОИСК ПЛОЩАДИ ПО РЕГУЛЯРНЫМ ВЫРАЖЕНИЯМ")
    print("=" * 100)

    for item in AREA_PATTERNS:
        name = item["name"]
        pattern = item["pattern"]

        matches = list(re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL))

        print()
        print(f"Шаблон: {name}")
        print(f"Regex: {pattern}")
        print(f"Найдено совпадений: {len(matches)}")

        if not matches:
            continue

        found_anything = True

        for i, match in enumerate(matches, start=1):
            raw_value = match.group(1)
            value = clean_value(raw_value)
            context = get_context(text, match.start(), match.end(), CONTEXT_CHARS)

            print()
            print(f"  Совпадение №{i}")
            print(f"  Найденное значение: {value}")
            print(f"  Позиция в тексте: {match.start()}–{match.end()}")
            print(f"  Контекст:")
            print(f"  ...{context}...")

    if not found_anything:
        print()
        print("Площадь не найдена ни по одному шаблону.")
        print("Рекомендация: увеличь диапазон страниц или посмотри сырой текст PDF.")


# =========================
# ОСНОВНОЙ ЗАПУСК
# =========================

def main():
    if not PDF_PATH.exists():
        print(f"PDF не найден: {PDF_PATH}")
        return

    print(f"PDF: {PDF_PATH}")
    print(f"Страницы: {PAGE_SELECTION or 'все'}")

    raw_text, pages_note = extract_text_from_pdf(PDF_PATH, PAGE_SELECTION)
    text = normalize_text(raw_text)

    print(pages_note)
    print(f"Длина извлеченного текста: {len(text)} символов")

    if len(text) < 50:
        print()
        print("Текст почти не извлекся.")
        print("Возможно, PDF является сканом без текстового слоя.")
        return

    test_area_regex(text)


if __name__ == "__main__":
    main()