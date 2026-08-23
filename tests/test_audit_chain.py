from app.persistence import Persistence


def test_audit_hash_is_deterministic_and_chained():
    first = {
        "actor": "operator",
        "action": "event_acknowledged",
        "metadata": {"severity": "warning"},
    }
    second = {
        "actor": "admin",
        "action": "audit_chain_verified",
        "metadata": {"valid": True},
    }
    genesis = "0" * 64
    first_hash = Persistence._audit_hash(genesis, first)
    assert first_hash == Persistence._audit_hash(genesis, first)
    assert Persistence._audit_hash(first_hash, second) != Persistence._audit_hash(
        genesis, second
    )
