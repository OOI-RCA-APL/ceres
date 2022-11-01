from dataclasses import dataclass


class TypeEquals:
    def __eq__(self, other: object) -> bool:
        return type(self) is type(other) and super().__eq__(other)


@dataclass
class Dummy(TypeEquals):
    pass


@dataclass
class DerivedDummy(Dummy):
    pass


assert Dummy() == Dummy()
assert Dummy() != DerivedDummy()


@dataclass
class Three(TypeEquals):
    pass


@dataclass
class Two(TypeEquals):
    inner: Three


@dataclass
class One(TypeEquals):
    inner: Two


@dataclass
class ThreeCyclical(Three):
    inner: One


class MultipleDependencies:
    def __init__(self, a: Dummy, b: DerivedDummy, c: int, d: str) -> None:
        self.dependencies = [a, b, c, d]

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, MultipleDependencies)
            and type(self) is type(other)
            and self.dependencies == other.dependencies
        )


@dataclass
class MultipleDependencyDataclass:
    a: Dummy
    b: DerivedDummy
    c: int
    d: str
