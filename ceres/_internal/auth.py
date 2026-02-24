from __future__ import annotations

from typing import TYPE_CHECKING, TypeGuard

from ceres.config import Argon2HashingConfig, BCryptHashingConfig, HashingConfig
from ceres.config import HashType as HashType
from ceres.data import Argon2Hash, BCryptHash, Password, PasswordHash, validate

if TYPE_CHECKING:
    from argon2 import PasswordHasher


def get_password_hash_type(hash: str) -> HashType | None:
    try:
        validate(hash, BCryptHash)
        return HashType.BCRYPT
    except ValueError:
        pass

    try:
        validate(hash, Argon2Hash)
        return HashType.ARGON2
    except ValueError:
        pass

    return None


def verify_password_hash(hash: str) -> TypeGuard[PasswordHash]:
    return get_password_hash_type(hash) is not None


def get_password_hash(password: Password, config: HashingConfig) -> PasswordHash:
    match config:
        case BCryptHashingConfig():
            from bcrypt import gensalt, hashpw

            return BCryptHash(
                hashpw(
                    password.encode(),
                    gensalt(config.rounds),
                ).decode()
            )

        case Argon2HashingConfig():
            hasher = _create_argon2_hasher(config)
            return Argon2Hash(hasher.hash(password))

    raise ValueError("Unsupported hashing configuration.")


def verify_password(password: str, hash: PasswordHash) -> bool:

    match get_password_hash_type(hash):
        case HashType.BCRYPT:
            from bcrypt import checkpw

            try:
                return checkpw(password.encode(), hash.encode())
            except ValueError:
                return False
        case HashType.ARGON2:
            from argon2.exceptions import Argon2Error

            hasher = _create_argon2_hasher()
            try:
                return hasher.verify(hash, password)
            except Argon2Error:
                return False
        case None:
            return False

    return False


def _create_argon2_hasher(config: Argon2HashingConfig | None = None) -> PasswordHasher:
    if config is None:
        config = Argon2HashingConfig()

    from argon2 import PasswordHasher

    return PasswordHasher(
        time_cost=config.time_cost,
        memory_cost=config.memory_cost,
        parallelism=config.parallelism,
        hash_len=config.hash_length,
        salt_len=config.salt_length,
    )
