"""С1-Т2: поток каталога POST /exchange/1c/catalog (api_spec.md 3.1)."""

import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest

from app.exchange.onec import catalog as catalog_module
from app.models import CatalogGroup, CatalogProduct, CatalogUnit
from tests.exchange.conftest import ExchangeClient

# --- Построители записей порции ---


def new_id() -> str:
    return str(uuid.uuid4())


def group(group_id: str | None = None, **fields: Any) -> dict[str, Any]:
    return {
        "id": group_id or new_id(),
        "parent_id": None,
        "name": "Хлеб",
        "sort": 0,
        "deleted": False,
    } | fields


def unit(unit_id: str | None = None, **fields: Any) -> dict[str, Any]:
    return {"id": unit_id or new_id(), "name": "кг", "code": "166"} | fields


def product(product_id: str | None = None, **fields: Any) -> dict[str, Any]:
    return {
        "id": product_id or new_id(),
        "group_id": None,
        "name": "Батон нарезной",
        "article": "12345",
        "unit_id": new_id(),
        "weighted": False,
        "description": "Описание",
        "deleted": False,
    } | fields


def portion(*, full: bool = False, groups=(), units=(), products=()) -> dict[str, Any]:
    return {"full": full, "groups": list(groups), "units": list(units), "products": list(products)}


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


def as_dict(obj: Any, *names: str) -> dict[str, Any]:
    return {name: getattr(obj, name) for name in names}


PRODUCT_FIELDS = ("group_id", "name", "article", "unit_id", "weighted", "description", "deleted")


def fetch_product(db_fetch: Callable, product_id: str) -> CatalogProduct:
    found = db_fetch(CatalogProduct, CatalogProduct.id == uuid.UUID(product_id))
    assert len(found) == 1
    return found[0]


# --- Запись ---


def test_insert_groups_units_products(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    parent = group(name="Продукты", sort=2)
    child = group(parent_id=parent["id"], name="Хлеб", sort=0)
    kg = unit(name="кг", code="166")
    item = product(group_id=child["id"], unit_id=kg["id"], weighted=True)

    counts = assert_ok(
        exchange_client.post_json("/catalog", portion(groups=[parent, child], units=[kg], products=[item]))
    )
    assert counts == {"groups": 2, "units": 1, "products": 1, "deleted": 0}

    [saved_child] = db_fetch(CatalogGroup, CatalogGroup.id == uuid.UUID(child["id"]))
    assert as_dict(saved_child, "parent_id", "name", "sort", "deleted") == {
        "parent_id": uuid.UUID(parent["id"]),
        "name": "Хлеб",
        "sort": 0,
        "deleted": False,
    }
    [saved_parent] = db_fetch(CatalogGroup, CatalogGroup.id == uuid.UUID(parent["id"]))
    assert (saved_parent.parent_id, saved_parent.sort) == (None, 2)
    [saved_unit] = db_fetch(CatalogUnit, CatalogUnit.id == uuid.UUID(kg["id"]))
    assert (saved_unit.name, saved_unit.code) == ("кг", "166")
    saved = fetch_product(db_fetch, item["id"])
    assert as_dict(saved, *PRODUCT_FIELDS) == {
        "group_id": uuid.UUID(child["id"]),
        "name": "Батон нарезной",
        "article": "12345",
        "unit_id": uuid.UUID(kg["id"]),
        "weighted": True,
        "description": "Описание",
        "deleted": False,
    }
    assert saved.received_at is not None


def test_repeat_portion_is_idempotent(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    body = portion(groups=[group()], units=[unit()], products=[product(), product()])
    first = assert_ok(exchange_client.post_json("/catalog", body))
    second = assert_ok(exchange_client.post_json("/catalog", body))
    assert first == second == {"groups": 1, "units": 1, "products": 2, "deleted": 0}
    ids = [uuid.UUID(p["id"]) for p in body["products"]]
    assert len(db_fetch(CatalogProduct, CatalogProduct.id.in_(ids))) == 2
    assert len(db_fetch(CatalogGroup, CatalogGroup.id == uuid.UUID(body["groups"][0]["id"]))) == 1
    assert len(db_fetch(CatalogUnit, CatalogUnit.id == uuid.UUID(body["units"][0]["id"]))) == 1


def test_product_replaced_entirely(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    item = product(group_id=new_id(), article="A-1", description="Было")
    assert_ok(exchange_client.post_json("/catalog", portion(products=[item])))
    first_received = fetch_product(db_fetch, item["id"]).received_at

    changed = product(
        item["id"],
        group_id=None,
        name="Новое имя",
        article=None,
        unit_id=new_id(),
        weighted=True,
        description=None,
        deleted=True,
    )
    counts = assert_ok(exchange_client.post_json("/catalog", portion(products=[changed])))
    assert counts == {"groups": 0, "units": 0, "products": 1, "deleted": 1}
    saved = fetch_product(db_fetch, item["id"])
    assert as_dict(saved, *PRODUCT_FIELDS) == {
        "group_id": None,
        "name": "Новое имя",
        "article": None,
        "unit_id": uuid.UUID(changed["unit_id"]),
        "weighted": True,
        "description": None,
        "deleted": True,
    }
    assert saved.received_at >= first_received

    # Снятие пометки удаления — тоже замена целиком.
    restored = changed | {"deleted": False, "description": "", "article": ""}
    assert_ok(exchange_client.post_json("/catalog", portion(products=[restored])))
    saved = fetch_product(db_fetch, item["id"])
    assert (saved.deleted, saved.description, saved.article) == (False, "", "")


def test_group_and_unit_replaced_entirely(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    old_group = group(parent_id=new_id(), name="Было", sort=3)
    old_unit = unit(name="шт", code="796")
    assert_ok(exchange_client.post_json("/catalog", portion(groups=[old_group], units=[old_unit])))

    # Группа вышла из отбора (0.9): приходит с deleted: true и sort 0.
    new_group = group(old_group["id"], parent_id=None, name="Стало", sort=0, deleted=True)
    new_unit = unit(old_unit["id"], name="упак", code="778")
    counts = assert_ok(exchange_client.post_json("/catalog", portion(groups=[new_group], units=[new_unit])))
    assert counts == {"groups": 1, "units": 1, "products": 0, "deleted": 1}
    [saved_group] = db_fetch(CatalogGroup, CatalogGroup.id == uuid.UUID(old_group["id"]))
    assert as_dict(saved_group, "parent_id", "name", "sort", "deleted") == {
        "parent_id": None,
        "name": "Стало",
        "sort": 0,
        "deleted": True,
    }
    [saved_unit] = db_fetch(CatalogUnit, CatalogUnit.id == uuid.UUID(old_unit["id"]))
    assert (saved_unit.name, saved_unit.code) == ("упак", "778")

    assert_ok(
        exchange_client.post_json("/catalog", portion(groups=[new_group | {"deleted": False, "sort": 1}]))
    )
    [saved_group] = db_fetch(CatalogGroup, CatalogGroup.id == uuid.UUID(old_group["id"]))
    assert (saved_group.deleted, saved_group.sort) == (False, 1)


def test_duplicate_id_in_portion_keeps_last(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    product_id, group_id, unit_id = new_id(), new_id(), new_id()
    body = portion(
        groups=[group(group_id, name="Первая", deleted=True), group(group_id, name="Последняя")],
        units=[unit(unit_id, code="1"), unit(unit_id, code="2")],
        products=[product(product_id, name="Первый", deleted=True), product(product_id, name="Последний")],
    )
    counts = assert_ok(exchange_client.post_json("/catalog", body))
    assert counts == {"groups": 1, "units": 1, "products": 1, "deleted": 0}
    saved = fetch_product(db_fetch, product_id)
    assert (saved.name, saved.deleted) == ("Последний", False)
    [saved_group] = db_fetch(CatalogGroup, CatalogGroup.id == uuid.UUID(group_id))
    assert (saved_group.name, saved_group.deleted) == ("Последняя", False)
    [saved_unit] = db_fetch(CatalogUnit, CatalogUnit.id == uuid.UUID(unit_id))
    assert saved_unit.code == "2"


def test_product_before_group_and_unit(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    group_id, unit_id = new_id(), new_id()
    item = product(group_id=group_id, unit_id=unit_id)
    assert_ok(exchange_client.post_json("/catalog", portion(products=[item])))
    assert fetch_product(db_fetch, item["id"]).group_id == uuid.UUID(group_id)
    # Группа — раньше родителя.
    child = group(parent_id=new_id())
    assert_ok(exchange_client.post_json("/catalog", portion(groups=[child])))
    # Карточки группы и единицы приходят позже — товар не меняется.
    assert_ok(exchange_client.post_json("/catalog", portion(groups=[group(group_id)], units=[unit(unit_id)])))
    assert as_dict(fetch_product(db_fetch, item["id"]), *PRODUCT_FIELDS) == {
        "group_id": uuid.UUID(group_id),
        "name": item["name"],
        "article": item["article"],
        "unit_id": uuid.UUID(unit_id),
        "weighted": False,
        "description": item["description"],
        "deleted": False,
    }
    assert len(db_fetch(CatalogGroup, CatalogGroup.id == uuid.UUID(child["id"]))) == 1


def test_full_does_not_delete_absent(
    exchange_client: ExchangeClient, db_fetch: Callable, last_journal: Callable
) -> None:
    old_group, old_unit, old_product = group(), unit(), product()
    assert_ok(
        exchange_client.post_json(
            "/catalog", portion(groups=[old_group], units=[old_unit], products=[old_product])
        )
    )
    counts = assert_ok(exchange_client.post_json("/catalog", portion(full=True, products=[product()])))
    assert counts == {"groups": 0, "units": 0, "products": 1, "deleted": 0}
    assert fetch_product(db_fetch, old_product["id"]).deleted is False
    assert len(db_fetch(CatalogGroup, CatalogGroup.id == uuid.UUID(old_group["id"]))) == 1
    assert len(db_fetch(CatalogUnit, CatalogUnit.id == uuid.UUID(old_unit["id"]))) == 1
    assert last_journal()["full"] is True


def test_journal_row(exchange_client: ExchangeClient, last_journal: Callable) -> None:
    body = portion(full=True, groups=[group(deleted=True)], units=[unit()], products=[product(), product()])
    assert_ok(exchange_client.post_json("/catalog", body))
    row = last_journal()
    assert (row["stream"], row["method"], row["status_code"], row["full"]) == ("catalog", "POST", 200, True)
    assert row["counts"] == {"groups": 1, "units": 1, "products": 2, "deleted": 1}
    assert row["error_code"] is None
    assert row["body_bytes"] > 0


# --- Необязательные поля и приведение null ---


def test_missing_lists_and_full_default(exchange_client: ExchangeClient, last_journal: Callable) -> None:
    counts = assert_ok(exchange_client.post_json("/catalog", {}))
    assert counts == {"groups": 0, "units": 0, "products": 0, "deleted": 0}
    assert last_journal()["full"] is False  # full не передан — в журнале false (значение по умолчанию)

    counts = assert_ok(exchange_client.post_json("/catalog", {"units": [unit()]}))
    assert counts == {"groups": 0, "units": 1, "products": 0, "deleted": 0}


def test_nulls_and_optional_fields(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    bare_group = {"id": new_id(), "name": None}  # parent_id и deleted отсутствуют
    bare_unit = {"id": new_id(), "name": None, "code": None}
    bare_product = {"id": new_id(), "name": None, "unit_id": new_id(), "weighted": False}
    body = {"groups": [bare_group], "units": [bare_unit], "products": [bare_product], "extra": 1}
    counts = assert_ok(exchange_client.post_json("/catalog", body))
    assert counts == {"groups": 1, "units": 1, "products": 1, "deleted": 0}

    [saved_group] = db_fetch(CatalogGroup, CatalogGroup.id == uuid.UUID(bare_group["id"]))
    assert as_dict(saved_group, "parent_id", "name", "sort", "deleted") == {
        "parent_id": None,
        "name": "",
        "sort": 0,
        "deleted": False,
    }
    [saved_unit] = db_fetch(CatalogUnit, CatalogUnit.id == uuid.UUID(bare_unit["id"]))
    assert (saved_unit.name, saved_unit.code) == ("", "")
    saved = fetch_product(db_fetch, bare_product["id"])
    assert as_dict(saved, "group_id", "name", "article", "description", "deleted") == {
        "group_id": None,
        "name": "",
        "article": None,
        "description": None,
        "deleted": False,
    }


def test_product_without_unit(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    """Позиция-услуга в 1С: unit_id null или отсутствует -> null (поток не останавливается)."""
    service = product(unit_id=None, deleted=True)
    no_unit = {k: v for k, v in product().items() if k != "unit_id"}
    counts = assert_ok(exchange_client.post_json("/catalog", portion(products=[service, no_unit])))
    assert counts == {"groups": 0, "units": 0, "products": 2, "deleted": 1}
    assert fetch_product(db_fetch, service["id"]).unit_id is None
    assert fetch_product(db_fetch, service["id"]).deleted is True
    assert fetch_product(db_fetch, no_unit["id"]).unit_id is None
    # Повтор с единицей заменяет null.
    with_unit = service | {"unit_id": new_id()}
    assert_ok(exchange_client.post_json("/catalog", portion(products=[with_unit])))
    assert fetch_product(db_fetch, service["id"]).unit_id == uuid.UUID(with_unit["unit_id"])


def test_group_sort(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    """0.9: sort сохраняется; отсутствует или null -> 0; повтор без sort заменяет его на 0."""
    with_sort, null_sort = group(sort=7), group(sort=None)
    no_sort = {k: v for k, v in group().items() if k != "sort"}
    assert_ok(exchange_client.post_json("/catalog", portion(groups=[with_sort, null_sort, no_sort])))

    def sort_of(item: dict[str, Any]) -> int:
        [saved] = db_fetch(CatalogGroup, CatalogGroup.id == uuid.UUID(item["id"]))
        return saved.sort

    assert (sort_of(with_sort), sort_of(null_sort), sort_of(no_sort)) == (7, 0, 0)
    # Запись заменяется целиком: та же группа без sort -> 0.
    without = {k: v for k, v in with_sort.items() if k != "sort"}
    assert_ok(exchange_client.post_json("/catalog", portion(groups=[without])))
    assert sort_of(with_sort) == 0


@pytest.mark.parametrize("value", ["первый", 1.5, 2**31, [1]])
def test_group_sort_wrong_value_400(exchange_client: ExchangeClient, value: Any) -> None:
    error = assert_error(
        exchange_client.post_json("/catalog", portion(groups=[group(), group(sort=value)])), 400
    )
    assert fields_of(error) == ["groups[1].sort"]


def test_unknown_fields_ignored(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    item = product(price=10, images=["x"])
    body = portion(products=[item]) | {"version": "0.8"}
    assert_ok(exchange_client.post_json("/catalog", body))
    assert fetch_product(db_fetch, item["id"]).name == item["name"]


def test_nul_character_removed(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    item = product(name="Ба\u0000тон", description="\u0000", article="1\u00002")
    assert_ok(exchange_client.post_json("/catalog", portion(products=[item])))
    saved = fetch_product(db_fetch, item["id"])
    assert (saved.name, saved.description, saved.article) == ("Батон", "", "12")


def test_long_strings_accepted(exchange_client: ExchangeClient, db_fetch: Callable) -> None:
    """К-5: своих пределов длины нет."""
    item = product(name="Я" * 5000, description="д" * 100_000, article="9" * 300)
    assert_ok(exchange_client.post_json("/catalog", portion(products=[item])))
    assert len(fetch_product(db_fetch, item["id"]).description) == 100_000


# --- Ошибки ---


def test_no_auth_401(exchange_client: ExchangeClient, db_fetch: Callable, last_journal: Callable) -> None:
    item = product()
    response = exchange_client.post_json("/catalog", portion(products=[item]), auth=None)
    assert_error(response, 401, "UNAUTHORIZED")
    assert response.headers["www-authenticate"].startswith("Basic")
    assert db_fetch(CatalogProduct, CatalogProduct.id == uuid.UUID(item["id"])) == []
    assert (last_journal()["stream"], last_journal()["status_code"]) == ("catalog", 401)


@pytest.mark.parametrize("raw", [b"{", b"not json", b"[1, 2", b'{"groups": [}'])
def test_invalid_json_400(exchange_client: ExchangeClient, last_journal: Callable, raw: bytes) -> None:
    error = assert_error(exchange_client.post_json("/catalog", raw), 400)
    assert fields_of(error) == ["body"]
    assert (last_journal()["status_code"], last_journal()["error_code"]) == (400, "INVALID_FORMAT")


@pytest.mark.parametrize(
    ("body", "field"),
    [
        (portion(groups=[{"name": "Без id"}]), "groups[0].id"),
        (portion(units=[unit(), {"name": "шт", "code": "796"}]), "units[1].id"),
        (
            portion(products=[product(), product(), {k: v for k, v in product().items() if k != "id"}]),
            "products[2].id",
        ),
        (portion(products=[product(id=None)]), "products[0].id"),
        (portion(products=[{k: v for k, v in product().items() if k != "name"}]), "products[0].name"),
        (portion(units=[{"id": new_id(), "name": "шт"}]), "units[0].code"),
        (portion(products=[product(weighted=None)]), "products[0].weighted"),
    ],
)
def test_missing_required_field_400(
    exchange_client: ExchangeClient, db_fetch: Callable, body: dict[str, Any], field: str
) -> None:
    error = assert_error(exchange_client.post_json("/catalog", body), 400)
    assert field in fields_of(error)
    ids = [uuid.UUID(p["id"]) for p in body["products"] if p.get("id")]
    assert db_fetch(CatalogProduct, CatalogProduct.id.in_(ids)) == []


@pytest.mark.parametrize(
    ("body", "field"),
    [
        (portion(groups=[group("не-guid")]), "groups[0].id"),
        (portion(groups=[group(parent_id="123")]), "groups[0].parent_id"),
        (portion(units=[unit("3f2c8a10-5b7e-11ee-8c99-0242ac12000")]), "units[0].id"),
        (portion(products=[product(group_id="zzzz")]), "products[0].group_id"),
        (portion(products=[product(unit_id="")]), "products[0].unit_id"),
        (portion(products=[product(unit_id="не-guid")]), "products[0].unit_id"),
    ],
)
def test_invalid_guid_400(exchange_client: ExchangeClient, body: dict[str, Any], field: str) -> None:
    error = assert_error(exchange_client.post_json("/catalog", body), 400)
    assert field in fields_of(error)


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"full": "да"}, "full"),
        ({"products": {}}, "products"),
        (portion(products=[product(name=123)]), "products[0].name"),
        (portion(groups=[group(deleted="нет")]), "groups[0].deleted"),
    ],
)
def test_wrong_types_400(exchange_client: ExchangeClient, body: dict[str, Any], field: str) -> None:
    error = assert_error(exchange_client.post_json("/catalog", body), 400)
    assert field in fields_of(error)


def test_error_in_middle_of_portion_writes_nothing(
    exchange_client: ExchangeClient, db_fetch: Callable, last_journal: Callable
) -> None:
    groups = [group() for _ in range(3)]
    products = [product() for _ in range(500)]
    products[250]["unit_id"] = "битый"
    response = exchange_client.post_json("/catalog", portion(groups=groups, products=products))
    error = assert_error(response, 400)
    assert fields_of(error) == ["products[250].unit_id"]
    assert db_fetch(CatalogProduct, CatalogProduct.id.in_([uuid.UUID(p["id"]) for p in products])) == []
    assert db_fetch(CatalogGroup, CatalogGroup.id.in_([uuid.UUID(g["id"]) for g in groups])) == []
    assert last_journal()["counts"] is None


def test_db_failure_after_partial_write_rolls_back(
    exchange_client: ExchangeClient, db_fetch: Callable, last_journal: Callable, monkeypatch
) -> None:
    """Группы и единицы уже записаны, запись товаров падает — порция откатывается целиком."""
    real_upsert = catalog_module.upsert

    def failing_upsert(session, model, rows, **kwargs):  # noqa: ANN001, ANN202
        if model is CatalogProduct:
            raise RuntimeError("сбой записи товаров")
        return real_upsert(session, model, rows, **kwargs)

    existing = product()
    assert_ok(exchange_client.post_json("/catalog", portion(products=[existing])))
    monkeypatch.setattr(catalog_module, "upsert", failing_upsert)

    new_group, new_unit = group(), unit()
    changed = existing | {"name": "Изменён"}
    body = portion(groups=[new_group], units=[new_unit], products=[changed])
    assert_error(exchange_client.post_json("/catalog", body), 500, "INTERNAL_ERROR")
    assert db_fetch(CatalogGroup, CatalogGroup.id == uuid.UUID(new_group["id"])) == []
    assert db_fetch(CatalogUnit, CatalogUnit.id == uuid.UUID(new_unit["id"])) == []
    assert fetch_product(db_fetch, existing["id"]).name == existing["name"]
    assert (last_journal()["status_code"], last_journal()["counts"]) == (500, None)


# --- Крупная порция ---


def test_large_portion_500_products(
    exchange_client: ExchangeClient, db_fetch: Callable, last_journal: Callable
) -> None:
    groups = [group() for _ in range(50)]
    units = [unit() for _ in range(5)]
    products = [
        product(
            group_id=groups[i % 50]["id"],
            unit_id=units[i % 5]["id"],
            name=f"Товар {i} " + "описание " * 5,
            description="Подробное описание товара. " * 20,
            deleted=i % 100 == 0,
        )
        for i in range(500)
    ]
    body = portion(full=True, groups=groups, units=units, products=products)
    started = time.perf_counter()
    counts = assert_ok(exchange_client.post_json("/catalog", body))
    elapsed = time.perf_counter() - started
    assert counts == {"groups": 50, "units": 5, "products": 500, "deleted": 5}
    assert len(db_fetch(CatalogProduct, CatalogProduct.id.in_([uuid.UUID(p["id"]) for p in products]))) == 500
    # Повтор той же порции (обновление всех строк).
    assert assert_ok(exchange_client.post_json("/catalog", body)) == counts
    repeat_ms = last_journal()["duration_ms"]
    print(f"\ncatalog 500: {elapsed * 1000:.0f} мс (клиент), {repeat_ms} мс (журнал, повтор)")
    assert elapsed < 5  # ориентир — < 1 с; запас на медленную машину
