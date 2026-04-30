import pytest

from ceres.__internal__.auth import (
    get_password_hash,
    get_password_hash_type,
    verify_password,
    verify_password_hash,
)
from ceres.config import Argon2HashingConfig, BCryptHashingConfig, HashType


class TestGetPasswordHashType:
    def test_bcrypt_hash(self):
        hashed = get_password_hash("password", BCryptHashingConfig(rounds=4))
        assert get_password_hash_type(hashed) == HashType.BCRYPT

    def test_argon2_hash(self):
        hashed = get_password_hash("password", Argon2HashingConfig())
        assert get_password_hash_type(hashed) == HashType.ARGON2

    def test_unrecognized_string(self):
        assert get_password_hash_type("not-a-hash") is None

    def test_empty_string(self):
        assert get_password_hash_type("") is None


class TestVerifyPasswordHash:
    def test_valid_bcrypt(self):
        hashed = get_password_hash("password", BCryptHashingConfig(rounds=4))
        assert verify_password_hash(hashed) is True

    def test_valid_argon2(self):
        hashed = get_password_hash("password", Argon2HashingConfig())
        assert verify_password_hash(hashed) is True

    def test_invalid(self):
        assert verify_password_hash("garbage") is False


class TestGetPasswordHash:
    def test_bcrypt(self):
        hashed = get_password_hash("secret", BCryptHashingConfig(rounds=4))
        assert hashed.startswith("$2")
        assert len(hashed) == 60

    def test_argon2(self):
        hashed = get_password_hash("secret", Argon2HashingConfig())
        assert hashed.startswith("$argon2")

    def test_unsupported_config_raises(self):
        with pytest.raises(ValueError, match="Unsupported hashing configuration"):
            get_password_hash("secret", object())  # type: ignore[reportArgumentType]


class TestVerifyPassword:
    def test_bcrypt_correct_password(self):
        hashed = get_password_hash("correct", BCryptHashingConfig(rounds=4))
        assert verify_password("correct", hashed) is True

    def test_bcrypt_wrong_password(self):
        hashed = get_password_hash("correct", BCryptHashingConfig(rounds=4))
        assert verify_password("wrong", hashed) is False

    def test_argon2_correct_password(self):
        hashed = get_password_hash("correct", Argon2HashingConfig())
        assert verify_password("correct", hashed) is True

    def test_argon2_wrong_password(self):
        hashed = get_password_hash("correct", Argon2HashingConfig())
        assert verify_password("wrong", hashed) is False

    def test_unrecognized_hash_returns_false(self):
        assert verify_password("anything", "not-a-valid-hash") is False  # type: ignore[reportArgumentType]
