"""Generate a local Sentinel CA and per-service development certificates."""

from __future__ import annotations

import argparse
import ipaddress
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def _private(path: Path, key) -> None:
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    try:
        path.chmod(0o600)
    except OSError as exc:
        warnings.warn(f"Could not restrict permissions on {path}: {exc}")


def _certificate(path: Path, certificate: x509.Certificate) -> None:
    path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))


def _name(common_name: str) -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Sentinel Local Development"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )


def _leaf(
    root: Path,
    name: str,
    common_name: str,
    ca_key,
    ca_cert: x509.Certificate,
    *,
    server_names: tuple[str, ...] = (),
    client: bool = False,
) -> None:
    key_path, cert_path = root / f"{name}-key.pem", root / f"{name}-cert.pem"
    if key_path.exists() and cert_path.exists():
        return
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    now = datetime.now(timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(common_name))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=90))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
    )
    usages = []
    if server_names:
        usages.append(ExtendedKeyUsageOID.SERVER_AUTH)
        sans = [
            x509.IPAddress(ipaddress.ip_address(value))
            if value.replace(".", "").isdigit()
            else x509.DNSName(value)
            for value in server_names
        ]
        builder = builder.add_extension(
            x509.SubjectAlternativeName(sans), critical=False
        )
    if client:
        usages.append(ExtendedKeyUsageOID.CLIENT_AUTH)
    builder = builder.add_extension(x509.ExtendedKeyUsage(usages), critical=False)
    certificate = builder.sign(ca_key, hashes.SHA384())
    _private(key_path, key)
    _certificate(cert_path, certificate)


def ensure_tls_material(directory: Path) -> None:
    root = directory.resolve()
    root.mkdir(parents=True, exist_ok=True)
    ca_key_path, ca_cert_path = (
        root.parent / "tls-ca-private-key.pem",
        root / "ca-cert.pem",
    )
    if ca_key_path.exists() and ca_cert_path.exists():
        ca_key = serialization.load_pem_private_key(
            ca_key_path.read_bytes(), password=None
        )
        ca_cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())
    else:
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        now = datetime.now(timezone.utc)
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(_name("Sentinel Local Development CA"))
            .issuer_name(_name("Sentinel Local Development CA"))
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=True,
                    crl_sign=True,
                    encipher_only=None,
                    decipher_only=None,
                ),
                critical=True,
            )
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA384())
        )
        _private(ca_key_path, ca_key)
        _certificate(ca_cert_path, ca_cert)

    _leaf(
        root,
        "gateway-server",
        "sentinel-gateway",
        ca_key,
        ca_cert,
        server_names=("localhost", "127.0.0.1", "gateway"),
    )
    _leaf(
        root,
        "api-server",
        "sentinel-api",
        ca_key,
        ca_cert,
        server_names=("api", "sentinel-api"),
    )
    _leaf(root, "mqtt-server", "sentinel-mqtt", ca_key, ca_cert, server_names=("mqtt",))
    _leaf(
        root,
        "postgres-server",
        "sentinel-postgis",
        ca_key,
        ca_cert,
        server_names=("postgis",),
    )
    for filename, common_name in (
        ("gateway-api-client", "sentinel-gateway"),
        ("vision-api-client", "vision"),
        ("telemetry-api-client", "telemetry"),
        ("v2x-api-client", "v2x"),
        ("api-mqtt-client", "sentinel-api"),
        ("v2x-mqtt-client", "sentinel-v2x"),
        ("mqtt-health-client", "sentinel-mqtt-health"),
        ("api-postgres-client", "sentinel-api"),
        ("retention-postgres-client", "sentinel-retention"),
        ("api-health-client", "sentinel-api-health"),
        ("prometheus-api-client", "sentinel-prometheus"),
    ):
        _leaf(root, filename, common_name, ca_key, ca_cert, client=True)


def rotate_tls_material(directory: Path) -> None:
    root = directory.resolve()
    for path in root.glob("*.pem"):
        path.unlink()
    (root.parent / "tls-ca-private-key.pem").unlink(missing_ok=True)
    ensure_tls_material(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rotate", action="store_true")
    args = parser.parse_args()
    if args.rotate:
        rotate_tls_material(Path("secrets/tls"))
    else:
        ensure_tls_material(Path("secrets/tls"))
    print("TLS material created under secrets/tls; private keys were not printed.")
