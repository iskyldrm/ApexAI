from jose import JWTError

from app.core.security import (
    create_access_token,
    decode_token,
    generate_refresh_token,
    hash_password,
    verify_password,
)


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


def test_create_and_decode_access_token():
    token = create_access_token(
        user_id="user-123",
        email="ali@acme.com",
        is_platform_admin=False,
        orgs=[{"org_id": "org-1", "role": "developer", "teams": ["team-1"]}],
    )
    payload = decode_token(token)
    assert payload["sub"] == "user-123"
    assert payload["email"] == "ali@acme.com"
    assert payload["is_platform_admin"] is False
    assert payload["orgs"][0]["role"] == "developer"


def test_decode_invalid_token_raises():
    import pytest

    with pytest.raises(JWTError):
        decode_token("not-a-valid-token")


def test_generate_refresh_token_returns_pair():
    plain, hashed = generate_refresh_token()
    assert len(plain) > 20
    import hashlib

    assert hashed == hashlib.sha256(plain.encode("utf-8")).hexdigest()