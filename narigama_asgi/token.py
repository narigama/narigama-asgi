import dataclasses
import datetime
import json
import secrets
import uuid

import asyncpg
import fastapi
import fastapi.security

from narigama_asgi import postgres
from narigama_asgi import util
from narigama_asgi.problem import Problem


QUERY_TOKEN_SCHEMA_CREATE = """
create table if not exists "token" (
    "id" uuid not null default gen_random_uuid(),
    "created_at" timestamptz not null default date_trunc('second', current_timestamp),
    "expires_at" timestamptz not null,

    "key" text not null,
    "context" json not null default '{}'::json,

    primary key("id"),
    unique("key")
);
""".strip()


QUERY_TOKEN_CREATE = """
insert into "token" ("created_at", "expires_at", "key", "context")
values ($1, $2, $3, $4)
returning "id", "created_at", "expires_at", "key", "context"
""".strip()


QUERY_TOKEN_DELETE_BY_ID = """
delete from "token"
where "id" = $1
""".strip()


QUERY_TOKEN_GET_BY_KEY = """
select "id", "created_at", "expires_at", "key", "context"
from "token"
where "key" = $1
""".strip()


QUERY_TOKEN_CLEANUP = """
delete from "token"
where "expires_at" <= $1
""".strip()


class TokenRequiredError(Problem):
    status = fastapi.status.HTTP_400_BAD_REQUEST
    title = "A Token was required, but not provided"
    kind = "token-required"


class TokenNotFoundError(Problem):
    status = fastapi.status.HTTP_403_FORBIDDEN
    title = "Token was not found"
    kind = "token-not-found"


@dataclasses.dataclass()
class Token:
    id: uuid.UUID
    created_at: datetime.datetime
    expires_at: datetime.datetime

    key: str  # the unique key representing this token externally, sent to the client to identify this token
    context: dict  # a payload for this Token, use it to store whatever you wish

    @classmethod
    def from_row(cls, row: asyncpg.Record):
        return cls(
            id=row["id"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            key=row["key"],
            context=json.loads(row["context"]),
        )


async def schema_create(db: asyncpg.Connection):
    await db.execute(QUERY_TOKEN_SCHEMA_CREATE)


async def token_get_by_key(db: asyncpg.Connection, token_key: str) -> Token:
    """Fetch a token by it's id."""
    row = await db.fetchrow(QUERY_TOKEN_GET_BY_KEY, token_key)
    if not row:
        raise TokenNotFoundError(token_key)
    return Token.from_row(row)


async def token_create(
    db: asyncpg.Connection,
    expires_at: int | datetime.timedelta | datetime.datetime,
    context: dict,
    key: str | None = None,
) -> Token:
    """Create a new token.

    The key should be a cryptographically sound, high entropy, unique key.
    You'll be selecting this token by that key later. Store whatever you want
    in context.
    """
    created_at = util.now()

    # int -> delta
    if isinstance(expires_at, int):
        expires_at = datetime.timedelta(seconds=expires_at)

    # delta -> timestamp
    if isinstance(expires_at, datetime.timedelta):
        expires_at = util.now() + expires_at

    key = key or secrets.token_urlsafe(32)
    context = json.dumps(context)
    row = await db.fetchrow(QUERY_TOKEN_CREATE, created_at, expires_at, key, context)
    return Token.from_row(row)


async def token_delete(db: asyncpg.Connection, token: Token):
    """Delete a token by identifying it by it's id."""
    await db.execute(QUERY_TOKEN_DELETE_BY_ID, token.id)


async def token_cleanup_expired(db: asyncpg.Connection, timestamp: datetime.datetime | None = None):
    """Find all tokens that have expired, and remove them."""
    timestamp = timestamp or util.now()
    await db.execute(QUERY_TOKEN_CLEANUP, timestamp)


def token_require(*, name: str | None = None, handler=None):
    """Attempt to extract a token from a request.

    The token key will be checked in order via query -> header -> cookie, stopping at the first one found.

    This function will by default, return the Token. If you wish to transform
    the token into another object, pass a `handler` coroutine that accepts a
    request (fastapi.Request), database connection (asyncpg.Connection) and a
    token (Token), returning whatever you want from that. The handler is also a
    good place to enforce permissions if you're using some sort of ACLs.
    """
    name = name or "token"

    async def dep_get_token(
        request: fastapi.Request,
        db: asyncpg.Connection = fastapi.Depends(postgres.get_db),
        token_query: str | None = fastapi.Depends(fastapi.security.APIKeyQuery(name=name, auto_error=False)),
        token_header: str | None = fastapi.Depends(fastapi.security.APIKeyHeader(name=name, auto_error=False)),
        token_cookie: str | None = fastapi.Depends(fastapi.security.APIKeyCookie(name=name, auto_error=False)),
    ) -> Token:
        # before we start, cleanup any expired tokens, this spreads the cost of
        # cleanup and removes the requirement for a background task or cronjob
        await token_cleanup_expired(db)

        # grab the token_key in this order ->
        token_key = token_query or token_header or token_cookie

        # no token was provided by any method :(
        if not token_key:
            raise TokenRequiredError(name)

        # load token by it's key, optionally transform
        token = await token_get_by_key(db, token_key)
        if handler:
            return await handler(request, db, token)
        return token

    return fastapi.Depends(dep_get_token)


def install(app: fastapi.FastAPI) -> fastapi.FastAPI:
    """Install the token manager.

    This will setup a `token` table within your database. Depends on `postgres`.
    """
    if getattr(app.state, "_narigama_token_installed", False):
        raise Exception("Token Manager has already been installed.")

    @app.on_event("startup")
    async def token_manager_startup():
        if not getattr(app.state, "_narigama_postgres_installed", False):
            raise KeyError("Token Manager depends on Postgres, install it first.")

        if not getattr(app.state, "_narigama_problem_installed", False):
            raise KeyError("Token Manager depends on HTTPProblem, install it first.")

        # create the token table if missing
        await schema_create(app.state.database_pool)

    app.state._narigama_token_installed = True
    return app
