"""Proxy RTSP camera streams as fragmented MP4.

The public surface is `rtsp`, which remuxes a camera's video into fragmented MP4 through the
FFmpeg built into the Ceres extension and forwards it through a `StreamingOutput`. A lost camera
is reconnected and its packets continue the same timeline, so clients holding open video
connections keep decoding one continuous stream.
"""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import TYPE_CHECKING

from ceres.__internal__.core import RtspNotice, RtspStream
from ceres.component import StreamingOutput
from ceres.event import (
    StreamEndedEvent,
    StreamLostEvent,
    StreamReconnectedEvent,
    StreamReconnectScheduledEvent,
)

if TYPE_CHECKING:
    from ceres.component import Component, ComponentSystem

__all__ = [
    "rtsp",
]


async def rtsp(
    url: str,
    *,
    copy: bool = True,
    transport: str = "tcp",
    fragment_duration: float = 0.05,  # Seconds.
    dash: bool = True,
    reconnect: bool = True,
    stall_timeout: float | None = 10.0,  # Seconds.
    component: Component | None = None,
) -> StreamingOutput:
    """Proxy an RTSP stream as fragmented MP4 via a `StreamingOutput`.

    Read the camera's video from `url` and remux it into fragmented MP4 on threads of their own,
    forwarding the bytes through a `StreamingOutput` object. The returned output can be handed
    back from component queries or actions to stream the video to clients. Every open stream of
    one camera with the same `copy`, `transport`, and `stall_timeout` shares one connection to
    it, so a camera allowing few sessions serves any number of viewers. A viewer joining an
    open connection starts from its latest keyframe, and a viewer reading too slowly skips ahead
    to the next keyframe rather than holding up the others. The connection stays open for a few
    seconds after its last viewer leaves, so a viewer coming straight back finds it open. Only
    the camera's video is streamed, audio is dropped.

    When the camera drops, the connection is reopened and its packets are placed after the
    last one sent, so clients holding open video connections keep decoding one continuous
    stream across the gap. A camera that comes back with a picture the MP4 already sent cannot
    describe ends the stream. When copying, that is a different codec, resolution, or parameter
    set. When re-encoding, it is a different resolution or pixel format.

    The stream reports what happens to the camera as events on a component: `StreamLostEvent`
    once per outage, `StreamReconnectScheduledEvent` for its first reconnect attempt,
    `StreamReconnectedEvent` when the picture is back, and `StreamEndedEvent` when the stream
    ends on its own. Returned from a procedure, the output reports on that procedure's
    component, naming the procedure. Read anywhere else, it reports on `component` if given,
    and otherwise not at all.

    Args:
        url: URL of the RTSP stream to read from.
        copy: If true, copy the video stream without re-encoding. If false, decode it and
            re-encode it as H.264 with OpenH264, which costs CPU but plays in browsers that
            cannot decode the camera's codec. Re-encoding accepts only 8-bit 4:2:0 video.
        transport: The RTSP transport, `"tcp"` or `"udp"`. Defaults to `"tcp"`.
        fragment_duration: Longest duration in seconds of each emitted MP4 fragment. Defaults
            to 50 ms to reduce latency.
        dash: If true, fragments carry the DASH `sidx` index so the output is DASH-compatible.
        reconnect: If true, reopen the camera whenever the connection ends or fails to open,
            waiting between attempts with capped exponential backoff, 0.5 s doubling to a 10 s
            cap and resetting after a session that streamed for at least 5 s. If false, the
            stream ends when the first connection does, while other streams sharing the
            connection carry on.
        stall_timeout: Seconds without a packet after which the camera counts as lost, so a
            camera that dies while holding its TCP connection open triggers a reconnect.
            Pass `None` to wait on a silent camera forever.
        component: The component to report the stream's events on when no procedure returned
            the output.

    Returns:
        A `StreamingOutput` that yields `video/mp4` bytes.

    Raises:
        ValueError: If `transport` is not `"tcp"` or `"udp"`, or a duration is negative. The
            stream raises it when first read.
        ConnectionError: From the stream, when the camera cannot be reached and `reconnect`
            is false, when re-encoding meets video other than 8-bit 4:2:0, or when the remux
            fails.
    """

    async def stream() -> AsyncIterator[bytes]:
        # Read once the output opens, by when a procedure returning it has bound it.
        system = output._component  # noqa: SLF001
        if system is None and component is not None:
            system = component.system
        procedure = output._procedure  # noqa: SLF001

        session = RtspStream(
            url,
            copy=copy,
            transport=transport,
            fragment_duration=fragment_duration,
            dash=dash,
            reconnect=reconnect,
            stall_timeout=stall_timeout,
        )
        try:
            while (item := await session.next()) is not None:
                if isinstance(item, RtspNotice):
                    if system is not None:
                        _report(system, procedure, item)
                else:
                    yield item
        finally:
            # Ends the camera connection at once when the client leaves mid-stream.
            session.close()

    output = StreamingOutput(stream, "video/mp4")
    return output


def _report(system: ComponentSystem, procedure: str | None, notice: RtspNotice) -> None:
    """Emit the event a stream's notice stands for."""
    match notice.kind:
        case "lost":
            system.events.emit(StreamLostEvent, procedure=procedure, reason=notice.reason)
        case "retrying":
            system.events.emit(
                StreamReconnectScheduledEvent,
                procedure=procedure,
                delay=timedelta(seconds=notice.delay or 0),
            )
        case "reconnected":
            system.events.emit(
                StreamReconnectedEvent,
                procedure=procedure,
                attempts=notice.attempts or 0,
                outage=timedelta(seconds=notice.outage or 0),
            )
        case _:
            system.events.emit(StreamEndedEvent, procedure=procedure, reason=notice.reason or "")
