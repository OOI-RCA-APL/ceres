def dbg[T](value: T, /) -> T:
    import rich

    rich.print(value)
    return value
