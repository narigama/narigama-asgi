"""
A module that implements RFC7807 (https://www.rfc-editor.org/rfc/rfc7807) for FastAPI
"""
import urllib.parse

import fastapi
import fastapi.responses
from loguru import logger


PROBLEM_HEADERS = {"Content-Type": "application/problem+json"}


class ProblemMeta(type):
    """The Problem Metaclass, this will validate your Problems."""

    def __new__(cls, class_name, parents, attrs):  # noqa: D102
        # create the class
        _cls = type.__new__(cls, class_name, parents, attrs)

        # don't validate Problem
        if class_name == "Problem":
            return _cls

        # ensure required fields
        missing = []
        for key in ("status", "title", "kind"):
            if key not in attrs:
                missing.append(key)

        if missing:
            fmt = "Can't build a Problem: {} is missing the field(s): {}"
            raise Exception(fmt.format(class_name, ", ".join(missing)))

        # constructor
        def __init__(self, detail: str | None = None, context: dict | None = None):
            self.detail = detail or "No detail provided"
            self.context = context

        # make it printable
        def __str__(self):
            fmt = "<{}(status={}, title='{}', detail='{}')>"
            return fmt.format(self.__class__.__name__, self.status, self.title, self.detail)

        # serializer
        def to_dict(self, request: fastapi.Request) -> dict:
            data = {
                "status": self.status,  # the status code
                "title": self.title,  # a generic one liner about the issue
                "detail": self.detail,  # a more contextual one liner about the issue
                "instance": str(request.url),  # the endpoint called that caused this
                "type": urllib.parse.urljoin(str(request.base_url), "problem/{}".format(self.kind)),  # a doc endpoint
            }

            # if provided, additional data for debugging, etc...
            if self.context:
                data["context"] = self.context

            return data

        # bolt methods on and return class
        _cls.__init__ = __init__
        _cls.__str__ = __str__
        _cls.to_dict = to_dict
        return _cls


class Problem(Exception, metaclass=ProblemMeta):
    """The Problem base class, extend this to build new Problems.

    class UserNotFound(Problem):
        status=404
        title="The User was not found"
        kind="user-not-found"

    raise UserNotFound("Could not find a user with foobar@tescovalue.com")
    """


class UncaughtException(Problem):
    """A generic Problem for uncaught Exceptions.

    Add `include_uncaught_exceptions` when installing the error handler.
    """

    status = 500
    title = "The Server experienced an unexpected problem."
    kind = "uncaught-exception"


async def problem_exception_handler(request: fastapi.Request, exc: Problem):
    content = exc.to_dict(request)
    return fastapi.responses.JSONResponse(
        status_code=content["status"],
        headers=PROBLEM_HEADERS,
        content=content,
    )


def install(app: fastapi.FastAPI, handle_uncaught: bool = True) -> fastapi.FastAPI:
    """Install an exception handler for Problems."""

    @app.middleware("http")
    async def uncaught_exception_to_problem_middleware(request: fastapi.Request, call_next):
        try:
            # try to call the endpoint
            return await call_next(request)

        except Problem as ex:
            logger.error(ex)
            # return standardised error for Problems
            return await problem_exception_handler(request, ex)

        except Exception as ex:
            logger.error(ex)
            # convert uncaught errors into Problems, referencing the Error type in the description. otherwise dump it.
            if handle_uncaught:
                return await problem_exception_handler(request, UncaughtException(ex.__class__.__name__))
            raise ex

    # install a flag in app.state for other dependencies to find
    app.state.problem_handler_installed = True

    return app
