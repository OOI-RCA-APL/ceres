import asyncio
import subprocess
import sys
from collections.abc import AsyncIterator
from shutil import which
from typing import TYPE_CHECKING

from ceres.component import StreamingOutput
from ceres.concurrency import sleep

if TYPE_CHECKING:
    from os import PathLike

__all__ = [
    "rtsp",
]


async def rtsp(
    url: str,
    *,
    ffmpeg: str | PathLike | None = None,
    copy: bool = True,
    loglevel: str | None = "error",
    transport: str = "tcp",
    tune: str | None = "zerolatency",
    preset: str | None = "ultrafast",
    fragment_duration: float = 0.05,  # Seconds.
    dash: bool = True,
) -> StreamingOutput:
    """Proxy an RTSP stream as fragmented MP4 via a `StreamingOutput`.

    Spawn an `ffmpeg` subprocess that reads from `url`, transcodes or copies the video into
    fragmented MP4, and forwards the bytes through a `StreamingOutput` object. The returned
    output can be handed back from component queries or actions to stream the video to clients.

    `ffmpeg` must be installed. If the binary is not on the system `PATH`, pass an explicit path
    via the `ffmpeg` argument.

    Args:
        url: URL of the RTSP stream to read from.
        ffmpeg: Command or path of the `ffmpeg` executable. Defaults to looking up `ffmpeg` on
            the system `PATH`.
        copy: If true, copy the video stream without re-encoding. This is far cheaper than
            re-encoding when the input codec is already acceptable.
        loglevel: Value passed to `ffmpeg`'s `-loglevel`. Defaults to `"error"`. Pass `None` to
            omit the flag entirely.
        transport: Value passed to `ffmpeg`'s `-rtsp_transport`. Defaults to `"tcp"`.
        tune: Value passed to `ffmpeg`'s encoding `-tune`. Ignored when `copy` is true. Pass
            `None` to omit the flag.
        preset: Value passed to `ffmpeg`'s encoding `-preset`. Ignored when `copy` is true. Pass
            `None` to omit the flag.
        fragment_duration: Duration in seconds of each emitted MP4 fragment. Defaults to 50 ms
            to reduce latency.
        dash: If true, add the `dash` flag to `-movflags` so the output is DASH-compatible.

    Returns:
        A `StreamingOutput` that yields `video/mp4` bytes from the running `ffmpeg` subprocess.

    Raises:
        SystemError: If no `ffmpeg` path is provided and the executable cannot be found on the
            system `PATH`.
    """
    if ffmpeg is not None:
        ffmpeg = str(ffmpeg)
    else:
        if which("ffmpeg") is None:
            raise SystemError("Executable `ffmpeg` was not found in system path.")

        ffmpeg = "ffmpeg"

    async def stream() -> AsyncIterator[bytes]:
        # Flags passed into the `-movflags` option.
        movflags = [
            "empty_moov",  # Don't create a moov atom. Fragment everything.
            "default_base_moof",  # Use default base movie fragment.
        ]

        if dash:
            movflags.append("dash")  # Use DASH streaming for video output.

        command = [
            ffmpeg,
            # Use input media framerate.
            "-re",
            # Hide CLI banner.
            "-hide_banner",
            # Only log errors.
            *(("-loglevel", loglevel) if loglevel else ()),
            # Use TCP as the RTSP transport protocol.
            *("-rtsp_transport", transport),
            # Read data from the input RTSP URL.
            *("-i", url),
            # Whether to directly copy the input video codec.
            *(("-vcodec", "copy") if copy else ()),
            # Output video in MP4 format.
            *("-f", "mp4"),
            # Apply fragment duration option.
            *("-frag_duration", str(int(fragment_duration * 1e6))),
            # Apply movflags option.
            *("-movflags", "+" + "+".join(movflags)),
            # Reduce latency.
            *(("-tune", tune) if tune else ()),
            *(("-preset", preset) if preset else ()),
            # Write output to stdout.
            "-",
        ]

        # Spawn an `ffmpeg` subprocess asyncronously.
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
        )

        try:
            # Yield all MP4 data from `ffmpeg` stdout.
            assert process.stdout is not None
            while True:
                chunk = await process.stdout.read(2**13)
                if chunk == b"":
                    # If the chunk is empty, the stream has ended.
                    break

                yield chunk
                # Yield to the event loop.
                await sleep(0)
        finally:
            # Kill it! Behold, `ffmpeg` does not respect `SIGTERM`, and it does not respect me.
            try:
                process.kill()
            except ProcessLookupError:
                pass

    return StreamingOutput(stream, "video/mp4")
