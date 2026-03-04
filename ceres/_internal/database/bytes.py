def tokenize_bytes(value: bytes, /) -> str:
    if not value:
        return ""

    return value.hex(b" ") + " "
