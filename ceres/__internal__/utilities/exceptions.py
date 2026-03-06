import traceback


def trace(exception: BaseException) -> list[str]:
    return traceback.format_exception(exception)
