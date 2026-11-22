from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import get_db, make_engine
from app.main import app


def test_health_ok(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": True}


def test_health_db_unavailable(client: TestClient) -> None:
    # Порт 1 на localhost не слушается: подключение сразу отклоняется.
    dead_engine = make_engine("postgresql+psycopg://nobody:nothing@127.0.0.1:1/nodb")

    def broken_db():
        with Session(bind=dead_engine) as session:
            yield session

    app.dependency_overrides[get_db] = broken_db
    response = client.get("/api/health")
    dead_engine.dispose()
    assert response.status_code == 503
    assert response.json() == {"status": "ok", "db": False}
