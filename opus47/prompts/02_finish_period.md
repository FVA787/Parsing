## Task

You are given a numbered list of construction-stage events from a Russian real-estate declaration (section 17.1.1).

Pick the event whose text describes the moment of **получение разрешения на ввод в эксплуатацию** (i.e. obtaining the permit for commissioning the object). The same idea may appear with hyphenated line breaks (`...недви-жимости`), abbreviations or rewordings such as "ввод в эксплуатацию", "выдача разрешения на ввод", "получение разрешения на ввод в эксплуатацию объекта недвижимости".

The other events are intermediate progress milestones such as "20 процентов готовности", "40 процентов готовности", "монтаж", "отделка", and they must NOT be selected.

If the list contains **multiple** commissioning events (e.g. a multi-building project lists the same event for each building), pick the **last** one — it represents the latest planned completion across all buildings.

## Output

A single JSON object on one line:

`{"index": <number>}`

— where `<number>` is the 1-based position of the matching event in the input list.

If **none** of the events describes obtaining the commissioning permit, return:

`{"index": null}`

Output JSON only. No prose, no markdown fences.

## Examples

Input:
```
1. Этап реализации проекта строительства: 20 процентов готовности
2. Этап реализации проекта строительства: 40 процентов готовности
3. Этап реализации проекта строительства: 60 процентов готовности
4. Этап реализации проекта строительства: 80 процентов готовности
5. Этап реализации проекта строительства: получение разрешения на ввод в эксплуатацию объекта недвижимости
```
Output: `{"index": 5}`

Input:
```
1. Этап реализации: 20 процентов готовности
2. Этап реализации: 40 процентов готовности
3. Этап реализации: получение разрешения на ввод в эксплуатацию объекта недви-жимости
4. Этап реализации: 80 процентов готовности
```
Output: `{"index": 3}`

Input:
```
1. Этап: монтаж фундамента
2. Этап: монтаж стен
3. Этап: отделочные работы
```
Output: `{"index": null}`

Input (multi-building project):
```
1. Этап реализации: 20 процентов готовности
2. Этап реализации: 40 процентов готовности
3. Этап реализации: 60 процентов готовности
4. Этап реализации: 80 процентов готовности
5. Этап реализации: получение разрешения на ввод в эксплуатацию объекта недвижимости
6. Этап реализации: 20 процентов готовности
7. Этап реализации: 40 процентов готовности
8. Этап реализации: 60 процентов готовности
9. Этап реализации: 80 процентов готовности
10. Этап реализации: получение разрешения на ввод в эксплуатацию объекта недвижимости
11. Этап реализации: 20 процентов готовности
12. Этап реализации: 40 процентов готовности
13. Этап реализации: 60 процентов готовности
14. Этап реализации: 80 процентов готовности
15. Этап реализации: получение разрешения на ввод в эксплуатацию объекта недвижимости
```
Output: `{"index": 15}`

## Now choose

Input:
{EVENTS}
Output:
