def dbg[T](value: T, /) -> T:
    """Print ``value`` using ``rich.print`` and return it unchanged.

    Useful as an inline debugging helper that can be inserted into expressions without altering
    their result.

    Args:
        value: The value to print and pass through.

    Returns:
        The same ``value``, unmodified.
    """
    import rich

    rich.print(value)
    return value
