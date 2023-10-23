from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable, Sequence, final

from typing_extensions import override

from ceres.address import Address
from ceres.alert import Alert, Level
from ceres.data import jsonify
from ceres.internal.utilities import group_by
from ceres.roles.dispatcher import Dispatch, DispatchWriter
from ceres.roles.notifier import Notification
from ceres.standard.markdown import markdown
from ceres.standard.templates import templates


@final
class HTMLDispatchWriter(DispatchWriter):
    @override
    async def write(
        self,
        dispatch: Dispatch,
        alerts: Sequence[Alert],
    ) -> Notification:
        def get_size(index: dict[str, Any] | list[Any]) -> int:
            if isinstance(index, dict):
                values = index.values()
            elif isinstance(index, list):
                values = index
            else:
                return 1

            count = 0

            for value in values:
                if isinstance(value, (dict, list)):
                    count += get_size(value)
                else:
                    count += 1

            return count

        def get_latest_alert_timestamp(alerts: Iterable[Alert]) -> datetime:
            return max([alert.timestamp for alert in alerts])

        Index = dict[Level, dict[tuple[Address, str, str], list[Alert]]]

        def create_index() -> Index:
            return defaultdict(create_index)  # type: ignore

        index = create_index()

        for level, by_level in group_by(
            sorted(alerts, key=lambda alert: alert.level, reverse=True),
            key=lambda alert: alert.level,
        ):
            for key, by_key in group_by(
                sorted(by_level, key=lambda alert: -alert.timestamp.timestamp()),
                lambda alert: (alert.address, alert.code, jsonify(alert.info)),
            ):
                group = index[level]
                if key not in group:
                    group[key] = []

                group[key].extend(by_key)
                group[key].sort(key=lambda alert: -alert.timestamp.timestamp())

        template = templates.get_template("html-email-dispatch.jinja")
        content = template.render(
            dispatch=dispatch,
            index=index,
            markdown=markdown,
            get_size=get_size,
            get_latest_alert_timestamp=get_latest_alert_timestamp,
        )

        return Notification(
            subject=dispatch.subject,
            content=content,
            content_type="text/html",
        )
