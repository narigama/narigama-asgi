import datetime
import uuid
import asyncpg
import pypika
import pytest

import narigama_asgi


SCHEMA = """
    create table "user" (
        "id" uuid not null default gen_random_uuid(),
        "created_at" timestamptz not null default date_trunc('second', current_timestamp),
        "updated_at" timestamptz not null default date_trunc('second', current_timestamp),

        "email" text not null,
        "password" text not null,

        primary key("id"),
        unique("email")
    );

    create table "post" (
        "id" uuid not null default gen_random_uuid(),
        "created_at" timestamptz not null default date_trunc('second', current_timestamp),
        "updated_at" timestamptz not null default date_trunc('second', current_timestamp),

        "user_id" uuid not null references "user"("id") on delete cascade,

        "title" text not null,
        "content" text not null,

        primary key("id")
    );
""".strip()


Query = pypika.PostgreSQLQuery
User = pypika.Table("user")
Post = pypika.Table("post")
Parameter = narigama_asgi.query.Parameter


@pytest.fixture(autouse=True)
async def _setup(db: asyncpg.Connection):
    await db.execute(SCHEMA)


async def test_insert(db: asyncpg.Connection):
    query = (
        Query.into(User)
        .columns(User.email, User.password)
        .insert(Parameter("email"), Parameter("password"))
        .returning(User.id, User.created_at, User.updated_at)
    )

    sql, params = narigama_asgi.query.get_sql(query, {"email": "david@narigama.dev", "password": "tescovalue"})

    assert sql == '''INSERT INTO "user" ("email","password") VALUES ($1,$2) RETURNING "id","created_at","updated_at"'''
    assert params == ["david@narigama.dev", "tescovalue"]

    # and for this one, just check it's valid
    row = await db.fetchrow(sql, *params)
    assert isinstance(row[0], uuid.UUID)
    assert isinstance(row[1], datetime.datetime)
    assert isinstance(row[2], datetime.datetime)


async def test_select(db: asyncpg.Connection):
    query = Query.select(User.star).from_(User).where(User.email == Parameter("email"))

    sql, params = narigama_asgi.query.get_sql(query, {"email": "david@narigama.dev"})

    assert sql == """SELECT * FROM "user" WHERE "email"=$1"""
    assert params == ["david@narigama.dev"]

    # not bothering to insert mock data, but a valid response shows the query executed correctly and didn't break things
    assert await db.fetch(sql, *params) == []


async def test_join(db: asyncpg.Connection):
    query = (
        Query.select(Post.star)
        .from_(Post)
        .join(User)
        .on(Post.user_id == User.id)
        .where(User.email == Parameter("email"))
    )

    sql, params = narigama_asgi.query.get_sql(query, {"email": "david@narigama.dev"})

    assert sql == """SELECT "post".* FROM "post" JOIN "user" ON "post"."user_id"="user"."id" WHERE "user"."email"=$1"""
    assert params == ["david@narigama.dev"]

    # not bothering to insert mock data, but a valid response shows the query executed correctly and didn't break things
    assert await db.fetch(sql, *params) == []
