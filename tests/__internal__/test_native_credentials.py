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
from ceres_core import hash_password, normalize_email, special_use_domains

from ceres.__internal__.auth import get_password_hash_type, verify_password
from ceres.config import Argon2HashingConfig, HashType
from ceres.data import validate
from ceres.data.types import Argon2Hash, EmailAddress

PARAMETERS = Argon2HashingConfig()


def _hash(password: str, config: Argon2HashingConfig = PARAMETERS) -> Argon2Hash:
    hashed = hash_password(
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


NORMALIZED = [
    "ada@example.com",
    "Ada@Example.COM",
    "a.b+tag@Gmail.com",
    "linus@kernel.example.co.uk",
    "x@y.zz",
    "first.last@sub.domain.example.org",
    "user!#$%&'*+-/=?^_`{|}~@example.com",
]
"""Addresses the native subset is expected to serve."""

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
    "a@example.c",
    "a@example.c0m",
    ".a@example.com",
    "a.@example.com",
    "a..b@example.com",
    '"quoted local"@example.com',
    "user@über.de",
    "üser@example.com",
    "a b@example.com",
    "a@exam ple.com",
    "a@@example.com",
    "a@example.com ",
    " a@example.com",
    "a@[127.0.0.1]",
    "a@xn--80ak6aa92e.com",
    "a@127.0.0.1",
    "a@exa_mple.com",
    "Ada <ada@example.com>",
    "a@example.invalid",
    "a@sub.test",
    "a" * 65 + "@example.com",
    "a@" + "b" * 64 + ".com",
    "a@" + ("b" * 60 + ".") * 5 + "com",
]
"""Addresses outside the subset, which delegate rather than being guessed at."""


@pytest.mark.parametrize("address", NORMALIZED)
def test_a_served_address_matches_what_the_model_would_have_stored(address: str) -> None:
    """Every address the native path accepts normalizes exactly as the model does.

    This is the direction that can corrupt data. An address accepted here and refused by
    `email_validator`, or normalized differently, is a row written natively that Python
    would have written another way or not at all.
    """
    native = normalize_email(address)
    assert native is not None, "expected the native subset to serve this address"
    assert native == validate(EmailAddress, address)


@pytest.mark.parametrize("address", REFUSED)
def test_a_refused_address_delegates(address: str) -> None:
    """An address outside the subset is left to the model, whatever the model makes of it."""
    assert normalize_email(address) is None


def test_the_reserved_domain_list_matches_the_validators_own() -> None:
    """The native list of undeliverable names is the library's list.

    Holding the two together is what keeps a name the library adds later from being an
    address written natively that Python refuses.
    """
    from email_validator import SPECIAL_USE_DOMAIN_NAMES

    assert sorted(special_use_domains()) == sorted(SPECIAL_USE_DOMAIN_NAMES)
    for name in SPECIAL_USE_DOMAIN_NAMES:
        assert normalize_email(f"a@example.{name}") is None, name


def test_no_accepted_address_is_one_the_validator_rejects() -> None:
    """Sweep every combination of a nasty local part and a nasty domain, one way.

    A refusal is always safe, so the sweep asserts nothing about them. What it holds is
    that every address the native path accepts is one the model accepts too, and stores
    as the same text. The grammar comes from a crate whose accept surface is not the
    model's, so this product is what pins the difference.
    """
    from itertools import product

    from email_validator import EmailNotValidError

    locals_ = [
        "a",
        "ab",
        "a.b",
        ".a",
        "a.",
        "a..b",
        "a b",
        '"a b"',
        "a@b",
        "",
        "A",
        "Ada",
        "ada.lovelace",
        "ada+tag",
        "ü",
        "0",
        "-a",
        "a\t",
        "a\n",
        *(f"a{character}" for character in "!#$%&'*+-/=?^_`{|}~()<>[]\\,;:\""),
    ]
    domains = [
        "b.com",
        "B.COM",
        "b",
        "b.c",
        "b.co",
        "b.c0m",
        "b-c.com",
        "-b.com",
        "b-.com",
        "b..com",
        ".b.com",
        "b.com.",
        "b_c.com",
        "sub.b.com",
        "xn--80ak6aa92e.com",
        "b.xn--fiqs8s",
        "127.0.0.1",
        "[127.0.0.1]",
        "über.de",
        "localhost",
        "b.museum",
        "",
        "b .com",
        "b.c om",
        "b" * 64 + ".com",
        "b.c-m",
        "b.travel",
        *(f"b.{name}" for name in special_use_domains()),
    ]

    corpus = [f"{local}@{domain}" for local, domain in product(locals_, domains)]
    corpus += [
        *NORMALIZED,
        *REFUSED,
        "a@b.com ",
        " a@b.com",
        "a@@b.com",
        "a",
        "@",
        "Ada <a@b.com>",
        "<a@b.com>",
        "a@b.com,c@d.com",
    ]

    served = 0
    for address in corpus:
        native = normalize_email(address)
        if native is None:
            continue

        served += 1
        try:
            expected = validate(EmailAddress, address)
        except (ValueError, EmailNotValidError) as error:
            pytest.fail(f"native accepted {address!r} which the model rejects: {error}")

        assert native == expected, address

    # A sweep that served nothing would pass without testing anything.
    assert served > 100, served
