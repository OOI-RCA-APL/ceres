from typing import Mapping, Sequence

from ....address import GlobalComponentAddress
from ....alert import Alert
from ....data import jsonify
from ....dispatcher import Dispatch, DispatchWriter
from ....notifier import Notification


class HTMLDispatchWriter(DispatchWriter):
    def write(
        self,
        dispatch: Dispatch,
        alerts: Mapping[GlobalComponentAddress, Sequence[Alert]],
    ) -> Notification:
        return Notification(
            subject=dispatch.subject,
            content=f"<body>{jsonify({str(key): value for key, value in alerts.items()}, indent=2)}</body>",
            content_type="text/html",
        )
