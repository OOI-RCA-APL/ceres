from typing import TYPE_CHECKING, TypeGuard

from ceres.config import Argon2HashingConfig, BCryptHashingConfig, HashingConfig
from ceres.config import HashType as HashType
from ceres.data import Argon2Hash, BCryptHash, Password, PasswordHash, validate

if TYPE_CHECKING:
    from argon2 import PasswordHasher


def get_password_hash_type(hash: str) -> HashType | None:
    """Detect the hashing algorithm used to produce `hash`.

    Args:
        hash: A password hash string to inspect.

    Returns:
        The ``HashType`` (bcrypt or argon2) if the string validates as a known hash format,
        or ``None`` if the format is unrecognized.
    """
    try:
        validate(BCryptHash, hash)
        return HashType.BCRYPT
    except ValueError:
        pass

    try:
        validate(Argon2Hash, hash)
        return HashType.ARGON2
    except ValueError:
        pass

    return None


def verify_password_hash(hash: str) -> TypeGuard[PasswordHash]:
    """Check whether `hash` is a valid password hash in any supported format.

    Args:
        hash: A string to validate.

    Returns:
        ``True`` if `hash` is a recognized bcrypt or argon2 hash (narrowing to
        ``PasswordHash``).
    """
    return get_password_hash_type(hash) is not None


def get_password_hash(password: Password, config: HashingConfig) -> PasswordHash:
    """Hash a plaintext password using the algorithm specified by `config`.

    Args:
        password: The plaintext password to hash.
        config: Hashing configuration that selects the algorithm (bcrypt or argon2) and its
            parameters.

    Returns:
        The resulting password hash string, typed as ``PasswordHash``.

    Raises:
        ValueError: If `config` is not a supported hashing configuration type.
    """
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
    """Verify that `password` matches the given `hash`.

    Detect the hash algorithm automatically and delegate to the appropriate verification
    function.

    Args:
        password: The plaintext password to check.
        hash: A previously generated password hash.

    Returns:
        ``True`` if the password matches the hash, ``False`` otherwise (including for
        unrecognized hash formats or verification errors).
    """
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
    """Create an argon2 ``PasswordHasher`` with the given configuration.

    Args:
        config: Argon2 parameters. If ``None``, use default ``Argon2HashingConfig`` values.

    Returns:
        A configured ``PasswordHasher`` instance.
    """
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
