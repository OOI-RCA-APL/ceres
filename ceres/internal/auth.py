import bcrypt

from ceres.data import BCryptHash, PasswordHash
from ceres.internal.utilities import StrEnum, get_type_adapter


class HashAlgorithm(StrEnum):
    BCrypt = "bcrypt"


def get_password_hash_algorithm(hash: str) -> HashAlgorithm | None:
    try:
        get_type_adapter(BCryptHash).validate_python(hash)
        return HashAlgorithm.BCrypt
    except ValueError:
        pass

    return None


def get_password_hash(
    password: str,
    algorithm: HashAlgorithm = HashAlgorithm.BCrypt,
) -> PasswordHash:
    match algorithm:
        case HashAlgorithm.BCrypt:
            return BCryptHash(bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode())


def validate_password_hash(hash: PasswordHash) -> bool:
    return get_password_hash_algorithm(hash) is not None


def verify_password(password: str, hash: PasswordHash) -> bool:
    algorithm = get_password_hash_algorithm(hash)
    if algorithm is None:
        return False

    match algorithm:
        case HashAlgorithm.BCrypt:
            return bcrypt.checkpw(password.encode(), hash.encode())

    return False
