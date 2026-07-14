import copy

import pytest
from sqlalchemy import Column, MetaData, Table, create_engine, select

from ceres.__internal__.database.types import AddressMapper
from ceres.address import Address, AddressSelector, DynamicAddress


class TestAddressSelector:
    def test_construct_from_string(self) -> None:
        selector = AddressSelector("@sensor")
        assert selector.text == "@sensor"

    def test_construct_from_existing_selector_returns_same_object(self) -> None:
        selector = AddressSelector("@sensor")
        same = AddressSelector(selector)
        assert same is selector

    def test_construct_from_sequence_of_strings(self) -> None:
        selector = AddressSelector(["@sensor", "@motor"])
        assert selector.text == "@sensor|@motor"

    def test_construct_from_sequence_of_selectors(self) -> None:
        first = AddressSelector("@sensor")
        second = AddressSelector("@motor")
        combined = AddressSelector([first, second])
        assert combined.text == "@sensor|@motor"

    def test_construct_from_mixed_sequence(self) -> None:
        selector = AddressSelector(["@sensor", AddressSelector("@motor")])
        assert selector.text == "@sensor|@motor"

    def test_invalid_string_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="must match regex"):
            AddressSelector("!!!")

    def test_str_returns_text(self) -> None:
        selector = AddressSelector("@sensor")
        assert str(selector) == "@sensor"

    def test_repr(self) -> None:
        selector = AddressSelector("@sensor")
        assert repr(selector) == "AddressSelector('@sensor')"

    def test_hash_matches_equal_selectors(self) -> None:
        first = AddressSelector("@sensor")
        second = AddressSelector("@sensor")
        assert hash(first) == hash(second)

    def test_equality_with_same_text(self) -> None:
        first = AddressSelector("@sensor")
        second = AddressSelector("@sensor")
        assert first == second

    def test_inequality_with_different_text(self) -> None:
        first = AddressSelector("@sensor")
        second = AddressSelector("@motor")
        assert first != second

    def test_not_equal_to_non_selector(self) -> None:
        selector = AddressSelector("@sensor")
        assert selector != "@sensor"

    def test_less_than_comparison(self) -> None:
        first = AddressSelector("@aaa")
        second = AddressSelector("@zzz")
        assert first < second
        assert not second < first

    def test_less_than_non_selector_returns_not_implemented(self) -> None:
        selector = AddressSelector("@sensor")
        assert selector.__lt__("@sensor") is NotImplemented

    def test_or_combines_selectors(self) -> None:
        first = AddressSelector("@sensor")
        second = AddressSelector("@motor")
        combined = first | second
        assert combined.text == "@sensor|@motor"

    def test_segments_property(self) -> None:
        selector = AddressSelector("@sensor|@motor|@relay")
        segments = selector.segments
        assert len(segments) == 3
        assert segments[0].text == "@sensor"
        assert segments[1].text == "@motor"
        assert segments[2].text == "@relay"

    def test_single_segment_selector(self) -> None:
        selector = AddressSelector("@sensor")
        segments = selector.segments
        assert len(segments) == 1
        assert segments[0].text == "@sensor"

    def test_copy_returns_same_instance(self) -> None:
        selector = AddressSelector("@sensor")
        assert copy.copy(selector) is selector

    def test_deepcopy_returns_same_instance(self) -> None:
        selector = AddressSelector("@sensor")
        assert copy.deepcopy(selector) is selector

    def test_pickle_roundtrip(self) -> None:
        import pickle

        selector = AddressSelector("@sensor|@motor")
        restored = pickle.loads(pickle.dumps(selector))
        assert restored == selector
        assert restored.text == "@sensor|@motor"

    def test_caching_returns_same_instance_for_same_string(self) -> None:
        first = AddressSelector("@cached-test")
        second = AddressSelector("@cached-test")
        assert first is second

    def test_engine_selector(self) -> None:
        selector = AddressSelector("~")
        assert selector.text == "~"

    def test_modifier_all(self) -> None:
        selector = AddressSelector("@sensor:all")
        assert selector.text == "@sensor:all"

    def test_modifier_children(self) -> None:
        selector = AddressSelector("@sensor:children")
        assert selector.text == "@sensor:children"

    def test_modifier_descendants(self) -> None:
        selector = AddressSelector("@sensor:descendants")
        assert selector.text == "@sensor:descendants"

    def test_bare_all_modifier(self) -> None:
        selector = AddressSelector(":all")
        assert selector.text == ":all"


class TestAddressSelectorMatching:
    def test_exact_match(self) -> None:
        selector = AddressSelector("@sensor")
        assert selector.matches(Address("@sensor"), None)
        assert not selector.matches(Address("@motor"), None)

    def test_all_modifier_matches_self_and_descendants(self) -> None:
        selector = AddressSelector("@parent:all")
        assert selector.matches(Address("@parent"), None)
        assert selector.matches(Address("@parent.child"), None)
        assert selector.matches(Address("@parent.child.grandchild"), None)
        assert not selector.matches(Address("@other"), None)

    def test_descendants_modifier_excludes_self(self) -> None:
        selector = AddressSelector("@parent:descendants")
        assert not selector.matches(Address("@parent"), None)
        assert selector.matches(Address("@parent.child"), None)
        assert selector.matches(Address("@parent.child.grandchild"), None)

    def test_children_modifier_matches_only_immediate_children(self) -> None:
        selector = AddressSelector("@parent:children")
        assert not selector.matches(Address("@parent"), None)
        assert selector.matches(Address("@parent.child"), None)
        assert not selector.matches(Address("@parent.child.grandchild"), None)

    def test_engine_all_matches_everything(self) -> None:
        selector = AddressSelector("~:all")
        assert selector.matches(Address("~"), None)
        assert selector.matches(Address("@sensor"), None)
        assert selector.matches(Address("@sensor.child"), None)

    def test_engine_descendants_excludes_engine(self) -> None:
        selector = AddressSelector("~:descendants")
        assert not selector.matches(Address("~"), None)
        assert selector.matches(Address("@sensor"), None)

    def test_root_all_matches_all_except_engine(self) -> None:
        selector = AddressSelector("@:all")
        assert not selector.matches(Address("~"), None)
        assert selector.matches(Address("@sensor"), None)
        assert selector.matches(Address("@sensor.child"), None)

    def test_root_descendants_matches_all_components(self) -> None:
        # `@:descendants` aliases `@:all` now that bare `@` cannot be matched or constructed.
        selector = AddressSelector("@:descendants")
        assert not selector.matches(Address("~"), None)
        assert selector.matches(Address("@sensor"), None)
        assert selector.matches(Address("@sensor.child"), None)

    def test_root_children_matches_only_top_level_components(self) -> None:
        selector = AddressSelector("@:children")
        assert not selector.matches(Address("~"), None)
        assert selector.matches(Address("@sensor"), None)
        assert not selector.matches(Address("@sensor.child"), None)

    def test_pipe_separated_matches_any_segment(self) -> None:
        selector = AddressSelector("@sensor|@motor")
        assert selector.matches(Address("@sensor"), None)
        assert selector.matches(Address("@motor"), None)
        assert not selector.matches(Address("@relay"), None)

    def test_relative_selector_resolves_against_root(self) -> None:
        selector = AddressSelector("child")
        assert selector.matches(Address("@parent.child"), Address("@parent"))
        assert not selector.matches(Address("@parent"), Address("@parent"))

    def test_relative_selector_resolves_against_engine(self) -> None:
        # When root is the engine (or None), the selector resolves against `@` instead.
        selector = AddressSelector("child")
        assert selector.matches(Address("@child"), Address("~"))
        assert selector.matches(Address("@child"), None)

    def test_modifier_relative_to_root(self) -> None:
        selector = AddressSelector(":children")
        assert selector.matches(Address("@parent.child"), Address("@parent"))
        assert not selector.matches(Address("@parent.child.grandchild"), Address("@parent"))

    def test_modifier_all_relative_to_root(self) -> None:
        selector = AddressSelector(":all")
        assert selector.matches(Address("@parent"), Address("@parent"))
        assert selector.matches(Address("@parent.child"), Address("@parent"))

    def test_no_match_returns_false(self) -> None:
        selector = AddressSelector("@nonexistent")
        assert not selector.matches(Address("@sensor"), None)


class TestAddressSelectorAsAbsolute:
    def test_absolute_segment_left_unchanged(self) -> None:
        selector = AddressSelector("@sensor")
        absolute = selector.as_absolute(None)
        assert absolute.text == "@sensor"

    def test_engine_segment_left_unchanged(self) -> None:
        selector = AddressSelector("~")
        absolute = selector.as_absolute(None)
        assert absolute.text == "~"

    def test_modifier_segment_prefixed_with_root(self) -> None:
        selector = AddressSelector(":children")
        absolute = selector.as_absolute(Address("@parent"))
        assert absolute.text == "@parent:children"

    def test_relative_segment_joined_to_root(self) -> None:
        selector = AddressSelector("child")
        absolute = selector.as_absolute(Address("@parent"))
        assert absolute.text == "@parent.child"

    def test_relative_segment_joined_to_none_root(self) -> None:
        selector = AddressSelector("child")
        absolute = selector.as_absolute(None)
        assert absolute.text == "@child"

    def test_engine_root_resolves_to_actual_root(self) -> None:
        selector = AddressSelector("child")
        absolute = selector.as_absolute(Address.ENGINE)
        assert absolute.text == "@child"

    def test_modifier_with_engine_root(self) -> None:
        selector = AddressSelector(":all")
        absolute = selector.as_absolute(Address.ENGINE)
        assert absolute.text == "@:all"


class TestDynamicAddress:
    def test_construct_from_string(self) -> None:
        address = DynamicAddress("sensor")
        assert str(address) == "sensor"

    def test_construct_from_absolute_string(self) -> None:
        address = DynamicAddress("@sensor")
        assert str(address) == "@sensor"

    def test_construct_engine(self) -> None:
        address = DynamicAddress("~")
        assert str(address) == "~"

    def test_all_keyword_rejected(self) -> None:
        with pytest.raises(ValueError, match="cannot be used as an address"):
            DynamicAddress("all")

    def test_invalid_address_raises(self) -> None:
        with pytest.raises(ValueError, match="must match regex"):
            DynamicAddress("!!!")

    def test_construct_from_selector(self) -> None:
        selector = AddressSelector("@sensor")
        address = DynamicAddress(selector)
        assert str(address) == "@sensor"

    def test_construct_from_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError, match="must be an instance"):
            DynamicAddress(42)  # type: ignore[arg-type]

    def test_is_engine(self) -> None:
        assert DynamicAddress("~").is_engine
        assert not DynamicAddress("@sensor").is_engine
        assert not DynamicAddress("sensor").is_engine

    def test_is_absolute(self) -> None:
        assert DynamicAddress("~").is_absolute
        assert DynamicAddress("@sensor").is_absolute
        assert not DynamicAddress("sensor").is_absolute

    def test_is_relative(self) -> None:
        assert DynamicAddress("sensor").is_relative
        assert DynamicAddress("parent.child").is_relative
        assert not DynamicAddress("@sensor").is_relative
        assert not DynamicAddress("~").is_relative


class TestDynamicAddressName:
    def test_name_of_simple_address(self) -> None:
        assert DynamicAddress("sensor").name == "sensor"

    def test_name_of_dotted_address(self) -> None:
        assert DynamicAddress("parent.child").name == "child"

    def test_name_of_absolute_address(self) -> None:
        assert DynamicAddress("@sensor").name == "sensor"

    def test_name_of_deep_absolute_address(self) -> None:
        assert DynamicAddress("@parent.child.grandchild").name == "grandchild"

    def test_name_of_engine_is_none(self) -> None:
        assert DynamicAddress("~").name is None


class TestDynamicAddressParent:
    def test_parent_of_dotted_address(self) -> None:
        address = DynamicAddress("@parent.child")
        assert address.parent is not None
        assert str(address.parent) == "@parent"

    def test_parent_of_deep_address(self) -> None:
        address = DynamicAddress("@parent.child.grandchild")
        assert address.parent is not None
        assert str(address.parent) == "@parent.child"

    def test_parent_of_top_level_component_is_none(self) -> None:
        address = DynamicAddress("@sensor")
        assert address.parent is None

    def test_parent_of_engine_is_none(self) -> None:
        assert DynamicAddress("~").parent is None

    def test_parent_of_relative_bare_name_is_none(self) -> None:
        assert DynamicAddress("sensor").parent is None

    def test_parent_of_relative_dotted_name(self) -> None:
        address = DynamicAddress("parent.child")
        assert address.parent is not None
        assert str(address.parent) == "parent"


class TestDynamicAddressContainer:
    def test_container_of_dotted_address(self) -> None:
        address = DynamicAddress("@parent.child")
        assert str(address.container) == "@parent"

    def test_container_of_bare_name_is_engine(self) -> None:
        address = DynamicAddress("sensor")
        assert str(address.container) == "~"

    def test_container_of_engine_is_engine(self) -> None:
        address = DynamicAddress("~")
        assert str(address.container) == "~"

    def test_container_of_top_level_component_is_engine(self) -> None:
        address = DynamicAddress("@sensor")
        assert str(address.container) == "~"


class TestDynamicAddressDepth:
    def test_engine_depth_is_zero(self) -> None:
        assert DynamicAddress("~").depth == 0

    def test_top_level_component_depth(self) -> None:
        assert DynamicAddress("@sensor").depth == 1

    def test_nested_component_depth(self) -> None:
        assert DynamicAddress("@parent.child.grandchild").depth == 3

    def test_relative_depth(self) -> None:
        assert DynamicAddress("sensor").depth == 1
        assert DynamicAddress("parent.child").depth == 2


class TestDynamicAddressPath:
    def test_engine_path(self) -> None:
        path = DynamicAddress("~").path
        assert len(path) == 1
        assert str(path[0]) == "~"

    def test_nested_path(self) -> None:
        path = DynamicAddress("@parent.child.grandchild").path
        assert [str(segment) for segment in path] == [
            "@parent",
            "@parent.child",
            "@parent.child.grandchild",
        ]

    def test_top_level_path(self) -> None:
        path = DynamicAddress("@sensor").path
        assert [str(segment) for segment in path] == ["@sensor"]


class TestDynamicAddressAncestors:
    def test_engine_has_no_ancestors(self) -> None:
        assert DynamicAddress("~").ancestors == []

    def test_top_level_has_no_ancestors(self) -> None:
        assert DynamicAddress("@sensor").ancestors == []

    def test_nested_ancestors(self) -> None:
        ancestors = DynamicAddress("@parent.child.grandchild").ancestors
        assert [str(ancestor) for ancestor in ancestors] == ["@parent.child", "@parent"]


class TestDynamicAddressNames:
    def test_engine_has_no_names(self) -> None:
        assert DynamicAddress("~").names == []

    def test_simple_name(self) -> None:
        assert list(DynamicAddress("@sensor").names) == ["sensor"]

    def test_nested_names(self) -> None:
        assert list(DynamicAddress("@parent.child.grandchild").names) == [
            "parent",
            "child",
            "grandchild",
        ]

    def test_relative_names(self) -> None:
        assert list(DynamicAddress("parent.child").names) == ["parent", "child"]


class TestDynamicAddressDivision:
    def test_join_relative_to_absolute(self) -> None:
        address = DynamicAddress("@parent") / "child"
        assert str(address) == "@parent.child"

    def test_join_engine_returns_engine(self) -> None:
        address = DynamicAddress("~") / "anything"
        assert str(address) == "~"

    def test_chain_joins(self) -> None:
        address = DynamicAddress("@parent") / "child" / "grandchild"
        assert str(address) == "@parent.child.grandchild"

    def test_join_with_dynamic_address(self) -> None:
        address = DynamicAddress("@parent") / DynamicAddress("child")
        assert str(address) == "@parent.child"


class TestDynamicAddressAsAbsolute:
    def test_absolute_address_returned_as_is(self) -> None:
        address = DynamicAddress("@sensor")
        absolute = address.as_absolute(None)
        assert str(absolute) == "@sensor"

    def test_relative_address_resolved_against_root(self) -> None:
        address = DynamicAddress("child")
        absolute = address.as_absolute(Address("@parent"))
        assert str(absolute) == "@parent.child"

    def test_relative_address_resolved_against_none_root(self) -> None:
        address = DynamicAddress("child")
        absolute = address.as_absolute(None)
        assert str(absolute) == "@child"

    def test_engine_returned_as_is(self) -> None:
        address = DynamicAddress("~")
        absolute = address.as_absolute(None)
        assert str(absolute) == "~"


class TestDynamicAddressAsRelative:
    def test_engine_returns_none(self) -> None:
        assert DynamicAddress("~").as_relative() is None

    def test_absolute_address_strips_at(self) -> None:
        relative = DynamicAddress("@sensor").as_relative()
        assert relative is not None
        assert str(relative) == "sensor"

    def test_relative_address_returned_as_is(self) -> None:
        relative = DynamicAddress("sensor").as_relative()
        assert relative is not None
        assert str(relative) == "sensor"

    def test_deep_absolute_strips_at(self) -> None:
        relative = DynamicAddress("@parent.child").as_relative()
        assert relative is not None
        assert str(relative) == "parent.child"


class TestDynamicAddressModifiers:
    def test_all_returns_all_selector(self) -> None:
        selector = DynamicAddress("@sensor").all()
        assert selector.text == "@sensor:all"

    def test_descendants_returns_descendants_selector(self) -> None:
        selector = DynamicAddress("@sensor").descendants()
        assert selector.text == "@sensor:descendants"

    def test_children_returns_children_selector(self) -> None:
        selector = DynamicAddress("@sensor").children()
        assert selector.text == "@sensor:children"

    def test_base_property_with_no_modifier(self) -> None:
        assert DynamicAddress("@sensor").base == "@sensor"

    def test_base_property_returns_string(self) -> None:
        assert DynamicAddress("sensor").base == "sensor"


class TestAddress:
    def test_construct_from_absolute_string(self) -> None:
        address = Address("@sensor")
        assert str(address) == "@sensor"

    def test_construct_engine(self) -> None:
        address = Address("~")
        assert str(address) == "~"

    def test_construct_dotted_path(self) -> None:
        address = Address("@parent.child.grandchild")
        assert str(address) == "@parent.child.grandchild"

    def test_relative_string_raises(self) -> None:
        with pytest.raises(ValueError, match="must match regex"):
            Address("sensor")

    def test_engine_constant(self) -> None:
        assert str(Address.ENGINE) == "~"
        assert Address.ENGINE.is_engine

    def test_engine_classmethod(self) -> None:
        assert Address.engine() == Address.ENGINE
        assert Address.engine().is_engine

    def test_equality(self) -> None:
        assert Address("@sensor") == Address("@sensor")
        assert Address("@sensor") != Address("@motor")

    def test_hashing(self) -> None:
        address_set = {Address("@sensor"), Address("@motor"), Address("@sensor")}
        assert len(address_set) == 2

    def test_address_usable_as_dict_key(self) -> None:
        mapping = {Address("@sensor"): 1, Address("@motor"): 2}
        assert mapping[Address("@sensor")] == 1
        assert mapping[Address("@motor")] == 2


class TestAddressContains:
    def test_engine_contains_everything(self) -> None:
        engine = Address.ENGINE
        assert engine.contains(Address.ENGINE)
        assert engine.contains(Address("@sensor"))
        assert engine.contains(Address("@parent.child"))

    def test_parent_contains_child(self) -> None:
        parent = Address("@parent")
        assert parent.contains(Address("@parent.child"))
        assert parent.contains(Address("@parent.child.grandchild"))

    def test_parent_contains_itself(self) -> None:
        parent = Address("@parent")
        assert parent.contains(parent)

    def test_parent_does_not_contain_sibling(self) -> None:
        parent = Address("@parent")
        assert not parent.contains(Address("@sibling"))

    def test_child_does_not_contain_parent(self) -> None:
        child = Address("@parent.child")
        assert not child.contains(Address("@parent"))

    def test_does_not_contain_engine(self) -> None:
        assert not Address("@sensor").contains(Address.ENGINE)

    def test_does_not_contain_name_collision(self) -> None:
        # `@a` must not contain `@ab`, only real descendants separated by a dot.
        assert not Address("@a").contains(Address("@ab"))


class TestAddressParentChild:
    def test_parent_of_nested_address(self) -> None:
        address = Address("@parent.child")
        parent = address.parent
        assert parent is not None
        assert str(parent) == "@parent"
        assert isinstance(parent, Address)

    def test_engine_has_no_parent(self) -> None:
        assert Address.ENGINE.parent is None

    def test_path_of_deep_address(self) -> None:
        address = Address("@a.b.c")
        path = address.path
        assert [str(segment) for segment in path] == ["@a", "@a.b", "@a.b.c"]

    def test_division_creates_child(self) -> None:
        address = Address("@parent") / "child"
        assert str(address) == "@parent.child"
        assert isinstance(address, Address)


class TestAddressAllSelector:
    def test_all_returns_selector(self) -> None:
        selector = Address("@sensor").all()
        assert isinstance(selector, AddressSelector)
        assert selector.text == "@sensor:all"

    def test_all_selector_matches_self(self) -> None:
        address = Address("@sensor")
        selector = address.all()
        assert selector.matches(address, None)

    def test_all_selector_matches_descendants(self) -> None:
        selector = Address("@parent").all()
        assert selector.matches(Address("@parent.child"), None)
        assert selector.matches(Address("@parent.child.grandchild"), None)

    def test_all_selector_does_not_match_siblings(self) -> None:
        selector = Address("@parent").all()
        assert not selector.matches(Address("@sibling"), None)

    def test_engine_all_matches_everything(self) -> None:
        selector = Address.ENGINE.all()
        assert selector.matches(Address.ENGINE, None)
        assert selector.matches(Address("@sensor"), None)


class TestAddressGrammarTightening:
    """Bare `@` is no longer a constructible address, only a base that requires a modifier."""

    def test_bare_root_address_is_invalid(self) -> None:
        with pytest.raises(ValueError):
            Address("@")

        with pytest.raises(ValueError):
            DynamicAddress("@")

        with pytest.raises(ValueError):
            AddressSelector("@")

    def test_top_level_address_has_no_parent(self) -> None:
        assert Address("@sensor").parent is None
        assert Address("@sensor").container == Address("~")

    def test_engine_children_selector_is_invalid(self) -> None:
        with pytest.raises(ValueError):
            AddressSelector("~:children")

    def test_forest_selectors(self) -> None:
        selector = AddressSelector("@:all")
        assert selector.matches(Address("@sensor"), None)
        assert selector.matches(Address("@sensor.motor"), None)
        assert not selector.matches(Address("~"), None)

        descendants = AddressSelector("@:descendants")
        assert descendants.matches(Address("@sensor"), None)

        children = AddressSelector("@:children")
        assert children.matches(Address("@sensor"), None)
        assert not children.matches(Address("@sensor.motor"), None)

        engine_all = AddressSelector("~:all")
        assert engine_all.matches(Address("~"), None)
        assert engine_all.matches(Address("@sensor"), None)

    def test_truediv_joins_names(self) -> None:
        assert Address("@a") / "b" == Address("@a.b")

    def test_tilde_prefixed_garbage_address_is_invalid(self) -> None:
        with pytest.raises(ValueError):
            Address("~garbage")

        with pytest.raises(ValueError):
            Address("~x")

        with pytest.raises(ValueError):
            DynamicAddress("~garbage")

        assert Address("~") == Address("~")

    def test_as_relative_strips_leading_at(self) -> None:
        assert Address("@a").as_relative() == DynamicAddress("a")

    def test_contains_descendant_but_not_name_collision(self) -> None:
        assert Address("@a").contains(Address("@a.b"))
        assert not Address("@a").contains(Address("@ab"))


def _assert_matches_expression_parity(
    selector: AddressSelector,
    root: Address | None,
    candidates: list[str],
) -> None:
    """Assert `matches()` and a SQLite-compiled `matches_expression()` agree over `candidates`."""
    metadata = MetaData()
    table = Table("addresses", metadata, Column("address", AddressMapper))

    engine = create_engine("sqlite://")
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(table.insert(), [{"address": candidate} for candidate in candidates])

    with engine.connect() as connection:
        condition = selector.matches_expression(table.c.address, root)
        statement = select(table.c.address).where(condition)
        sql_matches = {str(row.address) for row in connection.execute(statement)}

    python_matches = {
        candidate for candidate in candidates if selector.matches(Address(candidate), root)
    }

    assert sql_matches == python_matches

    engine.dispose()


class TestAddressMatchesExpressionParity:
    """`matches()` and `matches_expression()` must agree for every forest selector."""

    CANDIDATES = [
        "~",
        "@sensor",
        "@sensor.motor",
        "@sensor.motor.encoder",
        "@other",
    ]

    def test_root_all_parity(self) -> None:
        _assert_matches_expression_parity(AddressSelector("@:all"), None, self.CANDIDATES)

    def test_root_descendants_parity(self) -> None:
        _assert_matches_expression_parity(AddressSelector("@:descendants"), None, self.CANDIDATES)

    def test_root_children_parity(self) -> None:
        _assert_matches_expression_parity(AddressSelector("@:children"), None, self.CANDIDATES)

    def test_engine_all_parity(self) -> None:
        _assert_matches_expression_parity(AddressSelector("~:all"), None, self.CANDIDATES)

    def test_piped_children_selector_falls_through_parity(self) -> None:
        _assert_matches_expression_parity(
            AddressSelector("@:children|@a.b"),
            None,
            ["@a", "@a.b", "@x.y.z", "~"],
        )

    def test_piped_children_selector_matches_second_segment(self) -> None:
        assert AddressSelector("@:children|@a.b").matches(Address("@a.b"), None)
