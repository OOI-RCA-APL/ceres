def strify(value: object, /) -> str:
    """Call ``str()`` on ``value``, returning a fallback message if it raises an exception.

    Args:
        value: The object to convert to a string.

    Returns:
        The string representation, or a placeholder if ``__str__`` raises.
    """
    try:
        return str(value)
    except Exception:
        return "<__str__() raised exception>"


def reprify(value: object, /) -> str:
    """Call ``repr()`` on ``value``, returning a fallback message if it raises an exception.

    Args:
        value: The object to convert to its repr.

    Returns:
        The repr string, or a placeholder if ``__repr__`` raises.
    """
    try:
        return repr(value)
    except Exception:
        return "<__repr__() raised exception>"
