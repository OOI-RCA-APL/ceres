from datetime import UTC, date, datetime, timedelta, timezone
from re import RegexFlag
from typing import Any, override

import pytest
from pydantic import TypeAdapter, ValidationError

from ceres.data.types import (
    BCryptHash,
    DateTime,
    EmailAddress,
    FromJSON,
    FromYAML,
    Name,
    NonBlankStr,
    NonEmptyStr,
    NonNegativeTimeDelta,
    Number,
    OrderedStrEnum,
    Password,
    PasswordHash,
    PositiveTimeDelta,
    RegexFlags,
    StrEnum,
    TimeDelta,
    Username,
)


class TestUsername:
    adapter = TypeAdapter(Username)

    def test_valid_letters(self) -> None:
        assert self.adapter.validate_python("alice") == "alice"

    def test_valid_with_hyphens_and_underscores(self) -> None:
        assert self.adapter.validate_python("my-user_name") == "my-user_name"

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self.adapter.validate_python("")

    def test_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self.adapter.validate_python("a" * 65)

    def test_max_length_accepted(self) -> None:
        value = "a" * 64
        assert self.adapter.validate_python(value) == value


class TestPassword:
    adapter = TypeAdapter(Password)

    def test_valid_password(self) -> None:
        assert self.adapter.validate_python("hunter2") == "hunter2"

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self.adapter.validate_python("")

    def test_a_passphrase_is_accepted(self) -> None:
        # The only cap is the one hashing imposes, so length alone is never a rejection.
        value = "correct horse battery staple and then some more"
        assert self.adapter.validate_python(value) == value

    def test_max_byte_length_accepted(self) -> None:
        value = "a" * 72
        assert self.adapter.validate_python(value) == value

    def test_too_long_by_byte_count_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self.adapter.validate_python("a" * 73)

    def test_multibyte_password_exceeding_72_bytes_rejected(self) -> None:
        # Each emoji is 4 bytes, so 19 emojis = 76 bytes > 72.
        with pytest.raises(ValidationError, match="72 bytes"):
            self.adapter.validate_python("\U0001f600" * 19)

    def test_multibyte_password_within_72_bytes_accepted(self) -> None:
        # 18 emojis = 72 bytes, exactly at the limit.
        value = "\U0001f600" * 18
        assert self.adapter.validate_python(value) == value


class TestEmailAddress:
    adapter = TypeAdapter(EmailAddress)

    def test_valid_email_normalized(self) -> None:
        result = self.adapter.validate_python("Alice@Example.COM")
        assert result == "alice@example.com"

    def test_invalid_email_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self.adapter.validate_python("not-an-email")


class TestBCryptHash:
    adapter = TypeAdapter(BCryptHash)

    def test_valid_bcrypt_hash(self) -> None:
        # A well-formed bcrypt hash: $2b$ prefix, 2-digit cost, $ then 53 chars of salt+hash.
        valid = "$2b$12$" + "a" * 53
        assert self.adapter.validate_python(valid) == valid

    def test_invalid_bcrypt_hash_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self.adapter.validate_python("not-a-hash")


class TestPasswordHash:
    adapter = TypeAdapter(PasswordHash)

    def test_bcrypt_hash_accepted(self) -> None:
        valid = "$2b$12$" + "a" * 53
        assert self.adapter.validate_python(valid) == valid

    def test_argon2_hash_accepted(self) -> None:
        valid = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$c29tZWhhc2g"
        assert self.adapter.validate_python(valid) == valid

    def test_plain_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self.adapter.validate_python("plain-password")


class TestStrEnum:
    def test_auto_generates_kebab_case(self) -> None:
        from enum import auto

        class Color(StrEnum):
            DARK_RED = auto()
            LIGHT_BLUE = auto()

        assert Color.DARK_RED == "dark-red"
        assert Color.LIGHT_BLUE == "light-blue"

    def test_str_returns_value(self) -> None:
        from enum import auto

        class Status(StrEnum):
            IN_PROGRESS = auto()

        assert str(Status.IN_PROGRESS) == "in-progress"


class TestOrderedStrEnum:
    def test_declaration_order_comparison(self) -> None:
        from enum import auto

        class Priority(OrderedStrEnum):
            LOW = auto()
            MEDIUM = auto()
            HIGH = auto()

        assert Priority.LOW < Priority.MEDIUM
        assert Priority.MEDIUM < Priority.HIGH
        assert Priority.HIGH > Priority.LOW

    def test_custom_order_mapping(self) -> None:
        from enum import auto

        class Severity(OrderedStrEnum):
            CRITICAL = auto()
            WARNING = auto()
            INFO = auto()

            @classmethod
            @override
            def __order_mapping__(cls) -> dict[Any, int]:
                return {cls.INFO: 0, cls.WARNING: 1, cls.CRITICAL: 2}

        assert Severity.INFO < Severity.WARNING
        assert Severity.WARNING < Severity.CRITICAL
        assert Severity.CRITICAL > Severity.INFO

    def test_comparison_with_none(self) -> None:
        from enum import auto

        class Level(OrderedStrEnum):
            ALPHA = auto()

        assert Level.ALPHA > None
        assert Level.ALPHA >= None
        assert not (Level.ALPHA < None)
        assert not (Level.ALPHA <= None)

    def test_le_and_ge_between_members(self) -> None:
        from enum import auto

        class Rank(OrderedStrEnum):
            FIRST = auto()
            SECOND = auto()

        assert Rank.FIRST <= Rank.SECOND
        assert Rank.FIRST <= Rank.FIRST
        assert Rank.SECOND >= Rank.FIRST
        assert Rank.SECOND >= Rank.SECOND

    def test_comparison_with_plain_string_delegates_to_super(self) -> None:
        from enum import auto

        class Tag(OrderedStrEnum):
            ALPHA = auto()
            BETA = auto()

        # StrEnum comparisons against plain strings use lexicographic order.
        assert Tag.ALPHA < "zzz"
        assert Tag.ALPHA <= "zzz"
        assert Tag.BETA > "aaa"
        assert Tag.BETA >= "aaa"


class TestRegexFlags:
    adapter = TypeAdapter(RegexFlags)

    def test_single_character_flag(self) -> None:
        result = self.adapter.validate_python("I")
        assert result == RegexFlag.IGNORECASE

    def test_multiple_character_flags(self) -> None:
        result = self.adapter.validate_python("IM")
        assert result == RegexFlag.IGNORECASE | RegexFlag.MULTILINE

    def test_named_flag_string(self) -> None:
        result = self.adapter.validate_python("ignorecase")
        assert result == RegexFlag.IGNORECASE

    def test_invalid_flag_character_rejected(self) -> None:
        with pytest.raises(ValidationError, match="invalid regex flag character"):
            self.adapter.validate_python("Z")

    def test_integer_passthrough(self) -> None:
        result = self.adapter.validate_python(RegexFlag.DOTALL)
        assert result == RegexFlag.DOTALL

    def test_lowercase_single_char_treated_as_named_flag_fallback(self) -> None:
        # "s" is a valid single-character flag alias for DOTALL.
        result = self.adapter.validate_python("s")
        assert result == RegexFlag.DOTALL


class TestName:
    adapter = TypeAdapter(Name)

    def test_valid_identifier(self) -> None:
        assert self.adapter.validate_python("my-name_01") == "my-name_01"

    def test_starts_with_digit_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self.adapter.validate_python("0invalid")

    def test_starts_with_hyphen_accepted(self) -> None:
        assert self.adapter.validate_python("-leading") == "-leading"

    def test_starts_with_underscore_accepted(self) -> None:
        assert self.adapter.validate_python("_leading") == "_leading"


class TestNonEmptyStr:
    adapter = TypeAdapter(NonEmptyStr)

    def test_non_empty_accepted(self) -> None:
        assert self.adapter.validate_python("hello") == "hello"

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self.adapter.validate_python("")


class TestNonBlankStr:
    adapter = TypeAdapter(NonBlankStr)

    def test_non_blank_accepted(self) -> None:
        assert self.adapter.validate_python("hello") == "hello"

    def test_whitespace_only_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self.adapter.validate_python("   ")

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self.adapter.validate_python("")


class TestDateTime:
    adapter = TypeAdapter(DateTime)

    def test_datetime_with_utc_preserved(self) -> None:
        value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = self.adapter.validate_python(value)
        assert result == value
        assert result.tzinfo is UTC

    def test_naive_datetime_assumes_utc(self) -> None:
        value = datetime(2024, 6, 15, 8, 30)
        result = self.adapter.validate_python(value)
        assert result.tzinfo is UTC
        assert result.hour == 8

    def test_non_utc_datetime_converted_to_utc(self) -> None:
        eastern = timezone(timedelta(hours=-5))
        value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=eastern)
        result = self.adapter.validate_python(value)
        assert result.tzinfo is UTC
        assert result.hour == 17

    def test_date_converted_to_midnight_utc(self) -> None:
        value = date(2024, 3, 15)
        result = self.adapter.validate_python(value)
        assert isinstance(result, datetime)
        assert result.tzinfo is UTC
        assert result.hour == 0
        assert result.minute == 0

    def test_none_passes_through(self) -> None:
        # The validator returns None when given None, which Pydantic will reject if the field
        # is required. Test the validator function directly.
        from ceres.data.types import _pre_validate_datetime

        assert _pre_validate_datetime(None) is None

    def test_iso_string_parsed(self) -> None:
        result = self.adapter.validate_python("2024-01-01T00:00:00Z")
        assert result.tzinfo is UTC

    def test_timestamp_number_parsed(self) -> None:
        result = self.adapter.validate_python(0)
        assert isinstance(result, datetime)
        assert result.tzinfo is UTC


class TestTimeDelta:
    adapter = TypeAdapter(TimeDelta)

    def test_timedelta_passthrough(self) -> None:
        value = timedelta(seconds=30)
        result = self.adapter.validate_python(value)
        assert result == value

    def test_integer_seconds(self) -> None:
        result = self.adapter.validate_python(60)
        assert result == timedelta(seconds=60)

    def test_float_seconds(self) -> None:
        result = self.adapter.validate_python(1.5)
        assert result == timedelta(seconds=1.5)

    def test_iso_duration_string(self) -> None:
        result = self.adapter.validate_python("PT30S")
        assert result == timedelta(seconds=30)

    def test_suffix_format_string(self) -> None:
        result = self.adapter.validate_python("5s")
        assert result == timedelta(seconds=5)

    def test_none_returns_none(self) -> None:
        from ceres.data.types import _pre_validate_timedelta

        assert _pre_validate_timedelta(None) is None

    def test_invalid_type_rejected(self) -> None:
        with pytest.raises(ValueError, match="invalid timedelta value"):
            from ceres.data.types import _pre_validate_timedelta

            _pre_validate_timedelta([1, 2, 3])


class TestPositiveTimeDelta:
    adapter = TypeAdapter(PositiveTimeDelta)

    def test_positive_accepted(self) -> None:
        result = self.adapter.validate_python(10)
        assert result == timedelta(seconds=10)

    def test_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self.adapter.validate_python(0)

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self.adapter.validate_python(-1)


class TestNonNegativeTimeDelta:
    adapter = TypeAdapter(NonNegativeTimeDelta)

    def test_positive_accepted(self) -> None:
        result = self.adapter.validate_python(10)
        assert result == timedelta(seconds=10)

    def test_zero_accepted(self) -> None:
        result = self.adapter.validate_python(0)
        assert result == timedelta(0)

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self.adapter.validate_python(-1)


class TestFromJSON:
    adapter = TypeAdapter(FromJSON[dict[str, int]])

    def test_json_string_parsed(self) -> None:
        result = self.adapter.validate_python('{"a": 1}')
        assert result == {"a": 1}

    def test_json_bytes_parsed(self) -> None:
        result = self.adapter.validate_python(b'{"a": 1}')
        assert result == {"a": 1}

    def test_non_string_passed_through(self) -> None:
        result = self.adapter.validate_python({"a": 1})
        assert result == {"a": 1}

    def test_invalid_json_rejected(self) -> None:
        with pytest.raises(ValidationError, match="invalid JSON"):
            self.adapter.validate_python("{not valid json}")


class TestFromYAML:
    adapter = TypeAdapter(FromYAML[dict[str, int]])

    def test_yaml_string_parsed(self) -> None:
        result = self.adapter.validate_python("a: 1\nb: 2")
        assert result == {"a": 1, "b": 2}

    def test_yaml_bytes_parsed(self) -> None:
        result = self.adapter.validate_python(b"a: 1\nb: 2")
        assert result == {"a": 1, "b": 2}

    def test_non_string_passed_through(self) -> None:
        result = self.adapter.validate_python({"a": 1})
        assert result == {"a": 1}

    def test_invalid_yaml_rejected(self) -> None:
        with pytest.raises(ValidationError, match="invalid YAML"):
            self.adapter.validate_python(":\n  :\n - ][")


class TestNumber:
    adapter = TypeAdapter(Number)

    def test_integer_preserved(self) -> None:
        result = self.adapter.validate_python(42)
        assert result == 42
        assert isinstance(result, int)

    def test_integer_valued_float_narrowed_to_int(self) -> None:
        result = self.adapter.validate_python(5.0)
        assert result == 5
        assert isinstance(result, int)

    def test_fractional_float_preserved(self) -> None:
        result = self.adapter.validate_python(3.14)
        assert result == 3.14
        assert isinstance(result, float)

    def test_serialization_narrows_integer_valued_float(self) -> None:
        # Verify the serializer also narrows floats.
        result = self.adapter.dump_python(5.0)
        assert result == 5
        assert isinstance(result, int)

    def test_serialization_preserves_fractional_float(self) -> None:
        result = self.adapter.dump_python(3.14)
        assert result == 3.14
        assert isinstance(result, float)


class TestJSONSerializable:
    def test_serializable_value_passes(self) -> None:
        from ceres.data.types import JSONSerializable

        adapter = TypeAdapter(JSONSerializable[dict[str, int]])
        result = adapter.validate_python({"key": 123})
        assert result == {"key": 123}

    def test_non_serializable_value_rejected(self) -> None:
        from ceres.data.types import JSONSerializable

        adapter = TypeAdapter(JSONSerializable[Any])
        with pytest.raises(ValidationError, match="not serializable to JSON"):
            adapter.validate_python(object())
