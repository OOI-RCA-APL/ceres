from collections import defaultdict
from datetime import datetime
from itertools import groupby
from typing import Any, Iterable, Sequence, final

from typing_extensions import override

from ceres.address import Address
from ceres.alert import Alert, AlertLevel
from ceres.data import jsonify
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

        Index = dict[AlertLevel, dict[tuple[Address, str, str], list[Alert]]]

        def create_index() -> Index:
            return defaultdict(create_index)  # type: ignore

        index = create_index()

        for level, by_level in groupby(
            sorted(
                alerts,
                key=lambda alert: -list(AlertLevel).index(alert.level),
            ),
            key=lambda alert: alert.level,
        ):
            for key, by_key in groupby(
                sorted(by_level, key=lambda alert: -alert.timestamp.timestamp()),
                lambda alert: (alert.source, alert.code, jsonify(alert.info)),
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
