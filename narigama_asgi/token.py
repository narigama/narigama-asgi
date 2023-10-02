import dataclasses
import datetime
import json
import secrets

import asyncpg
import fastapi
import fastapi.security

from narigama_asgi import postgres
from narigama_asgi import util
from narigama_asgi.problem import Problem


QUERY_TOKEN_SCHEMA_CREATE = """
create table if not exists "token" (
    "id" text not null,
    "context" json not null default '{}'::json,

    "created_at" timestamptz not null default date_trunc('second', current_timestamp),
    "utility_at" timestamptz,
    "expires_at" timestamptz,

    primary key("id")
);
""".strip()


QUERY_TOKEN_CREATE = """
insert into "token" ("id", "context", "created_at", "utility_at", "expires_at")
values ($1, $2, $3, $4, $5)
""".strip()


QUERY_TOKEN_GET_BY_ID = """
select "id", "context", "created_at", "utility_at", "expires_at" from "token"
where "id" = $1
""".strip()


QUERY_TOKEN_DELETE_BY_ID = """
delete from "token"
where "id" = $1
""".strip()


QUERY_TOKEN_CLEANUP = """
delete from "token"
where "expires_at" is not null and "expires_at" <= $1
""".strip()


class TokenRequiredError(Problem):
    status = fastapi.status.HTTP_400_BAD_REQUEST
    title = "A Token was required, but not provided"
    kind = "token-required"


class TokenNotFoundError(Problem):
    status = fastapi.status.HTTP_403_FORBIDDEN
    title = "Token was not found"
    kind = "token-not-found"


class TokenUsedTooEarly(Problem):
    status = fastapi.status.HTTP_400_BAD_REQUEST
    title = "Token was used before intended scope."
    kind = "token-used-too-early"


@dataclasses.dataclass()
class Token:
    id: str  # secret
    context: dict  # the payload stored server side for this token
    created_at: datetime.datetime
    utility_at: datetime.datetime | None  # don't use before
    expires_at: datetime.datetime | None  # don't use after

    @classmethod
    def from_row(cls, row: asyncpg.Record):
        return cls(
            id=row["id"],
            created_at=row["created_at"],
            utility_at=row["utility_at"],
            expires_at=row["expires_at"],
            context=json.loads(row["context"]),
        )


async def schema_create(db: asyncpg.Connection):
    await db.execute(QUERY_TOKEN_SCHEMA_CREATE)


async def token_get_by_id(db: asyncpg.Connection, token_id: str) -> Token:
    """Fetch a token by it's id. Don't return the token if it's either side of utility or expiry."""
    row = await db.fetchrow(QUERY_TOKEN_GET_BY_ID, token_id)
    if not row:
        raise TokenNotFoundError(token_id)

    return Token.from_row(row)


def _to_timestamp(timestamp: int | datetime.timedelta | datetime.datetime | None = None) -> datetime.datetime | None:
    if timestamp is None:
        return

    # int -> delta
    if isinstance(timestamp, int):
        timestamp = datetime.timedelta(seconds=timestamp)

    # delta -> timestamp
    if isinstance(timestamp, datetime.timedelta):
        timestamp = util.now() + timestamp

    # timestamp
    return timestamp


async def token_create(
    db: asyncpg.Connection,
    context: dict,
    *,
    id: str | None = None,
    utility_at: int | datetime.timedelta | datetime.datetime | None = None,
    expires_at: int | datetime.timedelta | datetime.datetime | None = None,
) -> Token:
    """Create a new token.

    The key should be a cryptographically sound, high entropy, unique key.
    You'll be selecting this token by that key later. Store whatever you want
    in context.
    """
    created_at = util.now()

    _id = id or secrets.token_urlsafe(32)
    utility_at = _to_timestamp(utility_at)
    expires_at = _to_timestamp(expires_at)

    await db.execute(QUERY_TOKEN_CREATE, _id, json.dumps(context), created_at, utility_at, expires_at)

    return Token(
        id=_id,
        context=context,
        created_at=created_at,
        utility_at=utility_at,
        expires_at=expires_at,
    )


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
        now = util.now()
        await token_cleanup_expired(db, now)

        # grab the token_key in this order ->
        token_id = token_query or token_header or token_cookie

        # no token was provided by any method :(
        if not token_id:
            raise TokenRequiredError(name)

        # load token by it's key, optionally transform
        token = await token_get_by_id(db, token_id)

        # make sure it's not too early to use it
        if token.utility_at is not None and now < token.utility_at:
            raise TokenUsedTooEarly(token.utility_at)

        # transform the token into something else if a handler was provided
        if handler:
            return await handler(request, db, token)

        # otherwise just return the token
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
