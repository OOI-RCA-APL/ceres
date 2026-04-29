from collections.abc import Callable
from typing import Any


def get_function_name(function: Callable[..., Any], /) -> str:
    """Return the effective name of ``function``, accounting for Python name-mangling.

    For functions whose names start with ``__`` (but do not end with ``__``), reconstruct the
    mangled name by prepending the defining class name.

    Args:
        function: The callable whose name to retrieve.

    Returns:
        The function's name as it would appear on the owning class.
    """
    original = function.__name__

    if function.__name__.startswith("__") and not function.__name__.endswith("__"):
        tokens = function.__qualname__.split(".")
        if len(tokens) < 2:
            return original

        return f"_{tokens[-2]}{original}"

    return original


def get_inner_function(function: Callable[..., Any], /) -> Callable[..., Any]:
    """Unwrap a decorated or bound function to find the innermost callable.

    Follow ``__wrapped__`` and ``__func__`` attributes until neither is present.

    Args:
        function: The callable to unwrap.

    Returns:
        The innermost underlying callable.
    """
    while True:
        __wrapped__ = getattr(function, "__wrapped__", None)
        if __wrapped__ is not None:
            function = __wrapped__
            continue

        __func__ = getattr(function, "__func__", None)
        if __func__ is not None and __func__ is not function:
            function = __func__
            continue

        break

    return function


def call_partial[**P, T](function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """Call ``function`` with only the positional and keyword arguments it actually accepts.

    Inspect the function's signature and discard any extra positional arguments beyond its arity
    and any keyword arguments it does not declare.

    Args:
        function: The callable to invoke.
        *args: Positional arguments, trimmed to the function's arity.
        **kwargs: Keyword arguments, filtered to those the function declares.

    Returns:
        The return value of calling ``function`` with the applicable arguments.
    """
    import inspect

    parameters = inspect.signature(function).parameters
    arity = len(
        [
            current
            for current in parameters.values()
            if current.kind != inspect.Parameter.KEYWORD_ONLY
        ]
    )

    applied_args = args[:arity]
    applied_kwargs: dict[str, Any] = {}

    for key, value in kwargs.items():
        parameter = parameters.get(key)
        if parameter is not None and parameter.kind != inspect.Parameter.POSITIONAL_ONLY:
            applied_kwargs[key] = value

    return function(*applied_args, **applied_kwargs)  # type: ignore
