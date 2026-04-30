def snakecase(text: str, /) -> str:
    """Convert a string to snake_case.

    >>> snakecase("Hello World")
    'hello_world'
    >>> snakecase("helloWorld")
    'hello_world'
    >>> snakecase("hello-world")
    'hello_world'
    >>> snakecase("hello_world")
    'hello_world'
    >>> snakecase("HELLO")
    'hello'
    """
    import re

    from pydantic.alias_generators import to_snake

    text = text.strip()
    # Convert all runs of whitespace and hyphens to a single underscore.
    text = re.sub(r"[\s-]+", "_", text)
    return to_snake(text)


def kebabcase(text: str, /) -> str:
    """Convert a string to kebab-case.

    >>> kebabcase("Hello World")
    'hello-world'
    >>> kebabcase("helloWorld")
    'hello-world'
    >>> kebabcase("hello-world")
    'hello-world'
    >>> kebabcase("hello_world")
    'hello-world'
    >>> kebabcase("HELLO")
    'hello'
    """
    return snakecase(text).replace("_", "-")


def ucamelcase(text: str, /) -> str:
    """Convert a string to UpperCamelCase (PascalCase).

    >>> upper_camelcase("Hello World")
    'HelloWorld'
    >>> upper_camelcase("helloWorld")
    'HelloWorld'
    >>> upper_camelcase("hello-world")
    'HelloWorld'
    >>> upper_camelcase("hello_world")
    'HelloWorld'
    >>> upper_camelcase("HELLO")
    'Hello'
    """
    import re

    from pydantic.alias_generators import to_camel

    text = text.strip()
    # Convert all runs of whitespace and hyphens to a single underscore.
    text = re.sub(r"[\s-]+", "_", text)
    text = to_camel(text)
    if not text:
        return ""

    return text[0].upper() + text[1:]  # Capitalize the first letter.


def titlecase(string: str, /) -> str:
    """Convert a string to Title Case.

    >>> titlecase("Hello World")
    'Hello World'
    >>> titlecase("helloWorld")
    'Hello World'
    >>> titlecase("hello-world")
    'Hello World'
    >>> titlecase("hello_world")
    'Hello World'
    >>> titlecase("HELLO")
    'Hello'
    """
    return " ".join(segment.capitalize() for segment in snakecase(string).split("_"))
