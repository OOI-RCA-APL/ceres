def tokenize_bytes(value: bytes, /) -> str:
    """Convert a bytes value to a space-separated hex string suitable for database tokenization.

    Return an empty string for empty bytes. Otherwise, return a hex representation with
    space-separated byte pairs and a trailing space for token boundary matching.

    Args:
        value: The raw bytes to tokenize.

    Returns:
        A hex-encoded string with spaces between each byte and a trailing space, or an empty
        string if the input is empty.
    """
    if not value:
        return ""

    return value.hex(b" ") + " "
