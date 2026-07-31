"""The two user columns a native write cannot store as it received them.

A password hashes and an email address normalizes before a user row is written, and the
native path now does both itself rather than handing the write to Python. Both have to
agree with what the Python model would have produced, and the checks that prove it run
in opposite directions.

A hash is checked by handing a natively-produced one to Python's own verifier. Reading
it back is not enough on its own, because Argon2 carries its parameters inside the
encoded string and so verifies against whatever produced it, which is why the parameters
are read out and compared as well.

An address is checked one way only. The native subset is deliberately narrower than
`email_validator`, so an address it refuses costs nothing but a delegation. What must
never happen is the other direction: accepting one the library rejects, or normalizing
one differently, would write a row Python would not have written.
"""

import pytest
from ceres_core import (
    hash_argon2,
    hash_bcrypt,
    normalize_email,
    special_use_domains,
    verify_bcrypt,
)

from ceres.__internal__.auth import get_password_hash_type, verify_password
from ceres.config import Argon2HashingConfig, HashType
from ceres.data import validate
from ceres.data.types import Argon2Hash, BCryptHash, EmailAddress, Password

PARAMETERS = Argon2HashingConfig()


def _hash(password: str, config: Argon2HashingConfig = PARAMETERS) -> Argon2Hash:
    hashed = hash_argon2(
        password,
        config.time_cost,
        config.memory_cost,
        config.parallelism,
        config.hash_length,
        config.salt_length,
    )
    assert hashed is not None
    # The native side answers plain text, and validating it here is what proves the
    # shape the model's own hash type demands.
    return validate(Argon2Hash, hashed)


def test_python_verifies_a_natively_produced_hash() -> None:
    """The hash the native path writes is one Python's own verifier accepts."""
    hashed = _hash("correct horse")

    assert get_password_hash_type(hashed) is HashType.ARGON2
    assert verify_password("correct horse", hashed)
    assert not verify_password("wrong horse", hashed)


ARGON2_CFFI_HASHES = [
    "$argon2id$v=19$m=65536,t=3,p=4$ZzRD0u38GKAGWzmasM/n2g$+HCdivS/yFZTh9vHznxtVwp0rOtMa7Pza/OyNfmaG0Y",
    "$argon2id$v=19$m=8192,t=2,p=1$nA4m0B7oRXRMYDstCnsEngX2tUs$CM/xugrNXgu1xIiaOFTMCwoihF99Nylp",
    "$argon2id$v=19$m=1024,t=1,p=1$l4CiMWHb5Rw$7NHtsbhY+bBtJ1NmacpGKg",
]
"""Hashes of `STORED_PASSWORD` produced by `argon2-cffi`, which used to do the hashing.

Written out rather than generated, because the library is no longer a dependency. They
cover the configured defaults and two other parameter sets, including salt and hash
lengths that differ from them.
"""

STORED_PASSWORD = "correct horse battery staple"


@pytest.mark.parametrize("hashed", ARGON2_CFFI_HASHES)
def test_a_hash_written_by_the_old_library_still_verifies(hashed: str) -> None:
    """A password stored before the switch verifies against the implementation after it.

    These are real rows in real databases. A verifier that rejected them would lock every
    existing account out, and no other test would notice, because everything else here
    hashes and verifies with the same implementation.
    """
    assert verify_password(STORED_PASSWORD, validate(Argon2Hash, hashed))
    assert not verify_password("wrong password", validate(Argon2Hash, hashed))


BCRYPT_HASHES = [
    "$2b$04$j/v0NxFqAUw3o1dK0ne0De3TIf53C7VFdy7jf83ZGozpKwrhvCbrK",
    "$2b$10$B/A0hl9j7.9PhClUYVAqxOExTGylSw3rzfjY1A9V.Ky1DFbdG0qCK",
    "$2b$12$XuliIpkUuqT7bH7h/X.pp.H0F1FgRjnvHqpZo4.IbEwfVqQDat0qy",
    # The older `$2a$` prefix, which stored rows can still carry.
    "$2a$04$FlBqeqnwBFuu4OG7VFyKfunWElXOM2JS/yzPCRQ36oxq81oyoSO6W",
]
"""Hashes of `STORED_PASSWORD` produced by the `bcrypt` package, which used to hash them.

Written out for the same reason as the Argon2 ones, the package no longer being a
dependency. They cover three cost factors and both prefixes a stored hash can carry.
"""


@pytest.mark.parametrize("hashed", BCRYPT_HASHES)
def test_a_bcrypt_hash_from_the_old_library_still_verifies(hashed: str) -> None:
    """A bcrypt password stored before the switch verifies against the crate."""
    assert verify_bcrypt(STORED_PASSWORD, hashed)
    assert not verify_bcrypt("wrong password", hashed)


def test_bcrypt_hashes_the_way_the_model_stores_them() -> None:
    """A natively-produced bcrypt hash is the shape the model's own type validates."""
    hashed = hash_bcrypt("secret", 4)
    assert hashed is not None
    assert validate(BCryptHash, hashed) == hashed
    assert get_password_hash_type(hashed) is HashType.BCRYPT
    assert verify_bcrypt("secret", hashed)
    assert not verify_bcrypt("nope", hashed)

    # A cost outside what bcrypt takes answers nothing rather than hashing weakly.
    assert hash_bcrypt("secret", 99) is None


def test_a_password_is_held_only_to_the_limit_hashing_imposes() -> None:
    """The cap is bcrypt's 72-byte input limit, so a passphrase is a password.

    Measured in bytes because that is how bcrypt measures it, and multi-byte characters
    reach the limit sooner than their character count suggests.
    """
    # A long passphrase is exactly the kind of password worth encouraging.
    passphrase = "correct horse battery staple and then some more"
    assert len(passphrase) > 32
    assert hash_argon2(passphrase, 3, 65536, 4, 32, 16) is not None
    assert validate(Password, passphrase) == passphrase

    assert hash_argon2("a" * 72, 3, 65536, 4, 32, 16) is not None
    assert hash_argon2("a" * 73, 3, 65536, 4, 32, 16) is None
    assert hash_argon2("", 3, 65536, 4, 32, 16) is None
    assert hash_bcrypt("a" * 73, 4) is None

    # Eighteen four-byte characters are 72 bytes, nineteen are over.
    assert hash_argon2("\U0001f600" * 18, 3, 65536, 4, 32, 16) is not None
    assert hash_argon2("\U0001f600" * 19, 3, 65536, 4, 32, 16) is None

    with pytest.raises(ValueError):
        validate(Password, "a" * 73)


def test_the_length_limit_never_rejects_a_stored_hash() -> None:
    """A hash is recognized before the limit applies, which it has to be.

    An Argon2 hash at the configured defaults is longer than a password may be, so a
    limit applied first would make storing one impossible and would fail every row of a
    dump of hashed users. bcrypt's are shorter and would survive by luck, which is not a
    reason to rely on the order any less.
    """
    default = _hash(STORED_PASSWORD)
    assert len(default) > 72, default

    for hashed in [default, *ARGON2_CFFI_HASHES, *BCRYPT_HASHES]:
        # Passing one back through hashing returns it untouched rather than refusing it.
        assert hash_argon2(hashed, 3, 65536, 4, 32, 16) == hashed, hashed
        assert hash_bcrypt(hashed, 4) == hashed, hashed


def test_a_hash_carries_the_parameters_it_was_configured_with() -> None:
    """The encoded string names the configuration's own costs and lengths.

    Argon2 reads its parameters back out of the string, so verification succeeds whatever
    produced the hash. Comparing them is what catches a length or cost that never made it
    across.
    """
    config = Argon2HashingConfig(
        time_cost=2, memory_cost=8192, parallelism=1, hash_length=24, salt_length=20
    )
    hashed = _hash("secret", config)

    _, algorithm, version, costs, salt, digest = hashed.split("$")
    assert algorithm == "argon2id"
    assert version == "v=19"
    assert costs == "m=8192,t=2,p=1"

    # The two encoded tails are base64 without padding, so their byte lengths are what
    # the configured salt and hash lengths asked for.
    from base64 import b64decode

    def decoded(text: str) -> int:
        return len(b64decode(text + "=" * (-len(text) % 4)))

    assert decoded(salt) == 20
    assert decoded(digest) == 24


def test_an_already_hashed_password_passes_through() -> None:
    """A stored hash is written as it arrived rather than hashed a second time.

    The user manager passes one through, which is what lets a dump of one database load
    into another without turning every hash into a hash of a hash.
    """
    stored = _hash("secret")
    assert _hash(stored) == stored


ADDRESSES = [
    ("ada@example.com", "ada@example.com"),
    ("Ada@Example.COM", "ada@example.com"),
    ("a.b+tag@Gmail.com", "a.b+tag@gmail.com"),
    ("first.last@sub.domain.example.org", "first.last@sub.domain.example.org"),
    ("user!#$%&'*+-/=?^_`{|}~@example.com", "user!#$%&'*+-/=?^_`{|}~@example.com"),
    # An internationalized domain stores in its own script however it arrives.
    ("a@münchen.de", "a@münchen.de"),
    ("a@xn--mnchen-3ya.de", "a@münchen.de"),
    ("A@MÜNCHEN.DE", "a@münchen.de"),
    ("a@例え.jp", "a@例え.jp"),
    ("üser@example.com", "üser@example.com"),
    ("u\u0308ser@example.com", "üser@example.com"),
]
"""Addresses and the single form each one stores as."""

REFUSED = [
    "",
    "nobody",
    "@example.com",
    "a@",
    "a@localhost",
    "a@example",
    "a@-example.com",
    "a@example-.com",
    "a@example..com",
    "a@example.c0m",
    ".a@example.com",
    "a.@example.com",
    "a..b@example.com",
    '"quoted local"@example.com',
    "Ada <ada@example.com>",
    "a b@example.com",
    "a@exam ple.com",
    "a@@example.com",
    "a@[127.0.0.1]",
    "a@127.0.0.1",
    "a" * 65 + "@example.com",
    "a@" + "b" * 64 + ".com",
]
"""Addresses Ceres will not store, none of which names a mailbox it can hold."""


@pytest.mark.parametrize(("address", "expected"), ADDRESSES)
def test_an_address_stores_as_one_normalized_form(address: str, expected: str) -> None:
    """Every spelling of a mailbox lands on the same stored text."""
    assert normalize_email(address) == expected
    assert validate(EmailAddress, address) == expected


@pytest.mark.parametrize(("address", "expected"), ADDRESSES)
def test_normalizing_is_idempotent(address: str, expected: str) -> None:
    """Normalizing a stored address answers itself.

    A filter normalizes the value it is given before comparing, so a form that changed on
    a second pass would never match the row a create wrote.
    """
    assert normalize_email(expected) == expected


@pytest.mark.parametrize("address", REFUSED)
def test_a_refused_address_raises(address: str) -> None:
    """An address Ceres will not store is a validation error rather than a stored row."""
    assert normalize_email(address) is None
    with pytest.raises(ValueError):
        validate(EmailAddress, address)


def test_reserved_domains_are_refused() -> None:
    """No address under a reserved name can receive mail, so none is stored."""
    for name in special_use_domains():
        assert normalize_email(f"a@example.{name}") is None, name

    # The list is the one RFC 2606 and RFC 7686 set aside.
    assert sorted(special_use_domains()) == [
        "arpa",
        "invalid",
        "local",
        "localhost",
        "onion",
        "test",
    ]
