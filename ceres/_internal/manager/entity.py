from __future__ import annotations

from typing import Any, Unpack, cast

from ceres._internal.lazy import lazy_imports
from ceres._internal.manager.manager import BaseManager
from ceres.entity import BaseEntity

with lazy_imports(__name__):
    from ceres._internal import util
    from ceres._internal.auth import verify_password_hash
    from ceres.data import PasswordHash


with lazy_imports(__name__):
    from sqlalchemy.sql import Delete, Select, Update, delete, func, select, update


class BaseEntityManager[
    EntityT: BaseEntity,
    RowT: BaseEntity.Row,
    CreateT: BaseEntity.Create,
    UpdateT: BaseEntity.Update,
    FilterT: BaseEntity.Filter[Any],
    FilterArgsT: BaseEntity.FilterArgs,
](BaseManager[EntityT]):
    async def create(self, data: CreateT) -> EntityT:
        result = await self._from_create(data)
        await self._insert(result)
        return result

    async def get_all(
        self,
        filter: FilterT | None = None,
        **kwargs: Unpack[FilterArgsT],  # type: ignore
    ) -> list[EntityT]:
        Row = self._get_row_cls()

        filter = self._apply_default_filter(filter, kwargs)
        statement = select(*Row.__table__.columns.values())
        statement = filter.apply(statement, self._database.type)
        return await self._execute_and_get_many(statement, self._cls)

    async def get(
        self,
        filter: FilterT | None = None,
        /,
        **kwargs: Unpack[FilterArgsT],  # type: ignore
    ) -> EntityT | None:
        entities = await self.get_all(filter, **{**kwargs, "limit": 1})
        return entities[0] if entities else None

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
        return await self._execute_and_get_one(statement, self._cls)

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
        return await self._execute_and_get_one(statement, self._cls)

    async def count(
        self,
        filter: FilterT | None = None,
        **kwargs: Unpack[FilterArgsT],  # type: ignore
    ) -> int:
        Row = self._get_row_cls()

        filter = self._apply_default_filter(filter, kwargs)
        statement = select(func.count(Row.id))
        statement = filter.apply(statement, self._database.type).order_by(None)
        return await self._execute_and_get_one(statement, int) or 0

    async def _execute_and_get_many[
        T
    ](self, statement: Select[tuple[Any, ...]] | Update | Delete, result_type: type[T]) -> list[T]:
        with util.wrap_database_errors():
            async with await self._database.init() as session:
                results = await session.execute(statement)
                await session.commit()

            if not results:
                return []

            return util.get_type_adapter(list[result_type]).validate_python(
                results, from_attributes=True
            )

    async def _execute_and_get_one[
        T
    ](self, statement: Select[tuple[Any, ...]] | Update | Delete, result_type: type[T]) -> T | None:
        with util.wrap_database_errors():
            async with await self._database.init() as session:
                result = await session.execute(statement)
                row = result.scalar()
                await session.commit()

        if row is None:
            return None

        return util.get_type_adapter(result_type).validate_python(row, from_attributes=True)

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

    async def _insert(self, data: EntityT) -> RowT:
        Row = self._get_row_cls()
        row = Row(**data.__dict__)
        with util.wrap_database_errors():
            async with await self._database.init() as session:
                session.add(row)
                await session.commit()
                return row

    async def _maybe_hash_password(self, password: str) -> PasswordHash | None:
        if verify_password_hash(password):
            return password

        return await self._database.hash_password(password)

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
