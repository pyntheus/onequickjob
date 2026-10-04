"""Error shapes shared by every endpoint.

Errors are JSON: {"detail": {"code": "...", "message": "..."}}. `message` is UK English
copy safe to show to the user; `code` is stable for the web to branch on.
"""

from typing import Any, Literal, NoReturn

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

type Lane = Literal["F", "L1", "L2", "L3"]


class ErrorDetail(BaseModel):
    code: str
    message: str
    lane: Lane | None = None
    extra: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    detail: ErrorDetail


class Conflict(Exception):
    """A domain error for code below the routers, which doesn't know about HTTP (repositories).
    Like any exception it aborts an open transaction; the app maps it to 409 with the usual error
    shape (conflict_handler, registered in app.main), so the response is what fail(409, ...) gives."""

    def __init__(self, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra

    @property
    def detail(self) -> dict[str, Any]:
        return ErrorDetail(code=self.code, message=self.message, extra=self.extra or None).model_dump(exclude_none=True)


async def conflict_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, Conflict)
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": exc.detail})


def fail(status_code: int, code: str, message: str, **extra: Any) -> NoReturn:
    raise HTTPException(
        status_code=status_code,
        detail=ErrorDetail(code=code, message=message, extra=extra or None).model_dump(exclude_none=True),
    )


def not_found(what: str = "That") -> NoReturn:
    fail(status.HTTP_404_NOT_FOUND, "not_found", f"{what} wasn't found.")


def not_implemented(lane: Lane) -> NoReturn:
    """Every lane endpoint starts as this. The lane replaces the body, never the contract."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=ErrorDetail(
            code="not_implemented",
            message=f"Not built yet. Lane {lane} implements this endpoint.",
            lane=lane,
        ).model_dump(exclude_none=True),
    )


# Documented on every route so the generated client knows the error shape. No 401: signed out
# is a 403 with the code "not_signed_in" (app.core.deps.current_user says why).
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    501: {"model": ErrorResponse},
}
