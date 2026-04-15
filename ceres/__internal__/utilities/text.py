def strify(value: object, /) -> str:
    try:
        return str(value)
    except Exception:
        return "<__str__() raised exception>"


def reprify(value: object, /) -> str:
    try:
        return repr(value)
    except Exception:
        return "<__repr__() raised exception>"
