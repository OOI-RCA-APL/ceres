//! Serves test clips over RTSP, with network faults on demand, until interrupted. Prints the
//! stream URL on its own line once listening.

use std::net::ToSocketAddrs;
use std::process::ExitCode;
use std::time::Duration;

use ceres_media::{RtspServer, RtspServerOptions};
use clap::Parser;

#[derive(Debug, Parser)]
#[command(about)]
struct Arguments {
    /// Address to listen on.
    #[arg(long, default_value = "127.0.0.1")]
    host: String,

    /// Port to listen on, 0 for any free port. The URL printed on startup names it.
    #[arg(long, default_value_t = 8554)]
    port: u16,

    /// URL path clients request.
    #[arg(long, default_value = "stream")]
    path: String,

    /// A built-in clip, h264 or h265, or a video file path. Repeat it to give successive
    /// sessions successive clips.
    #[arg(long = "clip", value_name = "CLIP", default_value = "h264")]
    clips: Vec<String>,

    /// Close each session this many seconds after it starts playing.
    #[arg(long, value_name = "SECONDS")]
    drop_after: Option<f64>,

    /// Stop sending media this many seconds after each session starts playing, keeping the
    /// connection open.
    #[arg(long, value_name = "SECONDS")]
    stall_after: Option<f64>,

    /// Close this many connections as soon as they are accepted.
    #[arg(long, value_name = "COUNT", default_value_t = 0)]
    refuse: usize,

    /// Close the listener and every session once, after the server has been up this many
    /// seconds.
    #[arg(long, value_name = "SECONDS")]
    restart_after: Option<f64>,

    /// Seconds the server stays down on a restart.
    #[arg(long, value_name = "SECONDS", default_value_t = 1.0)]
    restart_downtime: f64,
}

fn main() -> ExitCode {
    match serve(&Arguments::parse()) {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("{message}");
            ExitCode::FAILURE
        }
    }
}

fn serve(arguments: &Arguments) -> Result<(), String> {
    let address = (arguments.host.as_str(), arguments.port)
        .to_socket_addrs()
        .ok()
        .and_then(|mut addresses| addresses.next())
        .ok_or_else(|| format!("Cannot resolve {}.", arguments.host))?;
    let options = RtspServerOptions {
        clips: arguments.clips.clone(),
        path: arguments.path.clone(),
        drop_after: seconds("--drop-after", arguments.drop_after)?,
        stall_after: seconds("--stall-after", arguments.stall_after)?,
        refuse: arguments.refuse,
        restart_after: seconds("--restart-after", arguments.restart_after)?,
        restart_downtime: seconds("--restart-downtime", Some(arguments.restart_downtime))?
            .unwrap_or_default(),
    };
    let server = RtspServer::start(address, options)
        .map_err(|error| format!("Cannot start the RTSP server. {error}"))?;
    // Standard output is line buffered, so a parent reading the URL line sees it at once.
    println!("{}", server.url());
    server.wait();
    Ok(())
}

fn seconds(flag: &str, value: Option<f64>) -> Result<Option<Duration>, String> {
    value
        .map(|value| {
            Duration::try_from_secs_f64(value)
                .map_err(|_| format!("{flag} takes a non-negative number of seconds."))
        })
        .transpose()
}
