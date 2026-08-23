"""Create local Docker secrets for JWT auth without printing secret material."""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import secrets
import sys
from pathlib import Path

from argon2 import PasswordHasher
from generate_tls import ensure_tls_material


SERVICE_IDS = ("vision", "telemetry", "v2x")


def write_private(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8", newline="\n")
    try:
        path.chmod(0o600)
    except OSError as exc:
        print(f"Warning: could not restrict permissions on {path}: {exc}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secrets-dir", default="secrets")
    parser.add_argument("--operator", default="operator")
    parser.add_argument("--rotate-operator", action="store_true")
    parser.add_argument("--password-stdin", action="store_true",
                        help="Read two password lines from stdin for protected automation")
    args = parser.parse_args()
    root = Path(args.secrets_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    ensure_tls_material(root / "tls")
    hasher = PasswordHasher()

    signing_key = root / "jwt-signing-key"
    if not signing_key.exists():
        write_private(signing_key, secrets.token_urlsafe(64))
    evidence_key = root / "evidence-encryption-key"
    if not evidence_key.exists():
        write_private(
            evidence_key,
            base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"),
        )
    grafana_password = root / "grafana-admin-password"
    if not grafana_password.exists():
        write_private(grafana_password, secrets.token_urlsafe(32))

    users_file = root / "auth-users.json"
    if args.rotate_operator or not users_file.exists():
        if args.password_stdin:
            first, second = sys.stdin.readline().rstrip("\r\n"), sys.stdin.readline().rstrip("\r\n")
        else:
            first = getpass.getpass(f"Password for Sentinel operator '{args.operator}': ")
            second = getpass.getpass("Confirm password: ")
        if first != second:
            raise SystemExit("Passwords do not match.")
        if len(first) < 14:
            raise SystemExit("Use at least 14 characters.")
        users = {
            "version": 1,
            "users": [
                {
                    "username": args.operator,
                    "secret_hash": hasher.hash(first),
                    "roles": ["operator"],
                    "disabled": False,
                }
            ],
        }
        write_private(users_file, json.dumps(users, indent=2) + "\n")

    service_records = []
    for service_id in SERVICE_IDS:
        secret_file = root / f"{service_id}-client-secret"
        if not secret_file.exists():
            write_private(secret_file, secrets.token_urlsafe(48))
        secret_value = secret_file.read_text(encoding="utf-8").strip()
        service_records.append(
            {
                "client_id": service_id,
                "secret_hash": hasher.hash(secret_value),
                "roles": ["service"],
                "disabled": False,
            }
        )
    write_private(
        root / "service-credentials.json",
        json.dumps({"version": 1, "services": service_records}, indent=2) + "\n",
    )
    print(f"Security bootstrap complete for operator '{args.operator}'.")
    print(f"Docker secrets created under: {root}")
    print("No plaintext operator password was written or printed.")


if __name__ == "__main__":
    main()
