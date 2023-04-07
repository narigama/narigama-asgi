import dataclasses
import datetime
import json
import uuid

import asyncpg
import fastapi
import fastapi.security

from narigama_asgi import postgres
from narigama_asgi import util
from narigama_asgi.problem import Problem


QUERY_TOKEN_SCHEMA_CREATE = """
create table if not exists "token" (
    "id" uuid not null unique default gen_random_uuid() primary key,
    "created_at" timestamptz not null default date_trunc('second', current_timestamp),

    "expiry_at" timestamptz not null,
    "kind" text not null,
    "data" json not null
)
""".strip()

QUERY_TOKEN_CREATE = """
insert into "token" ("expiry_at", "kind", "data")
values ($1, $2, $3)
returning "id", "created_at", "expiry_at", "kind", "data"
""".strip()


QUERY_TOKEN_DELETE_BY_ID = """
delete from "token"
where "id" = $1
""".strip()


QUERY_TOKEN_GET_BY_ID = """
select "id", "created_at", "expiry_at", "kind", "data"
from "token"
where "id" = $1
""".strip()


QUERY_TOKEN_CLEANUP = """
delete from "token"
where "expiry_at" <= current_timestamp
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
    expiry_at: datetime.datetime

    kind: str
    data: dict  # a payload for this Token, use it to store whatever you wish

    @classmethod
    def from_row(cls, row: asyncpg.Record):
        return cls(
            id=row["id"],
            created_at=row["created_at"],
            expiry_at=row["expiry_at"],
            kind=row["kind"],
            data=json.loads(row["data"]),
        )


async def _token_get_by_id(db: asyncpg.Connection, token_id: str) -> Token:
    """Fetch a token by it's id."""
    row = await db.fetchrow(QUERY_TOKEN_GET_BY_ID, token_id)
    if not row:
        raise TokenNotFoundError(token_id)
    return Token.from_row(row)


async def create_token(
    db: asyncpg.Connection,
    expiry_at: int | datetime.timedelta | datetime.datetime,
    data: dict,
    kind: str | None = None,
) -> Token:
    """Create a new token.

    The token kind can be used to help discriminate in the future, but you'll
    probably fetch tokens by their id. Once fetched, the `data` field will be
    contextual to it's application.
    """
    # int -> delta -> timestamp
    if isinstance(expiry_at, int):
        expiry_at = datetime.timedelta(seconds=expiry_at)
    if isinstance(expiry_at, datetime.timedelta):
        expiry_at = util.now() + expiry_at

    kind = kind or "token"
    data = json.dumps(data)
    row = await db.fetchrow(QUERY_TOKEN_CREATE, expiry_at, kind, data)

    return Token.from_row(row)


async def delete_token(db: asyncpg.Connection, token: Token):
    """Delete a token by identifying it by it's id."""
    await db.execute(QUERY_TOKEN_DELETE_BY_ID, token.id)


async def cleanup_expired_tokens(db: asyncpg.Connection):
    """Find all tokens that have expired, and remove them."""
    await db.execute(QUERY_TOKEN_CLEANUP)


def require_token(name: str | None = None):
    """Attempt to extract a token from the request.

    The token name will be checked via query -> header -> cookie, in that order, stopping at the first one found.
    """
    name = "token-{}".format(name) if name else "token"  # "token" unless kind is provided

    async def dep_get_token(
        db: asyncpg.Connection = fastapi.Depends(postgres.get_db),
        token_query: str | None = fastapi.Depends(fastapi.security.APIKeyQuery(name=name, auto_error=False)),
        token_header: str | None = fastapi.Depends(fastapi.security.APIKeyHeader(name=name, auto_error=False)),
        token_cookie: str | None = fastapi.Depends(fastapi.security.APIKeyCookie(name=name, auto_error=False)),
    ) -> Token:
        # before we start, cleanup any expired tokens
        await cleanup_expired_tokens(db)

        # grab the token_id in this order
        token_id = token_query or token_header or token_cookie

        # no token was provided, by any method :(
        if not token_id:
            raise TokenRequiredError(name)

        # load token by it's id
        return await _token_get_by_id(db, token_id)

    return fastapi.Depends(dep_get_token)


def install(app: fastapi.FastAPI) -> fastapi.FastAPI:
    """Install the token manager. This will setup a `token` table within your database. Depends on `postgres`."""

    @app.on_event("startup")
    async def token_manager_startup():
        if not getattr(app.state, "database_pool", None):
            raise KeyError("Token Manager depends on Postgres, install it first.")

        if not getattr(app.state, "problem_handler_installed", False):
            raise KeyError("Token Manager depends on HTTPProblem, install it first.")

        # create the token table if missing
        await app.state.database_pool.execute(QUERY_TOKEN_SCHEMA_CREATE)

    return app
