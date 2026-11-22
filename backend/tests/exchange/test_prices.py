"""С1-Т2: поток цен POST /exchange/1c/prices (api_spec.md 3.2)."""

import time
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest

from app.exchange.onec import prices as prices_module
from app.models import CatalogPrice, CatalogProduct
from tests.exchange import OTHER_STORE_ID, TEST_STORE_ID
from tests.exchange.conftest import ExchangeClient

OWN = str(TEST_STORE_ID)
OTHER = str(OTHER_STORE_ID)


def new_id() -> str:
    return str(uuid.uuid4())


def price(product_id: str | None = None, value: Any = 89.90, store_id: str = OWN) -> dict[str, Any]:
    return {"store_id": store_id, "product_id": product_id or new_id(), "price": value}


def portion(*items: dict[str, Any], full: bool = False) -> dict[str, Any]:
    return {"full": full, "prices": list(items)}


def assert_ok(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    body = response.json()
    assert body["ok"] is True
    return body["counts"]


def assert_error(response: Any, status: int, code: str = "INVALID_FORMAT") -> dict[str, Any]:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    assert isinstance(error["details"], list)
    return error


def fields_of(error: dict[str, Any]) -> list[str]:
    return [detail["field"] for detail in error["details"]]


def stored(db_fetch: Callable, product_id: str, store_id: str = OWN) -> list[CatalogPrice]:
    return db_fetch(
        CatalogPrice,
        CatalogPrice.product_id == uuid.UUID(product_id),
        CatalogPrice.store_id == uuid.UUID(store_id),
    )


def stored_price(db_fetch: Callable, product_id: str, store_id: str = OWN) -> Decimal:
    found = stored(db_fetch, product_id, store_id)
    assert len(found) == 1
    return found[0].price


# --- Запись ---


def test_insert(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    first, second = price(value=89.90), price(value=150)
    counts = assert_ok(exchange_client.post_json("/prices", portion(first, second)))
    assert counts == {"prices": 2, "other_store": 0}
    assert stored_price(db_fetch, first["product_id"]) == Decimal("89.90")
    assert stored_price(db_fetch, second["product_id"]) == Decimal("150.00")
    assert stored(db_fetch, first["product_id"])[0].received_at is not None


def test_repeat_portion_is_idempotent(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    body = portion(price(), price(), price(store_id=OTHER))
    first = assert_ok(exchange_client.post_json("/prices", body))
    second = assert_ok(exchange_client.post_json("/prices", body))
    assert first == second == {"prices": 3, "other_store": 1}
    ids = [uuid.UUID(item["product_id"]) for item in body["prices"]]
    assert len(db_fetch(CatalogPrice, CatalogPrice.product_id.in_(ids))) == 3


def test_change_replaces_price(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    item = price(value=100)
    assert_ok(exchange_client.post_json("/prices", portion(item)))
    first_received = stored(db_fetch, item["product_id"])[0].received_at
    assert_ok(exchange_client.post_json("/prices", portion(item | {"price": 95.5})))
    assert stored_price(db_fetch, item["product_id"]) == Decimal("95.50")
    assert stored(db_fetch, item["product_id"])[0].received_at >= first_received


def test_zero_price_saved(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    item = price(value=100)
    assert_ok(exchange_client.post_json("/prices", portion(item)))
    counts = assert_ok(exchange_client.post_json("/prices", portion(item | {"price": 0})))
    assert counts == {"prices": 1, "other_store": 0}
    assert stored_price(db_fetch, item["product_id"]) == Decimal("0.00")


def test_duplicate_key_in_portion_keeps_last(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    product_id = new_id()
    body = portion(
        price(product_id, 10),
        price(product_id, 20, store_id=OTHER),
        price(product_id, 30),
        price(product_id, 40, store_id=OTHER),
    )
    counts = assert_ok(exchange_client.post_json("/prices", body))
    assert counts == {"prices": 2, "other_store": 1}
    assert stored_price(db_fetch, product_id) == Decimal("30.00")
    assert stored_price(db_fetch, product_id, OTHER) == Decimal("40.00")


def test_price_before_product(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    item = price()
    assert_ok(exchange_client.post_json("/prices", portion(item)))
    assert db_fetch(CatalogProduct, CatalogProduct.id == uuid.UUID(item["product_id"])) == []
    assert stored_price(db_fetch, item["product_id"]) == Decimal("89.90")


def test_other_store_saved_and_counted(
    exchange_client: ExchangeClient, db_fetch: Callable, last_journal: Callable
) -> None:
    product_id = new_id()
    body = portion(price(product_id, 10), price(product_id, 12, store_id=OTHER), price(store_id=new_id()))
    counts = assert_ok(exchange_client.post_json("/prices", body))
    assert counts == {"prices": 3, "other_store": 2}
    assert stored_price(db_fetch, product_id) == Decimal("10.00")
    assert stored_price(db_fetch, product_id, OTHER) == Decimal("12.00")
    assert last_journal()["counts"] == counts


def test_other_store_when_own_store_not_set(
    exchange_client: ExchangeClient, exchange_settings: Any, monkeypatch
) -> None:
    """ONEC_STORE_ID не задан — все записи считаются чужими, но сохраняются."""
    monkeypatch.setattr(exchange_settings, "onec_store_id", "")
    counts = assert_ok(exchange_client.post_json("/prices", portion(price(), price())))
    assert counts == {"prices": 2, "other_store": 2}


def test_full_does_not_delete_absent(
    exchange_client: ExchangeClient, db_fetch: Callable, last_journal: Callable
) -> None:
    old = price()
    assert_ok(exchange_client.post_json("/prices", portion(old)))
    counts = assert_ok(exchange_client.post_json("/prices", portion(price(), full=True)))
    assert counts == {"prices": 1, "other_store": 0}
    assert stored_price(db_fetch, old["product_id"]) == Decimal("89.90")
    assert last_journal()["full"] is True


def test_missing_list_and_unknown_fields(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    assert assert_ok(exchange_client.post_json("/prices", {})) == {"prices": 0, "other_store": 0}
    item = price() | {"currency": "RUB"}
    assert_ok(exchange_client.post_json("/prices", {"prices": [item], "version": "0.9"}))
    assert stored_price(db_fetch, item["product_id"]) == Decimal("89.90")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (89.9, "89.90"),
        ("89.90", "89.90"),
        (1, "1.00"),
        (0.005, "0.005"),  # без округления: округляет витрина
        (9999999999.99, "9999999999.99"),
        (1e10, "10000000000"),  # разрядность не ограничена — не 500 и не 400 (К-5)
        ("123456789012345678901234567890.123456789", "123456789012345678901234567890.123456789"),
        (-5, "-5.00"),  # своих пределов нет (К-5)
    ],
)
def test_price_values(exchange_client: ExchangeClient, db_fetch: Callable, value: Any, expected: str) -> None:
    item = price(value=value)
    assert_ok(exchange_client.post_json("/prices", portion(item)))
    saved = stored_price(db_fetch, item["product_id"])
    assert saved == Decimal(expected)
    assert saved.as_tuple().exponent == Decimal(str(value)).as_tuple().exponent  # знаки — как пришли


def test_huge_number_literal_stored_as_is(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    """Число в JSON (не строка) с огромной разрядностью разбирается в Decimal и пишется без потерь."""
    product_id = new_id()
    raw = f'{{"prices": [{{"store_id": "{OWN}", "product_id": "{product_id}", "price": 1e40}}]}}'
    assert_ok(exchange_client.post_json("/prices", raw))
    assert stored_price(db_fetch, product_id) == Decimal("1e40")


def test_journal_row(exchange_client: ExchangeClient, last_journal: Callable) -> None:
    assert_ok(exchange_client.post_json("/prices", portion(price(), price(store_id=OTHER), full=False)))
    row = last_journal()
    assert (row["stream"], row["method"], row["status_code"], row["full"]) == ("prices", "POST", 200, False)
    assert row["counts"] == {"prices": 2, "other_store": 1}
    assert row["error_code"] is None


# --- Ошибки ---


def test_no_auth_401(exchange_client: ExchangeClient, db_fetch: Callable, last_journal: Callable) -> None:
    item = price()
    response = exchange_client.post_json("/prices", portion(item), auth=None)
    assert_error(response, 401, "UNAUTHORIZED")
    assert response.headers["www-authenticate"].startswith("Basic")
    assert stored(db_fetch, item["product_id"]) == []
    assert (last_journal()["stream"], last_journal()["status_code"]) == ("prices", 401)


@pytest.mark.parametrize("raw", [b"{", b"", b"\xff\xfe", b'{"prices": [NaN]}'])
def test_invalid_json_400(exchange_client: ExchangeClient, last_journal: Callable, raw: bytes) -> None:
    error = assert_error(exchange_client.post_json("/prices", raw), 400)
    assert fields_of(error) == ["body"]
    assert (last_journal()["stream"], last_journal()["error_code"]) == ("prices", "INVALID_FORMAT")


@pytest.mark.parametrize(
    ("item", "field"),
    [
        ({"store_id": OWN, "price": 1}, "prices[1].product_id"),
        ({"product_id": new_id(), "price": 1}, "prices[1].store_id"),
        ({"store_id": OWN, "product_id": new_id()}, "prices[1].price"),
        (price(value=None), "prices[1].price"),
        (price() | {"product_id": None}, "prices[1].product_id"),
    ],
)
def test_missing_required_field_400(
    exchange_client: ExchangeClient, db_fetch: Callable, item: dict[str, Any], field: str
) -> None:
    good = price()
    error = assert_error(exchange_client.post_json("/prices", portion(good, item)), 400)
    assert fields_of(error) == [field]
    assert stored(db_fetch, good["product_id"]) == []


@pytest.mark.parametrize(
    ("item", "field"),
    [
        (price(product_id="не-guid"), "prices[0].product_id"),
        (price(store_id="123"), "prices[0].store_id"),
        (price(value="дорого"), "prices[0].price"),
        (price(value=True), "prices[0].price"),
        (price(value="Infinity"), "prices[0].price"),
        (price(value="-Infinity"), "prices[0].price"),
        (price(value="NaN"), "prices[0].price"),
        # Вне пределов самого типа numeric PostgreSQL — 400 (иначе 500 и бесконечный повтор).
        (price(value="1E+131072"), "prices[0].price"),
        (price(value="1E-16384"), "prices[0].price"),
    ],
)
def test_invalid_values_400(exchange_client: ExchangeClient, item: dict[str, Any], field: str) -> None:
    error = assert_error(exchange_client.post_json("/prices", portion(item)), 400)
    assert field in fields_of(error)


def test_error_in_middle_of_portion_writes_nothing(
    exchange_client: ExchangeClient, db_fetch: Callable, last_journal: Callable
) -> None:
    items = [price(value=i) for i in range(500)]
    items[250]["store_id"] = "битый"
    error = assert_error(exchange_client.post_json("/prices", portion(*items)), 400)
    assert fields_of(error) == ["prices[250].store_id"]
    ids = [uuid.UUID(item["product_id"]) for item in items]
    assert db_fetch(CatalogPrice, CatalogPrice.product_id.in_(ids)) == []
    assert last_journal()["counts"] is None


def test_db_failure_after_partial_write_rolls_back(
    exchange_client: ExchangeClient, db_fetch: Callable, last_journal: Callable, monkeypatch
) -> None:
    """Пакет записан, затем сбой до фиксации — порция откатывается целиком."""
    existing = price(value=10)
    assert_ok(exchange_client.post_json("/prices", portion(existing)))
    real_upsert = prices_module.upsert

    def failing_upsert(session, model, rows, **kwargs):  # noqa: ANN001, ANN202
        real_upsert(session, model, rows, **kwargs)
        raise RuntimeError("сбой после записи")

    monkeypatch.setattr(prices_module, "upsert", failing_upsert)
    new = price()
    response = exchange_client.post_json("/prices", portion(new, existing | {"price": 20}))
    assert_error(response, 500, "INTERNAL_ERROR")
    assert stored(db_fetch, new["product_id"]) == []
    assert stored_price(db_fetch, existing["product_id"]) == Decimal("10.00")
    assert (last_journal()["status_code"], last_journal()["counts"]) == (500, None)


# --- Крупная порция ---


def test_large_portion_500_prices(
    exchange_client: ExchangeClient, db_fetch: Callable, last_journal: Callable
) -> None:
    items = [price(value=f"{i}.{i % 100:02d}", store_id=OTHER if i % 50 == 0 else OWN) for i in range(500)]
    started = time.perf_counter()
    counts = assert_ok(exchange_client.post_json("/prices", portion(*items, full=True)))
    elapsed = time.perf_counter() - started
    assert counts == {"prices": 500, "other_store": 10}
    ids = [uuid.UUID(item["product_id"]) for item in items]
    assert len(db_fetch(CatalogPrice, CatalogPrice.product_id.in_(ids))) == 500
    assert stored_price(db_fetch, items[123]["product_id"]) == Decimal("123.23")
    assert assert_ok(exchange_client.post_json("/prices", portion(*items, full=True))) == counts
    print(
        f"\nprices 500: {elapsed * 1000:.0f} мс (клиент), {last_journal()['duration_ms']} мс (журнал, повтор)"
    )
    assert elapsed < 5  # ориентир — < 1 с; запас на медленную машину
