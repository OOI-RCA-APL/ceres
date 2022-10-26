from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseConfig, BaseModel

from ceres.internal.container import Container, is_proxy


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


def test_has_cached_is_false_when_empty() -> None:
    container = Container()
    assert not container.has_cached(Dummy)


def test_has_cached_is_false_when_provided() -> None:
    container = Container()
    for _ in range(10):
        container.provide(Dummy)
        assert not container.has_cached(Dummy)


def test_has_cached_is_true_when_set() -> None:
    container = Container()
    for _ in range(10):
        container.set(Dummy, Dummy())
        assert container.has_cached(Dummy)
        assert not container.has_cached(DerivedDummy)


def test_has_cached_is_true_after_get() -> None:
    container = Container()
    for _ in range(10):
        container.get(Dummy)
        assert container.has_cached(Dummy)
        assert not container.has_cached(DerivedDummy)


def test_has_provider_is_false_when_empty() -> None:
    container = Container()
    assert not container.has_provider(Dummy)


def test_has_provider_is_true_when_provided() -> None:
    container = Container()
    for _ in range(10):
        container.provide(Dummy)
        assert container.has_provider(Dummy)
        assert not container.has_provider(DerivedDummy)


def test_has_provider_true_when_set() -> None:
    container = Container()
    for _ in range(10):
        container.set(Dummy, Dummy())
        assert container.has_provider(Dummy)
        assert not container.has_provider(DerivedDummy)


def test_provide_self() -> None:
    container = Container()
    container.provide(Dummy)

    original = container.get(Dummy)

    for _ in range(10):
        assert container.get(Dummy) is original

    for _ in range(10):
        other = container.get(Dummy, cached=False)
        assert other == Dummy()
        assert other is not original


def test_provide_subtype() -> None:
    container = Container()
    container.provide(Dummy, DerivedDummy)

    original = container.get(Dummy)
    assert original == DerivedDummy()

    for _ in range(10):
        assert container.get(Dummy) is original

    for _ in range(10):
        other = container.get(Dummy, cached=False)
        assert other == DerivedDummy()
        assert other is not original


def test_provide_lambda() -> None:
    container = Container()
    container.provide(Dummy, lambda: DerivedDummy())

    original = container.get(Dummy)
    assert original == DerivedDummy()

    for _ in range(10):
        assert container.get(Dummy) is original

    for _ in range(10):
        other = container.get(Dummy, cached=False)
        assert other == DerivedDummy()
        assert other is not original


def test_clear_provided() -> None:
    container = Container()
    container.provide(Dummy, Dummy)
    container.provide(DerivedDummy, DerivedDummy)

    assert container.has_provider(Dummy)
    assert container.has_provider(DerivedDummy)
    assert not container.has_cached(Dummy)
    assert not container.has_cached(DerivedDummy)

    for _ in range(10):
        container.clear()

        assert not container.has_provider(Dummy)
        assert not container.has_provider(DerivedDummy)
        assert not container.has_cached(Dummy)
        assert not container.has_cached(DerivedDummy)


def test_clear_cached() -> None:
    container = Container()

    container.get(Dummy)
    container.get(DerivedDummy)

    assert container.has_provider(Dummy)
    assert container.has_provider(DerivedDummy)
    assert container.has_cached(Dummy)
    assert container.has_cached(DerivedDummy)

    for _ in range(10):
        container.clear()

        assert not container.has_provider(Dummy)
        assert not container.has_provider(DerivedDummy)
        assert not container.has_cached(Dummy)
        assert not container.has_cached(DerivedDummy)


def test_remove_provided() -> None:
    container = Container()
    container.provide(Dummy, Dummy)
    container.provide(DerivedDummy, DerivedDummy)

    assert container.has_provider(Dummy)
    assert container.has_provider(DerivedDummy)
    assert not container.has_cached(Dummy)
    assert not container.has_cached(DerivedDummy)

    container.remove(Dummy)

    assert not container.has_provider(Dummy)
    assert container.has_provider(DerivedDummy)
    assert not container.has_provider(Dummy)
    assert not container.has_cached(Dummy)

    container.remove(DerivedDummy)

    assert not container.has_provider(Dummy)
    assert not container.has_provider(DerivedDummy)
    assert not container.has_provider(Dummy)
    assert not container.has_cached(Dummy)


def test_set() -> None:
    container = Container()

    original = Dummy()
    container.set(Dummy, original)

    assert container.has_provider(Dummy)
    assert container.has_cached(Dummy)

    assert container.get(Dummy) is original


class SingleDependency:
    def __init__(self, dependency: Dummy) -> None:
        self.dependency = dependency

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, SingleDependency)
            and type(self) is type(other)
            and self.dependency == other.dependency
        )


def test_get_class_with_one_dependency() -> None:
    container = Container()
    single = container.get(SingleDependency)
    assert single == SingleDependency(Dummy())


class MultipleDependencies:
    def __init__(self, a: Dummy, b: DerivedDummy, c: int, d: str) -> None:
        self.dependencies = [a, b, c, d]

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, MultipleDependencies)
            and type(self) is type(other)
            and self.dependencies == other.dependencies
        )


def test_get_class_with_multiple_dependencies() -> None:
    container = Container()
    container.provide(int, lambda: 5)
    multiple = container.get(MultipleDependencies)
    assert multiple == MultipleDependencies(Dummy(), DerivedDummy(), 5, "")


@dataclass
class MultipleDependencyDataclass:
    a: Dummy
    b: DerivedDummy
    c: int
    d: str


def test_get_dataclass_with_multiple_dependencies() -> None:
    container = Container()
    container.set(int, 5)
    multiple = container.get(MultipleDependencyDataclass)
    assert multiple == MultipleDependencyDataclass(Dummy(), DerivedDummy(), 5, "")


class MultipleDependencyBaseModel(BaseModel):
    class Config(BaseConfig):
        arbitrary_types_allowed = True

    a: Dummy
    b: DerivedDummy
    c: int
    d: str


def test_get_base_model_with_multiple_dependencies() -> None:
    container = Container()
    container.set(int, 5)
    multiple = container.get(MultipleDependencyBaseModel)
    assert multiple == MultipleDependencyBaseModel(a=Dummy(), b=DerivedDummy(), c=5, d="")


@dataclass
class Three(TypeEquals):
    pass


@dataclass
class Two(TypeEquals):
    inner: Three


@dataclass
class One(TypeEquals):
    inner: Two


def test_get_nested_dependencies() -> None:
    container = Container()
    one = container.get(One)
    assert one == One(Two(Three()))


@dataclass
class ThreeCyclical(Three):
    inner: One


def test_get_nested_dependencies_with_cycle() -> None:
    container = Container()
    container.provide(Three, ThreeCyclical)

    one = container.get(One)
    cyclical = one.inner.inner

    assert one == One(Two(ThreeCyclical(one)))
    assert not is_proxy(one)
    assert not is_proxy(one.inner)
    assert isinstance(cyclical, ThreeCyclical) and is_proxy(cyclical.inner)
