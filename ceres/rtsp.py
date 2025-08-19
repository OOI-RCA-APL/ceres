import subprocess
import sys
from shutil import which

import anyio

from ceres._internal.util import BytesLike
from ceres.component import Writer
from ceres.stream import WriteStream


async def rtsp(url: str) -> Writer:
    if not url.startswith("rtsp://"):
        raise ValueError("Invalid RTSP URL.")
    if which("ffmpeg") is None:
        raise SystemError("Executable `ffmpeg` was not found in system path.")

    async def write(output: WriteStream[BytesLike]) -> None:
        # Use ffmpeg to read from the RTSP stream, convert it to the MP4 format and put the output
        # MP4 data into to the output stream.
        command = [
            "ffmpeg",
            # Hide CLI banner.
            "-hide_banner",
            # Only log errors.
            *("-loglevel", "error"),
            # Use TCP as the RTSP transport protocol.
            *("-rtsp_transport", "tcp"),
            # Read data from the input RTSP URL.
            *("-i", url),
            # Output in the MP4 format.
            *("-f", "mp4"),
            # Configure the stream to be fragmented and optimized for live streaming.
            *("-movflags", "+faststart+empty_moov+default_base_moof+frag_keyframe"),
            # Reduce latency.
            *("-tune", "zerolatency"),
            # Write output to stdout.
            "-",
        ]

        async with await anyio.open_process(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
        ) as process:
            assert process.stdout is not None
            async for chunk in process.stdout:
                output.put(chunk)

    return Writer(
        mime="video/mp4",
        write=write,
    )
