import contextlib
import dataclasses
import enum
from unittest.mock import AsyncMock

import asyncpg
import fastapi
import pytest
from async_asgi_testclient import TestClient

import narigama_asgi


class MockConnectionPool:
    """
    Mocks a connection pool, but always returns the same connection.
    """

    def __init__(self, connection):
        self.connection = connection

    async def execute(self, query: str):
        await self.connection.execute(query)

    @contextlib.asynccontextmanager
    async def acquire(self):
        yield self.connection

    async def close(self):
        pass


class Permission(enum.StrEnum):
    UserPermission = "USER_PERMISSION"
    AdminPermission = "ADMIN_PERMISSION"


@dataclasses.dataclass(frozen=True)
class Config:
    database_url: str = narigama_asgi.util.env("DATABASE_URL")


@pytest.fixture
async def config():
    yield Config()


@pytest.fixture()
async def db(config: Config):
    conn = await asyncpg.connect(config.database_url)
    transaction = conn.transaction()

    # by ensuring this is the _only_ connection the testsuite will use, we can
    # make sure _all_ changes made are rolled back. See the above MockConnectionPool.
    try:
        await transaction.start()
        yield conn

    finally:
        await transaction.rollback()


@pytest.fixture(autouse=True)
async def _mocks(db, monkeypatch: pytest.MonkeyPatch):
    # mock the connection pool, this allows for inspection of the currently
    # active transaction after the test logic has been run.
    monkeypatch.setattr("asyncpg.create_pool", AsyncMock(return_value=MockConnectionPool(db)))


@pytest.fixture
async def app(config: Config):
    """
    Create a base application. Different modules can use a fixture to attach middlewares and routes.
    """
    yield fastapi.FastAPI()


@pytest.fixture
async def client(app):
    async with TestClient(app) as client:
        yield client
