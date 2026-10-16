"""Outputs whose live source a browser can play directly over WebRTC."""

from dataclasses import dataclass
from typing import Any

from ceres.component import DataStream, OutputMediaType, StreamingOutput


@dataclass(frozen=True, slots=True)
class LiveSource:
    """The live source an output reads, as the WebRTC server connects to it."""

    url: str
    transport: str
    copy: bool
    reconnect: bool
    stall_timeout: float | None


class LiveOutput(StreamingOutput):
    """A streaming output reading a live source that a browser can also play over WebRTC.

    The server answers a WebRTC offer for the procedure returning it with `source`, sharing the
    source connection the output's own stream reads.
    """

    __slots__ = ("source",)

    def __init__(
        self, source: LiveSource, stream: DataStream, media: OutputMediaType, **kwargs: Any
    ) -> None:
        """Construct an output reading `source`, with the arguments `StreamingOutput` takes."""
        super().__init__(stream, media, **kwargs)
        self.source = source
