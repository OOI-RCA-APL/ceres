//! The `run` and `check` commands, hosting the engine in the Python runtime.
//!
//! Components are written in Python, so both commands spawn the host module rather than
//! doing the work natively. A plain run replaces this process with the host, so signals
//! and the exit code flow through untouched. Watch mode, or a development console, keeps
//! the binary resident as a parent owning the host child, the console dev server, and
//! the ports both bind, so the console and its ports survive engine restarts.

use std::collections::BTreeSet;
use std::convert::Infallible;
use std::path::{Path, PathBuf};
use std::time::Duration;

use notify::{RecursiveMode, Watcher as _};
use tokio::process::Child;
use tokio::sync::mpsc::{UnboundedReceiver, UnboundedSender};

use crate::cli::RunArgs;
use crate::error::{Result, fail, failure};
use crate::output::Output;
use crate::project::Project;
use crate::{development, runtime};

/// How long a batch of file changes gets to settle before a restart acts on it.
const DEBOUNCE: Duration = Duration::from_millis(300);

/// How long a stopping child gets to exit before the escalation, and after it.
const STOP_BUDGET: Duration = Duration::from_secs(15);
const KILL_BUDGET: Duration = Duration::from_secs(5);

/// Validate the project configuration in the Python runtime, where component imports
/// resolve.
pub fn check(project: &Project) -> Result<Infallible> {
    runtime::replace(runtime::host(&payload(project, &[], true, None))?)
}

/// Start the engine, optionally under a watcher or beside a console dev server.
pub fn run(
    args: RunArgs,
    project: &Project,
    source: Option<PathBuf>,
    output: &Output,
) -> Result<()> {
    let source = source
        .map(|source| {
            source.canonicalize().map_err(|error| {
                failure!(
                    "Cannot resolve the development source {}. {error}",
                    source.display()
                )
            })
        })
        .transpose()?;

    let development = source
        .as_deref()
        .map(|source| Development::plan(project, source, args.development_console_port))
        .transpose()?;

    // The engine only moves off its configured port when the dev console stands in for
    // the built-in one, so the host is told to rebind only then.
    let server_port = development.as_ref().and_then(|development| {
        let addresses = &development.addresses;
        addresses.moved.then_some(addresses.engine)
    });
    let payload = payload(project, &args.addresses, false, server_port);

    if !args.watch && development.is_none() {
        return runtime::replace(runtime::host(&payload)?).map(|never| match never {});
    }

    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|error| failure!("Failed to start the async runtime. {error}"))?;
    runtime.block_on(resident(
        args.watch,
        project,
        development,
        source.as_deref(),
        &payload,
        output,
    ))
}

/// The host module's JSON payload.
fn payload(
    project: &Project,
    addresses: &[String],
    check: bool,
    server_port: Option<u16>,
) -> String {
    serde_json::json!({
        "config": project.config_path(),
        "addresses": addresses,
        "check": check,
        "server_port": server_port,
    })
    .to_string()
}

/// Run the host as a child, restarting on file changes and serving the dev console.
async fn resident(
    watch: bool,
    project: &Project,
    development: Option<Development>,
    source: Option<&Path>,
    payload: &str,
    output: &Output,
) -> Result<()> {
    let mut exit = ExitSignals::new()?;

    // The console dev server first, so a spawn failure costs nothing to unwind.
    let mut console = development
        .as_ref()
        .map(|development| development.spawn(output))
        .transpose()?;

    let rust = source.map(|source| source.join("rust"));
    let (sender, mut receiver) = tokio::sync::mpsc::unbounded_channel();
    let _watcher = watch
        .then(|| watcher(project, rust.as_deref(), sender))
        .transpose()?;

    let mut child = start(payload)?;
    let mut alive = true;
    let mut status = None;

    loop {
        tokio::select! {
            _ = exit.recv() => break,
            exited = child.wait(), if alive => {
                alive = false;
                status = exited.ok();
                if !watch {
                    break;
                }
            }
            changed = receiver.recv(), if watch => {
                let Some(first) = changed else { break };
                let paths = settle(first, &mut receiver).await;
                let info = paths
                    .iter()
                    .map(|path| path.display().to_string())
                    .collect::<Vec<_>>()
                    .join(", ");

                // A Rust edit only matters once the extension is rebuilt, and a failed
                // build keeps the running engine instead of restarting onto stale code.
                if let (Some(rust), Some(source)) = (&rust, source)
                    && paths.iter().any(|path| path.starts_with(rust))
                {
                    output.write(format!("Rebuilding the development source: {info}"));
                    if !rebuild(source).await {
                        output.write("Rebuild failed, keeping the running engine.");
                        continue;
                    }
                }

                output.write(format!("Restarting, watch mode detected changes: {info}"));
                if alive {
                    stop(&mut child).await;
                }

                child = start(payload)?;
                alive = true;
            }
        }
    }

    if alive {
        stop(&mut child).await;
    }

    if let Some(console) = &mut console {
        stop_console(console).await;
    }

    // Watch mode restarts a failed engine on the next edit, so only a plain resident run
    // carries the child's own exit status out.
    match status {
        Some(status) if !watch && !status.success() => {
            Err(crate::error::Exit::status(status.code().unwrap_or(1)))
        }
        _ => Ok(()),
    }
}

/// Start the host child.
fn start(payload: &str) -> Result<Child> {
    tokio::process::Command::from(runtime::host(payload)?)
        // A backstop for error paths, the ordinary shutdown escalating on its budget.
        .kill_on_drop(true)
        .spawn()
        .map_err(|error| failure!("Failed to start the engine host. {error}"))
}

/// Stop the host child, escalating when the budget runs out.
async fn stop(child: &mut Child) {
    if child.try_wait().is_ok_and(|status| status.is_some()) {
        return;
    }

    #[cfg(unix)]
    {
        terminate(child);
        if tokio::time::timeout(STOP_BUDGET, child.wait())
            .await
            .is_ok()
        {
            return;
        }
    }

    let _ = child.start_kill();
    let _ = tokio::time::timeout(KILL_BUDGET, child.wait()).await;
}

/// Send SIGTERM to a child, asking it to exit on its own terms.
#[cfg(unix)]
fn terminate(child: &Child) {
    if let Some(id) = child.id() {
        // SAFETY: signaling a child this process spawned and still owns.
        unsafe { libc::kill(id as i32, libc::SIGTERM) };
    }
}

/// Collect the paths of one settled batch of file changes.
///
/// Editors write several files per save and a save can land as more than one event, so a
/// batch is open until the changes go quiet.
async fn settle(first: PathBuf, receiver: &mut UnboundedReceiver<PathBuf>) -> BTreeSet<PathBuf> {
    let mut paths = BTreeSet::from([first]);
    while let Ok(Some(path)) = tokio::time::timeout(DEBOUNCE, receiver.recv()).await {
        paths.insert(path);
    }

    paths
}

/// Watch everything whose edits should restart the engine.
///
/// That is the project directory, the interpreter's own `ceres` package, and a
/// development source's Rust crates. The watcher stops when dropped.
fn watcher(
    project: &Project,
    rust: Option<&Path>,
    sender: UnboundedSender<PathBuf>,
) -> Result<notify::RecommendedWatcher> {
    let config_path = project.config_path().to_owned();
    let rust_directory = rust.map(Path::to_owned);

    let mut roots = vec![project.directory().to_owned(), package_directory()?];
    roots.extend(rust.map(Path::to_owned));

    let filter_roots = roots.clone();
    let mut watcher = notify::recommended_watcher(move |event: notify::Result<notify::Event>| {
        let Ok(event) = event else { return };
        if !matches!(
            event.kind,
            notify::EventKind::Create(_)
                | notify::EventKind::Modify(_)
                | notify::EventKind::Remove(_)
        ) {
            return;
        }

        for path in event.paths {
            if relevant(
                &path,
                &config_path,
                &filter_roots,
                rust_directory.as_deref(),
            ) {
                let _ = sender.send(path);
            }
        }
    })
    .map_err(|error| failure!("Failed to start the file watcher. {error}"))?;

    for root in roots {
        watcher
            .watch(&root, RecursiveMode::Recursive)
            .map_err(|error| failure!("Failed to watch {}. {error}", root.display()))?;
    }

    Ok(watcher)
}

/// Whether a changed path should restart the engine.
fn relevant(path: &Path, config_path: &Path, roots: &[PathBuf], rust: Option<&Path>) -> bool {
    if path == config_path {
        return true;
    }

    // Only what sits below a watch root is judged, so a project living under a hidden
    // parent, `~/.config` say, is not ignored wholesale. The longest matching root wins
    // since the roots can nest.
    let Some(below) = roots
        .iter()
        .filter_map(|root| path.strip_prefix(root).ok())
        .min_by_key(|relative| relative.components().count())
    else {
        return false;
    };

    // Dot components cover version control, virtual environments, and tool caches in one
    // stroke, and `site-packages` quiets a virtual environment whatever it is named.
    let ignored = below.components().any(|component| {
        component.as_os_str().to_str().is_some_and(|name| {
            name.starts_with('.')
                || matches!(
                    name,
                    "__pycache__" | "node_modules" | "site-packages" | "target"
                )
        })
    });
    if ignored {
        return false;
    }

    match path.extension().and_then(|extension| extension.to_str()) {
        Some("py") => true,
        Some("rs" | "toml") => rust.is_some_and(|rust| path.starts_with(rust)),
        _ => false,
    }
}

/// The directory of the interpreter's `ceres` package.
fn package_directory() -> Result<PathBuf> {
    const PROBE: &str = "import importlib.util; print(importlib.util.find_spec('ceres').origin)";

    let python = runtime::find_python()?;
    let probed = std::process::Command::new(&python)
        .args(["-c", PROBE])
        .output()
        .map_err(|error| failure!("Failed to locate the ceres package. {error}"))?;
    let origin = String::from_utf8_lossy(&probed.stdout);
    let origin = Path::new(origin.trim());
    origin
        .parent()
        .filter(|parent| parent.is_dir())
        .map(Path::to_owned)
        .ok_or_else(|| failure!("Failed to locate the ceres package."))
}

/// Rebuild the source's extension into the environment, returning whether it succeeded.
async fn rebuild(source: &Path) -> bool {
    let Ok(command) = development::installer(source, true) else {
        return false;
    };

    tokio::process::Command::from(command)
        .status()
        .await
        .is_ok_and(|status| status.success())
}

/// The console dev server for a development source, and where everything listens.
struct Development {
    console_directory: PathBuf,
    addresses: Addresses,
}

impl Development {
    /// Resolve the console directory and decide where the engine and the console listen.
    fn plan(project: &Project, source: &Path, console_port: Option<u16>) -> Result<Self> {
        let console_directory = find_console_source(source)?;
        if runtime::which("npm").is_none() {
            fail!(
                "npm was not found on PATH, and the console's dev server is an npm \
                 project. Install Node.js, which npm comes with, from https://nodejs.org \
                 or a package manager, then run this again."
            );
        }

        let meta = project.load_meta()?;
        Ok(Self {
            console_directory,
            addresses: assign_addresses(&meta.server.host, meta.server.port, console_port)?,
        })
    }

    /// Spawn the console's dev server.
    ///
    /// It proxies API calls through to the engine and holds its websockets straight to
    /// it, so it is told where the engine ended up rather than assuming the default port.
    fn spawn(&self, output: &Output) -> Result<Child> {
        let addresses = &self.addresses;
        let child = tokio::process::Command::new("npm")
            .args(["run", "dev"])
            .current_dir(&self.console_directory)
            // Bound where the engine's own server would be, standing in for it. Nuxt
            // otherwise defaults to `localhost`, which Node resolves to the IPv6
            // loopback alone.
            .env("NUXT_HOST", &addresses.host)
            .env("NUXT_PORT", addresses.console.to_string())
            // Read by the dev proxy for API calls and by the console itself for
            // websockets, which the proxy cannot upgrade and which therefore go straight
            // to the engine.
            .env("CERES_API_PORT", addresses.engine.to_string())
            .env("VITE_CERES_API_PORT", addresses.engine.to_string())
            // A backstop for error paths, the ordinary shutdown terminating gracefully.
            .kill_on_drop(true)
            .spawn()
            .map_err(|error| failure!("Failed to start the console dev server. {error}"))?;

        output.write(format!(
            "Console dev server on port {}, engine on {}.",
            addresses.console, addresses.engine
        ));
        Ok(child)
    }
}

/// Stop the console dev server.
///
/// Terminated and awaited so the run releases the console's port on the way out.
async fn stop_console(child: &mut Child) {
    #[cfg(unix)]
    terminate(child);
    #[cfg(not(unix))]
    let _ = child.start_kill();

    let _ = tokio::time::timeout(KILL_BUDGET, child.wait()).await;
}

/// Locate the console within a Ceres source tree.
fn find_console_source(source: &Path) -> Result<PathBuf> {
    let console = source.join("console");
    if !console.join("package.json").is_file() {
        fail!(
            "\"{}\" is not a Ceres source tree, no console/package.json in it.",
            source.display()
        );
    }

    Ok(console)
}

/// Where the engine and the console's dev server each listen.
struct Addresses {
    host: String,
    engine: u16,
    console: u16,
    /// Whether the engine moved off its configured port, which the host must then rebind.
    moved: bool,
}

/// Decide which port the engine and the dev console each take, moving the engine if
/// needed.
///
/// Without a console port the dev console stands in for the built-in one, taking the
/// configured port so the address in the browser does not change, and the engine moves
/// to a free port behind it. With one, both consoles are served and neither moves.
fn assign_addresses(
    host: &str,
    configured: Option<u16>,
    console_port: Option<u16>,
) -> Result<Addresses> {
    let configured = configured.unwrap_or(8080);
    match console_port {
        Some(console) => Ok(Addresses {
            host: host.to_owned(),
            engine: configured,
            console,
            moved: false,
        }),
        None => Ok(Addresses {
            host: host.to_owned(),
            engine: free_port(host)?,
            console: configured,
            moved: true,
        }),
    }
}

/// Ask the operating system for a port nothing is listening on.
///
/// Probed on the host the engine goes on to bind, so a port taken on that host alone is
/// not reported as free.
fn free_port(host: &str) -> Result<u16> {
    std::net::TcpListener::bind((host, 0))
        .and_then(|listener| listener.local_addr())
        .map(|address| address.port())
        .map_err(|error| failure!("Failed to find a free port on {host}. {error}"))
}

/// Resolve when the process is asked to exit.
struct ExitSignals {
    #[cfg(unix)]
    interrupt: tokio::signal::unix::Signal,
    #[cfg(unix)]
    terminate: tokio::signal::unix::Signal,
}

impl ExitSignals {
    fn new() -> Result<Self> {
        #[cfg(unix)]
        {
            use tokio::signal::unix::{SignalKind, signal};

            let make = |kind| {
                signal(kind).map_err(|error| failure!("Failed to listen for signals. {error}"))
            };

            Ok(Self {
                interrupt: make(SignalKind::interrupt())?,
                terminate: make(SignalKind::terminate())?,
            })
        }

        #[cfg(not(unix))]
        {
            Ok(Self {})
        }
    }

    async fn recv(&mut self) {
        #[cfg(unix)]
        {
            tokio::select! {
                _ = self.interrupt.recv() => {}
                _ = self.terminate.recv() => {}
            }
        }

        #[cfg(not(unix))]
        {
            let _ = tokio::signal::ctrl_c().await;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_dev_console_takes_the_configured_port() {
        let addresses = assign_addresses("127.0.0.1", Some(9000), None).unwrap();

        assert_eq!(addresses.console, 9000);
        assert_ne!(addresses.engine, 9000);
        assert!(addresses.moved);
    }

    #[test]
    fn an_unset_port_falls_back_to_the_default() {
        let addresses = assign_addresses("127.0.0.1", None, None).unwrap();

        assert_eq!(addresses.console, 8080);
    }

    #[test]
    fn a_console_port_serves_both_consoles() {
        let addresses = assign_addresses("127.0.0.1", Some(9000), Some(9001)).unwrap();

        assert_eq!((addresses.engine, addresses.console), (9000, 9001));
        assert!(!addresses.moved);
    }

    #[test]
    fn the_dev_console_binds_the_engines_host() {
        let addresses = assign_addresses("127.0.0.1", None, None).unwrap();

        assert_eq!(addresses.host, "127.0.0.1");
    }

    #[test]
    fn a_directory_that_is_not_a_source_tree_is_rejected() {
        let missing = tempfile::tempdir().unwrap();

        let error = find_console_source(missing.path()).unwrap_err();

        assert!(error.message.unwrap().contains("not a Ceres source tree"));
    }

    #[test]
    fn a_source_edit_is_only_relevant_where_it_can_matter() {
        let config = Path::new("/project/ceres.yaml");
        let rust = Path::new("/source/rust");
        let roots = [PathBuf::from("/project"), PathBuf::from("/source/rust")];
        let judge = |path: &str, rust| relevant(Path::new(path), config, &roots, rust);

        assert!(relevant(config, config, &roots, None));
        assert!(judge("/project/driver.py", None));
        assert!(judge("/source/rust/lib.rs", Some(rust)));
        assert!(!judge("/source/rust/lib.rs", None));
        assert!(!judge("/project/notes.txt", None));
        assert!(!judge("/project/__pycache__/driver.py", None));
        assert!(!judge("/project/.venv/lib/site.py", None));
        assert!(!judge(
            "/project/venv/lib/python3/site-packages/thing.py",
            None
        ));
        assert!(!judge("/source/rust/target/debug/build.rs", Some(rust)));
        assert!(!judge("/elsewhere/driver.py", None));
    }

    #[test]
    fn a_project_under_a_hidden_parent_is_still_watched() {
        let config = Path::new("/home/user/.config/project/ceres.yaml");
        let roots = [PathBuf::from("/home/user/.config/project")];

        assert!(relevant(
            Path::new("/home/user/.config/project/driver.py"),
            config,
            &roots,
            None
        ));
        assert!(!relevant(
            Path::new("/home/user/.config/project/.venv/site.py"),
            config,
            &roots,
            None
        ));
    }
}
