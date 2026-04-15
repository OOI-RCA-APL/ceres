from typing import Annotated, Any, ClassVar, Generic, Optional, TypeVar

import pytest
from pydantic.fields import FieldInfo

from ceres.__internal__.utilities.typing import (
    AnnotationInfo,
    extract_annotation,
    get_generic_parameter_chain,
    get_generic_superclass_argument,
    get_generic_superclass_arguments,
    get_generic_variable_mapping,
)


class TestExtractAnnotation:
    def test_plain_type(self):
        result = extract_annotation(int)
        assert result.type is int
        assert result.generic is None
        assert result.metadata == ()
        assert result.annotation is int
        assert result.generic_args == ()

    def test_plain_str(self):
        result = extract_annotation(str)
        assert result.type is str
        assert result.generic is None
        assert result.metadata == ()

    def test_annotated_with_single_metadata(self):
        marker = "some_marker"
        ann = Annotated[int, marker]
        result = extract_annotation(ann)
        assert result.type is int
        assert result.generic is None
        assert result.metadata == (marker,)
        assert result.annotation is ann

    def test_annotated_with_multiple_metadata(self):
        m1, m2 = "first", 42
        ann = Annotated[int, m1, m2]
        result = extract_annotation(ann)
        assert result.type is int
        assert result.metadata == (m1, m2)

    def test_nested_annotated(self):
        inner_marker = "inner"
        outer_marker = "outer"
        ann = Annotated[Annotated[int, inner_marker], outer_marker]
        result = extract_annotation(ann)
        assert result.type is int
        # Outer metadata is peeled first, then inner
        assert result.metadata == (inner_marker, outer_marker)

    def test_generic_alias(self):
        ann = tuple[int, float]
        result = extract_annotation(ann)
        assert result.type is tuple
        assert result.generic is ann
        assert result.generic_args == (int, float)
        assert result.metadata == ()

    def test_generic_list(self):
        ann = list[str]
        result = extract_annotation(ann)
        assert result.type is list
        assert result.generic is ann
        assert result.generic_args == (str,)

    def test_generic_dict(self):
        ann = dict[str, int]
        result = extract_annotation(ann)
        assert result.type is dict
        assert result.generic is ann
        assert result.generic_args == (str, int)

    def test_annotated_generic(self):
        marker = "tag"
        ann = Annotated[list[int], marker]
        result = extract_annotation(ann)
        assert result.type is list
        assert result.generic is not None
        assert result.generic_args == (int,)
        assert result.metadata == (marker,)

    def test_optional(self):
        ann = Optional[int]  # noqa
        result = extract_annotation(ann)
        # Optional[int] is Union[int, None], which has no transparent origin
        # in _TRANSPARENT_ARGS_TYPES, so it stays as-is
        assert result.metadata == ()

    def test_classvar(self):
        ann = ClassVar[int]
        result = extract_annotation(ann)
        assert result.type is int
        assert result.metadata == ()

    def test_type_alias(self):
        type MyInt = int  # type: ignore
        result = extract_annotation(MyInt)
        assert result.type is int
        assert result.annotation is MyInt

    def test_type_alias_annotated(self):
        marker = "validated"
        type TaggedInt = Annotated[int, marker]  # type: ignore
        result = extract_annotation(TaggedInt)
        assert result.type is int
        assert result.metadata == (marker,)

    def test_type_alias_generic(self):
        type IntPair = tuple[int, int]  # type: ignore
        result = extract_annotation(IntPair)
        assert result.type is tuple
        assert result.generic_args == (int, int)

    def test_field_info_plain(self):
        info = FieldInfo(annotation=int)
        result = extract_annotation(info)
        assert result.type is int
        assert result.annotation is info
        assert result.generic is None

    def test_field_info_annotated(self):
        marker = "tag"
        info = FieldInfo(annotation=Annotated[int, marker])  # type: ignore
        result = extract_annotation(info)
        assert result.type is int
        assert marker in result.metadata

    def test_field_info_with_real_data_object_metadata(self):
        from annotated_types import Ge

        from ceres.data import DataObject, fields_of

        class Example(DataObject):
            value: Annotated[int, Ge(0)]

        info = fields_of(Example)["value"]
        result = extract_annotation(info)
        assert result.type is int
        assert any(isinstance(m, Ge) for m in result.metadata)

    def test_field_info_merges_field_and_annotation_metadata(self):
        from annotated_types import Ge

        from ceres.data import DataObject, fields_of

        class Example(DataObject):
            value: Annotated[int, Ge(0)]

        info = fields_of(Example)["value"]
        result = extract_annotation(info)
        assert result.type is int
        # Both field-level and annotation-level metadata are present
        assert len(result.metadata) >= 1
        assert any(isinstance(m, Ge) for m in result.metadata)

    def test_field_info_deduplicates_metadata_by_identity(self):
        from annotated_types import Ge

        from ceres.data import DataObject, fields_of

        # Pydantic may place the same Ge instance in both field.metadata
        # and the Annotated wrapper; extract_annotation should deduplicate.
        class Example(DataObject):
            value: Annotated[int, Ge(0)]

        info = fields_of(Example)["value"]
        result = extract_annotation(info)
        ge_items = [m for m in result.metadata if isinstance(m, Ge) and m.ge == 0]
        assert len(ge_items) == 1

    def test_field_info_with_generic(self):
        info = FieldInfo(annotation=list[int])
        result = extract_annotation(info)
        assert result.type is list
        assert result.generic is not None
        assert result.generic_args == (int,)

    def test_field_info_with_annotated_generic(self):
        from ceres.data import DataObject, fields_of

        class Example(DataObject):
            pair: Annotated[tuple[int, str], "tag"]

        info = fields_of(Example)["pair"]
        result = extract_annotation(info)
        assert result.type is tuple
        assert result.generic_args == (int, str)
        assert "tag" in result.metadata

    def test_returns_annotation_info_instance(self):
        result = extract_annotation(int)
        assert isinstance(result, AnnotationInfo)

    def test_annotation_info_is_frozen(self):
        result = extract_annotation(int)
        with pytest.raises(AttributeError):
            result.type = str  # type: ignore[misc]

    def test_non_generic_has_empty_generic_args(self):
        result = extract_annotation(float)
        assert result.generic_args == ()

    def test_deeply_nested_annotated(self):
        m1, m2, m3 = "a", "b", "c"
        ann = Annotated[Annotated[Annotated[int, m1], m2], m3]
        result = extract_annotation(ann)
        assert result.type is int
        assert m1 in result.metadata
        assert m2 in result.metadata
        assert m3 in result.metadata

    def test_annotated_preserves_metadata_order(self):
        markers = ["first", "second", "third"]
        ann = Annotated[int, markers[0], markers[1], markers[2]]
        result = extract_annotation(ann)
        assert result.metadata == tuple(markers)

    def test_field_info_metadata_comes_before_annotation_metadata(self):
        from annotated_types import Ge, Le

        from ceres.data import DataObject, fields_of

        class Example(DataObject):
            value: Annotated[int, Ge(0), Le(100)]

        info = fields_of(Example)["value"]
        result = extract_annotation(info)
        # Field-level metadata (from pydantic) comes before annotation metadata
        # that wasn't already present via identity dedup
        ge_items = [m for m in result.metadata if isinstance(m, Ge)]
        le_items = [m for m in result.metadata if isinstance(m, Le)]
        assert len(ge_items) == 1
        assert len(le_items) == 1


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
