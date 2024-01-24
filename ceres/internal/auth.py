import re

import bcrypt

from ceres.internal.utilities import StrEnum


class HashAlgorithm(StrEnum):
    BCrypt = "bcrypt"


def get_password_hash_algorithm(hash: str) -> HashAlgorithm | None:
    if re.match(r"^\$2[ayb]\$.{56}$", hash):
        return HashAlgorithm.BCrypt

    return None


def get_password_hash(password: str, algorithm: HashAlgorithm = HashAlgorithm.BCrypt) -> str:
    match algorithm:
        case HashAlgorithm.BCrypt:
            return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def validate_password_hash(hash: str) -> bool:
    return get_password_hash_algorithm(hash) is not None


def validate_password(password: str, hash: str) -> bool:
    algorithm = get_password_hash_algorithm(hash)
    if algorithm is None:
        return False

    match algorithm:
        case HashAlgorithm.BCrypt:
            return bcrypt.checkpw(password.encode(), hash.encode())

    return False
