# С1. Приём данных из 1С — проект и микрозадачи

Основание: `api_spec.md` 0.8 раздел 1 и 3 (К-4 журнала контракта); эталон — `mock_app.py`.
Базовый адрес для 1С: `http://localhost:8090/exchange/1c` (1С добавляет `/catalog`, `/prices`, `/stock`,
`/images/{product_id}`, `/orders/status`).

## Общие правила приёма

- **Вход.** `Authorization: Basic` (`EXCHANGE_BASIC_USER` / `EXCHANGE_BASIC_PASSWORD`) или
  `Authorization: Bearer <токен>` (`EXCHANGE_BEARER_TOKENS`); сравнение — `secrets.compare_digest`.
  Иначе `401 UNAUTHORIZED` + `WWW-Authenticate: Basic realm="exchange"`. Пароль и токен в журнал не пишутся.
- **Ошибки** — всегда `{"error": {"code", "message", "details": []}}`.
  `400 INVALID_FORMAT` (неверный JSON, нет обязательных полей, неверные типы; `details` — список полей),
  `401 UNAUTHORIZED`, `413 IMAGE_TOO_LARGE`, `415 UNSUPPORTED_IMAGE`, `500 INTERNAL_ERROR`.
- **Неизвестные поля** игнорируются. Ошибка в одной записи — вся порция `400` (1С повторит порцию).
- **Проверяем только то, что задаёт контракт** (К-5): обязательные поля, типы, формат GUID.
  Своих пределов длины и значений не вводим — иначе одна запись остановит весь поток (1С повторяет
  порцию без конца). Строки в БД — `text`; `article` и `description` могут быть пустыми или `null`.
- **Порция — одна транзакция.** Ответ `200 {"ok": true, "counts": {...}}` только после фиксации.
- **Идемпотентность.** Запись по ключу заменяется целиком (UPSERT). Дубли ключа внутри одной порции —
  остаётся последняя (иначе `ON CONFLICT` падает на повторной строке).
- **`full: true`** ничего не удаляет и не обнуляет; только отмечается в журнале.
- **`deleted: true`** — запись сохраняется с флагом, витрина её скрывает.
- **Порядок потоков не гарантирован:** остаток, цена, картинка могут прийти раньше карточки товара —
  внешних ключей между этими таблицами нет (только индексы).
- **Остатки:** запись с `updated_at` строго раньше сохранённой игнорируется (считается в `counts.skipped`).
  **Статусы:** то же по `changed_at`.
- **`store_id`** не равный `ONEC_STORE_ID` — запись сохраняется (ключ включает магазин), в `counts.other_store`;
  витрина показывает только свой магазин. Ответ всё равно `200`, чтобы 1С не повторяла бесконечно.
- **Журнал обмена** (`exchange_batches`) — строка на каждый запрос, в отдельной транзакции, в том числе при ошибке:
  время, метод, путь, поток, HTTP-код, схема и логин (без пароля), `full`, счётчики, код и текст ошибки,
  байты, длительность. Тело порции не хранится.
- **Предел тела:** JSON — 20 МБ; картинка — `IMAGE_MAX_BYTES` (4 МБ), проверка `Content-Length` до чтения
  и при потоковом чтении.

## Модель данных (PostgreSQL)

| Таблица | Ключ | Поля |
|---|---|---|
| `catalog_groups` | `id` uuid | `parent_id` uuid null, `name`, `sort` integer (0.9), `deleted`, `received_at` |
| `catalog_units` | `id` uuid | `name`, `code`, `received_at` |
| `catalog_products` | `id` uuid | `group_id` null, `name`, `article` null, `unit_id` null (услуга без единицы), `weighted`, `description` null, `deleted`, `received_at` (строки — `text`) |
| `catalog_prices` | `store_id`, `product_id` | `price` numeric, `received_at` |
| `catalog_stock` | `store_id`, `product_id` | `available` numeric, `updated_at` timestamptz (из 1С), `received_at` |
| `catalog_images` | `product_id` | `content_type`, `size_bytes`, `sha256`, `width`, `height`, `original_path`, `received_at` |
| `orders` | `order_id` varchar(36) | `number` (номер сайта, null до С4), `onec_number`, `status`, `onec_created_at`, `onec_changed_at`, `total` numeric, `received_at` |
| `order_onec_items` | `order_id`, `line_no` | `product_id`, `quantity`, `price`, `amount` (numeric), `cancelled` |
| `exchange_batches` | `id` bigserial | см. «Журнал обмена» |

Числа — `numeric` без разрядности: значения хранятся как пришли (Decimal), округление — дело витрины.

`orders` создаётся уже в С1: статус может прийти по заказу, которого сайт не создавал (тесты через заглушку) —
он сохраняется. Поля покупателя и состав, который видел покупатель, добавит С4.
`order_onec_items` заменяется целиком при каждом принятом статусе.

## Картинки

- `PUT /images/{product_id}`: `product_id` — GUID, иначе `400`. Тело ≤ `IMAGE_MAX_BYTES`, иначе `413`.
  Pillow: формат по содержимому только JPEG или PNG, иначе `415`; ≤ `IMAGE_MAX_MEGAPIXELS`, иначе `413`.
- Оригинал: `MEDIA_DIR/products/<product_id>/original.<jpg|png>`; превью WebP по длинной стороне
  400 и 1000 px: `.../<sha256[:12]>_400.webp`, `..._1000.webp`. Запись атомарная (временный файл + `os.replace`).
  Тот же `sha256` — превью не пересоздаются (идемпотентность).
- `DELETE /images/{product_id}`: удалить строку и файлы; если картинки не было — тоже `200`.

## Микрозадачи

Порядок: сначала Т1 (общая основа), затем Т2–Т6 параллельно — у каждой свои файлы.

| № | Что | Файлы (только эти) |
|---|---|---|
| Т1 | Модели, миграция Alembic, вход, ошибки, журнал обмена, общий разбор JSON, роутер с заглушками потоков | `app/models/*`, `alembic/versions/*`, `app/exchange/onec/{router,auth,errors,journal,common}.py`, заглушки `catalog.py prices.py stock.py images.py orders_status.py`, `tests/exchange/conftest.py`, `tests/exchange/test_auth_and_journal.py` |
| Т2 | Каталог и цены | `app/exchange/onec/catalog.py`, `prices.py`, `tests/exchange/test_catalog.py`, `test_prices.py` |
| Т3 | Остатки | `app/exchange/onec/stock.py`, `tests/exchange/test_stock.py` |
| Т4 | Картинки и превью | `app/exchange/onec/images.py`, `app/services/images.py`, `tests/exchange/test_images.py` |
| Т5 | Статусы заказов | `app/exchange/onec/orders_status.py`, `tests/exchange/test_orders_status.py` |
| Т6 | Повтор порций из `state.json` заглушки (только чтение) | `tools/replay_mock.py` |
| Т7 | Админка: журнал обмена и принятые данные (только чтение), после Т2–Т5 | `app/admin/*`, подключение в `app/main.py` |

Каждая задача: тесты на повтор порции, неверный порядок, запись раньше карточки, неверный JSON,
запрос без входа. Проверку и приёмку делает ведущая сессия.

## Критерий готовности С1 (стенд)

1. Все автотесты зелёные, `ruff` чисто.
2. `tools/replay_mock.py` загружает данные заглушки: количества групп, товаров, цен, остатков совпадают.
3. Пользователь переключает 1С на `http://localhost:8090/exchange/1c` и запускает «Полную выгрузку»:
   количества совпадают с 1С, ошибок в журнале обмена 0.
4. Сайт остановлен → 1С не снимает регистрацию и повторяет; после запуска данные доходят.
5. Изменение цены, остатка, картинки и статуса тестового заказа в 1С доходит до сайта.
