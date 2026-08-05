"""Proxy RTSP camera streams as fragmented MP4.

The public surface is `rtsp`, which spawns an `ffmpeg` subprocess and forwards its fragmented
MP4 output through a `StreamingOutput`. When the RTSP source drops, the subprocess is respawned
with capped exponential backoff, and `_FragmentSplicer` rewrites each fresh session's fragments
so clients holding open video connections keep decoding one continuous stream.
"""

import asyncio
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from shutil import which
from time import monotonic
from typing import TYPE_CHECKING, Final

from ceres.component import StreamingOutput
from ceres.concurrency import sleep

if TYPE_CHECKING:
    from os import PathLike

__all__ = [
    "rtsp",
]

# Reconnect backoff bounds, in seconds. The delay starts at the initial value, doubles after
# each failed session up to the cap, and resets after a session that streamed healthily for at
# least the healthy duration.
_BACKOFF_INITIAL: Final = 0.5
_BACKOFF_CAP: Final = 10.0
_HEALTHY_SESSION_DURATION: Final = 5.0

# Sanity cap on the splicer's box buffer. Live fragmented output emits small boxes, so a single
# box larger than this means the stream is not something the splicer understands, and it falls
# back to raw passthrough rather than ballooning memory.
_BUFFER_CAP: Final = 32 * 1024 * 1024


class _FragmentSplicer:
    """Splice the fragmented MP4 output of successive `ffmpeg` sessions into one stream.

    A respawned `ffmpeg` emits a fresh init segment (`ftyp` plus `moov`) and restarts its
    fragment decode timestamps at zero, either of which breaks a decoder mid-stream. The
    splicer buffers raw bytes, walks top-level ISO BMFF boxes, passes the first session through
    byte-identical, and rewrites every later session so it continues the first. It drops the
    repeated init segment, renumbers `mfhd` sequence numbers with a counter it owns, and
    offsets each track's `tfdt` baseMediaDecodeTime so the timeline never jumps backwards.

    This is hand-rolled rather than built on `pymp4` because the module needs box-boundary
    walking plus two fixed-offset field patches on small buffered boxes, not general MP4
    parsing, and `pymp4` would add a Construct dependency to every install for that.
    """

    def __init__(self) -> None:
        # Bytes fed but not yet emitted, holding at most one incomplete top-level box. Bounded
        # by `_BUFFER_CAP`, beyond which the splicer degrades to raw passthrough.
        self._buffer = bytearray()
        # Once true, every byte passes through unmodified for the rest of the splicer's life.
        self._passthrough = False
        # True from the first respawned session onward, enabling init-segment dropping and
        # fragment patching. The first session always passes through untouched.
        self._splicing = False
        # The continuing `mfhd` sequence counter. It adopts the values the first session emits
        # and takes over numbering from the second session on.
        self._sequence_number = 0
        # Per-track state keyed by `tfhd` track ID. Bounded by the number of tracks `ffmpeg`
        # emits, which is a handful, so no eviction is needed. `_last_times` holds the last
        # emitted `tfdt` time, `_deltas` the difference between the last two, and `_offsets`
        # the amount added to the current session's raw times, all in native track units.
        self._last_times: dict[int, int] = {}
        self._deltas: dict[int, int] = {}
        self._offsets: dict[int, int] = {}

    def start_new_session(self) -> None:
        """Prepare for the output of a respawned `ffmpeg` process.

        Discard any incomplete box left over from the dead process, and compute each track's
        timestamp offset as the previous session's estimated end, assuming the final fragment
        lasted as long as the delta between the last two. When a track only ever produced one
        fragment, the offset is its time plus zero, accepting the small overlap.
        """
        self._buffer.clear()
        self._splicing = True
        self._offsets = {
            track_id: last_time + self._deltas.get(track_id, 0)
            for track_id, last_time in self._last_times.items()
        }

    def feed(self, data: bytes) -> bytes:
        """Consume raw stream bytes and return the spliced bytes ready to emit.

        Args:
            data: The next chunk of raw `ffmpeg` output.

        Returns:
            Zero or more complete, possibly patched boxes. Bytes forming an incomplete box stay
            buffered until a later `feed` completes them.
        """
        if self._passthrough:
            return data

        self._buffer += data
        output = bytearray()
        while True:
            header = self._parse_header()
            if header is None:
                break

            size, box_type, header_size = header
            if size == 0 or size < header_size or size > _BUFFER_CAP:
                # A zero size means the box extends to the end of the stream, which live
                # fragmented output never produces. A size smaller than its own header is
                # malformed, and one beyond the sanity cap would balloon memory. In every case
                # the stream is not something the splicer understands, so flush the buffer and
                # degrade to raw passthrough for the rest of the session.
                self._passthrough = True
                output += self._buffer
                self._buffer.clear()
                return bytes(output)

            if len(self._buffer) < size:
                break

            box = self._buffer[:size]
            del self._buffer[:size]
            if self._splicing and box_type in (b"ftyp", b"moov"):
                # A respawned session re-emits its init segment, but clients already hold the
                # original, so drop it.
                continue

            if box_type == b"moof":
                self._process_moof(box, header_size)

            output += box

        return bytes(output)

    def _parse_header(self) -> tuple[int, bytes, int] | None:
        """Parse the top-level box header at the front of the buffer.

        Returns:
            The box size, type, and header size, or `None` when too few bytes are buffered.
            A size of 1 means a 64-bit largesize follows the 8-byte header, which is resolved
            here into the actual size with a 16-byte header.
        """
        buffer = self._buffer
        if len(buffer) < 8:
            return None

        size = int.from_bytes(buffer[0:4], "big")
        box_type = bytes(buffer[4:8])
        header_size = 8
        if size == 1:
            if len(buffer) < 16:
                return None

            size = int.from_bytes(buffer[8:16], "big")
            header_size = 16

        return size, box_type, header_size

    @staticmethod
    def _children(box: bytearray, start: int, end: int) -> Iterator[tuple[int, int, bytes, int]]:
        """Yield `(offset, size, type, header_size)` for each child box in `box[start:end]`.

        Stop at the first malformed child rather than guessing at boundaries.
        """
        offset = start
        while offset + 8 <= end:
            size = int.from_bytes(box[offset : offset + 4], "big")
            child_type = bytes(box[offset + 4 : offset + 8])
            header_size = 8
            if size == 1:
                if offset + 16 > end:
                    return

                size = int.from_bytes(box[offset + 8 : offset + 16], "big")
                header_size = 16

            if size < header_size or offset + size > end:
                return

            yield offset, size, child_type, header_size
            offset += size

    def _process_moof(self, box: bytearray, header_size: int) -> None:
        """Track and, on respawned sessions, patch a `moof` box in place.

        Walk the fragment's `mfhd` and `traf` children, recording per-track timing state in
        every session and rewriting sequence numbers and decode times from the second session
        on.
        """
        for offset, size, child_type, child_header_size in self._children(
            box, header_size, len(box)
        ):
            payload = offset + child_header_size
            if child_type == b"mfhd":
                self._process_mfhd(box, payload)
            elif child_type == b"traf":
                self._process_traf(box, payload, offset + size)

    def _process_mfhd(self, box: bytearray, payload: int) -> None:
        """Continue the fragment sequence numbering through an `mfhd` box.

        The sequence number sits 4 bytes into the payload, after the version and flags. The
        first session's values are adopted as-is, and later sessions are renumbered with the
        continuing counter.
        """
        if payload + 8 > len(box):
            return

        if self._splicing:
            self._sequence_number += 1
            box[payload + 4 : payload + 8] = self._sequence_number.to_bytes(4, "big")
        else:
            self._sequence_number = int.from_bytes(box[payload + 4 : payload + 8], "big")

    def _process_traf(self, box: bytearray, start: int, end: int) -> None:
        """Track and patch the `tfdt` of a `traf` box, keyed by its `tfhd` track ID."""
        track_id: int | None = None
        for offset, size, child_type, child_header_size in self._children(box, start, end):
            payload = offset + child_header_size
            if child_type == b"tfhd" and payload + 8 <= offset + size:
                # The `tfhd` payload starts with version and flags, then the 4-byte track ID.
                track_id = int.from_bytes(box[payload + 4 : payload + 8], "big")
            elif child_type == b"tfdt" and track_id is not None:
                self._process_tfdt(box, payload, track_id)

    def _process_tfdt(self, box: bytearray, payload: int, track_id: int) -> None:
        """Offset a `tfdt` baseMediaDecodeTime and record the track's timing state.

        The time follows the version and flags, as 4 bytes for version 0 and 8 bytes for
        version 1.
        """
        version = box[payload]
        width = 8 if version == 1 else 4
        start = payload + 4
        end = start + width
        if end > len(box):
            return

        time = int.from_bytes(box[start:end], "big")
        if self._splicing:
            time += self._offsets.get(track_id, 0)
            # Mask to the field width. A version 0 field can only overflow after the same
            # runtime that would overflow a single unspliced session.
            box[start:end] = (time & ((1 << (width * 8)) - 1)).to_bytes(width, "big")

        last_time = self._last_times.get(track_id)
        if last_time is not None:
            self._deltas[track_id] = time - last_time

        self._last_times[track_id] = time


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
    reconnect: bool = True,
    stall_timeout: float | None = 10.0,  # Seconds.
) -> StreamingOutput:
    """Proxy an RTSP stream as fragmented MP4 via a `StreamingOutput`.

    Spawn an `ffmpeg` subprocess that reads from `url`, transcodes or copies the video into
    fragmented MP4, and forwards the bytes through a `StreamingOutput` object. The returned
    output can be handed back from component queries or actions to stream the video to clients.

    When the RTSP source drops, the subprocess is respawned and its output is spliced onto the
    original timeline, so clients holding open video connections keep decoding one continuous
    stream across the gap.

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
        reconnect: If true, respawn `ffmpeg` whenever its output ends or the spawn fails,
            waiting between attempts with capped exponential backoff, 0.5 s doubling to a 10 s
            cap and resetting after a session that streamed for at least 5 s. Each respawned
            session is spliced so the stream continues the original timeline and clients keep
            decoding without reconnecting. If false, the stream ends when `ffmpeg`'s output
            does.
        stall_timeout: Seconds of socket silence after which `ffmpeg` gives up on the source,
            passed as the RTSP demuxer's `-timeout`. Without it a source that dies while
            holding its TCP connection open stalls the stream forever instead of triggering a
            reconnect, since RTSP has no `-reconnect` family of its own. Pass `None` to omit
            the flag.

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
            # Give up on a silent source, so a dead camera holding its connection open
            # becomes an exit the respawn loop recovers from rather than a stalled read.
            # `-timeout` is the RTSP demuxer's socket I/O timeout in microseconds on
            # ffmpeg 5 and newer. Older ffmpeg spelled that `-stimeout` and read
            # `-timeout` as a listen-mode option, so pass `stall_timeout=None` there.
            *(("-timeout", str(int(stall_timeout * 1e6))) if stall_timeout else ()),
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

        splicer = _FragmentSplicer()
        delay = _BACKOFF_INITIAL
        respawned = False

        while True:
            if respawned:
                splicer.start_new_session()

            started = monotonic()
            process = None

            try:
                try:
                    # Spawn an `ffmpeg` subprocess asynchronously.
                    process = await asyncio.create_subprocess_exec(
                        *command,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=sys.stderr,
                    )
                except OSError:
                    if not reconnect:
                        raise

                    process = None

                if process is not None:
                    # Yield all MP4 data from `ffmpeg` stdout.
                    assert process.stdout is not None
                    while True:
                        chunk = await process.stdout.read(2**13)
                        if chunk == b"":
                            # An empty chunk means the source dropped or `ffmpeg` exited.
                            break

                        spliced = splicer.feed(chunk)
                        if spliced:
                            yield spliced

                        # Yield to the event loop.
                        await sleep(0)
            finally:
                # Kill it! Behold, `ffmpeg` does not respect `SIGTERM`, and it does not
                # respect me.
                if process is not None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass

            if not reconnect:
                break

            respawned = True

            # A session that streamed healthily for a while earns a fresh backoff.
            if monotonic() - started >= _HEALTHY_SESSION_DURATION:
                delay = _BACKOFF_INITIAL

            await sleep(delay)
            delay = min(delay * 2.0, _BACKOFF_CAP)

    return StreamingOutput(stream, "video/mp4")
