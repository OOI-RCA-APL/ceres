def randstr(characters: str, length: int, /) -> str:
    """Generate a random string by sampling from ``characters``.

    Args:
        characters: The alphabet of characters to sample from.
        length: The number of characters in the resulting string.

    Returns:
        A string of the given ``length`` composed of randomly chosen characters.
    """
    import random

    return "".join(random.choice(characters) for _ in range(length))
