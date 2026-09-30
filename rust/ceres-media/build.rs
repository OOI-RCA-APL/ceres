//! Builds the vendored FFmpeg release into `OUT_DIR` and links its static libraries.

use std::env;
use std::fs::{self, File};
use std::io::{BufReader, ErrorKind};
use std::path::{Path, PathBuf};
use std::process::Command;

const FFMPEG_VERSION: &str = "9.0.2";

/// The FFmpeg libraries linked, in static link order.
const LIBRARIES: &[&str] = &["avformat", "avcodec", "avutil"];

/// Every FFmpeg option passed to `configure` apart from the toolchain, which `main` adds.
const OPTIONS: &[&str] = &[
    "--disable-everything",
    "--disable-autodetect",
    "--disable-programs",
    "--disable-doc",
    "--disable-debug",
    "--enable-static",
    "--disable-shared",
    "--enable-pic",
    "--disable-x86asm",
    "--disable-avdevice",
    "--disable-avfilter",
    "--disable-swscale",
    "--disable-swresample",
    "--enable-network",
    "--enable-protocol=file,pipe,rtp,tcp,udp",
    "--enable-demuxer=mov,rtp,rtsp,sdp",
    "--enable-muxer=mp4,rtp",
    "--enable-parser=h264,hevc",
    "--enable-bsf=h264_mp4toannexb,hevc_mp4toannexb",
];

fn main() {
    println!("cargo::rerun-if-changed=build.rs");
    let tarball = PathBuf::from(env_var("CARGO_MANIFEST_DIR"))
        .join(format!("vendor/ffmpeg-{FFMPEG_VERSION}.tar.xz"));
    println!("cargo::rerun-if-changed={}", tarball.display());

    let out_dir = PathBuf::from(env_var("OUT_DIR"));
    let prefix = out_dir.join("ffmpeg");
    let compiler = cc::Build::new().get_compiler();
    let arguments = configure_arguments(&prefix, &compiler);

    // The stamp holds the arguments of the last completed build, so a changed option rebuilds.
    let stamp = prefix.join("ceres-configure");
    let configured = arguments.join("\n");
    if fs::read_to_string(&stamp).ok().as_deref() != Some(configured.as_str()) {
        build(&tarball, &out_dir, &prefix, &arguments, &compiler);
        fs::write(&stamp, configured).expect("write the FFmpeg build stamp");
    }

    // The shim links before FFmpeg, since a static library resolves only earlier references.
    println!("cargo::rerun-if-changed=src/shim.c");
    cc::Build::new()
        .file("src/shim.c")
        .include(prefix.join("include"))
        .warnings(true)
        .compile("ceres_media_shim");
    link(&prefix);
    println!("cargo::rustc-env=CERES_FFMPEG_VERSION={FFMPEG_VERSION}");
}

fn configure_arguments(prefix: &Path, compiler: &cc::Tool) -> Vec<String> {
    let mut arguments = vec![format!("--prefix={}", shell_path(prefix))];
    arguments.extend(OPTIONS.iter().map(ToString::to_string));
    if compiler.is_like_msvc() {
        arguments.push("--toolchain=msvc".to_owned());
    } else {
        // FFmpeg splits `--cc` on spaces, which carries the target flags `cc` picked into every
        // compile and link step configure runs.
        let mut cc = compiler.path().display().to_string();
        for argument in compiler.args() {
            cc.push(' ');
            cc.push_str(&argument.to_string_lossy());
        }
        arguments.push(format!("--cc={cc}"));
    }
    if env_var("TARGET") != env_var("HOST") {
        arguments.push("--enable-cross-compile".to_owned());
        arguments.push(format!("--arch={}", env_var("CARGO_CFG_TARGET_ARCH")));
        arguments.push(format!("--target-os={}", target_os()));
    }
    arguments
}

fn target_os() -> &'static str {
    match env_var("CARGO_CFG_TARGET_OS").as_str() {
        "macos" => "darwin",
        "linux" => "linux",
        "windows" => "win64",
        other => panic!("no FFmpeg target OS for `{other}`"),
    }
}

fn build(tarball: &Path, out_dir: &Path, prefix: &Path, arguments: &[String], compiler: &cc::Tool) {
    let source = out_dir.join(format!("ffmpeg-{FFMPEG_VERSION}"));
    let build = out_dir.join("build");
    for directory in [&source, &build, &prefix.to_path_buf()] {
        match fs::remove_dir_all(directory) {
            Err(error) if error.kind() != ErrorKind::NotFound => {
                panic!("remove {}: {error}", directory.display())
            }
            _ => {}
        }
    }

    let archive = File::open(tarball).expect("open the vendored FFmpeg tarball");
    let decoder = lzma_rust2::XzReader::new(BufReader::new(archive), false);
    tar::Archive::new(decoder)
        .unpack(out_dir)
        .expect("extract the vendored FFmpeg tarball");
    fs::create_dir_all(&build).expect("create the FFmpeg build directory");

    let mut configure = Command::new("sh");
    configure
        .arg(shell_path(&source.join("configure")))
        .args(arguments);
    run(configure
        .current_dir(&build)
        .envs(compiler.env().iter().cloned()));

    // Joining cargo's jobserver keeps make within the build's job budget. MSYS2's make cannot
    // open the Windows jobserver, so there it takes the budget as a plain job count.
    let mut make = Command::new("make");
    match env::var("CARGO_MAKEFLAGS") {
        Ok(flags) if !cfg!(windows) => make.env("MAKEFLAGS", flags),
        _ => make.arg(format!(
            "-j{}",
            env::var("NUM_JOBS").as_deref().unwrap_or("1")
        )),
    };
    run(make
        .arg("install")
        .current_dir(&build)
        .envs(compiler.env().iter().cloned()));

    // FFmpeg names its MSVC static libraries `libname.a`, and rustc looks for `name.lib`.
    if compiler.is_like_msvc() {
        let lib = prefix.join("lib");
        for name in LIBRARIES {
            fs::copy(
                lib.join(format!("lib{name}.a")),
                lib.join(format!("{name}.lib")),
            )
            .expect("copy an FFmpeg static library to its MSVC name");
        }
    }
}

fn link(prefix: &Path) {
    let lib = prefix.join("lib");
    println!("cargo::rustc-link-search=native={}", lib.display());
    for name in LIBRARIES {
        println!("cargo::rustc-link-lib=static={name}");
    }

    // Each library's `Libs.private` names the system libraries a static link needs.
    let mut system: Vec<String> = Vec::new();
    for name in LIBRARIES {
        let pkgconfig = fs::read_to_string(lib.join(format!("pkgconfig/lib{name}.pc")))
            .expect("read an FFmpeg pkg-config file");
        let Some(private) = pkgconfig
            .lines()
            .find_map(|line| line.strip_prefix("Libs.private:"))
        else {
            continue;
        };
        let mut tokens = private.split_whitespace();
        while let Some(token) = tokens.next() {
            let kind = if let Some(library) = token.strip_prefix("-l") {
                format!("dylib={library}")
            } else if let Some(library) = token.strip_suffix(".lib") {
                format!("dylib={library}")
            } else if token == "-framework" {
                format!("framework={}", tokens.next().expect("a framework name"))
            } else {
                continue;
            };
            if !system.contains(&kind) {
                system.push(kind);
            }
        }
    }
    for kind in system {
        println!("cargo::rustc-link-lib={kind}");
    }
}

/// Converts a path for FFmpeg's shell scripts, which on Windows run under MSYS2.
fn shell_path(path: &Path) -> String {
    if !cfg!(windows) {
        return path.display().to_string();
    }
    let output = Command::new("cygpath")
        .arg("-u")
        .arg(path)
        .output()
        .expect("run cygpath");
    String::from_utf8(output.stdout)
        .expect("cygpath prints UTF-8")
        .trim()
        .to_owned()
}

fn run(command: &mut Command) {
    let status = command
        .status()
        .unwrap_or_else(|error| panic!("run {command:?}: {error}"));
    assert!(status.success(), "{command:?} failed with {status}");
}

fn env_var(name: &str) -> String {
    env::var(name).unwrap_or_else(|_| panic!("cargo sets `{name}` for build scripts"))
}
