//! Builds the vendored FFmpeg and OpenH264 releases into `OUT_DIR` and links their static
//! libraries.

use std::env;
use std::fs::{self, File};
use std::io::{BufReader, ErrorKind};
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus};

const FFMPEG_VERSION: &str = "9.0.2";

/// The OpenH264 release, vendored without its test bitstreams as `vendor/README.md` describes.
const OPENH264_VERSION: &str = "2.6.0";

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
    "--enable-decoder=h264,hevc",
    "--enable-libopenh264",
    "--enable-encoder=libopenh264",
];

/// The OpenH264 directories whose sources make up its encoder, relative to its source tree.
const OPENH264_SOURCES: &[&str] = &[
    "codec/common/src",
    "codec/encoder/core/src",
    "codec/processing/src",
];

/// The OpenH264 encoder's include directories, relative to its source tree.
const OPENH264_INCLUDES: &[&str] = &[
    "codec/api/wels",
    "codec/common/inc",
    "codec/encoder/core/inc",
    "codec/encoder/plus/inc",
    "codec/processing/interface",
    "codec/processing/src/common",
    "codec/processing/src/adaptivequantization",
    "codec/processing/src/downsample",
    "codec/processing/src/scrolldetection",
    "codec/processing/src/vaacalc",
];

fn main() {
    println!("cargo::rerun-if-changed=build.rs");
    let out_dir = PathBuf::from(env_var("OUT_DIR"));
    let compiler = cc::Build::new().get_compiler();

    let openh264 = out_dir.join("openh264");
    let rebuilt = build_openh264(&out_dir, &openh264);
    let pkg_config = write_pkg_config(&out_dir, &openh264);

    println!("cargo::rerun-if-changed=vendor/ffmpeg-{FFMPEG_VERSION}.tar.xz");
    let prefix = out_dir.join("ffmpeg");
    let arguments = configure_arguments(&prefix, &pkg_config, &compiler);
    // The stamp holds the arguments of the last completed build, so a changed option rebuilds.
    let stamp = prefix.join("ceres-configure");
    let configured = arguments.join("\n");
    if rebuilt || fs::read_to_string(&stamp).ok().as_deref() != Some(configured.as_str()) {
        let source = vendored(&format!("ffmpeg-{FFMPEG_VERSION}"), &out_dir);
        build_ffmpeg(&source, &out_dir, &prefix, &arguments, &compiler);
        fs::write(&stamp, configured).expect("write the FFmpeg build stamp");
    }

    // The shim links before FFmpeg, since a static library resolves only earlier references.
    println!("cargo::rerun-if-changed=src/shim.c");
    cc::Build::new()
        .file("src/shim.c")
        .include(prefix.join("include"))
        .warnings(true)
        .compile("ceres_media_shim");
    link(&prefix, &openh264);
    println!("cargo::rustc-env=CERES_FFMPEG_VERSION={FFMPEG_VERSION}");
}

/// Extracts the vendored tarball `name`, returning its source tree.
fn vendored(name: &str, out_dir: &Path) -> PathBuf {
    let tarball =
        PathBuf::from(env_var("CARGO_MANIFEST_DIR")).join(format!("vendor/{name}.tar.xz"));
    let source = out_dir.join(name);
    remove(&source);
    let archive =
        File::open(&tarball).unwrap_or_else(|error| panic!("open {}: {error}", tarball.display()));
    let decoder = lzma_rust2::XzReader::new(BufReader::new(archive), false);
    tar::Archive::new(decoder)
        .unpack(out_dir)
        .unwrap_or_else(|error| panic!("extract {}: {error}", tarball.display()));
    source
}

/// Compiles the OpenH264 encoder into `prefix`, true when it was built rather than reused.
fn build_openh264(out_dir: &Path, prefix: &Path) -> bool {
    let name = format!("openh264-{OPENH264_VERSION}");
    println!("cargo::rerun-if-changed=vendor/{name}.tar.xz");
    let stamp = prefix.join("ceres-version");
    if fs::read_to_string(&stamp).ok().as_deref() == Some(OPENH264_VERSION) {
        return false;
    }
    remove(prefix);
    let source = vendored(&name, out_dir);
    let lib = prefix.join("lib");
    fs::create_dir_all(&lib).expect("create the OpenH264 library directory");

    let mut build = cc::Build::new();
    for directory in OPENH264_SOURCES {
        build.files(cpp_files(&source.join(directory)));
    }
    // `DllEntry.cpp`, the other file beside it, serves only the Windows DLL.
    build.file(source.join("codec/encoder/plus/src/welsEncoderExt.cpp"));
    for directory in OPENH264_INCLUDES {
        build.include(source.join(directory));
    }
    // Encoding runs in debug builds too, where an unoptimized encoder falls behind real time.
    build
        .cpp(true)
        .opt_level(3)
        .debug(false)
        .define("NDEBUG", None)
        .warnings(false)
        .cargo_metadata(false)
        .out_dir(&lib)
        .compile("openh264");

    let include = prefix.join("include/wels");
    fs::create_dir_all(&include).expect("create the OpenH264 include directory");
    for header in [
        "codec_api.h",
        "codec_app_def.h",
        "codec_def.h",
        "codec_ver.h",
    ] {
        fs::copy(
            source.join("codec/api/wels").join(header),
            include.join(header),
        )
        .expect("install an OpenH264 header");
    }
    fs::write(&stamp, OPENH264_VERSION).expect("write the OpenH264 build stamp");
    true
}

/// Every C++ file under `directory`, sorted so the archive's member order is stable.
fn cpp_files(directory: &Path) -> Vec<PathBuf> {
    let mut files = Vec::new();
    for entry in fs::read_dir(directory).expect("list OpenH264 sources") {
        let path = entry.expect("read an OpenH264 source entry").path();
        if path.is_dir() {
            files.extend(cpp_files(&path));
        } else if path.extension().is_some_and(|extension| extension == "cpp") {
            files.push(path);
        }
    }
    files.sort();
    files
}

/// Writes a `pkg-config` stand-in describing OpenH264, so `configure` finds the library
/// without `pkg-config` on the build machine.
fn write_pkg_config(out_dir: &Path, openh264: &Path) -> PathBuf {
    let msvc = env_var("CARGO_CFG_TARGET_ENV") == "msvc";
    let runtime = match env_var("CARGO_CFG_TARGET_OS").as_str() {
        _ if msvc => "",
        "macos" => " -lc++",
        _ => " -lstdc++ -lm -lpthread",
    };
    // `cl` and `link` read these flags, and MSYS2 does not convert a path inside
    // `-libpath:`, so they carry the Windows path with forward slashes.
    let prefix = if msvc {
        openh264.display().to_string().replace('\\', "/")
    } else {
        shell_path(openh264)
    };
    let script = format!(
        "#!/bin/sh\n\
         for argument in \"$@\"; do\n\
         \x20 case \"$argument\" in\n\
         \x20   --version|--modversion) echo {OPENH264_VERSION}; exit 0 ;;\n\
         \x20   --cflags) echo \"-I{prefix}/include\"; exit 0 ;;\n\
         \x20   --libs) echo \"-L{prefix}/lib -lopenh264{runtime}\"; exit 0 ;;\n\
         \x20   --variable=includedir) echo \"{prefix}/include\"; exit 0 ;;\n\
         \x20 esac\n\
         done\n\
         case \"$*\" in\n\
         \x20 *openh264*) exit 0 ;;\n\
         esac\n\
         exit 1\n"
    );
    let path = out_dir.join("pkg-config");
    fs::write(&path, script).expect("write the pkg-config stand-in");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&path, fs::Permissions::from_mode(0o755))
            .expect("make the pkg-config stand-in executable");
    }
    path
}

fn configure_arguments(prefix: &Path, pkg_config: &Path, compiler: &cc::Tool) -> Vec<String> {
    let mut arguments = vec![
        format!("--prefix={}", shell_path(prefix)),
        format!("--pkg-config={}", shell_path(pkg_config)),
    ];
    arguments.extend(OPTIONS.iter().map(ToString::to_string));
    // `--disable-autodetect` leaves FFmpeg single-threaded unless threads are named.
    if env_var("CARGO_CFG_TARGET_OS") == "windows" {
        arguments.push("--enable-w32threads".to_owned());
    } else {
        arguments.push("--enable-pthreads".to_owned());
    }
    if compiler.is_like_msvc() {
        arguments.push("--toolchain=msvc".to_owned());
        // `cl` defaults to the static CRT, while `cc` compiles OpenH264 and the shim against the
        // one Rust links, so FFmpeg takes the same flag to keep one CRT in every link.
        let crt = compiler
            .args()
            .iter()
            .find(|argument| *argument == "-MD" || *argument == "-MT")
            .expect("`cc` names the MSVC runtime");
        arguments.push(format!("--extra-cflags={}", crt.to_string_lossy()));
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

fn build_ffmpeg(
    source: &Path,
    out_dir: &Path,
    prefix: &Path,
    arguments: &[String],
    compiler: &cc::Tool,
) {
    let build = out_dir.join("build");
    remove(&build);
    remove(prefix);
    fs::create_dir_all(&build).expect("create the FFmpeg build directory");

    let mut configure = Command::new("sh");
    configure
        .arg(shell_path(&source.join("configure")))
        .args(arguments)
        .current_dir(&build)
        .envs(compiler.env().iter().cloned());
    if !status(&mut configure).success() {
        // `configure` names only the failed check, its log holds the compiler's reason.
        let log = fs::read_to_string(build.join("ffbuild/config.log")).unwrap_or_default();
        let lines: Vec<&str> = log.lines().collect();
        eprintln!("{}", lines[lines.len().saturating_sub(60)..].join("\n"));
        panic!("{configure:?} failed");
    }

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
}

fn link(prefix: &Path, openh264: &Path) {
    println!(
        "cargo::rustc-link-search=native={}",
        prefix.join("lib").display()
    );
    println!(
        "cargo::rustc-link-search=native={}",
        openh264.join("lib").display()
    );
    // OpenH264 follows `avcodec`, which references it.
    for name in LIBRARIES.iter().chain(&["openh264"]) {
        println!("cargo::rustc-link-lib=static={name}");
    }

    // The system libraries a static link needs, the C++ runtime OpenH264 needs among them.
    // FFmpeg lists them under `Libs` when it builds no shared libraries, else `Libs.private`.
    let mut system: Vec<String> = Vec::new();
    for name in LIBRARIES {
        let pkgconfig = fs::read_to_string(prefix.join(format!("lib/pkgconfig/lib{name}.pc")))
            .expect("read an FFmpeg pkg-config file");
        let mut tokens = pkgconfig
            .lines()
            .filter_map(|line| {
                line.strip_prefix("Libs:")
                    .or_else(|| line.strip_prefix("Libs.private:"))
            })
            .flat_map(str::split_whitespace);
        while let Some(token) = tokens.next() {
            let library = token
                .strip_prefix("-l")
                .or_else(|| token.strip_suffix(".lib"));
            let kind = match library {
                // Linked statically above.
                Some(library) if library == "openh264" || LIBRARIES.contains(&library) => continue,
                Some(library) => format!("dylib={library}"),
                None if token == "-framework" => {
                    format!("framework={}", tokens.next().expect("a framework name"))
                }
                None => continue,
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

fn remove(directory: &Path) {
    match fs::remove_dir_all(directory) {
        Err(error) if error.kind() != ErrorKind::NotFound => {
            panic!("remove {}: {error}", directory.display())
        }
        _ => {}
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
    let status = status(command);
    assert!(status.success(), "{command:?} failed with {status}");
}

fn status(command: &mut Command) -> ExitStatus {
    command
        .status()
        .unwrap_or_else(|error| panic!("run {command:?}: {error}"))
}

fn env_var(name: &str) -> String {
    env::var(name).unwrap_or_else(|_| panic!("cargo sets `{name}` for build scripts"))
}
