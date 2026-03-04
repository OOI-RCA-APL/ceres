def randstr(characters: str, length: int, /) -> str:
    import random

    return "".join(random.choice(characters) for _ in range(length))
