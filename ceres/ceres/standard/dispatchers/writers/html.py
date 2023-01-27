from collections import defaultdict
from itertools import groupby
from typing import Any, Mapping, Sequence

from ceres.standard.templates import templates

from ....address import ComponentAddress
from ....alert import Alert, AlertLevel
from ....data import ImmutableDataObject, jsonify
from ....dispatcher import Dispatch, DispatchWriter
from ....notifier import Notification
from ...markdown import markdown


class _AddressedAlert(ImmutableDataObject):
    address: ComponentAddress
    alert: Alert


AlertIndex = dict[AlertLevel, dict[ComponentAddress, dict[str, dict[str, list[Alert]]]]]


def _size_of(index: dict[str, Any] | list[Any]) -> int:
    if isinstance(index, dict):
        values = index.values()
    elif isinstance(index, list):
        values = index
    else:
        return 1

    count = 0

    for value in values:
        if isinstance(value, (dict, list)):
            count += _size_of(value)
        else:
            count += 1

    return count


class HTMLDispatchWriter(DispatchWriter):
    async def write(
        self,
        dispatch: Dispatch,
        alerts: Mapping[ComponentAddress, Sequence[Alert]],
    ) -> Notification:
        addressed: list[_AddressedAlert] = []
        for address, group in alerts.items():
            for alert in group:
                addressed.append(_AddressedAlert(address=address, alert=alert))

        def create_index() -> AlertIndex:
            return defaultdict(create_index)  # type: ignore

        index = create_index()

        for level, by_level in groupby(
            sorted(
                addressed,
                key=lambda current: -list(AlertLevel).index(current.alert.level),
            ),
            key=lambda current: current.alert.level,
        ):
            for address, by_address in groupby(by_level, lambda current: current.address):
                for code, by_code in groupby(by_address, lambda current: current.alert.code):
                    for info, by_info in groupby(
                        by_code, lambda current: jsonify(current.alert.info)
                    ):
                        listing = index[level][address][code]
                        if info not in listing:
                            listing[info] = []

                        listing[info].extend([current.alert for current in by_info])

        template = templates.get_template("html-email-dispatch.jinja")
        content = template.render(
            dispatch=dispatch,
            index=index,
            size_of=_size_of,
            str=str,
            markdown=markdown,
        )

        return Notification(
            subject=dispatch.subject,
            content=content,
            content_type="text/html",
        )
