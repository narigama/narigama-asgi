from typing import TypeVar

import fastapi

from .problem import Problem


P = TypeVar("P")  # P should set-friendly


class PermissionMissing(Problem):
    status = 403
    title = "The request does not contain the correct permissions."
    kind = "permission-missing"


def permissions_enforce(permissions_claimed: set[P], permissions_required: set[P], raise_exception: bool = True):
    # ensure requirements are a subset of claimed...
    if not permissions_required <= permissions_claimed and raise_exception:
        # ...find the intersection, these are the missing claims
        permission_missing = ", ".join(sorted(permissions_required - permissions_claimed))
        err = "The request is missing the following permission(s): {}".format(permission_missing)
        raise PermissionMissing(err)


def install(app: fastapi.FastAPI) -> fastapi.FastAPI:
    """Install an ACL manager for Problems."""
    if getattr(app.state, "_narigama_acl_installed", False):
        raise Exception("ACL is already installed")

    @app.on_event("startup")
    async def acl_startup():
        if not getattr(app.state, "_narigama_problem_installed", False):
            raise KeyError("ACL Manager depends on HTTPProblem, install it first.")

    app.state._narigama_acl_installed = True
    return app
