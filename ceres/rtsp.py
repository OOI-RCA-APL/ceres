import asyncio
import subprocess
import sys
from os import PathLike
from shutil import which

from ceres._internal.util import BytesLike
from ceres.component import Media
from ceres.stream import WriteStream


async def rtsp(
    url: str,
    *,
    ffmpeg: str | PathLike[str] | None = None,
    copy: bool = True,
    loglevel: str | None = "error",
    transport: str = "tcp",
    tune: str | None = "zerolatency",
    preset: str | None = "ultrafast",
    fragment_duration: float = 0.05,  # Seconds.
    dash: bool = True,
) -> Media:
    """
    Using `ffmpeg`, read from an RTSP stream at the provided URL, then convert it into MP4 format
    and output the live video into an output stream `Media` object. This media object can be
    returned directly from component queries/actions to proxy video from an external RTSP source.

    :param url: The URL of the RTSP stream to read from.
    :param ffmpeg: Optional command or path of the `ffmpeg` executable. Defaults to "ffmpeg".
    :param copy: Whether to copy the video stream without re-encoding. If the video stream is already in MP4 format, this will use far less resources than re-encoding.
    :param loglevel: The `ffmpeg` `-loglevel` to use. Defaults to "error". Set to `None` to omit `-loglevel`.
    :param transport: The `ffmpeg` `-rtsp_transport` protocol to use. Defaults to "tcp".
    :param tune: The `ffmpeg` encoding `-tune` to use. Defaults to "zerolatency". This has no effect if `copy` is `True`. Set to `None` to omit `-tune`.
    :param preset: The`ffmpeg`  encoding `-preset` to use. Defaults to "ultrafast". This has no effect if `copy` is `True`. Set to `None` to omit `-preset`.
    :param fragment_duration: The interval in seconds at which new video fragments will be sent. Defaults to 1/20th of a second to reduce latency.
    :param dash: Whether to use DASH streaming for the output.

    This function requires `ffmpeg` to be installed. If this command is not available in the system
    path, provide its location through the `ffmpeg_path` argument.
    """
    if ffmpeg is not None:
        ffmpeg = str(ffmpeg)
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

        # Spawn an async `ffmpeg` subprocess.
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
        )

        try:
            # Read all MP4 data from the `ffmpeg` stdout and put it into the output stream.
            assert process.stdout is not None
            await asyncio.sleep(0)
            while True:
                chunk = await process.stdout.read(2**13)
                if chunk == b"":
                    break

                output.put(chunk)
        finally:
            # Kill it! I've learned `ffmpeg` does not respect `SIGTERM`, and it does not respect me.
            process.kill()

    return Media("video/mp4", write)
