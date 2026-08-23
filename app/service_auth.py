"""OAuth2 client-credentials helper used by internal workers."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import requests


class ServiceTokenProvider:
    def __init__(
        self,
        api_url: str,
        client_id: str,
        client_secret_file: str,
        timeout_s: float = 3.0,
        ca_cert: str = "",
        client_cert: str = "",
        client_key: str = "",
    ) -> None:
        self._api_url = api_url.rstrip("/")
        if ca_cert and not self._api_url.lower().startswith("https://"):
            raise ValueError("A TLS-configured service identity requires an HTTPS API URL")
        self._client_id = client_id
        self._secret_file = Path(client_secret_file) if client_secret_file else None
        self._timeout_s = timeout_s
        self._token = ""
        self._refresh_at = 0.0
        self._lock = threading.Lock()
        self._verify: str | bool = ca_cert or True
        self._cert: tuple[str, str] | None = (
            (client_cert, client_key) if client_cert and client_key else None
        )

    @property
    def configured(self) -> bool:
        return bool(self._client_id and self._secret_file)

    def _read_secret(self) -> str:
        if not self._secret_file:
            raise RuntimeError("SERVICE_CLIENT_SECRET_FILE is not configured")
        secret = self._secret_file.read_text(encoding="utf-8").strip()
        if not secret:
            raise RuntimeError("Service client secret is empty")
        return secret

    def authorization_header(self) -> dict[str, str]:
        if not self.configured:
            return {}
        with self._lock:
            if time.monotonic() >= self._refresh_at:
                response = requests.post(
                    f"{self._api_url}/api/auth/service-token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._read_secret(),
                    },
                    timeout=self._timeout_s,
                    verify=self._verify,
                    cert=self._cert,
                )
                response.raise_for_status()
                payload = response.json()
                self._token = str(payload["access_token"])
                expires_in = max(60, int(payload.get("expires_in", 300)))
                self._refresh_at = time.monotonic() + max(30, expires_in * 0.8)
            return {"Authorization": f"Bearer {self._token}"}

    def invalidate(self) -> None:
        with self._lock:
            self._refresh_at = 0.0

    def configure_session(self, session: requests.Session) -> None:
        session.verify = self._verify
        if self._cert:
            session.cert = self._cert
