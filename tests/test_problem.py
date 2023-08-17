import fastapi
import pytest
from async_asgi_testclient import TestClient

import narigama_asgi


class OhDear(narigama_asgi.problem.Problem):
    status = 400
    title = "Oh Dear"
    kind = "oh-dear"


def raises_problem():
    raise OhDear("Here's a user readable reason.")


def raises_uncaught_exception():
    1 / 0


@pytest.fixture(autouse=True)
def _setup(app: fastapi.FastAPI):
    narigama_asgi.problem.install(app)

    app.router.add_api_route("/problem/known", raises_problem, methods=["GET"])
    app.router.add_api_route("/problem/unknown", raises_uncaught_exception, methods=["GET"])


async def test_client_raises_known_problem(client: TestClient):
    # calling this endpoint throws a Problem, ensure the response is correct
    response = await client.get("/problem/known")

    assert response.status_code == fastapi.status.HTTP_400_BAD_REQUEST
    assert response.json() == {
        "detail": "Here's a user readable reason.",
        "instance": "http://localhost/problem/known",
        "status": 400,
        "title": "Oh Dear",
        "type": "http://localhost/problem/oh-dear",
    }


async def test_client_raises_unknown_problem(client: TestClient):
    response = await client.get("/problem/unknown")

    assert response.status_code == fastapi.status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json() == {
        "detail": "ZeroDivisionError",
        "instance": "http://localhost/problem/unknown",
        "status": 500,
        "title": "The Server experienced an unexpected problem.",
        "type": "http://localhost/problem/uncaught-exception",
    }
