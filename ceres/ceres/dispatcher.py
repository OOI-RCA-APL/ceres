import traceback
from abc import abstractmethod
from collections import defaultdict
from datetime import timedelta
from typing import Any, Mapping, Sequence

from pydantic import Field, validator
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from .address import ComponentAddress
from .alert import Alert, AlertLevel
from .component import Component
from .data import ImmutableDataObject
from .database.entity import AlertEntity
from .datetime import utc
from .internal.utilities import validate_positive_timedelta
from .loaded import Loaded
from .notifier import Notification, Notifier


class DispatchFilter(ImmutableDataObject):
    within: timedelta
    code: str | None = None
    levels: Sequence[AlertLevel] | None
    limit: int | None = Field(None, ge=0)

    @validator("within", pre=True)
    def _validate_within(cls, value: Any) -> timedelta:
        return validate_positive_timedelta(value)


class Dispatch(ImmutableDataObject):
    subject: str
    description: str | None = None
    signature: str | None = None
    alerts: DispatchFilter
    recipients: Sequence[str]


class DispatchWriter:
    @abstractmethod
    async def write(
        self,
        dispatch: Dispatch,
        alerts: Mapping[ComponentAddress, Sequence[Alert]],
    ) -> Notification:
        ...


class Dispatcher(Component):
    class Parameters(Component.Parameters):
        dispatches: Sequence[Dispatch] = Field(default_factory=list)
        writer: Loaded[DispatchWriter]

    class References(Component.References):
        notifier: Notifier

    parameters: Parameters
    references: References

    async def _get_notification_alerts(
        self,
        filter: DispatchFilter,
    ) -> Mapping[ComponentAddress, Sequence[Alert]]:
        mapping: defaultdict[ComponentAddress, list[Alert]] = defaultdict(list)

        async with self.database.session() as session:
            query = (
                select(AlertEntity)
                .options(joinedload(AlertEntity.component))
                .order_by(AlertEntity.timestamp.desc())
            )

            query.where(AlertEntity.timestamp > (utc() - filter.within))

            if filter.code is not None:
                query.where(AlertEntity.code.regexp_match(filter.code))
            if filter.levels is not None:
                query.where(AlertEntity.level.in_(filter.levels))
            if filter.limit is not None:
                query.limit(filter.limit)

            for alert in await session.scalars(query):
                mapping[alert.component.address].append(Alert.from_orm(alert))

        return dict(mapping)

    async def dispatch(self, dispatch: Dispatch) -> None:
        try:
            alerts = await self._get_notification_alerts(dispatch.alerts)
        except Exception:
            self.logger.error(
                f"An exception occurred while reading alerts for dispatch '{dispatch.subject}': {traceback.format_exc()}"
            )
            return

        if not alerts:
            return

        try:
            notification = await self.parameters.writer.write(dispatch, alerts)
            self.logger.info(
                f"Sending notification '{notification.subject}' to {len(dispatch.recipients)} recipients referring to {sum(len(group) for _, group in alerts.items())} alerts..."
            )
        except Exception:
            self.logger.error(
                f"An exception occurred while writing notification for distribution '{dispatch.subject}': {traceback.format_exc()}"
            )
            return

        try:
            await self.references.notifier.notify(notification, dispatch.recipients)
        except Exception:
            self.logger.error(
                f"An exception occurred while sending notification to distribution '{dispatch.subject}': {traceback.format_exc()}"
            )
