from typing import TYPE_CHECKING

import bcrypt

from ceres.data import BCryptHash, PasswordHash
from ceres.internal.utilities import StrEnum, get_type_adapter

if TYPE_CHECKING:
    from ceres.config import HashingConfig
else:
    HashingConfig = object()


class HashAlgorithm(StrEnum):
    BCRYPT = "bcrypt"


def get_password_hash_algorithm(hash: str) -> HashAlgorithm | None:
    try:
        get_type_adapter(BCryptHash).validate_python(hash)
        return HashAlgorithm.BCRYPT
    except ValueError:
        pass

    return None


def get_password_hash(password: str, config: HashingConfig) -> PasswordHash:
    match config.algorithm:
        case HashAlgorithm.BCRYPT:
            return BCryptHash(
                bcrypt.hashpw(password.encode(), bcrypt.gensalt(config.rounds)).decode()
            )

    raise ValueError("unsupported hashing algorithm")


def verify_password(password: str, hash: PasswordHash) -> bool:
    algorithm = get_password_hash_algorithm(hash)
    if algorithm is None:
        return False

    match algorithm:
        case HashAlgorithm.BCRYPT:
            return bcrypt.checkpw(password.encode(), hash.encode())

    return False
