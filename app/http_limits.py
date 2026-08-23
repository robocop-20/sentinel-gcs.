"""ASGI guard that rejects oversized bodies before model parsing."""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_body_size: int) -> None:
        self.app = app
        self.max_body_size = max(1, int(max_body_size))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or scope.get("method") not in {
            "POST",
            "PUT",
            "PATCH",
        }:
            await self.app(scope, receive, send)
            return
        messages: list[Message] = []
        total = 0
        while True:
            message = await receive()
            messages.append(message)
            total += len(message.get("body", b""))
            if total > self.max_body_size:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b'{"detail":"Request body exceeds configured limit"}',
                    }
                )
                return
            if message.get("type") == "http.disconnect" or not message.get(
                "more_body", False
            ):
                break
        iterator = iter(messages)

        async def replay_receive() -> Message:
            try:
                return next(iterator)
            except StopIteration:
                return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)
