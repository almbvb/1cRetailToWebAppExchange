# tools — служебные утилиты

## replay_mock.py — повтор порций обмена из заглушки

Отправляет на приём сайта (`/exchange/1c`, см. `docs/c1_exchange.md`) данные, накопленные Python-заглушкой
приложения (`c:\_1c_edt\rt_httpsvc\collab\files\mock_app\state.json`, файл только читается), — так, как
их шлёт 1С по `api_spec.md` 0.8, раздел 3:

- порциями по `--batch` записей (по умолчанию 500), вход HTTP Basic, таймаут 60 с;
- порядок: каталог (единицы, затем группы — родители раньше детей, затем товары), цены, остатки,
  статусы заказов, картинки;
- каталог, цены, остатки — с `full: true` (или `full: false` с `--no-full`); помеченные на удаление
  записи каталога при `full: true` уходят отдельной порцией с `full: false` (в полную выгрузку 1С их
  не включает); в теле каталога неиспользуемые списки — пустые массивы;
- остатки и статусы сгруппированы так, что у всей порции один `updated_at` / `changed_at` (как в 1С),
  группы — по возрастанию времени;
- картинок в `state.json` нет (только метаданные): с `--images-dir ПАПКА` для файлов
  `<GUID>.jpg|.jpeg|.png` выполняется `PUT /images/<guid>` с `image/jpeg` или `image/png`; без опции
  поток пропускается с сообщением.

Строка прогресса на каждую порцию: поток, номер, что в порции, записей, HTTP-код, мс. При ответе
не `2xx` печатаются код и тело ответа, поток прекращается (остальные потоки идут дальше), код выхода — 1.
Если сервер не отвечает — скрипт останавливается сразу с кодом 1.

Логин и пароль — `EXCHANGE_BASIC_USER` / `EXCHANGE_BASIC_PASSWORD` из `.env` в корне репозитория
(или из переменных окружения с теми же именами; другой файл — `--env`). Для `--verify` — `DATABASE_URL`.
Значения секретов скрипт не выводит.

### Опции

| Опция | Что делает |
|---|---|
| `--state ФАЙЛ` | другой `state.json` |
| `--base-url URL` | адрес приёма, по умолчанию `http://127.0.0.1:8090/exchange/1c` |
| `--batch N` | записей в порции (500) |
| `--no-full` | `full: false` для каталога, цен, остатков |
| `--only СПИСОК` | потоки через запятую: `catalog,prices,stock,orders,images` |
| `--limit N` | только первые N записей каждого списка (и N картинок) |
| `--repeat` | каждую порцию отправить дважды — проверка идемпотентности |
| `--dry-run` | только посчитать порции, ничего не отправлять |
| `--images-dir ПАПКА` | отправить картинки `<GUID>.jpg/.jpeg/.png` |
| `--verify` | после отправки сравнить число строк в `catalog_units`, `catalog_groups`, `catalog_products`, `catalog_prices`, `catalog_stock`, `orders` с числом записей в `state.json` (с полным файлом, без учёта `--limit`); если таблицы нет — сообщает; расхождение — код выхода 1 |

### Примеры (PowerShell, из корня репозитория)

```powershell
# сколько порций уйдёт (сервер не нужен)
backend\.venv\Scripts\python.exe tools\replay_mock.py --dry-run

# быстрая проверка: по 10 записей каждого списка, каждая порция дважды
backend\.venv\Scripts\python.exe tools\replay_mock.py --limit 10 --repeat

# полная загрузка и сверка количеств с БД (критерий готовности С1, п. 2)
backend\.venv\Scripts\python.exe tools\replay_mock.py --verify

# только остатки, как изменения (не полная выгрузка), порциями по 100
backend\.venv\Scripts\python.exe tools\replay_mock.py --only stock --no-full --batch 100

# картинки из папки
backend\.venv\Scripts\python.exe tools\replay_mock.py --only images --images-dir D:\tmp\images

# только сверка, без отправки
backend\.venv\Scripts\python.exe tools\replay_mock.py --dry-run --only orders --limit 0 --verify
```

HTTP — только стандартная библиотека (`urllib`); для `--verify` нужны SQLAlchemy и psycopg из
`backend\.venv`.

## clear_catalog.py — очистка каталога перед полной выгрузкой

По `api_spec.md` 0.10 (3.1, К-19) перед «Полной выгрузкой» из 1С каталог сайта стоит очистить: полная
выгрузка не удаляет записи, вышедшие из отбора раньше неё. Скрипт очищает `catalog_units`,
`catalog_groups`, `catalog_products`, `catalog_prices`, `catalog_stock`, `catalog_images` и папку
`MEDIA_DIR\products`. Заказы и журнал обмена не трогает. База и папка — из `.env`.

```powershell
# показать, что будет удалено (ничего не удаляет)
backend\.venv\Scripts\python.exe tools\clear_catalog.py

# удалить
backend\.venv\Scripts\python.exe tools\clear_catalog.py --yes
```
