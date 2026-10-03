"""Error shapes shared by every endpoint.

Errors are JSON: {"detail": {"code": "...", "message": "..."}}. `message` is UK English
copy safe to show to the user; `code` is stable for the web to branch on.
"""

from typing import Any, Literal, NoReturn

from fastapi import HTTPException, status
from pydantic import BaseModel

type Lane = Literal["F", "L1", "L2", "L3"]


class ErrorDetail(BaseModel):
    code: str
    message: str
    lane: Lane | None = None
    extra: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    detail: ErrorDetail


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


# Documented on every route so the generated client knows the error shape.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse},
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    501: {"model": ErrorResponse},
}
