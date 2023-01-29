from collections import defaultdict
from itertools import groupby
from typing import Any, Sequence, final

from ....address import ComponentAddress
from ....alert import Alert, AlertLevel
from ....data import jsonify
from ....dispatcher import Dispatch, DispatchWriter
from ....notifier import Notification
from ...markdown import markdown
from ...templates import templates


@final
class HTMLDispatchWriter(DispatchWriter):
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

        Index = dict[AlertLevel, dict[ComponentAddress, dict[str, dict[str, list[Alert]]]]]

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
            for source, by_source in groupby(by_level, lambda alert: alert.source):
                for code, by_code in groupby(by_source, lambda alert: alert.code):
                    for info, by_info in groupby(by_code, lambda alert: jsonify(alert.info)):
                        listing = index[level][source][code]
                        if info not in listing:
                            listing[info] = []

                        listing[info].extend(by_info)

        template = templates.get_template("html-email-dispatch.jinja")
        content = template.render(
            dispatch=dispatch,
            index=index,
            get_size=get_size,
            str=str,
            markdown=markdown,
        )

        return Notification(
            subject=dispatch.subject,
            content=content,
            content_type="text/html",
        )
