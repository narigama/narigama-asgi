import asyncpg
import fastapi
import pytest
from fastapi.testclient import TestClient

from narigama_asgi.postgres import get_db
from narigama_asgi.postgres import install


async def check_db(db: asyncpg.Connection) -> bool:
    return await db.fetchval("""SELECT true::bool as ok;""")


async def check_db_raises_error(db: asyncpg.Connection):
    await db.execute("""select * from "user";""")


async def index(db: asyncpg.Connection = fastapi.Depends(get_db)) -> dict:
    return {"ok": await check_db(db)}


async def index_raises_error(db: asyncpg.Connection = fastapi.Depends(get_db)) -> dict:
    await check_db_raises_error(db)


@pytest.fixture(autouse=True)
def _setup(app: fastapi.FastAPI, config):
    install(app, config.database_url, "narigama")

    app.router.add_api_route("/check_db", index, methods=["GET"])
    app.router.add_api_route("/check_db_raises_error", index_raises_error, methods=["GET"])


async def test_postgres_responds(client: TestClient):
    response = await client.get("/check_db")

    assert response.status_code == fastapi.status.HTTP_200_OK
    assert response.json() == {"ok": True}


async def test_postgres_raises_exception(client: TestClient):
    with pytest.raises(asyncpg.exceptions.UndefinedTableError) as ex:
        await client.get("/check_db_raises_error")

    assert str(ex.value) == 'relation "user" does not exist'
