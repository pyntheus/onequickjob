"""A stand-in for Stripe's HTTP API: the real stripe-python client, with its transport swapped
for canned responses shaped like Stripe's, recording every request (method, path, form
parameters, headers) so tests can check exactly what would have been sent."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import stripe

type Responder = dict | Callable[["Call"], tuple[int, dict]]


@dataclass
class Call:
    method: str
    path: str
    params: dict[str, str]
    headers: dict[str, str]

    @property
    def idempotency_key(self) -> str | None:
        return next((v for k, v in self.headers.items() if k.lower() == "idempotency-key"), None)

    @property
    def stripe_account(self) -> str | None:
        return next((v for k, v in self.headers.items() if k.lower() == "stripe-account"), None)


class MockStripe(stripe.HTTPClient):
    name = "mock"

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[Call] = []
        self.routes: list[tuple[str, re.Pattern, Responder, int]] = []

    def on(self, method: str, path: str, response: Responder, status: int = 200) -> MockStripe:
        """Answer METHOD path (a regex matched against the whole path) with response."""
        self.routes.insert(0, (method.upper(), re.compile(path + "$"), response, status))
        return self

    def find(self, method: str, path: str) -> list[Call]:
        rx = re.compile(path + "$")
        return [c for c in self.calls if c.method == method.upper() and rx.match(c.path)]

    def one(self, method: str, path: str) -> Call:
        found = self.find(method, path)
        assert len(found) == 1, f"expected one {method} {path}, got {len(found)}: {[c.path for c in self.calls]}"
        return found[0]

    async def request_async(self, method: str, url: str, headers: Any, post_data: Any = None):
        parts = urlsplit(url)
        raw = post_data.decode() if isinstance(post_data, bytes) else (post_data or parts.query or "")
        call = Call(method.upper(), parts.path, dict(parse_qsl(raw, keep_blank_values=True)), dict(headers or {}))
        self.calls.append(call)
        for m, rx, responder, status in self.routes:
            if m == call.method and rx.match(call.path):
                if callable(responder):
                    status, body = responder(call)
                else:
                    body = responder
                return json.dumps(body).encode(), status, {"request-id": "req_mock"}
        return (
            json.dumps({"error": {"type": "invalid_request_error", "message": f"no mock for {url}"}}).encode(),
            404,
            {},
        )

    async def sleep_async(self, secs: float) -> None:
        return None

    async def close_async(self) -> None:
        return None

    def request(self, *args: Any, **kwargs: Any):  # pragma: no cover - the gateway is async only
        raise NotImplementedError


def client(mock: MockStripe) -> stripe.StripeClient:
    return stripe.StripeClient("sk_test_mock", http_client=mock, max_network_retries=0)


def card_error(code: str, message: str, pi: dict | None = None, decline_code: str | None = None) -> tuple[int, dict]:
    err: dict = {"type": "card_error", "code": code, "message": message}
    if decline_code:
        err["decline_code"] = decline_code
    if pi:
        err["payment_intent"] = pi
    return 402, {"error": err}


def payment_intent(pid: str = "pi_1", status: str = "succeeded", **extra: Any) -> dict:
    return {
        "id": pid,
        "object": "payment_intent",
        "status": status,
        "amount": extra.pop("amount", 3000),
        "application_fee_amount": extra.pop("application_fee_amount", 450),
        "latest_charge": extra.pop("latest_charge", "ch_1" if status == "succeeded" else None),
        "created": 1790000000,
        "metadata": extra.pop("metadata", {}),
        **extra,
    }
