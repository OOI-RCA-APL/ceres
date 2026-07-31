"""Password hashing and verification.

Argon2 is the native implementation's, called through `ceres_core` rather than
reimplemented here, so a password hashed by a native command and one hashed through the
entity manager cannot drift apart. bcrypt stays on its Python library, being the
configurable alternative rather than the default.
"""

from typing import TypeGuard

# The configuration getters return the native base classes, and the Python subclasses in
# `ceres.config` extend them, so matching against the bases covers both.
from ceres_core import Argon2HashingConfig, BCryptHashingConfig

from ceres.config import HashType as HashType
from ceres.data import Argon2Hash, BCryptHash, Password, PasswordHash, validate


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


def get_password_hash(
    password: Password,
    config: BCryptHashingConfig | Argon2HashingConfig,
) -> PasswordHash:
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
            from ceres_core import hash_bcrypt

            hashed = hash_bcrypt(password, config.rounds)
            if hashed is None:
                raise ValueError("bcrypt cost out of range.")

            return BCryptHash(hashed)

        case Argon2HashingConfig():
            from ceres_core import hash_argon2

            hashed = hash_argon2(
                password,
                config.time_cost,
                config.memory_cost,
                config.parallelism,
                config.hash_length,
                config.salt_length,
            )
            if hashed is None:
                raise ValueError("Argon2 parameters out of range.")

            return Argon2Hash(hashed)

    raise ValueError("Unsupported hashing configuration.")


def verify_password(password: str, hash: PasswordHash) -> bool:
    """Verify that `password` matches the given `hash`.

    The algorithm is read off the stored hash rather than taken from the configuration, so
    a row written before a database's hashing was changed still verifies.

    Args:
        password: The plaintext password to check.
        hash: A previously generated password hash.

    Returns:
        `True` if the password matches the hash, `False` otherwise, an unrecognized hash
        format included.
    """
    from ceres_core import verify_password as verify

    return verify(password, hash)
