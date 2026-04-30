from ceres.__internal__.utilities.exceptions import trace


def _make_exception() -> BaseException:
    try:
        raise ValueError("something went wrong")
    except ValueError as error:
        return error
    raise AssertionError("unreachable")


def test_trace_returns_list_of_strings():
    result = trace(_make_exception())
    assert isinstance(result, list)
    assert all(isinstance(line, str) for line in result)


def test_trace_contains_exception_message():
    result = trace(_make_exception())
    combined = "".join(result)
    assert "something went wrong" in combined


def test_trace_contains_exception_type_name():
    result = trace(_make_exception())
    combined = "".join(result)
    assert "ValueError" in combined
