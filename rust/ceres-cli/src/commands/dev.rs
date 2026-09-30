//! The `dev` command group, tools for developing against Ceres.

use std::net::{SocketAddr, ToSocketAddrs};
use std::time::Duration;

use ceres_media::{RtspServer, RtspServerOptions};

use crate::cli::RtspServerArgs;
use crate::error::{Exit, Result};
use crate::output::Output;

/// Serve test clips over RTSP, printing the URL once listening, until interrupted.
pub fn rtsp_server(args: &RtspServerArgs, output: &Output) -> Result<()> {
    let address = (args.host.as_str(), args.port)
        .to_socket_addrs()
        .ok()
        .and_then(|mut addresses| addresses.next())
        .ok_or_else(|| Exit::failed(format!("Cannot resolve {}.", args.host)))?;
    let options = RtspServerOptions {
        clips: args.clips.clone(),
        path: args.path.clone(),
        drop_after: seconds("--drop-after", args.drop_after)?,
        stall_after: seconds("--stall-after", args.stall_after)?,
        refuse: args.refuse,
        restart_after: seconds("--restart-after", args.restart_after)?,
        restart_downtime: seconds("--restart-downtime", Some(args.restart_downtime))?
            .unwrap_or_default(),
    };
    let server = start(address, options)?;
    output.put(server.url());
    server.wait();
    Ok(())
}

fn start(address: SocketAddr, options: RtspServerOptions) -> Result<RtspServer> {
    RtspServer::start(address, options)
        .map_err(|error| Exit::failed(format!("Cannot start the RTSP server. {error}")))
}

fn seconds(flag: &str, value: Option<f64>) -> Result<Option<Duration>> {
    value
        .map(|value| {
            Duration::try_from_secs_f64(value).map_err(|_| {
                Exit::failed(format!("{flag} takes a non-negative number of seconds."))
            })
        })
        .transpose()
}
