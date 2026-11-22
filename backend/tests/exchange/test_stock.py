"""С1-Т3: поток остатков POST /exchange/1c/stock (api_spec.md 3.3)."""

import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session

from app.exchange.onec import common
from app.exchange.onec.errors import INVALID_FORMAT
from app.models import CatalogProduct, CatalogStock
from tests.exchange import OTHER_STORE_ID, TEST_STORE_ID
from tests.exchange.conftest import ExchangeClient

MOMENT = datetime(2026, 11, 17, 15, 31, tzinfo=UTC)


def iso(moment: datetime) -> str:
    return moment.isoformat()


def item(
    product_id: uuid.UUID,
    available: Any = 12,
    updated_at: datetime | str = MOMENT,
    store_id: uuid.UUID = TEST_STORE_ID,
) -> dict[str, Any]:
    return {
        "store_id": str(store_id),
        "product_id": str(product_id),
        "available": available,
        "updated_at": updated_at if isinstance(updated_at, str) else iso(updated_at),
    }


def post_stock(client: ExchangeClient, items: list[dict[str, Any]], **extra: Any) -> httpx.Response:
    return client.post_json("/stock", {**extra, "stock": items})


def counts(response: httpx.Response) -> dict[str, int]:
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    return body["counts"]


def assert_error(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    return error


@pytest.fixture
def stock_of(db_fetch: Callable) -> Callable[..., CatalogStock | None]:
    """stock_of(product_id, store_id=TEST_STORE_ID) -> строка catalog_stock или None."""

    def fetch(product_id: uuid.UUID, store_id: uuid.UUID = TEST_STORE_ID) -> CatalogStock | None:
        found = db_fetch(
            CatalogStock, CatalogStock.product_id == product_id, CatalogStock.store_id == store_id
        )
        return found[0] if found else None

    return fetch


# --- Приём и замена ---


def test_insert(exchange_client: ExchangeClient, stock_of: Callable) -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    response = post_stock(exchange_client, [item(first, 12), item(second, "3.5")])
    assert counts(response) == {"stock": 2, "skipped": 0, "other_store": 0}
    row = stock_of(first)
    assert row.available == Decimal("12.000")
    assert row.updated_at == MOMENT
    assert row.received_at is not None
    assert stock_of(second).available == Decimal("3.500")


def test_empty_or_missing_list(exchange_client: ExchangeClient, last_journal: Callable) -> None:
    for body in ({}, {"full": False, "stock": []}):
        response = exchange_client.post_json("/stock", body)
        assert counts(response) == {"stock": 0, "skipped": 0, "other_store": 0}
    assert last_journal()["status_code"] == 200


def test_repeat_batch_idempotent(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    ids = [uuid.uuid4() for _ in range(3)]
    batch = [item(product_id, index) for index, product_id in enumerate(ids)]
    assert counts(post_stock(exchange_client, batch)) == {"stock": 3, "skipped": 0, "other_store": 0}
    # Повтор той же порции: равный updated_at заменяет — ошибок и пропусков нет, данные те же.
    assert counts(post_stock(exchange_client, batch)) == {"stock": 3, "skipped": 0, "other_store": 0}
    rows = db_fetch(CatalogStock, CatalogStock.product_id.in_(ids))
    assert sorted(row.available for row in rows) == [Decimal("0"), Decimal("1"), Decimal("2")]


def test_later_replaces(exchange_client: ExchangeClient, stock_of: Callable) -> None:
    product_id = uuid.uuid4()
    counts(post_stock(exchange_client, [item(product_id, 5)]))
    later = MOMENT + timedelta(minutes=1)
    assert counts(post_stock(exchange_client, [item(product_id, 4, later)])) == {
        "stock": 1,
        "skipped": 0,
        "other_store": 0,
    }
    row = stock_of(product_id)
    assert (row.available, row.updated_at) == (Decimal("4.000"), later)


def test_earlier_ignored_and_skipped(exchange_client: ExchangeClient, stock_of: Callable) -> None:
    late, early, fresh = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    counts(post_stock(exchange_client, [item(late, 5), item(early, 6)]))
    before = MOMENT - timedelta(seconds=1)
    response = post_stock(
        exchange_client, [item(late, 99, before), item(early, 98, before), item(fresh, 1, before)]
    )
    assert counts(response) == {"stock": 1, "skipped": 2, "other_store": 0}
    row = stock_of(late)
    assert (row.available, row.updated_at) == (Decimal("5.000"), MOMENT)
    assert stock_of(early).available == Decimal("6.000")
    assert stock_of(fresh).available == Decimal("1.000")


def test_equal_updated_at_replaces(exchange_client: ExchangeClient, stock_of: Callable) -> None:
    product_id = uuid.uuid4()
    counts(post_stock(exchange_client, [item(product_id, 5)]))
    # Тот же момент в другом смещении — равный, заменяет.
    same_moment = "2026-11-17T18:31:00+03:00"
    response = post_stock(exchange_client, [item(product_id, 7, same_moment)])
    assert counts(response) == {"stock": 1, "skipped": 0, "other_store": 0}
    row = stock_of(product_id)
    assert (row.available, row.updated_at) == (Decimal("7.000"), MOMENT)


def test_duplicate_key_in_batch_last_wins(exchange_client: ExchangeClient, stock_of: Callable) -> None:
    product_id, other = uuid.uuid4(), uuid.uuid4()
    response = post_stock(exchange_client, [item(product_id, 1), item(other, 2), item(product_id, 3)])
    assert counts(response) == {"stock": 2, "skipped": 0, "other_store": 0}
    assert stock_of(product_id).available == Decimal("3.000")
    assert stock_of(other).available == Decimal("2.000")


def test_zero_kept_as_zero(exchange_client: ExchangeClient, stock_of: Callable) -> None:
    product_id = uuid.uuid4()
    counts(post_stock(exchange_client, [item(product_id, 10)]))
    later = MOMENT + timedelta(minutes=1)
    assert counts(post_stock(exchange_client, [item(product_id, 0, later)]))["stock"] == 1
    row = stock_of(product_id)
    assert row is not None
    assert (row.available, row.updated_at) == (Decimal("0.000"), later)


def test_fractional_weight(exchange_client: ExchangeClient, stock_of: Callable) -> None:
    product_id = uuid.uuid4()
    # float 0.199 уходит в JSON числом 0.199 (не строкой) и разбирается в Decimal без потерь.
    response = post_stock(exchange_client, [item(product_id, 0.199, "2026-11-17T15:31:00+03:00")])
    assert counts(response)["stock"] == 1
    assert stock_of(product_id).available == Decimal("0.199")


def test_stock_before_product_card(exchange_client: ExchangeClient, stock_of: Callable, db_fetch) -> None:
    product_id = uuid.uuid4()
    assert db_fetch(CatalogProduct, CatalogProduct.id == product_id) == []
    assert counts(post_stock(exchange_client, [item(product_id, 4)]))["stock"] == 1
    assert stock_of(product_id).available == Decimal("4.000")


def test_other_store_saved_and_counted(exchange_client: ExchangeClient, stock_of: Callable) -> None:
    product_id = uuid.uuid4()
    batch = [item(product_id, 1), item(product_id, 2, store_id=OTHER_STORE_ID)]
    assert counts(post_stock(exchange_client, batch)) == {"stock": 2, "skipped": 0, "other_store": 1}
    assert stock_of(product_id).available == Decimal("1.000")
    assert stock_of(product_id, OTHER_STORE_ID).available == Decimal("2.000")
    # Пропущенная (более ранняя) запись чужого магазина тоже считается в other_store.
    earlier = MOMENT - timedelta(minutes=1)
    response = post_stock(exchange_client, [item(product_id, 9, earlier, store_id=OTHER_STORE_ID)])
    assert counts(response) == {"stock": 0, "skipped": 1, "other_store": 1}


def test_full_does_not_touch_missing(exchange_client: ExchangeClient, stock_of: Callable) -> None:
    kept, sent = uuid.uuid4(), uuid.uuid4()
    counts(post_stock(exchange_client, [item(kept, 8), item(sent, 1)]))
    later = MOMENT + timedelta(hours=1)
    response = post_stock(exchange_client, [item(sent, 2, later)], full=True)
    assert counts(response) == {"stock": 1, "skipped": 0, "other_store": 0}
    row = stock_of(kept)
    assert (row.available, row.updated_at) == (Decimal("8.000"), MOMENT)
    assert stock_of(sent).available == Decimal("2.000")


def test_unknown_fields_ignored(exchange_client: ExchangeClient, stock_of: Callable) -> None:
    product_id = uuid.uuid4()
    body = {"full": False, "extra": 1, "stock": [{**item(product_id, 3), "reserve": 2}]}
    assert counts(exchange_client.post_json("/stock", body))["stock"] == 1
    assert stock_of(product_id).available == Decimal("3.000")


# --- Ошибки ---


def test_no_auth_401(exchange_client: ExchangeClient, stock_of: Callable, last_journal: Callable) -> None:
    product_id = uuid.uuid4()
    response = exchange_client.post_json("/stock", {"stock": [item(product_id)]}, auth=None)
    assert_error(response, 401, "UNAUTHORIZED")
    assert response.headers["www-authenticate"].startswith("Basic")
    assert stock_of(product_id) is None
    row = last_journal()
    assert (row["stream"], row["status_code"]) == ("stock", 401)


def test_invalid_json_400(exchange_client: ExchangeClient, last_journal: Callable) -> None:
    error = assert_error(exchange_client.post_json("/stock", b'{"stock": ['), 400, INVALID_FORMAT)
    assert error["details"][0]["field"] == "body"
    assert last_journal()["error_code"] == INVALID_FORMAT


@pytest.mark.parametrize(
    ("patch", "field"),
    [
        ({"updated_at": None}, "stock[1].updated_at"),
        ({"updated_at": "2026-11-17T15:31:00"}, "stock[1].updated_at"),  # без смещения
        ({"updated_at": "вчера"}, "stock[1].updated_at"),
        ({"product_id": "not-a-guid"}, "stock[1].product_id"),
        ({"store_id": "3f2c8a10-5b7e-11ee-8c99"}, "stock[1].store_id"),
        ({"available": "много"}, "stock[1].available"),
        ({"available": None}, "stock[1].available"),
    ],
)
def test_invalid_record_400_with_details(
    exchange_client: ExchangeClient, stock_of: Callable, patch: dict[str, Any], field: str
) -> None:
    good = uuid.uuid4()
    bad = {**item(uuid.uuid4()), **patch}
    error = assert_error(post_stock(exchange_client, [item(good), bad]), 400, INVALID_FORMAT)
    assert field in [detail["field"] for detail in error["details"]]
    assert stock_of(good) is None  # вся порция отклонена


def test_missing_updated_at_400(exchange_client: ExchangeClient) -> None:
    bad = item(uuid.uuid4())
    del bad["updated_at"]
    error = assert_error(post_stock(exchange_client, [bad]), 400, INVALID_FORMAT)
    assert error["details"][0]["field"] == "stock[0].updated_at"


def test_stock_not_a_list_400(exchange_client: ExchangeClient) -> None:
    error = assert_error(exchange_client.post_json("/stock", {"stock": {}}), 400, INVALID_FORMAT)
    assert error["details"][0]["field"] == "stock"


def test_error_in_middle_nothing_written(
    exchange_client: ExchangeClient, stock_of: Callable, last_journal: Callable, monkeypatch
) -> None:
    # Пакеты по одной строке: первые две пачки уже записаны, на третьей — сбой записи.
    monkeypatch.setattr(common, "MAX_PARAMS_PER_STATEMENT", 4)
    real_insert = common.pg_insert
    calls = 0

    def failing_insert(table: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("сбой записи третьей пачки")
        return real_insert(table)

    monkeypatch.setattr(common, "pg_insert", failing_insert)
    ids = [uuid.uuid4() for _ in range(4)]
    batch = [item(product_id, n) for n, product_id in enumerate(ids, start=1)]
    assert_error(post_stock(exchange_client, batch), 500, "INTERNAL_ERROR")
    assert calls == 3  # сбой именно в середине порции, после записанных пачек
    assert all(stock_of(product_id) is None for product_id in ids)
    row = last_journal()
    assert (row["stream"], row["status_code"], row["counts"]) == ("stock", 500, None)


def test_large_values_stored_as_is(exchange_client: ExchangeClient, stock_of: Callable) -> None:
    """Разрядность не ограничена (К-5): большое и очень дробное число пишется как пришло, не 500."""
    big, fine = uuid.uuid4(), uuid.uuid4()
    response = post_stock(exchange_client, [item(big, 10**12), item(fine, "0.1234567")])
    assert counts(response) == {"stock": 2, "skipped": 0, "other_store": 0}
    assert stock_of(big).available == Decimal(10**12)
    assert str(stock_of(fine).available) == "0.1234567"


def test_full_absent_journal_false(exchange_client: ExchangeClient, last_journal: Callable) -> None:
    counts(post_stock(exchange_client, [item(uuid.uuid4())]))
    assert last_journal()["full"] is False


# --- Журнал ---


@pytest.mark.parametrize("full", [True, False])
def test_journal_row(exchange_client: ExchangeClient, journal_rows: Callable, full: bool) -> None:
    earlier = MOMENT - timedelta(minutes=1)
    product_id = uuid.uuid4()
    counts(post_stock(exchange_client, [item(product_id, 1)]))
    batch = [item(product_id, 2, earlier), item(uuid.uuid4(), 3, store_id=OTHER_STORE_ID)]
    response = post_stock(exchange_client, batch, full=full)
    assert counts(response) == {"stock": 1, "skipped": 1, "other_store": 1}
    row = journal_rows()[0]
    assert row["stream"] == "stock"
    assert row["method"] == "POST"
    assert row["status_code"] == 200
    assert row["full"] is full
    assert row["counts"] == {"stock": 1, "skipped": 1, "other_store": 1}
    assert row["error_code"] is None
    assert row["body_bytes"] > 0


# --- Порция 500 записей ---


def test_batch_500_timing(exchange_client: ExchangeClient, db_session: Session, db_fetch: Callable) -> None:
    ids = [uuid.uuid4() for _ in range(500)]
    batch = [item(product_id, f"{index}.125") for index, product_id in enumerate(ids)]
    started = time.perf_counter()
    response = post_stock(exchange_client, batch, full=True)
    first = time.perf_counter() - started
    assert counts(response) == {"stock": 500, "skipped": 0, "other_store": 0}
    started = time.perf_counter()
    assert counts(post_stock(exchange_client, batch, full=True))["stock"] == 500
    repeat = time.perf_counter() - started
    print(f"\nПорция 500 остатков: вставка {first * 1000:.0f} мс, повтор {repeat * 1000:.0f} мс")
    assert len(db_fetch(CatalogStock, CatalogStock.product_id.in_(ids))) == 500
    assert first < 5 and repeat < 5
