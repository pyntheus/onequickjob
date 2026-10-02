"""Validate a customer's answers against a category's intake schema.

Missing answers take the field's default (as the prototype's defaultsFor does), unknown
keys and invalid values are rejected, so the pricing models only ever see clean input.
"""

from typing import Any

from app.models.categories import Category, IntakeField

MAX_TEXT = 2000
MAX_COUNT = 10
DEFAULT_MAX_PHOTOS = 8


class AnswerError(ValueError):
    def __init__(self, key: str, message: str):
        super().__init__(f"{key}: {message}")
        self.key = key
        self.message = message


def _option_values(f: IntakeField) -> list[str]:
    return [o.value for o in f.options or []]


def _check(f: IntakeField, value: Any) -> Any:
    match f.type:
        case "choice" | "chips":
            if value not in _option_values(f):
                raise AnswerError(f.key, f"must be one of {', '.join(_option_values(f))}")
            return value
        case "multi":
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise AnswerError(f.key, "must be a list of options")
            allowed = _option_values(f)
            bad = [v for v in value if v not in allowed]
            if bad:
                raise AnswerError(f.key, f"unknown option {bad[0]!r}")
            return [v for v in allowed if v in value]  # schema order, no duplicates
        case "number":
            if not isinstance(value, int) or isinstance(value, bool):
                raise AnswerError(f.key, "must be a whole number")
            lo, hi, step = f.min or 0, f.max if f.max is not None else 10_000, f.step or 1
            if not lo <= value <= hi or (value - lo) % step:
                raise AnswerError(f.key, f"must be between {lo} and {hi} in steps of {step}")
            return value
        case "counts":
            if not isinstance(value, dict):
                raise AnswerError(f.key, "must be counts per item")
            keys = [it.key for it in f.items or []]
            unknown = [k for k in value if k not in keys]
            if unknown:
                raise AnswerError(f.key, f"unknown item {unknown[0]!r}")
            out: dict[str, int] = {}
            for k in keys:
                n = value.get(k, 0)
                if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= MAX_COUNT:
                    raise AnswerError(f.key, f"{k} must be between 0 and {MAX_COUNT}")
                out[k] = n
            return out
        case "text":
            if not isinstance(value, str) or len(value) > MAX_TEXT:
                raise AnswerError(f.key, f"must be text of at most {MAX_TEXT} characters")
            return value.strip()
        case "photos":
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise AnswerError(f.key, "must be a list of uploaded file ids")
            if len(value) > (f.max_photos or DEFAULT_MAX_PHOTOS):
                raise AnswerError(f.key, "too many photos")
            return list(dict.fromkeys(value))
    raise AnswerError(f.key, f"unsupported field type {f.type}")  # pragma: no cover


def defaults_for(category: Category) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in category.intake:
        d = f.default
        out[f.key] = list(d) if isinstance(d, list) else dict(d) if isinstance(d, dict) else d
    return out


def validate_answers(category: Category, answers: dict[str, Any] | None) -> dict[str, Any]:
    answers = answers or {}
    known = {f.key for f in category.intake}
    unknown = [k for k in answers if k not in known]
    if unknown:
        raise AnswerError(unknown[0], "isn't a question for this job")
    out = defaults_for(category)
    for f in category.intake:
        if f.key in answers:
            out[f.key] = _check(f, answers[f.key])
    return out


def has_empty_counts(category: Category, answers: dict[str, Any]) -> bool:
    """The prototype won't price a counts job with nothing in it ("Add at least one item")."""
    return any(f.type == "counts" and not any((answers.get(f.key) or {}).values()) for f in category.intake)
