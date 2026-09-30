use std::io::{self, Write};
use std::net::{Shutdown, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, PoisonError};
use std::thread;
use std::time::Instant;

use super::{POLL, StreamFaults};
use crate::{MediaError, MediaInput, MediaOutput, MediaPacket, MediaSink};

/// The largest RTP packet, an Ethernet MTU less its IP and UDP headers.
const PACKET_SIZE: usize = 1472;

pub(super) struct PlayContext {
    pub(super) clip: PathBuf,
    pub(super) faults: StreamFaults,
    pub(super) stop: Arc<AtomicBool>,
    pub(super) writer: Arc<Mutex<TcpStream>>,
}

/// The SDP describing `clip`'s video as the server streams it.
pub(super) fn describe(clip: &Path) -> Result<String, MediaError> {
    let (input, video) = open(clip)?;
    let discard: MediaSink = Box::new(|_| Ok(()));
    MediaOutput::open("rtp", &[], &input, &[video], PACKET_SIZE, discard)?.sdp()
}

/// Streams `clip` in a loop at its own pace until stopped, a fault fires, or the client leaves.
pub(super) fn play(context: &PlayContext) {
    // A failed write means the client left, which already ends the session.
    let _ = stream(context);
}

fn stream(context: &PlayContext) -> Result<(), MediaError> {
    let (mut input, video) = open(&context.clip)?;
    let time_base = input.time_base(video);
    let writer = Arc::clone(&context.writer);
    let sink: MediaSink = Box::new(move |data| interleave(&writer, data));
    let mut output = MediaOutput::open("rtp", &[], &input, &[video], PACKET_SIZE, sink)?;
    let started = Instant::now();
    let mut packet = MediaPacket::new();
    // Each loop of the clip is shifted to start where the previous one ended.
    let (mut offset, mut rebase, mut end) = (0, false, 0);
    let mut anchor = None;
    while !context.stop.load(Ordering::Relaxed) {
        let elapsed = started.elapsed();
        if context
            .faults
            .drop_after
            .is_some_and(|after| elapsed >= after)
        {
            let writer = context
                .writer
                .lock()
                .unwrap_or_else(PoisonError::into_inner);
            let _ = writer.shutdown(Shutdown::Both);
            return Ok(());
        }
        if context
            .faults
            .stall_after
            .is_some_and(|after| elapsed >= after)
        {
            while !context.stop.load(Ordering::Relaxed) {
                thread::sleep(POLL);
            }
            return Ok(());
        }
        if !input.read(&mut packet)? {
            (input, _) = open(&context.clip)?;
            rebase = true;
            continue;
        }
        if packet.stream() != video {
            continue;
        }
        let timing = packet.timing();
        if let Some(time) = timing.dts.or(timing.pts) {
            if rebase {
                offset = end - time;
                rebase = false;
            }
            let time = time + offset;
            end = end.max(time + timing.duration.max(1));
            let due = started + time_base.duration(time - *anchor.get_or_insert(time));
            while !context.stop.load(Ordering::Relaxed) && Instant::now() < due {
                thread::sleep(due.saturating_duration_since(Instant::now()).min(POLL));
            }
        }
        packet.shift(offset);
        output.write(0, &mut packet, time_base)?;
    }
    Ok(())
}

fn open(clip: &Path) -> Result<(MediaInput, usize), MediaError> {
    let mut input = MediaInput::open(&clip.to_string_lossy())?;
    let video = input.video_stream()?;
    Ok((input, video))
}

/// Frames one RTP or RTCP packet for the interleaved channel RTSP assigned it.
fn interleave(writer: &Mutex<TcpStream>, data: &[u8]) -> io::Result<()> {
    // RTCP packet types occupy 200 to 204 in the second byte, where RTP carries a dynamic
    // payload type, 96 to 127, or 224 to 255 with the marker bit set.
    let channel = u8::from(data.get(1).is_some_and(|kind| (200..=204).contains(kind)));
    let length = u16::try_from(data.len()).map_err(|_| io::Error::other("RTP packet too large"))?;
    let mut frame = Vec::with_capacity(4 + data.len());
    frame.extend_from_slice(&[b'$', channel]);
    frame.extend_from_slice(&length.to_be_bytes());
    frame.extend_from_slice(data);
    let mut writer = writer.lock().unwrap_or_else(PoisonError::into_inner);
    writer.write_all(&frame)
}
