import asyncpg
import fastapi


async def get_db(request: fastapi.Request) -> asyncpg.Connection:
    """A fastapi Dependency to get the active postgres connection within this
    request context."""
    return request.state.database_connection


def install(app: fastapi.FastAPI, postgres_dsn: str) -> fastapi.FastAPI:
    @app.on_event("startup")
    async def postgres_startup():
        app.state.database_pool = await asyncpg.create_pool(
            dsn=postgres_dsn,
            server_settings={
                "application_name": "{}".format(app),
            },
        )

    @app.on_event("shutdown")
    async def postgres_shutdown():
        # attempt to cleanly shutdown the connections in the pool
        await app.state.database_pool.close()

    @app.middleware("http")
    async def postgres_middleware(request: fastapi.Request, call_next):
        async with request.app.state.database_pool.acquire() as database_connection:
            async with database_connection.transaction():
                request.state.database_connection = database_connection
                return await call_next(request)

    return app
