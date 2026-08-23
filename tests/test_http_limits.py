from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.http_limits import RequestBodyLimitMiddleware


def test_request_body_limit_rejects_before_route_parsing():
    app = FastAPI()
    app.add_middleware(RequestBodyLimitMiddleware, max_body_size=8)

    @app.post("/body")
    async def body(request: Request):
        return {"size": len(await request.body())}

    with TestClient(app) as client:
        assert client.post("/body", content=b"12345678").json() == {"size": 8}
        response = client.post("/body", content=b"123456789")
    assert response.status_code == 413
