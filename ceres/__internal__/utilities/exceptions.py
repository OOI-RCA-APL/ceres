import traceback


def trace(exception: BaseException) -> list[str]:
    """Format an exception's full traceback as a list of strings.

    Args:
        exception: The exception to format.

    Returns:
        A list of pre-formatted traceback lines, suitable for logging or display.
    """
    return traceback.format_exception(exception)
