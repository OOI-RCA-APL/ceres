import pytest
from pydantic import TypeAdapter

from ceres.address import Address
from ceres.data import simplify
from ceres.data.converters import to_json
from ceres.error import (
    ComponentCombinedError,
    ComponentValidationError,
    DatabaseUnreachableError,
    Error,
    ExceptionInfo,
    NotConnectedError,
    NotFoundError,
    ProcedureInternalError,
    ProcedureNotFoundError,
    ValidationProblem,
    trace,
)


class TestErrorIsException:
    def test_error_subclass_is_exception(self):
        assert issubclass(NotFoundError, Exception)

    def test_error_instance_is_exception(self):
        assert isinstance(NotFoundError(), Exception)

    def test_error_instance_is_error(self):
        assert isinstance(NotFoundError(), Error)

    def test_raise_and_catch_as_error(self):
        with pytest.raises(Error):
            raise NotFoundError()

    def test_raise_and_catch_as_exception(self):
        with pytest.raises(Exception):
            raise NotFoundError()

    def test_raise_and_catch_specific_type(self):
        with pytest.raises(NotFoundError):
            raise NotFoundError()

    def test_str_returns_type_discriminator(self):
        assert str(NotFoundError()) == "not-found-error"

    def test_args_contains_type(self):
        error = NotFoundError()
        assert error.args == ("not-found-error",)

    def test_error_with_fields_str(self):
        error = DatabaseUnreachableError(reason="connection refused")
        assert str(error) == "database-unreachable-error"

    def test_catch_child_as_parent_base(self):
        with pytest.raises(Error) as context:
            raise ProcedureNotFoundError()
        assert context.value.type == "procedure-not-found-error"


class TestErrorHierarchyCatching:
    def test_catch_component_error_as_error(self):
        with pytest.raises(Error):
            raise ComponentValidationError(
                address=Address("@root"),
                problems=[],
            )

    def test_specific_catch_takes_priority(self):
        caught_type = None
        try:
            raise NotFoundError()
        except NotFoundError:
            caught_type = "specific"
        except Error:
            caught_type = "base"
        assert caught_type == "specific"

    def test_unrelated_error_not_caught(self):
        with pytest.raises(NotFoundError):
            try:
                raise NotFoundError()
            except ProcedureNotFoundError:
                pytest.fail("Should not catch unrelated error type")


class TestErrorSerialization:
    def test_simplify_includes_error_marker(self):
        result = simplify(NotFoundError())
        assert result["__error__"] is True

    def test_simplify_includes_type(self):
        result = simplify(NotFoundError())
        assert result["type"] == "not-found-error"

    def test_error_marker_is_first_key(self):
        result = simplify(NotFoundError())
        first_key = next(iter(result))
        assert first_key == "__error__"

    def test_simplify_includes_fields(self):
        result = simplify(DatabaseUnreachableError(reason="timeout"))
        assert result["reason"] == "timeout"

    def test_to_json_roundtrip(self):
        error = DatabaseUnreachableError(reason="timeout")
        json_str = to_json(error)
        assert '"__error__":true' in json_str
        assert '"reason":"timeout"' in json_str
        assert '"type":"database-unreachable-error"' in json_str

    def test_simplify_optional_field_present(self):
        result = simplify(NotConnectedError(message="detail"))
        assert result["message"] == "detail"

    def test_simplify_optional_field_absent(self):
        result = simplify(NotConnectedError())
        assert result["message"] is None

    def test_type_adapter_serialization(self):
        adapter = TypeAdapter(NotFoundError)
        data = adapter.dump_python(NotFoundError())
        assert data["__error__"] is True
        assert data["type"] == "not-found-error"

    def test_simplify_nested_error(self):
        inner = ComponentValidationError(
            address=Address("@root"),
            problems=[],
        )
        combined = ComponentCombinedError(errors=[inner])
        result = simplify(combined)
        assert result["__error__"] is True
        assert len(result["errors"]) == 1
        assert result["errors"][0]["type"] == "component-validation-error"


class TestErrorFields:
    def test_type_field_default(self):
        assert NotFoundError().type == "not-found-error"

    def test_classvar_status_code(self):
        assert NotFoundError.__error_status_code__ == 404
        assert ProcedureNotFoundError.__error_status_code__ == 400

    def test_computed_error_field(self):
        assert NotFoundError().__error__ is True

    def test_required_field(self):
        with pytest.raises(TypeError):
            DatabaseUnreachableError()  # type: ignore[reportCallIssue]

    def test_required_field_value(self):
        error = DatabaseUnreachableError(reason="host down")
        assert error.reason == "host down"


class TestErrorAsExceptionInTraceback:
    def test_trace_captures_error(self):
        try:
            raise NotFoundError()
        except Error as error:
            info = trace(error)

        assert isinstance(info, ExceptionInfo)
        assert info.type == "NotFoundError"
        assert info.message == "not-found-error"
        assert any("raise NotFoundError" in line for line in info.traceback)

    def test_trace_captures_error_with_fields(self):
        try:
            raise DatabaseUnreachableError(reason="timeout")
        except Error as error:
            info = trace(error)

        assert info.type == "DatabaseUnreachableError"
        assert info.message == "database-unreachable-error"

    def test_error_in_exception_chain(self):
        try:
            try:
                raise ValueError("root cause")
            except ValueError:
                raise NotFoundError() from None
        except NotFoundError as error:
            assert error.__cause__ is None
            assert error.__suppress_context__ is True

    def test_error_chained_from_original(self):
        original = ValueError("root cause")
        try:
            raise NotFoundError() from original
        except NotFoundError as error:
            assert error.__cause__ is original


class TestErrorWithComplexFields:
    def test_error_with_exception_info_field(self):
        info = ExceptionInfo(
            type="ValueError",
            message="bad value",
            traceback=["Traceback ..."],
        )
        error = ProcedureInternalError(exception=info)
        result = simplify(error)
        assert result["exception"]["type"] == "ValueError"
        assert result["exception"]["message"] == "bad value"

    def test_error_with_validation_problems(self):
        problems = [
            ValidationProblem(type="missing", location=["field"], message="required"),
        ]
        error = ComponentValidationError(
            address=Address("@root"),
            problems=problems,
        )
        result = simplify(error)
        assert result["problems"][0]["type"] == "missing"
        assert result["problems"][0]["location"] == ["field"]
