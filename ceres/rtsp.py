"""Proxy RTSP camera streams as fragmented MP4.

The public surface is `rtsp`, which remuxes a camera's video into one fragmented MP4 stream
through the FFmpeg built into the Ceres extension and forwards it through a
`StreamingOutput`. A lost camera is reconnected and its packets continue the same timeline, so
clients holding open video connections keep decoding one continuous stream.
"""

from collections.abc import AsyncIterator

from ceres.__internal__.core import RtspStream
from ceres.component import StreamingOutput

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
) -> StreamingOutput:
    """Proxy an RTSP stream as fragmented MP4 via a `StreamingOutput`.

    Read the camera's video from `url` and remux it into fragmented MP4 on a thread of its own,
    forwarding the bytes through a `StreamingOutput` object. The returned output can be handed
    back from component queries or actions to stream the video to clients. Each client that
    opens the output gets its own connection to the camera. Only the camera's video is
    streamed, audio is dropped.

    When the camera drops, the connection is reopened and its packets are placed after the
    last one sent, so clients holding open video connections keep decoding one continuous
    stream across the gap. A camera that comes back with a different codec, resolution, or
    parameter set ends the stream, because the MP4 already sent describes the old one.

    FFmpeg's log goes to the Rust `log` facade at debug level, and every failure also ends
    the stream with an error.

    Args:
        url: URL of the RTSP stream to read from.
        copy: If true, copy the video stream without re-encoding. Re-encoding is not
            available yet, so false raises.
        transport: The RTSP transport, `"tcp"` or `"udp"`. Defaults to `"tcp"`.
        fragment_duration: Longest duration in seconds of each emitted MP4 fragment. Defaults
            to 50 ms to reduce latency.
        dash: If true, fragments carry the DASH `sidx` index so the output is DASH-compatible.
        reconnect: If true, reopen the camera whenever the connection ends or fails to open,
            waiting between attempts with capped exponential backoff, 0.5 s doubling to a 10 s
            cap and resetting after a session that streamed for at least 5 s. If false, the
            stream ends when the first connection does.
        stall_timeout: Seconds without a packet after which the camera counts as lost, so a
            camera that dies while holding its TCP connection open triggers a reconnect.
            Pass `None` to wait on a silent camera forever.

    Returns:
        A `StreamingOutput` that yields `video/mp4` bytes.

    Raises:
        NotImplementedError: If `copy` is false.
        ValueError: If `transport` is not `"tcp"` or `"udp"`, or a duration is negative. The
            stream raises it when first read.
        ConnectionError: From the stream, when the camera cannot be reached and `reconnect`
            is false, or when the remux fails.
    """
    if not copy:
        raise NotImplementedError("rtsp(copy=False) re-encoding is not available yet.")

    async def stream() -> AsyncIterator[bytes]:
        session = RtspStream(
            url,
            transport=transport,
            fragment_duration=fragment_duration,
            dash=dash,
            reconnect=reconnect,
            stall_timeout=stall_timeout,
        )
        try:
            while (chunk := await session.next()) is not None:
                yield chunk
        finally:
            # Ends the camera connection at once when the client leaves mid-stream.
            session.close()

    return StreamingOutput(stream, "video/mp4")
