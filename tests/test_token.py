import dataclasses
import datetime
import json

import asyncpg
import fastapi
import freezegun
import pytest
from fastapi.testclient import TestClient

import narigama_asgi
from narigama_asgi.token import Token, token_require


@dataclasses.dataclass(frozen=True)
class User:
    email: str
    is_admin: bool

    @classmethod
    async def handle_token(cls, request: fastapi.Request, db: asyncpg.Connection, token: Token) -> "User":
        # here's where you'd go to the DB to fetch the user, permissions, acls, etc
        # in this test case, we're just going to unpack the token context
        return cls(
            email=token.context["email"],
            is_admin=token.context["is_admin"],
        )


# this endpoint is guarded by token_require, it"ll reject if a valid token isn"t
# included in the request
async def index(token: Token = token_require()) -> dict:
    return {
        "token": token,
    }


async def index_with_handler(user: User = token_require(handler=User.handle_token)) -> dict:
    return {
        "user": user,
    }


@pytest.fixture(autouse=True)
def _setup(app: fastapi.FastAPI, config):
    narigama_asgi.problem.install(app)
    narigama_asgi.postgres.install(app, config.database_url, "narigama")
    narigama_asgi.token.install(app)  # token depends on problem and postgres

    app.router.add_api_route("/", index, methods=["POST"])
    app.router.add_api_route("/user", index_with_handler, methods=["POST"])


@pytest.mark.parametrize(
    "expires_at",
    [
        60,  # seconds
        datetime.timedelta(seconds=60),  # delta
        datetime.datetime.fromisoformat("2022-01-01T00:00:00"),  # fixed timestamp
    ],
)
# include the client to get the middleware to run, this is required to install the token table
async def test_token_create(client: TestClient, db: asyncpg.Connection, expires_at):
    context = {"kind": "test", "email": "david@narigama.dev"}
    token = await narigama_asgi.token.token_create(db, expires_at, context)

    # grab the row
    row = await db.fetchrow("select * from token where key = $1", token.key)

    # check table is sane
    assert token.id == row["id"]
    assert token.created_at == row["created_at"]
    assert token.expires_at == row["expires_at"]
    assert token.key == row["key"]
    assert token.context == json.loads(row["context"])

    # check from_row also works
    assert token == Token.from_row(row)


async def test_token_delete(db: asyncpg.Connection, client: TestClient):
    # first, create the token
    token = await narigama_asgi.token.token_create(db, 60, {})
    token_id = await db.fetchval("select id from token where id=$1", token.id)
    assert token.id == token_id

    # now delete it
    await narigama_asgi.token.token_delete(db, token)
    token_id = await db.fetchval("select id from token where id=$1", token.id)
    assert token_id is None


async def test_token_cleanup_expired(db: asyncpg.Connection, client: TestClient):
    now = datetime.datetime.fromisoformat("2022-01-01T00:00:00")

    # create the token
    with freezegun.freeze_time(now):
        # expire in 10 seconds
        token = await narigama_asgi.token.token_create(db, now + datetime.timedelta(10), {})
        await narigama_asgi.token.token_cleanup_expired(db)  # demonstrate the token survives this purge

        # prove the token survives this purge
        token_id = await db.fetchval("select id from token where id=$1", token.id)
        assert token.id == token_id

    with freezegun.freeze_time(now + datetime.timedelta(10)):
        # wait 10 seconds, now we"re precisely on time for the token to expire.
        await narigama_asgi.token.token_cleanup_expired(db)

        # prove the token _didn"t_ survive this purge
        token_id = await db.fetchval("select id from token where id=$1", token.id)
        assert token_id is None


async def test_token_get_by_key(db: asyncpg.Connection, client: TestClient):
    # insert the row, then refetch it
    token = await narigama_asgi.token.token_create(db, 60, {"kind": "test", "email": "david@narigama.dev"})
    assert await narigama_asgi.token.token_get_by_key(db, token.key) == token


async def test_token_required_by_header(db: asyncpg.Connection, client: TestClient):
    with freezegun.freeze_time("2022-01-01T00:00:00"):
        # create a token, make a valid request
        token = await narigama_asgi.token.token_create(db, 60, {"email": "david@narigama.dev"})
        response = await client.post("/", headers={"token": token.key})

    assert response.status_code == fastapi.status.HTTP_200_OK
    assert response.json() == {
        "token": {
            "id": str(token.id),
            "key": token.key,
            "created_at": "2022-01-01T00:00:00+00:00",
            "expires_at": "2022-01-01T00:01:00+00:00",
            "context": {"email": "david@narigama.dev"},
        }
    }


async def test_token_required_by_query(db: asyncpg.Connection, client: TestClient):
    with freezegun.freeze_time("2022-01-01T00:00:00"):
        # create a token, make a valid request
        token = await narigama_asgi.token.token_create(db, 60, {"email": "david@narigama.dev"})
        response = await client.post("/?token={}".format(token.key))

    assert response.status_code == fastapi.status.HTTP_200_OK
    assert response.json() == {
        "token": {
            "id": str(token.id),
            "key": token.key,
            "created_at": "2022-01-01T00:00:00+00:00",
            "expires_at": "2022-01-01T00:01:00+00:00",
            "context": {"email": "david@narigama.dev"},
        }
    }


async def test_token_required_by_cookie(db: asyncpg.Connection, client: TestClient):
    with freezegun.freeze_time("2022-01-01T00:00:00"):
        # create a token, make a valid request
        token = await narigama_asgi.token.token_create(db, 60, {"email": "david@narigama.dev"})
        response = await client.post("/", cookies={"token": token.key})

    assert response.status_code == fastapi.status.HTTP_200_OK
    assert response.json() == {
        "token": {
            "id": str(token.id),
            "key": token.key,
            "created_at": "2022-01-01T00:00:00+00:00",
            "expires_at": "2022-01-01T00:01:00+00:00",
            "context": {"email": "david@narigama.dev"},
        }
    }


async def test_token_required_but_missing(db: asyncpg.Connection, client: TestClient):
    with freezegun.freeze_time("2022-01-01T00:00:00"):
        # make a request, should reject as it"s not in the tokens table
        response = await client.post("/", headers={"token": "E0o9ffwiVZKqV51uJ5lvoe2BG3ge8lKJ"})

    assert response.status_code == fastapi.status.HTTP_403_FORBIDDEN
    assert response.json() == {
        "detail": "E0o9ffwiVZKqV51uJ5lvoe2BG3ge8lKJ",  # this is the token you provided
        "instance": "http://localhost/",
        "status": 403,
        "title": "Token was not found",
        "type": "http://localhost/problem/token-not-found",
    }


async def test_token_required_but_expired(db: asyncpg.Connection, client: TestClient):
    with freezegun.freeze_time("2022-01-01T00:00:00"):
        # create a new token, check it's there
        token = await narigama_asgi.token.token_create(db, 60, {})
        assert await db.fetchrow("select * from token where key = $1", token.key) is not None

    with freezegun.freeze_time("2022-01-01T00:01:00"):
        # now a minute has passed, the token will get cleaned up when attempting to use it
        response = await client.post("/", headers={"token": token.key})
        assert await db.fetchrow("select * from token where key = $1", token.key) is None

    # assert a normal "forbidden" response
    assert response.status_code == fastapi.status.HTTP_403_FORBIDDEN
    assert response.json() == {
        "status": 403,
        "detail": token.key,  # this is the token you provided
        "title": "Token was not found",
        "instance": "http://localhost/",
        "type": "http://localhost/problem/token-not-found",
    }


async def test_token_handler(db: asyncpg.Connection, client: TestClient):
    context = {"email": "david@narigama.dev", "is_admin": True}

    # create a new token, check it's there
    with freezegun.freeze_time("2022-01-01T00:00:00"):
        token = await narigama_asgi.token.token_create(db, 60, context)
        assert await db.fetchrow("select * from token where key = $1", token.key) is not None

        # now fetch using the endpoint with the token handler
        response = await client.post("/user", headers={"token": token.key})

    assert response.status_code == fastapi.status.HTTP_200_OK
    assert response.json() == {
        "user": {
            "email": "david@narigama.dev",
            "is_admin": True,
        }
    }
