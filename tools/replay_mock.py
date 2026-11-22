"""Повтор порций обмена 1С из state.json заглушки приложения (api_spec.md 0.8, раздел 3).

Читает состояние, накопленное заглушкой mock_app.py, и отправляет его на приём сайта так, как это
делает 1С: порциями, с `full: true` для каталога, цен и остатков. Порядок потоков: каталог (единицы,
группы, товары), цены, остатки, статусы заказов, картинки (только с --images-dir).

Запуск (из корня репозитория):
  backend\\.venv\\Scripts\\python.exe tools\\replay_mock.py --dry-run
  backend\\.venv\\Scripts\\python.exe tools\\replay_mock.py --only catalog --limit 10 --repeat
  backend\\.venv\\Scripts\\python.exe tools\\replay_mock.py --verify

Логин и пароль обмена берутся из .env (EXCHANGE_BASIC_USER, EXCHANGE_BASIC_PASSWORD), для --verify —
DATABASE_URL. Переменные окружения с теми же именами имеют приоритет. Значения секретов не выводятся.

Код выхода: 0 — всё принято (и при --verify количества совпали); 1 — ошибка отправки, настройки
или расхождение количеств.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE = Path(r"c:\_1c_edt\rt_httpsvc\collab\files\mock_app\state.json")
DEFAULT_ENV = REPO_ROOT / ".env"
DEFAULT_BASE_URL = "http://127.0.0.1:8090/exchange/1c"
TIMEOUT_SECONDS = 60
MAX_ERROR_BODY = 4000

STREAMS = ("catalog", "prices", "stock", "orders", "images")
GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}

# Таблица БД -> ключ списка в state.json (для --verify).
VERIFY_TABLES = (
    ("catalog_units", "units"),
    ("catalog_groups", "groups"),
    ("catalog_products", "products"),
    ("catalog_prices", "prices"),
    ("catalog_stock", "stock"),
    ("orders", "orders"),
)


class FatalError(Exception):
    """Ошибка, после которой продолжать нет смысла (настройки, недоступный сервер)."""


class Secrets:
    """Значения секретов: нужны для запросов и для вычёркивания из сообщений об ошибках."""

    def __init__(self) -> None:
        self.values: list[str] = []

    def add(self, value: str | None) -> None:
        if value and len(value) >= 3:
            self.values.append(value)

    def scrub(self, text: str) -> str:
        for value in self.values:
            text = text.replace(value, "***")
        return text


SECRETS = Secrets()


def configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]


def say(text: str = "") -> None:
    print(SECRETS.scrub(text), flush=True)


# ---------------------------------------------------------------- настройки


def read_env_file(path: Path) -> dict[str, str]:
    """Простой разбор .env: KEY=VALUE, комментарии #, необязательные кавычки."""
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        result[key] = value
    return result


def setting(env: dict[str, str], name: str) -> str:
    return os.environ.get(name) or env.get(name, "")


# ---------------------------------------------------------------- данные


def load_state(path: Path) -> dict[str, list[dict]]:
    if not path.is_file():
        raise FatalError(f"нет файла состояния заглушки: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise FatalError(f"не удалось прочитать {path}: {error.__class__.__name__}: {error}") from None
    state: dict[str, list[dict]] = {}
    for key in ("units", "groups", "products", "prices", "stock", "orders", "images"):
        value = data.get(key) or {}
        state[key] = list(value.values()) if isinstance(value, dict) else list(value)
    return state


def order_groups(groups: list[dict]) -> list[dict]:
    """Родительские группы раньше дочерних (как удобно приёму; контракт порядок не требует)."""
    by_id = {g.get("id"): g for g in groups}
    done: set = set()
    result: list[dict] = []

    def visit(group: dict, path: set) -> None:
        gid = group.get("id")
        if gid in done:
            return
        parent = by_id.get(group.get("parent_id"))
        if parent is not None and parent.get("id") not in path:
            visit(parent, path | {gid})
        done.add(gid)
        result.append(group)

    for group in groups:
        visit(group, {group.get("id")})
    return result


def chunks(rows: list[dict], size: int) -> Iterator[list[dict]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def chunks_by_field(rows: list[dict], field: str, size: int) -> Iterator[list[dict]]:
    """Порции, в каждой одно значение field (updated_at / changed_at), по возрастанию значения."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(str(row.get(field) or ""), []).append(row)
    for value in sorted(groups):
        yield from chunks(groups[value], size)


class Batch:
    def __init__(
        self, stream: str, label: str, method: str, path: str, records: int, body: bytes, ctype: str
    ):
        self.stream = stream
        self.label = label
        self.method = method
        self.path = path
        self.records = records
        self.body = body
        self.ctype = ctype


def json_body(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


JSON_CT = "application/json; charset=utf-8"


def catalog_batches(state: dict, size: int, full: bool) -> Iterator[Batch]:
    lists = (
        ("units", state["units"]),
        ("groups", order_groups(state["groups"])),
        ("products", state["products"]),
    )
    for key, rows in lists:
        if full:
            # В полную выгрузку 1С не включает помеченные на удаление; они приходят отдельно,
            # как обычное изменение записи (full: false), — чтобы количества совпали со state.json.
            live = [r for r in rows if not r.get("deleted")]
            dead = [r for r in rows if r.get("deleted")]
        else:
            live, dead = rows, []
        for part, part_full in ((live, full), (dead, False)):
            for chunk in chunks(part, size):
                payload = {"full": part_full, "units": [], "groups": [], "products": []}
                payload[key] = chunk
                label = key if part_full == full else f"{key} deleted"
                yield Batch("catalog", label, "POST", "/catalog", len(chunk), json_body(payload), JSON_CT)


def price_batches(state: dict, size: int, full: bool) -> Iterator[Batch]:
    for chunk in chunks(state["prices"], size):
        yield Batch(
            "prices",
            "prices",
            "POST",
            "/prices",
            len(chunk),
            json_body({"full": full, "prices": chunk}),
            JSON_CT,
        )


def stock_batches(state: dict, size: int, full: bool) -> Iterator[Batch]:
    for chunk in chunks_by_field(state["stock"], "updated_at", size):
        yield Batch(
            "stock", "stock", "POST", "/stock", len(chunk), json_body({"full": full, "stock": chunk}), JSON_CT
        )


def order_batches(state: dict, size: int) -> Iterator[Batch]:
    for chunk in chunks_by_field(state["orders"], "changed_at", size):
        yield Batch(
            "orders", "orders", "POST", "/orders/status", len(chunk), json_body({"orders": chunk}), JSON_CT
        )


def image_files(images_dir: Path, limit: int | None) -> tuple[list[tuple[str, Path, str]], list[str]]:
    """Файлы <GUID>.jpg|.jpeg|.png; возвращает (подходящие, пропущенные имена)."""
    found: list[tuple[str, Path, str]] = []
    skipped: list[str] = []
    for path in sorted(images_dir.iterdir()):
        if not path.is_file():
            continue
        ctype = IMAGE_TYPES.get(path.suffix.lower())
        guid = path.stem.lower()
        if ctype is None or not GUID_RE.match(guid):
            skipped.append(path.name)
            continue
        found.append((guid, path, ctype))
    if limit is not None:
        found = found[:limit]
    return found, skipped


def image_batches(files: list[tuple[str, Path, str]]) -> Iterator[Batch]:
    for guid, path, ctype in files:
        body = path.read_bytes()
        yield Batch("images", path.name, "PUT", f"/images/{guid}", 1, body, ctype)


# ---------------------------------------------------------------- отправка


class Sender:
    def __init__(self, base_url: str, user: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
        SECRETS.add(token)
        self.auth = f"Basic {token}"

    def send(self, batch: Batch) -> tuple[int, str, float]:
        """Возвращает (HTTP-код, тело ответа, мс). Сетевая ошибка — FatalError."""
        request = urllib.request.Request(
            self.base_url + batch.path,
            data=batch.body,
            method=batch.method,
            headers={"Content-Type": batch.ctype, "Authorization": self.auth, "Accept": "application/json"},
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                status, text = response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            status = error.code
            try:
                text = error.read().decode("utf-8", "replace")
            except OSError:
                text = ""
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise FatalError(
                f"{batch.method} {self.base_url}{batch.path}: нет ответа сервера: {reason}"
            ) from None
        return status, text, (time.perf_counter() - started) * 1000


class Totals:
    def __init__(self) -> None:
        self.batches: dict[str, int] = {}
        self.records: dict[str, int] = {}
        self.requests: dict[str, int] = {}
        self.failed: dict[str, str] = {}

    def add(self, stream: str, records: int, requests: int) -> None:
        self.batches[stream] = self.batches.get(stream, 0) + 1
        self.records[stream] = self.records.get(stream, 0) + records
        self.requests[stream] = self.requests.get(stream, 0) + requests


def run_stream(
    stream: str, batches: Iterator[Batch], sender: Sender | None, repeat: bool, totals: Totals
) -> bool:
    """Отправляет порции одного потока; при не-2xx печатает ответ и прекращает поток (False)."""
    number = 0
    totals.batches.setdefault(stream, 0)
    totals.records.setdefault(stream, 0)
    totals.requests.setdefault(stream, 0)
    for batch in batches:
        number += 1
        head = f"{stream:<8} #{number:<4} {batch.label:<18} {batch.records:>6} зап."
        if sender is None:
            say(f"{head}  {len(batch.body):>9} байт")
            totals.add(stream, batch.records, 0)
            continue
        attempts = 2 if repeat else 1
        for attempt in range(1, attempts + 1):
            status, text, ms = sender.send(batch)
            mark = " (повтор)" if attempt > 1 else ""
            say(f"{head}  {status}  {ms:>7.0f} мс{mark}")
            if not 200 <= status < 300:
                body = text if len(text) <= MAX_ERROR_BODY else text[:MAX_ERROR_BODY] + " …"
                say(f"  ОШИБКА {status} на {batch.method} {batch.path}: {body}")
                say(f"  поток {stream} прекращён")
                totals.failed[stream] = f"HTTP {status} на порции #{number}"
                return False
        totals.add(stream, batch.records, attempts)
    return True


# ---------------------------------------------------------------- сверка с БД


def verify(env: dict[str, str], state: dict) -> bool:
    url_text = setting(env, "DATABASE_URL")
    if not url_text:
        say("сверка: DATABASE_URL не задан (.env или окружение) — пропущена")
        return False
    SECRETS.add(url_text)
    try:
        from sqlalchemy import create_engine, inspect, text
        from sqlalchemy.engine import make_url
    except ImportError:
        say("сверка: нет SQLAlchemy — запускайте Python из backend\\.venv")
        return False
    try:
        url = make_url(url_text)
        SECRETS.add(url.password if isinstance(url.password, str) else None)
        if url.drivername in ("postgresql", "postgres"):
            url = url.set(drivername="postgresql+psycopg")
        engine = create_engine(url, connect_args={"connect_timeout": 10})
    except Exception as error:  # любое: неверный адрес не должен ронять скрипт
        say(f"сверка: неверный DATABASE_URL ({error.__class__.__name__})")
        return False

    ok = True
    say("")
    say("Сверка с БД (с полным state.json, без учёта --limit):")
    say(f"  {'таблица':<18} {'в БД':>8} {'в state':>8}")
    try:
        with engine.connect() as conn:
            existing = set(inspect(conn).get_table_names())
            for table, key in VERIFY_TABLES:
                expected = len(state[key])
                if table not in existing:
                    say(f"  {table:<18} {'—':>8} {expected:>8}  таблицы нет")
                    ok = False
                    continue
                count = conn.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
                mark = "совпадает" if count == expected else "РАСХОЖДЕНИЕ"
                ok = ok and count == expected
                say(f"  {table:<18} {count:>8} {expected:>8}  {mark}")
    except Exception as error:  # сообщить и не падать
        first_line = str(error).strip().splitlines()[0] if str(error).strip() else ""
        say(f"сверка: ошибка БД {error.__class__.__name__}: {first_line}")
        ok = False
    finally:
        engine.dispose()
    return ok


# ---------------------------------------------------------------- main


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE, help="state.json заглушки")
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV, help="файл .env сайта")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"по умолчанию {DEFAULT_BASE_URL}")
    parser.add_argument("--batch", type=int, default=500, help="записей в порции (по умолчанию 500)")
    parser.add_argument("--no-full", action="store_true", help="full: false для каталога, цен, остатков")
    parser.add_argument(
        "--only", default=",".join(STREAMS), help="потоки через запятую: " + ",".join(STREAMS)
    )
    parser.add_argument("--limit", type=int, help="только первые N записей каждого списка")
    parser.add_argument("--repeat", action="store_true", help="каждую порцию отправить дважды")
    parser.add_argument("--dry-run", action="store_true", help="только посчитать порции, без отправки")
    parser.add_argument("--images-dir", type=Path, help="папка с файлами <GUID>.jpg|.jpeg|.png")
    parser.add_argument("--verify", action="store_true", help="сверить количества строк в БД со state.json")
    args = parser.parse_args(argv)
    if args.batch < 1:
        parser.error("--batch должен быть не меньше 1")
    if args.limit is not None and args.limit < 0:
        parser.error("--limit должен быть не меньше 0")
    only = [s.strip() for s in args.only.split(",") if s.strip()]
    unknown = [s for s in only if s not in STREAMS]
    if unknown:
        parser.error(f"неизвестные потоки в --only: {', '.join(unknown)}")
    args.only = [s for s in STREAMS if s in only]
    return args


def main(argv: list[str] | None = None) -> int:
    configure_stdout()
    args = parse_args(argv)
    env = read_env_file(args.env)
    full = not args.no_full

    try:
        state = load_state(args.state)
        source = state
        if args.limit is not None:
            source = {key: rows[: args.limit] for key, rows in state.items()}
        say(
            "state.json: "
            + ", ".join(
                f"{key} {len(state[key])}" for key in ("units", "groups", "products", "prices", "stock")
            )
            + f", orders {len(state['orders'])}, images (метаданные) {len(state['images'])}"
        )

        sender: Sender | None = None
        if not args.dry_run and args.only:
            user = setting(env, "EXCHANGE_BASIC_USER")
            password = setting(env, "EXCHANGE_BASIC_PASSWORD")
            SECRETS.add(password)
            if not user or not password:
                raise FatalError(
                    f"не заданы EXCHANGE_BASIC_USER / EXCHANGE_BASIC_PASSWORD ({args.env} или окружение)"
                )
            sender = Sender(args.base_url, user, password)
            say(f"адрес: {args.base_url}  порция: {args.batch}  full: {full}  повтор: {args.repeat}")
        elif args.dry_run:
            say(f"dry-run: порция {args.batch}, full: {full}; ничего не отправляется")

        totals = Totals()
        for stream in args.only:
            if stream == "catalog":
                batches = catalog_batches(source, args.batch, full)
            elif stream == "prices":
                batches = price_batches(source, args.batch, full)
            elif stream == "stock":
                batches = stock_batches(source, args.batch, full)
            elif stream == "orders":
                batches = order_batches(source, args.batch)
            else:
                if args.images_dir is None:
                    say(
                        f"images   пропущены: не задан --images-dir "
                        f"(в state.json только метаданные {len(state['images'])} картинок)"
                    )
                    continue
                if not args.images_dir.is_dir():
                    say(f"images   пропущены: нет папки {args.images_dir}")
                    totals.failed["images"] = "нет папки"
                    continue
                files, skipped = image_files(args.images_dir, args.limit)
                if skipped:
                    say(f"images   пропущено файлов (имя не <GUID>.jpg|.jpeg|.png): {len(skipped)}")
                batches = image_batches(files)
            run_stream(stream, batches, sender, args.repeat, totals)
    except FatalError as error:
        say(f"ОШИБКА: {error}")
        return 1

    say("")
    say("Итог:" + (" (dry-run, порций к отправке)" if args.dry_run else ""))
    for stream in args.only:
        if stream not in totals.batches:
            continue
        line = f"  {stream:<8} порций {totals.batches[stream]:>5}, записей {totals.records[stream]:>7}"
        if not args.dry_run:
            line += f", запросов {totals.requests[stream]:>5}"
        if stream in totals.failed:
            line += f"  — ПРЕКРАЩЁН: {totals.failed[stream]}"
        say(line)

    ok = not totals.failed
    if args.verify:
        ok = verify(env, state) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
