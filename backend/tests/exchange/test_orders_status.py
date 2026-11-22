"""С1-Т5: поток статусов заказов POST /exchange/1c/orders/status (api_spec.md 3.5).

Данные — по образцу заказов из state.json заглушки приложения (ЛЕР2-000009…000011).
"""

import logging
from collections.abc import Callable
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.exchange.onec import orders_status
from app.models import Order, OrderOnecItem
from tests.exchange.conftest import ExchangeClient

ORDER_A = "b748e6f8-7723-454c-9a3a-12f888cb0527"
ORDER_B = "95203ac4-70b1-4406-a051-7ead3f916f3e"
ORDER_C = "e2c7702a-adcb-4de8-a008-bb12d80517fe"
PRODUCT_1 = "4730ff25-5b92-11ee-b698-a8a159e65459"
PRODUCT_2 = "73fd5575-424b-11ee-b695-a8a159e65459"

CREATED = "2026-11-22T07:57:23+03:00"
T1 = "2026-11-22T10:00:00+03:00"
T2 = "2026-11-22T12:00:00+03:00"
T3 = "2026-11-22T19:04:27+03:00"


def item(product_id: str = PRODUCT_1, quantity: Any = 2, price: Any = 7, cancelled: bool = False) -> dict:
    # Сумму строки 1С присылает округлённой до копеек; сайт хранит её как пришла (numeric без разрядности).
    amount = (Decimal(str(quantity)) * Decimal(str(price))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "product_id": product_id,
        "quantity": quantity,
        "price": price,
        "amount": float(amount),
        "cancelled": cancelled,
    }


def order(
    order_id: str = ORDER_A,
    status: str = "new",
    changed_at: str = T1,
    items: list[dict] | None = None,
    number: str = "ЛЕР2-000009",
    total: Any = None,
) -> dict:
    items = [item()] if items is None else items
    if total is None:
        total = float(sum(Decimal(str(row["amount"])) for row in items if not row["cancelled"]))
    return {
        "order_id": order_id,
        "number": number,
        "status": status,
        "created_at": CREATED,
        "changed_at": changed_at,
        "items": items,
        "total": total,
    }


def post(client: ExchangeClient, *orders: dict) -> Any:
    return client.post_json("/orders/status", {"orders": list(orders)})


def counts(response: Any) -> dict[str, int]:
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    return body["counts"]


def ok_counts(orders: int = 1, items: int = 1, skipped: int = 0, unknown_status: int = 0) -> dict[str, int]:
    return {"orders": orders, "items": items, "skipped": skipped, "unknown_status": unknown_status}


@pytest.fixture
def fetch_order(db_fetch: Callable) -> Callable[[str], Order | None]:
    def fetch(order_id: str) -> Order | None:
        found = db_fetch(Order, Order.order_id == order_id)
        return found[0] if found else None

    return fetch


@pytest.fixture
def fetch_items(db_fetch: Callable) -> Callable[[str], list[tuple]]:
    """Состав заказа как кортежи (line_no, product_id, quantity, price, amount, cancelled)."""

    def fetch(order_id: str) -> list[tuple]:
        rows = db_fetch(OrderOnecItem, OrderOnecItem.order_id == order_id, order_by=OrderOnecItem.line_no)
        return [
            (row.line_no, str(row.product_id), row.quantity, row.price, row.amount, row.cancelled)
            for row in rows
        ]

    return fetch


def assert_error_400(response: Any, field: str | None = None) -> list[dict]:
    assert response.status_code == 400, response.text
    error = response.json()["error"]
    assert error["code"] == "INVALID_FORMAT"
    if field is not None:
        assert field in [detail["field"] for detail in error["details"]], error["details"]
    return error["details"]


# --- Приём и повтор ---


def test_new_order_with_items(
    exchange_client: ExchangeClient, fetch_order: Callable, fetch_items: Callable, last_journal: Callable
) -> None:
    body = order(items=[item(quantity=2, price=7), item(PRODUCT_2, quantity="0.199", price="549.00")])
    response = post(exchange_client, body)
    assert counts(response) == ok_counts(items=2)

    saved = fetch_order(ORDER_A)
    assert saved is not None
    assert saved.number is None  # номер сайта заполнит С4
    assert saved.onec_number == "ЛЕР2-000009"
    assert saved.status == "new"
    assert saved.onec_created_at == datetime.fromisoformat(CREATED)
    assert saved.onec_changed_at == datetime.fromisoformat(T1)
    assert saved.total == Decimal("123.25")
    assert saved.received_at is not None
    assert fetch_items(ORDER_A) == [
        (1, PRODUCT_1, Decimal("2.000"), Decimal("7.00"), Decimal("14.00"), False),
        (2, PRODUCT_2, Decimal("0.199"), Decimal("549.00"), Decimal("109.25"), False),
    ]

    row = last_journal()
    assert (row["stream"], row["status_code"], row["full"], row["error_code"]) == (
        "orders_status",
        200,
        None,
        None,
    )
    assert row["counts"] == ok_counts(items=2)


def test_repeat_batch_idempotent(
    exchange_client: ExchangeClient, fetch_order: Callable, fetch_items: Callable, db_fetch: Callable
) -> None:
    body = order(items=[item(), item(PRODUCT_2, quantity=1, price=79)])
    first = counts(post(exchange_client, body))
    before = fetch_items(ORDER_A)
    second = counts(post(exchange_client, body))
    assert first == second == ok_counts(items=2)
    assert fetch_items(ORDER_A) == before
    assert len(db_fetch(Order)) == 1
    assert len(db_fetch(OrderOnecItem)) == 2


def test_status_change_to_confirmed(
    exchange_client: ExchangeClient, fetch_order: Callable, fetch_items: Callable
) -> None:
    counts(post(exchange_client, order(status="new", changed_at=T1)))
    response = post(exchange_client, order(status="confirmed", changed_at=T2))
    assert counts(response) == ok_counts()
    saved = fetch_order(ORDER_A)
    assert saved.status == "confirmed"
    assert saved.onec_changed_at == datetime.fromisoformat(T2)


def test_earlier_changed_at_ignored(
    exchange_client: ExchangeClient, fetch_order: Callable, fetch_items: Callable, last_journal: Callable
) -> None:
    counts(post(exchange_client, order(status="confirmed", changed_at=T2, items=[item(), item(PRODUCT_2)])))
    header_before = fetch_order(ORDER_A)
    snapshot = (header_before.status, header_before.onec_changed_at, header_before.total)
    items_before = fetch_items(ORDER_A)

    late = order(status="new", changed_at=T1, items=[item(quantity=5)], number="ЛЕР2-СТАРЫЙ")
    response = post(exchange_client, late)
    assert counts(response) == ok_counts(orders=0, items=0, skipped=1)

    saved = fetch_order(ORDER_A)
    assert (saved.status, saved.onec_changed_at, saved.total) == snapshot
    assert saved.onec_number == "ЛЕР2-000009"
    assert fetch_items(ORDER_A) == items_before
    assert last_journal()["counts"] == ok_counts(orders=0, items=0, skipped=1)


def test_equal_changed_at_replaces(
    exchange_client: ExchangeClient, fetch_order: Callable, fetch_items: Callable
) -> None:
    counts(post(exchange_client, order(status="new", changed_at=T2)))
    response = post(exchange_client, order(status="confirmed", changed_at=T2, items=[item(quantity=3)]))
    assert counts(response) == ok_counts()
    assert fetch_order(ORDER_A).status == "confirmed"
    assert fetch_items(ORDER_A) == [
        (1, PRODUCT_1, Decimal("3.000"), Decimal("7.00"), Decimal("21.00"), False)
    ]


def test_mixed_batch_accepts_and_skips(
    exchange_client: ExchangeClient, fetch_order: Callable, fetch_items: Callable
) -> None:
    counts(post(exchange_client, order(ORDER_A, status="confirmed", changed_at=T2)))
    response = post(
        exchange_client,
        order(ORDER_A, status="new", changed_at=T1, items=[item(quantity=9)]),
        order(ORDER_B, status="confirmed", changed_at=T3, number="ЛЕР2-000010", items=[item(quantity=1)]),
    )
    assert counts(response) == ok_counts(orders=1, items=1, skipped=1)
    assert fetch_order(ORDER_A).status == "confirmed"
    assert fetch_items(ORDER_A)[0][2] == Decimal("2.000")
    assert fetch_order(ORDER_B).onec_number == "ЛЕР2-000010"


# --- Состав ---


def test_fewer_items_extra_lines_removed(exchange_client: ExchangeClient, fetch_items: Callable) -> None:
    three = [item(), item(PRODUCT_2, quantity=1, price=79), item(quantity="0.5", price=10)]
    counts(post(exchange_client, order(changed_at=T1, items=three)))
    assert [line[0] for line in fetch_items(ORDER_A)] == [1, 2, 3]

    response = post(exchange_client, order(status="confirmed", changed_at=T2, items=[item(PRODUCT_2)]))
    assert counts(response) == ok_counts(items=1)
    assert fetch_items(ORDER_A) == [
        (1, PRODUCT_2, Decimal("2.000"), Decimal("7.00"), Decimal("14.00"), False)
    ]


def test_empty_items_clears_composition(exchange_client: ExchangeClient, fetch_items: Callable) -> None:
    counts(post(exchange_client, order(changed_at=T1, items=[item(), item(PRODUCT_2)])))
    response = post(exchange_client, order(status="cancelled", changed_at=T2, items=[], total=0))
    assert counts(response) == ok_counts(items=0)
    assert fetch_items(ORDER_A) == []


def test_cancelled_line_kept(
    exchange_client: ExchangeClient, fetch_order: Callable, fetch_items: Callable
) -> None:
    lines = [item(quantity=1, price=7), item(PRODUCT_2, quantity=1, price=79, cancelled=True)]
    response = post(exchange_client, order(status="confirmed", items=lines))
    assert counts(response) == ok_counts(items=2)
    assert fetch_order(ORDER_A).total == Decimal("7.00")  # отменённая строка в total не входит
    assert fetch_items(ORDER_A) == [
        (1, PRODUCT_1, Decimal("1.000"), Decimal("7.00"), Decimal("7.00"), False),
        (2, PRODUCT_2, Decimal("1.000"), Decimal("79.00"), Decimal("79.00"), True),
    ]


def test_cancelled_order(
    exchange_client: ExchangeClient, fetch_order: Callable, fetch_items: Callable
) -> None:
    # Как ЛЕР2-000011 из state.json: пометка удаления -> cancelled с последним составом.
    lines = [item(quantity=1, price=7), item(PRODUCT_2, quantity=1, price=79, cancelled=True)]
    counts(post(exchange_client, order(ORDER_C, status="new", changed_at=T1, items=lines)))
    cancelled = order(
        ORDER_C,
        status="cancelled",
        changed_at="2026-11-22T19:10:34+03:00",
        number="ЛЕР2-000011",
        items=lines,
        total=7,
    )
    assert counts(post(exchange_client, cancelled)) == ok_counts(items=2)
    saved = fetch_order(ORDER_C)
    assert (saved.status, saved.onec_number, saved.total) == ("cancelled", "ЛЕР2-000011", Decimal("7.00"))
    assert [line[5] for line in fetch_items(ORDER_C)] == [False, True]


# --- Статус, номер сайта, повторы ---


def test_unknown_status_saved_and_counted(
    exchange_client: ExchangeClient,
    fetch_order: Callable,
    last_journal: Callable,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=orders_status.logger.name)
    response = post(
        exchange_client,
        order(ORDER_A, status="on_hold"),
        order(ORDER_B, status="completed", number="ЛЕР2-000010"),
    )
    assert counts(response) == ok_counts(orders=2, items=2, unknown_status=1)
    assert fetch_order(ORDER_A).status == "on_hold"
    assert fetch_order(ORDER_B).status == "completed"
    assert last_journal()["counts"]["unknown_status"] == 1
    assert "неизвестный статус" in caplog.text
    assert ORDER_A in caplog.text
    assert "on_hold" in caplog.text


def test_site_number_not_overwritten(
    exchange_client: ExchangeClient, db_session: Session, fetch_order: Callable
) -> None:
    db_session.add(
        Order(
            order_id=ORDER_A,
            number="D-000001",
            onec_number="",
            status="new",
            onec_created_at=datetime.fromisoformat(CREATED),
            onec_changed_at=datetime.fromisoformat(T1),
            total=Decimal("14"),
        )
    )
    db_session.commit()

    response = post(exchange_client, order(status="confirmed", changed_at=T2))
    assert counts(response) == ok_counts()
    saved = fetch_order(ORDER_A)
    assert saved.number == "D-000001"
    assert saved.onec_number == "ЛЕР2-000009"
    assert saved.status == "confirmed"


def test_duplicate_order_id_last_wins(
    exchange_client: ExchangeClient, fetch_order: Callable, fetch_items: Callable
) -> None:
    response = post(
        exchange_client,
        order(status="new", changed_at=T2, items=[item(), item(PRODUCT_2)]),
        order(status="confirmed", changed_at=T1, items=[item(quantity=4)]),
    )
    assert counts(response) == ok_counts()
    saved = fetch_order(ORDER_A)
    assert (saved.status, saved.onec_changed_at) == ("confirmed", datetime.fromisoformat(T1))
    assert fetch_items(ORDER_A) == [
        (1, PRODUCT_1, Decimal("4.000"), Decimal("7.00"), Decimal("28.00"), False)
    ]


def test_order_id_any_string_up_to_36(exchange_client: ExchangeClient, fetch_order: Callable) -> None:
    # Контракт (2.2): order_id — строка до 36 символов, не обязательно GUID.
    response = post(exchange_client, order("test-1c-order"), order("x" * 36))
    assert counts(response) == ok_counts(orders=2, items=2)
    assert fetch_order("test-1c-order") is not None
    assert fetch_order("x" * 36) is not None


@pytest.mark.parametrize("body", [{}, {"orders": []}])
def test_empty_batch(exchange_client: ExchangeClient, last_journal: Callable, body: dict) -> None:
    response = exchange_client.post_json("/orders/status", body)
    assert counts(response) == ok_counts(orders=0, items=0)
    assert last_journal()["status_code"] == 200


# --- Ошибки ---


def test_no_auth_401(exchange_client: ExchangeClient, db_fetch: Callable, last_journal: Callable) -> None:
    response = exchange_client.post_json("/orders/status", {"orders": [order()]}, auth=None)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert db_fetch(Order) == []
    row = last_journal()
    assert (row["stream"], row["status_code"]) == ("orders_status", 401)


def test_invalid_json_400(exchange_client: ExchangeClient, last_journal: Callable) -> None:
    response = exchange_client.post_json("/orders/status", b'{"orders": [')
    assert_error_400(response, "body")
    row = last_journal()
    assert (row["stream"], row["status_code"], row["error_code"]) == ("orders_status", 400, "INVALID_FORMAT")


def test_missing_changed_at_400(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    bad = order(ORDER_B)
    del bad["changed_at"]
    response = post(exchange_client, order(ORDER_A), bad)
    assert_error_400(response, "orders[1].changed_at")
    assert db_fetch(Order) == []


def test_order_id_too_long_400(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    response = post(exchange_client, order("y" * 37))
    assert_error_400(response, "orders[0].order_id")
    assert db_fetch(Order) == []


def test_bad_product_guid_400(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    bad = order(items=[item(), item(product_id="не-guid")])
    response = post(exchange_client, bad)
    assert_error_400(response, "orders[0].items[1].product_id")
    assert db_fetch(Order) == []
    assert db_fetch(OrderOnecItem) == []


def test_bad_changed_at_without_timezone_400(exchange_client: ExchangeClient) -> None:
    response = post(exchange_client, order(changed_at="2026-11-22T10:00:00"))
    assert_error_400(response, "orders[0].changed_at")


def test_failure_mid_batch_writes_nothing(
    exchange_client: ExchangeClient,
    fetch_order: Callable,
    fetch_items: Callable,
    db_fetch: Callable,
    last_journal: Callable,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counts(post(exchange_client, order(ORDER_A, status="new", changed_at=T1)))
    items_before = fetch_items(ORDER_A)

    def broken_replace(db: Session, orders: list) -> int:
        raise RuntimeError("сбой после записи шапок")

    monkeypatch.setattr(orders_status, "_replace_items", broken_replace)
    response = post(
        exchange_client,
        order(ORDER_A, status="confirmed", changed_at=T2),
        order(ORDER_B, status="new", changed_at=T2, number="ЛЕР2-000010"),
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"

    assert fetch_order(ORDER_A).status == "new"
    assert fetch_order(ORDER_B) is None
    assert fetch_items(ORDER_A) == items_before
    assert len(db_fetch(Order)) == 1
    row = last_journal()
    assert (row["stream"], row["status_code"], row["error_code"]) == ("orders_status", 500, "INTERNAL_ERROR")


def test_nul_removed_from_strings_and_counted(
    exchange_client: ExchangeClient, journal_rows: Any, db_fetch: Any
) -> None:
    """К-10: U+0000 в строках убирается, порция принимается (не 400/500), в журнал — nul_removed."""
    response = post(exchange_client, order(order_id="nul-test-1", number="НФ-\u00000001"))
    assert counts(response)["nul_removed"] == 1
    saved = db_fetch(Order, Order.order_id == "nul-test-1")
    assert saved[0].onec_number == "НФ-0001"
    assert journal_rows(1)[0]["counts"]["nul_removed"] == 1
