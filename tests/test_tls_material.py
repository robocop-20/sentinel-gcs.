from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID

from scripts.generate_tls import ensure_tls_material


def test_tls_generator_creates_distinct_server_and_client_identities(tmp_path):
    ensure_tls_material(tmp_path)
    api = x509.load_pem_x509_certificate(
        (tmp_path / "api-server-cert.pem").read_bytes()
    )
    vision = x509.load_pem_x509_certificate(
        (tmp_path / "vision-api-client-cert.pem").read_bytes()
    )
    api_usage = api.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    vision_usage = vision.extensions.get_extension_for_class(
        x509.ExtendedKeyUsage
    ).value
    api.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier)
    assert ExtendedKeyUsageOID.SERVER_AUTH in api_usage
    assert ExtendedKeyUsageOID.CLIENT_AUTH not in api_usage
    assert ExtendedKeyUsageOID.CLIENT_AUTH in vision_usage
    assert api.serial_number != vision.serial_number
