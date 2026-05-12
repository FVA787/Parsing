## Task

Parse a Russian project address from a real-estate declaration into structured components.

## Input

A free-form Russian address string (one line).

## Output

A single JSON object on one line, with exactly these keys (use `null` when the component is not present in the input):

- `city` — city name only (e.g. `"Москва"`). Strip prefixes like `"г."`, `"Г."`, `"город "`.
- `district` — administrative okrug code (`"ЦАО"`, `"САО"`, `"НАО"`, `"ВАО"`, `"СВАО"`, `"СЗАО"`, `"ЮАО"`, `"ЮВАО"`, `"ЮЗАО"`, `"ЗАО"`) **or** the full okrug name written in the input (e.g. `"Новомосковский административный округ"`).
- `street` — street with its type prefix exactly as written (e.g. `"улица Саларьевская"`, `"ул.Куусинена"`, `"Краснопресненская наб."`, `"пр-д 2-й Иртышский"`).
- `land_plot` — land plot designator (e.g. `"земельный участок 17"`, `"з/у 4"`, `"вл.21"`, `"вл.14"`).
- `building` — building/corpus designator (e.g. `"корпус 82"`, `"стр.1"`, `"д 14"`, `"21А"`).

## Rules

1. Output JSON only. No prose, no explanation, no markdown fences.
2. Do not invent values. If the input has only a building number, set the other four fields to `null`.
3. Preserve original spelling and casing for `street`, `land_plot`, `building`. Normalise `city` to `"Москва"` if any spelling of Moscow is present.
4. If the input is a non-address description (e.g. `"Многофункциональный гостиничный комплекс ..."`), set every field to `null`.

## Examples

Input: `Г.Москва, НАО, вн.тер.г. муниципальный округ Коммунарка, улица Саларьевская, земельный участок 17, корпус 82`
Output: `{"city":"Москва","district":"НАО","street":"улица Саларьевская","land_plot":"земельный участок 17","building":"корпус 82"}`

Input: `Москва, САО, г.Москва, Хорошевский, ул.Куусинена, вл.21, 21А`
Output: `{"city":"Москва","district":"САО","street":"ул.Куусинена","land_plot":"вл.21","building":"21А"}`

Input: `Г. Москва, ЦАО, район Пресненский, Краснопресненская наб. вл.14, стр.1`
Output: `{"city":"Москва","district":"ЦАО","street":"Краснопресненская наб.","land_plot":"вл.14","building":"стр.1"}`

Input: `Корпус 11 (этап 16)`
Output: `{"city":null,"district":null,"street":null,"land_plot":null,"building":"Корпус 11 (этап 16)"}`

Input: `Земельный участок 32`
Output: `{"city":null,"district":null,"street":null,"land_plot":"Земельный участок 32","building":null}`

Input: `Многофункциональный гостиничный комплекс с подземной автостоянкой. Этап 1. Корпуса 2, 4`
Output: `{"city":null,"district":null,"street":null,"land_plot":null,"building":null}`

Input: `Коммунарка, квартал 226, земельный участок 3/3, Прокшино 9`
Output: `{"city":null,"district":null,"street":null,"land_plot":"земельный участок 3/3","building":"Прокшино 9"}`

## Now parse

Input: `{ADDRESS}`
Output:
