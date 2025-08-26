import asyncio
import subprocess
import sys
from shutil import which
from typing import TYPE_CHECKING

import anyio

from ceres._internal.util import BytesLike
from ceres.component import Media
from ceres.stream import WriteStream

if TYPE_CHECKING:
    from anyio.abc import Process


async def rtsp(
    url: str,
    *,
    fragment_duration: float = 0.05,  # Seconds. 1/20 of a second by default to reduce latency.
    dash: bool = True,
    ffmpeg_path: str | None = None,
) -> Media:
    """
    Using `ffmpeg`, read from an RTSP stream at the provided URL, then convert it into MP4 format
    and output the live video into an output stream `Media` object. This media object can be
    returned directly from component queries/actions to proxy video from an external RTSP source.

    :param url: The URL of the RTSP stream to read from.
    :param fragment_duration: The interval in seconds at which new video fragments will be sent.
    :param dash: Whether to use DASH streaming for the output.
    :param ffmpeg_path: The path to the `ffmpeg` executable.

    This function requires `ffmpeg` to be installed. If this command is not available in the system
    path, provide its location through the `ffmpeg_path` argument.
    """
    if ffmpeg_path is not None:
        ffmpeg = ffmpeg_path
    else:
        if which("ffmpeg") is None:
            raise SystemError("Executable `ffmpeg` was not found in system path.")

        ffmpeg = "ffmpeg"

    async def write(output: WriteStream[BytesLike]) -> None:
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
            *("-loglevel", "error"),
            # Use TCP as the RTSP transport protocol.
            *("-rtsp_transport", "tcp"),
            # Read data from the input RTSP URL.
            *("-i", url),
            # Output video in MP4 format.
            *("-f", "mp4"),
            # Apply fragment duration option.
            *("-frag_duration", str(int(fragment_duration * 1e6))),
            # Apply movflags option.
            *("-movflags", "+" + "+".join(movflags)),
            # Reduce latency.
            *("-tune", "zerolatency"),
            *("-preset", "ultrafast"),
            # Write output to stdout.
            "-",
        ]

        # Read all chunks of MP4 data `ffmpeg` stdout and put it into the output stream.
        process: Process | None = None

        try:
            async with await anyio.open_process(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=sys.stderr,
            ) as process:
                assert process.stdin is not None
                assert process.stdout is not None
                async for chunk in process.stdout:
                    output.put(chunk)
        finally:
            if process is not None:

                async def kill():
                    try:
                        process.kill()
                    except ProcessLookupError:
                        # Process already exited.
                        pass

                    try:
                        async with asyncio.timeout(3):
                            await process.wait()
                    except TimeoutError:
                        print("WARNING: Failed to kill `ffmpeg` process within 3 seconds.")  # noqa

                await asyncio.shield(asyncio.create_task(kill()))

    return Media("video/mp4", write)
