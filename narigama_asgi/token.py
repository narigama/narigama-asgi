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

    "value" text not null,
    "context" json not null default '{}'::json,

    primary key("id"),
    unique("value")
);
""".strip()

QUERY_TOKEN_CREATE = """
insert into "token" ("expires_at", "value", "context")
values ($1, $2, $3)
returning "id", "created_at", "expires_at", "value", "context"
""".strip()

QUERY_TOKEN_DELETE_BY_ID = """
delete from "token"
where "id" = $1
""".strip()

QUERY_TOKEN_GET_BY_VALUE = """
select "id", "created_at", "expires_at", "value", "context"
from "token"
where "value" = $1
""".strip()

QUERY_TOKEN_CLEANUP = """
delete from "token"
where "expires_at" <= $1
""".strip()


class TokenRequiredError(Problem):
    status = 400
    title = "A Token was not provided"
    kind = "token-required"


class TokenNotFoundError(Problem):
    status = 404
    title = "A Token was not found"
    kind = "token-not-found"


class TokenExpiredError(Problem):
    status = 400
    title = "The Token has expired"
    kind = "token-expired"


@dataclasses.dataclass()
class Token:
    id: uuid.UUID
    created_at: datetime.datetime
    expires_at: datetime.datetime

    value: str  # the value sent to the client to identify this token
    context: dict  # a payload for this Token, use it to store whatever you wish

    @classmethod
    def from_row(cls, row: asyncpg.Record):
        return cls(
            id=row["id"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            value=row["value"],
            context=json.loads(row["context"]),
        )


async def _token_get_by_value(db: asyncpg.Connection, token_value: str) -> Token:
    """Fetch a token by it's id."""
    row = await db.fetchrow(QUERY_TOKEN_GET_BY_VALUE, token_value)
    if not row:
        raise TokenNotFoundError(token_value)
    return Token.from_row(row)


async def create_token(
    db: asyncpg.Connection,
    expires_at: int | datetime.timedelta | datetime.datetime,
    context: dict,
    value: str | None = None,
) -> Token:
    """Create a new token.

    The value should be a cryptographically sound, high entropy, unique value.
    You'll be selecting this token by that value later. Store whatever you want
    in context.
    """
    # int -> delta
    if isinstance(expires_at, int):
        expires_at = datetime.timedelta(seconds=expires_at)

    # delta -> timestamp
    if isinstance(expires_at, datetime.timedelta):
        expires_at = util.now() + expires_at

    value = value or secrets.token_urlsafe(32)
    context = json.dumps(context)
    row = await db.fetchrow(QUERY_TOKEN_CREATE, expires_at, value, context)
    return Token.from_row(row)


async def delete_token(db: asyncpg.Connection, token: Token):
    """Delete a token by identifying it by it's id."""
    await db.execute(QUERY_TOKEN_DELETE_BY_ID, token.id)


async def cleanup_expired_tokens(db: asyncpg.Connection, timestamp: datetime.datetime | None = None):
    """Find all tokens that have expired, and remove them."""
    timestamp = timestamp or util.now()
    await db.execute(QUERY_TOKEN_CLEANUP, timestamp)


def require_token(*, name: str | None = None, handler=None):
    """Attempt to extract a token from a request.

    The token value will be checked in order via query -> header -> cookie, stopping at the first one found.

    This function will by default, return the Token. If you wish to transform
    the token into another object, pass a `handler` coroutine that accepts a
    database connection (asyncpg.Connection) and a token (Token), returning
    whatever you want from that.
    """
    name = name or "token"

    async def dep_get_token(
        db: asyncpg.Connection = fastapi.Depends(postgres.get_db),
        token_query: str | None = fastapi.Depends(fastapi.security.APIKeyQuery(name=name, auto_error=False)),
        token_header: str | None = fastapi.Depends(fastapi.security.APIKeyHeader(name=name, auto_error=False)),
        token_cookie: str | None = fastapi.Depends(fastapi.security.APIKeyCookie(name=name, auto_error=False)),
    ) -> Token:
        # before we start, cleanup any expired tokens
        await cleanup_expired_tokens(db)

        # grab the token_id in this order
        token_value = token_query or token_header or token_cookie

        # no token was provided, by any method :(
        if not token_value:
            raise TokenRequiredError(name)

        # load token by it's value, optionally transform
        token = await _token_get_by_value(db, token_value)
        if handler:
            return await handler(db, token)
        return token

    return fastapi.Depends(dep_get_token)


def install(app: fastapi.FastAPI) -> fastapi.FastAPI:
    """Install the token manager.

    This will setup a `token` table within your database. Depends on `postgres`.
    """

    @app.on_event("startup")
    async def token_manager_startup():
        if not getattr(app.state, "database_pool", None):
            raise KeyError("Token Manager depends on Postgres, install it first.")

        if not getattr(app.state, "problem_handler_installed", False):
            raise KeyError("Token Manager depends on HTTPProblem, install it first.")

        # create the token table if missing
        await app.state.database_pool.execute(QUERY_TOKEN_SCHEMA_CREATE)

    return app
