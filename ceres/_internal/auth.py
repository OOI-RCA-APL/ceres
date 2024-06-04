from __future__ import annotations

from typing import TypeGuard

from ceres._internal.lazy import lazy_imports
from ceres.config import Argon2HashingConfig, BCryptHashingConfig, HashingConfig
from ceres.config import HashType as HashType
from ceres.data import Argon2Hash, BCryptHash, PasswordHash, PasswordStr

with lazy_imports(__name__):
    from argon2 import PasswordHasher

    from ceres._internal import util


def get_password_hash_type(hash: str) -> HashType | None:

    try:
        util.get_type_adapter(BCryptHash).validate_python(hash)
        return HashType.BCRYPT
    except ValueError:
        pass

    try:
        util.get_type_adapter(Argon2Hash).validate_python(hash)
        return HashType.ARGON2
    except ValueError:
        pass

    return None


def verify_password_hash(hash: str) -> TypeGuard[PasswordHash]:
    return get_password_hash_type(hash) is not None


def get_password_hash(password: PasswordStr, config: HashingConfig) -> PasswordHash:
    import bcrypt

    match config:
        case BCryptHashingConfig():
            return BCryptHash(
                bcrypt.hashpw(password.encode(), bcrypt.gensalt(config.rounds)).decode()
            )
        case Argon2HashingConfig():
            hasher = _get_argon2_hasher(config)
            return Argon2Hash(hasher.hash(password))

    raise ValueError("unsupported hashing configuration")


def verify_password(password: str, hash: PasswordHash) -> bool:
    import bcrypt
    from argon2.exceptions import Argon2Error

    match get_password_hash_type(hash):
        case HashType.BCRYPT:
            try:
                return bcrypt.checkpw(password.encode(), hash.encode())
            except ValueError:
                return False
        case HashType.ARGON2:
            hasher = _get_argon2_hasher()
            try:
                return hasher.verify(hash, password)
            except Argon2Error:
                return False
        case None:
            return False

    return False


def _get_argon2_hasher(config: Argon2HashingConfig | None = None) -> PasswordHasher:
    if config is None:
        config = Argon2HashingConfig()

    return PasswordHasher(
        time_cost=config.time_cost,
        memory_cost=config.memory_cost,
        parallelism=config.parallelism,
        hash_len=config.hash_length,
        salt_len=config.salt_length,
    )
