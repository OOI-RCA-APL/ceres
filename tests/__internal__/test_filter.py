import json

import pytest
from pydantic import ValidationError

from ceres import Address, Component, User
from ceres.__internal__.utilities.collections import seq
from ceres.engine import Engine
from ceres.group import GroupFilter
from ceres.user import UserFilter


class TestSubfilterFields:
    """Subfilters must accept the fields their own filter class declares, not just base fields."""

    def test_or_subfilter_accepts_subclass_fields(self):
        filter = UserFilter.model_validate({"or": [{"username_contains": "a"}]})
        assert filter.or__ is not None
        assert [subfilter.username_contains for subfilter in seq(filter.or__)] == ["a"]

    def test_and_subfilter_accepts_subclass_fields(self):
        filter = UserFilter.model_validate({"and": [{"email_contains": "a"}]})
        assert filter.and__ is not None
        assert [subfilter.email_contains for subfilter in seq(filter.and__)] == ["a"]

    def test_nested_subfilters_accept_subclass_fields(self):
        filter = UserFilter.model_validate(
            {"and": [{"or": [{"username_contains": "a"}, {"email_contains": "b"}]}]}
        )
        assert filter.and__ is not None
        outer = seq(filter.and__)[0]
        assert outer.or__ is not None
        inner = seq(outer.or__)
        assert [subfilter.username_contains for subfilter in inner] == ["a", None]
        assert [subfilter.email_contains for subfilter in inner] == [None, "b"]

    def test_subfilter_parsed_from_a_json_string(self):
        raw = json.dumps({"or": [{"username_contains": "a"}]})
        filter = UserFilter.model_validate({"and": [raw]})
        assert filter.and__ is not None
        outer = seq(filter.and__)[0]
        assert outer.or__ is not None
        assert [subfilter.username_contains for subfilter in seq(outer.or__)] == ["a"]

    def test_subfilter_fields_are_scoped_to_their_own_filter_class(self):
        with pytest.raises(ValidationError):
            GroupFilter.model_validate({"or": [{"username_contains": "a"}]})


class TestSubfilterQueries:
    async def test_or_subfilter_matches_either_field(self):
        engine = Engine()
        await engine.database.migrate()
        for username in ("alice", "bob"):
            await engine.database.users.create(
                User.Create(username=username, email=f"{username}@test.com", password="x")
            )

        filter = UserFilter.model_validate(
            {"and": [{"or": [{"username_contains": "ali"}, {"email_contains": "ali"}]}]}
        )
        assert sorted(user.username for user in await engine.users.where(filter)) == ["alice"]

    async def test_empty_contains_subfilter_matches_everything(self):
        engine = Engine()
        await engine.database.migrate()
        for username in ("alice", "bob"):
            await engine.database.users.create(
                User.Create(username=username, email=f"{username}@test.com", password="x")
            )

        filter = UserFilter.model_validate(
            {"and": [{"or": [{"username_contains": ""}, {"email_contains": ""}]}]}
        )
        assert sorted(user.username for user in await engine.users.where(filter)) == [
            "alice",
            "bob",
        ]


async def test_filter_defaults():
    engine = Engine()
    database = engine.database
    root = Component("root", __with_container__=engine)
    child = Component("child", __with_container__=root)

    assert database.__get_filter_defaults__() == {}
    # The engine's address selects everything, so only the root defaults, which keeps
    # `or` subfilters from short-circuiting against a match-all condition.
    assert engine.__get_filter_defaults__() == {"root": Address.ENGINE}
    assert root.__get_filter_defaults__() == {
        "root": Address("@root"),
        "address": Address("@root").all(),
    }
    assert child.__get_filter_defaults__() == {
        "root": Address("@root.child"),
        "address": Address("@root.child").all(),
    }
