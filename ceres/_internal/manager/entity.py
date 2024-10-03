from __future__ import annotations

from typing import Any, AsyncIterable, Sequence, Unpack, cast

from ceres._internal.entity import (
    BaseEntity,
    BaseEntityCreate,
    BaseEntityFilter,
    BaseEntityFilterArgs,
    BaseEntityRow,
    BaseEntityUpdate,
)
from ceres._internal.lazy import lazy_imports
from ceres._internal.manager.manager import BaseManager
from ceres.database.enums import DatabaseType

with lazy_imports(__name__):
    from sqlalchemy.sql import Delete, Select, Update, delete, func, select, update
    from sqlalchemy.sql.elements import ColumnElement
    from sqlalchemy.sql.roles import DDLConstraintColumnRole
    from sqlalchemy.sql.schema import Column

    from ceres._internal import util


class BaseEntityManager[
    EntityT: BaseEntity,
    RowT: BaseEntityRow,
    CreateT: BaseEntityCreate,
    UpdateT: BaseEntityUpdate,
    FilterT: BaseEntityFilter[Any, Any, Any],
    FilterArgsT: BaseEntityFilterArgs[Any, Any],
](BaseManager[EntityT]):
    async def create(
        self,
        data: CreateT,
        *,
        upsert_on: Sequence[str | ColumnElement[Any] | DDLConstraintColumnRole] | None = None,
    ) -> EntityT:
        result = await self._from_create(data)
        await self._insert(result, upsert_on=upsert_on)
        return result

    async def get_all(
        self,
        filter: FilterT | None = None,
        **kwargs: Any,
    ) -> list[EntityT]:
        Row = self._get_row_cls()

        filter = self._apply_default_filter(filter, kwargs)
        statement = select(*Row.__table__.columns.values())
        statement = filter.apply(statement, self._database.type)
        return await self._execute_and_get_many(statement, self._cls)

    async def get(
        self,
        filter: FilterT | None = None,
        **kwargs: Unpack[FilterArgsT],  # type: ignore
    ) -> EntityT | None:
        entities = await self.get_all(filter, **{**kwargs, "limit": 1})
        return entities[0] if entities else None

    async def select(
        self,
        filter: FilterT | None = None,
        **kwargs: Unpack[FilterArgsT],  # type: ignore
    ) -> AsyncIterable[EntityT]:
        Row = self._get_row_cls()

        filter = self._apply_default_filter(filter, kwargs)
        statement = select(*Row.__table__.columns.values())
        statement = filter.apply(statement, self._database.type)
        async for result in self._execute_and_iter(statement, self._cls):
            yield result

    async def update_all(self, filter: FilterT, assign: UpdateT) -> int:
        Row = self._get_row_cls()
        if not assign:
            return 0

        filter = self._apply_default_filter(filter)
        statement = update(Row).values(assign)
        statement = filter.apply(statement, self._database.type)
        return await self._execute_and_get_count(statement)

    async def update(self, filter: FilterT, assign: UpdateT) -> EntityT | None:
        Row = self._get_row_cls()
        if not assign:
            return None

        filter = self._apply_default_filter(filter, {"limit": 1})
        statement = update(Row).values(assign).returning(self._cls.Row)
        statement = filter.apply(statement, self._database.type)  # type: ignore
        return await self._execute_and_get_scalar(statement, self._cls)

    async def delete_all(
        self,
        filter: FilterT | None = None,
        **kwargs: Unpack[FilterArgsT],  # type: ignore
    ) -> int:
        Row = self._get_row_cls()

        filter = self._apply_default_filter(filter, kwargs)
        statement = delete(Row)
        statement = filter.apply(statement, self._database.type)  # type: ignore
        return await self._execute_and_get_count(statement)

    async def delete(
        self,
        filter: FilterT | None = None,
        **kwargs: Unpack[FilterArgsT],  # type: ignore
    ) -> EntityT | None:
        Row = self._get_row_cls()

        filter = self._apply_default_filter(filter, {**kwargs, "limit": 1})
        statement = delete(Row).returning(Row)
        statement = filter.apply(statement, self._database.type)
        return await self._execute_and_get_scalar(statement, self._cls)

    async def count(
        self,
        filter: FilterT | None = None,
        **kwargs: Unpack[FilterArgsT],  # type: ignore
    ) -> int:
        filter = self._apply_default_filter(filter, kwargs)
        statement = select(func.count())
        statement = filter.apply(
            statement,
            self._database.type,
            ignore_order=True,
        )

        return await self._execute_and_get_scalar(statement, int) or 0

    async def _execute_and_iter[T: BaseEntity](
        self,
        statement: Select[tuple[Any, ...]] | Delete | Update,
        parse: type[T],
    ) -> AsyncIterable[T]:
        with util.wrap_database_errors():
            async with await self._database.init() as session:
                results = await session.stream(statement)
                try:
                    async for result in results:
                        yield parse.model_construct(**result._mapping)
                finally:
                    await session.commit()

    async def _execute_and_get_many[T: BaseEntity](
        self,
        statement: Select[tuple[Any, ...]] | Update | Delete,
        parse: type[T],
    ) -> list[T]:
        results = []
        async for result in self._execute_and_iter(statement, parse):
            results.append(result)

        return results

    async def _execute_and_get_scalar[T](
        self,
        statement: Select[tuple[Any, ...]] | Update | Delete,
        parse: type[T],
    ) -> T | None:
        adapter = util.get_type_adapter(parse)

        with util.wrap_database_errors():
            async with await self._database.init() as session:
                result = await session.execute(statement)
                row = result.scalar()
                await session.commit()

        if row is None:
            return None

        return adapter.validate_python(row, from_attributes=True)

    async def _execute_and_get_count(self, statement: Update | Delete) -> int:
        with util.wrap_database_errors():
            async with await self._database.init() as session:
                result = await session.execute(statement)
                await session.commit()
                return result.rowcount

    async def _from_create(self, data: CreateT) -> EntityT:
        if isinstance(data, self._cls):
            return data

        return self._cls(**data.__dict__)

    async def _insert(
        self,
        data: EntityT,
        *,
        upsert_on: Sequence[str | Column[Any] | DDLConstraintColumnRole] | None = None,
    ) -> RowT:
        Row = self._get_row_cls()
        row = Row(**data.__dict__)
        match self._database.type:
            case DatabaseType.SQLITE:
                from sqlalchemy.dialects.sqlite import insert
            case DatabaseType.POSTGRES:
                from sqlalchemy.dialects.postgresql import insert

        with util.wrap_database_errors():
            async with await self._database.init() as session:
                statement = insert(Row).values(row.values())
                pk = Row.get_primary_key_columns()

                if upsert_on is not None:
                    upsert = {
                        name: column
                        for name, column in statement.excluded.items()
                        if name not in pk
                    }
                    statement = statement.on_conflict_do_update(
                        index_elements=upsert_on,
                        set_=upsert,
                    )

                await session.execute(statement)
                await session.commit()
                return row

    def _apply_default_filter(
        self,
        filter: FilterT | None,
        kwargs: Any | None = None,
    ) -> FilterT:
        if kwargs is None:
            kwargs = {}

        Filter = self._get_filter_cls()
        result = Filter(**kwargs).with_defaults(filter)  # type: ignore
        defaults = self._get_filter_defaults()
        if defaults is not None:
            result = result.with_defaults(defaults)  # type: ignore

        return result  # type: ignore

    def _get_filter_defaults(self) -> FilterT | None:
        if self._node is None:
            return None

        Filter = self._get_filter_cls()
        address = self._node.address
        return util.call_partial(
            Filter,  # type: ignore
            root=address,  # type: ignore
            address=address.all(),  # type: ignore
        )

    def _get_filter_cls(self) -> type[FilterT]:
        Filter = self._cls.Filter
        return cast(type[FilterT], Filter)

    def _get_row_cls(self) -> type[RowT]:
        Row = self._cls.Row
        return cast(type[RowT], Row)
