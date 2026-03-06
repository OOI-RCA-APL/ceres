from typing import Any, Generic, TypeVar

import pytest

from ceres.__internal__.utilities.typing import (
    get_generic_parameter_chain,
    get_generic_superclass_argument,
    get_generic_superclass_arguments,
    get_generic_variable_mapping,
)


def test_generic_variable_mapping():
    TA = TypeVar("TA")
    TB = TypeVar("TB")
    TD = TypeVar("TD")

    class A(Generic[TA]):
        pass

    assert get_generic_variable_mapping(A) == {}
    assert get_generic_superclass_argument(A, A, 0) is TA
    assert get_generic_superclass_arguments(A, A) == (TA,)

    class B(A[TB]):
        pass

    assert get_generic_variable_mapping(B) == {
        (A, TA): (A[TB], TB),  # type: ignore
        (A[TB], TB): (B, TB),  # type: ignore
    }

    assert get_generic_variable_mapping(A[str]) == {
        (A, TA): (A[str], str),
    }

    class C(A[str]):
        pass

    assert get_generic_variable_mapping(C) == {
        (A, TA): (A[str], str),
    }

    class D(B[TD]):
        pass

    assert get_generic_variable_mapping(D) == {
        (B, TB): (B[TD], TD),  # type: ignore
        (B[TD], TD): (D, TD),  # type: ignore
        (A, TA): (A[TB], TB),  # type: ignore
        (A[TB], TB): (B, TB),  # type: ignore
    }


def test_generic_variables():
    class First[A, B]:
        pass

    assert get_generic_variable_mapping(First) == {}
    assert get_generic_superclass_argument(First, First, 0) is First.__type_params__[0]
    assert get_generic_superclass_argument(First, First, 1) is First.__type_params__[1]
    assert get_generic_superclass_arguments(First, First) == (
        First.__type_params__[0],
        First.__type_params__[1],
    )

    with pytest.raises(IndexError):
        get_generic_superclass_argument(First, First, -1)
        get_generic_superclass_argument(First, First, 2)
    with pytest.raises(TypeError, match="does not inherit"):
        get_generic_superclass_argument(First, list, 0)
    with pytest.raises(TypeError, match="`superclass` must be a class"):
        get_generic_superclass_argument(First, 0, 0)  # type: ignore
    with pytest.raises(TypeError, match="`cls` must be a class"):
        get_generic_superclass_argument(0, First, 0)  # type: ignore

    class Second[B](First[int, B]):
        pass

    assert get_generic_superclass_argument(Second, First, 0) is int
    assert get_generic_superclass_argument(Second, First, 1) is Second.__type_params__[0]
    assert get_generic_superclass_arguments(Second, First) == (int, Second.__type_params__[0])

    with pytest.raises(IndexError):
        get_generic_superclass_argument(Second, First, -1)
        get_generic_superclass_argument(Second, First, 2)

    class Third(Second[str]):
        pass

    assert get_generic_superclass_argument(Third, First, 0) is int
    assert get_generic_superclass_argument(Third, First, 1) is str
    assert get_generic_superclass_arguments(Third, First) == (int, str)

    class HasDefault[B = str](Second[B]):
        pass

    assert get_generic_superclass_argument(HasDefault, First, 0) is int
    assert get_generic_superclass_argument(HasDefault, First, 1) is str
    assert get_generic_superclass_arguments(HasDefault, First) == (int, str)

    class OverridesDefault(HasDefault[bool]):
        pass

    assert get_generic_superclass_argument(OverridesDefault, First, 0) is int
    assert get_generic_superclass_argument(OverridesDefault, First, 1) is bool
    assert get_generic_superclass_arguments(OverridesDefault, First) == (int, bool)

    class InheritsDefault(HasDefault):
        pass

    assert get_generic_superclass_argument(InheritsDefault, First, 0) is int
    assert get_generic_superclass_argument(InheritsDefault, First, 1) is str
    assert get_generic_superclass_arguments(InheritsDefault, First) == (int, str)

    class Class[A, B]:
        pass

    alias = Class[int, str]
    assert get_generic_superclass_argument(alias, Class, 0) is int
    assert get_generic_superclass_argument(alias, Class, 1) is str
    assert get_generic_superclass_arguments(alias, Class) == (int, str)

    class Subclass(alias):
        pass

    assert get_generic_superclass_argument(Subclass, Class, 0) is int
    assert get_generic_superclass_argument(Subclass, Class, 1) is str
    assert get_generic_superclass_arguments(Subclass, Class) == (int, str)

    class A[TA]:
        pass

    class B[TB](A[TB]):
        pass

    class C:
        pass

    assert get_generic_superclass_argument(B[C], A, 0) is C
    assert get_generic_superclass_arguments(B[C], A) == (C,)

    class BC(B[C]):
        pass

    assert get_generic_superclass_argument(BC, A, 0) is C
    assert get_generic_superclass_arguments(BC, A) == (C,)


def test_get_associated_generic_parameters():
    class A[TA]:
        pass

    TA: Any = A.__type_params__[0]

    class B[TB](A[TB]):
        pass

    TB: Any = B.__type_params__[0]

    assert get_generic_parameter_chain(B, TB) == [TB, TA]

    class C[TC](B[TC]):
        pass

    TC: Any = C.__type_params__[0]

    assert get_generic_parameter_chain(C, TC) == [TC, TB, TA]
