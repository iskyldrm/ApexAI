from app.core.security import hash_password, verify_password


def test_hash_and_verify_password():
    h = hash_password("my-secret-123")
    assert h != "my-secret-123"
    assert verify_password("my-secret-123", h) is True
    assert verify_password("wrong", h) is False


def test_hash_is_bcrypt_format():
    h = hash_password("any-password")
    assert h.startswith("$2b$") or h.startswith("$2a$")


def test_verify_password_invalid_hash_returns_false():
    assert verify_password("anything", "not-a-valid-hash") is False