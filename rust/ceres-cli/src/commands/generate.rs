//! The `generate` command group, rendering project resources.

use ceres_config::ServerCertificateAutoConfig;
use ceres_server::{Managed, SubjectName};
use time::OffsetDateTime;

use crate::cli::{CertificateArgs, OpenapiArgs, SchemaFormat};
use crate::error::{Exit, Result, fail, failure};
use crate::output::Output;
use crate::project::Project;

/// Generate the OpenAPI schema and write it to a file or stdout.
pub fn openapi(args: &OpenapiArgs) -> Result<()> {
    let document = ceres_server::openapi_document(crate::cli::VERSION);
    let rendered = match args.format {
        SchemaFormat::Yaml => {
            // The YAML emitter has no indentation setting, so an indent it cannot
            // honor is refused rather than silently rendered at two.
            if args.indent != 2 {
                return Err(Exit::failed(
                    "YAML output uses a fixed indent of 2. --indent applies to JSON output.",
                ));
            }

            yaml_serde::to_string(&document)
                .map_err(|error| Exit::failed(format!("Cannot render the schema. {error}")))?
        }
        SchemaFormat::Json => {
            let indent = " ".repeat(args.indent as usize);
            let mut rendered = Vec::new();
            let formatter = serde_json::ser::PrettyFormatter::with_indent(indent.as_bytes());
            let mut serializer = serde_json::Serializer::with_formatter(&mut rendered, formatter);
            serde::Serialize::serialize(&document, &mut serializer)
                .map_err(|error| Exit::failed(format!("Cannot render the schema. {error}")))?;
            String::from_utf8(rendered).expect("serde_json writes UTF-8")
        }
    };

    match &args.output {
        Some(path) => std::fs::write(path, rendered)
            .map_err(|error| Exit::failed(format!("Cannot write {}. {error}", path.display()))),
        None => {
            use std::io::Write;

            let stdout = std::io::stdout();
            let mut lock = stdout.lock();
            let _ = lock.write_all(rendered.as_bytes());
            Ok(())
        }
    }
}

/// Issue the HTTPS certificate the `server.https.certificate` section describes, signed by
/// its certificate authority.
///
/// Under `auto` this is the issuance startup runs, writing only when a certificate is due
/// or `--force` is passed. Otherwise the certificate is signed by the default authority,
/// created when missing, and existing files are only replaced with `--force`. Either way
/// `--ip` and `--dns` add names and `--days` sets the lifetime. Keys are readable by their
/// owner alone.
pub fn certificate(args: &CertificateArgs, project: &Project, output: &Output) -> Result<()> {
    let meta = project.load_meta()?;
    let certificate = meta
        .server
        .https
        .map(|https| https.certificate)
        .unwrap_or_default();
    let directory = project.directory();

    let (auto, force) = match &certificate.auto {
        Some(auto) => (auto.clone(), args.force),
        None => {
            if certificate.key_password.is_some() {
                fail!(
                    "`server.https.certificate.key-password` is set, and generate certificate \
                     writes the key unencrypted. Remove it, or write the certificate yourself."
                );
            }
            if !args.force {
                for shown in [&certificate.path, &certificate.key] {
                    if directory.join(shown).exists() {
                        fail!(
                            "{} already exists. Pass --force to replace it.",
                            shown.display()
                        );
                    }
                }
            }
            (ServerCertificateAutoConfig::default(), true)
        }
    };
    let auto = ServerCertificateAutoConfig {
        days: args.days.unwrap_or(auto.days),
        ..auto
    };

    // Startup keeps a certificate naming more than it needs, so added names stay put.
    let mut names = SubjectName::required(&auto, SubjectName::detected);
    names.extend(args.ips.iter().copied().map(SubjectName::Ip));
    names.extend(args.dns.iter().cloned().map(SubjectName::Dns));
    let names = SubjectName::unique(names);

    let managed = Managed::ensure(
        directory,
        &certificate,
        &auto,
        &names,
        OffsetDateTime::now_utc(),
        force,
    )
    .map_err(|error| failure!("{error}"))?;

    let authority = auto.authority().path;
    if managed.created_authority {
        output.write(format!(
            "Created the certificate authority {}.",
            authority.display()
        ));
    }
    match &managed.issued {
        Some(_) => {
            output.write(format!(
                "Wrote the certificate to {}.",
                certificate.path.display()
            ));
            output.write(format!("Wrote the key to {}.", certificate.key.display()));
        }
        None => output.write(format!(
            "The certificate {} is current, so it stays. Pass --force to replace it.",
            certificate.path.display()
        )),
    }
    let names: Vec<String> = managed.names.iter().map(ToString::to_string).collect();
    output.write(format!("Names: {}", names.join(", ")));
    output.write(format!("Expires: {}", managed.expires.date()));
    output.write(format!("SHA-256 fingerprint: {}", managed.fingerprint));
    output.write(format!(
        "Trust the certificate authority {} on each client to trust the certificate.",
        authority.display()
    ));
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::path::Path;

    use ceres_config::{ServerCertificateAuthorityConfig, ServerCertificateConfig};
    use ceres_server::CertificateStatus;

    use super::*;

    fn args(ips: &[&str], dns: &[&str], days: Option<u32>, force: bool) -> CertificateArgs {
        CertificateArgs {
            ips: ips.iter().map(|ip| ip.parse().unwrap()).collect(),
            dns: dns.iter().map(ToString::to_string).collect(),
            days,
            force,
        }
    }

    fn project(directory: &Path, config: &str) -> Project {
        std::fs::write(directory.join("ceres.yaml"), config).unwrap();
        Project::at(directory.join("ceres.yaml"))
    }

    fn read(path: impl AsRef<Path>) -> String {
        std::fs::read_to_string(path).unwrap()
    }

    /// The listener's view of the certificate at `path`, as signed by the authority at `ca`
    /// for `dns`: when it expires and what startup would reissue it for.
    fn status(path: &Path, key: &Path, ca: &Path, dns: &[&str]) -> CertificateStatus {
        let auto = ServerCertificateAutoConfig {
            dns: dns.iter().map(ToString::to_string).collect(),
            ca: Some(ServerCertificateAuthorityConfig {
                path: ca.join("ca.crt"),
                key: ca.join("ca.key"),
                key_password: None,
            }),
            ..ServerCertificateAutoConfig::default()
        };
        let https = ceres_config::ServerHttpsConfig {
            certificate: ServerCertificateConfig {
                path: path.to_path_buf(),
                key: key.to_path_buf(),
                key_password: None,
                auto: Some(auto),
            },
            ..ceres_config::ServerHttpsConfig::default()
        };
        CertificateStatus::of(&https, Vec::new, OffsetDateTime::now_utc()).unwrap()
    }

    fn days_left(status: &CertificateStatus) -> i64 {
        (status.expires.unwrap() - OffsetDateTime::now_utc().unix_timestamp()) / 86_400
    }

    #[test]
    fn unmanaged_certificates_are_signed_by_the_default_authority() {
        let directory = tempfile::tempdir().unwrap();
        let project = project(directory.path(), "");
        let output = Output::new(Some(false));

        certificate(
            &args(&["10.0.0.9"], &["Bench.example"], None, false),
            &project,
            &output,
        )
        .unwrap();

        let state = directory.path().join(".ceres");
        assert_eq!(read(state.join(".gitignore")), "*\n");
        // The staged files were renamed into place, leaving nothing else behind.
        let tls = state.join("tls");
        let mut written: Vec<_> = std::fs::read_dir(&tls)
            .unwrap()
            .map(|entry| entry.unwrap().file_name())
            .collect();
        written.sort();
        assert_eq!(written, ["ca.crt", "ca.key", "server.crt", "server.key"]);

        // Signed by the authority beside it, for the names asked for besides the machine's.
        let current = status(
            &tls.join("server.crt"),
            &tls.join("server.key"),
            &tls,
            &["localhost", "bench.example"],
        );
        assert_eq!(current.plan, None);
        assert!((363..=364).contains(&days_left(&current)), "{current:?}");

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;

            for key in ["server.key", "ca.key"] {
                let mode = std::fs::metadata(tls.join(key))
                    .unwrap()
                    .permissions()
                    .mode();
                assert_eq!(mode & 0o777, 0o600, "{key}");
            }
        }
    }

    #[test]
    fn existing_files_are_replaced_only_with_force() {
        let directory = tempfile::tempdir().unwrap();
        let project = project(
            directory.path(),
            "server:\n  https:\n    certificate:\n      path: certs/site.crt\n      key: certs/site.key\n",
        );
        let output = Output::new(Some(false));

        certificate(&args(&[], &[], Some(30), false), &project, &output).unwrap();
        let cert = directory.path().join("certs/site.crt");
        let first = read(&cert);
        let authority = read(directory.path().join(".ceres/tls/ca.crt"));

        let error = certificate(&args(&[], &[], None, false), &project, &output).unwrap_err();
        assert!(
            error
                .to_string()
                .contains("certs/site.crt already exists. Pass --force to replace it."),
            "{error}"
        );
        assert_eq!(read(&cert), first);

        certificate(&args(&[], &[], None, true), &project, &output).unwrap();
        assert_ne!(read(&cert), first);
        // The authority is created once and signs every certificate after.
        assert_eq!(read(directory.path().join(".ceres/tls/ca.crt")), authority);
        let renewed = status(
            &cert,
            &directory.path().join("certs/site.key"),
            &directory.path().join(".ceres/tls"),
            &["localhost"],
        );
        assert_eq!(renewed.plan, None);
        assert!((363..=364).contains(&days_left(&renewed)), "{renewed:?}");
    }

    #[test]
    fn encrypted_keys_are_not_overwritten() {
        let directory = tempfile::tempdir().unwrap();
        let project = project(
            directory.path(),
            "server:\n  https:\n    certificate:\n      key-password: hunter2\n",
        );
        let output = Output::new(Some(false));

        let error = certificate(&args(&[], &[], None, true), &project, &output).unwrap_err();
        assert!(
            error.to_string().contains(
                "`server.https.certificate.key-password` is set, and generate certificate \
                 writes the key unencrypted."
            ),
            "{error}"
        );
        assert!(!directory.path().join(".ceres").exists());
    }

    #[test]
    fn managed_certificates_are_issued_the_way_startup_issues_them() {
        let directory = tempfile::tempdir().unwrap();
        let project = project(
            directory.path(),
            "server:\n  https:\n    certificate:\n      auto:\n        dns: [bench.example]\n        days: 90\n",
        );
        let output = Output::new(Some(false));
        let tls = directory.path().join(".ceres/tls");
        let (cert, key) = (tls.join("server.crt"), tls.join("server.key"));

        certificate(&args(&[], &[], None, false), &project, &output).unwrap();
        let first = read(&cert);
        let issued = status(&cert, &key, &tls, &["bench.example"]);
        assert_eq!(issued.plan, None);
        assert!((88..=89).contains(&days_left(&issued)), "{issued:?}");

        // A current certificate stays, even when another lifetime is asked for.
        certificate(&args(&[], &[], Some(30), false), &project, &output).unwrap();
        assert_eq!(read(&cert), first);

        // A name it lacks reissues it, keeping the configured ones.
        certificate(&args(&["10.0.0.9"], &[], None, false), &project, &output).unwrap();
        let added = read(&cert);
        assert_ne!(added, first);
        let both = status(&cert, &key, &tls, &["bench.example"]);
        assert_eq!(both.plan, None);
        certificate(&args(&["10.0.0.9"], &[], None, false), &project, &output).unwrap();
        assert_eq!(read(&cert), added);

        certificate(&args(&[], &[], Some(60), true), &project, &output).unwrap();
        assert_ne!(read(&cert), added);
        let forced = status(&cert, &key, &tls, &["bench.example"]);
        assert!((58..=59).contains(&days_left(&forced)), "{forced:?}");
    }

    #[test]
    fn supplied_authorities_are_never_created() {
        let directory = tempfile::tempdir().unwrap();
        let project = project(
            directory.path(),
            "server:\n  https:\n    certificate:\n      auto:\n        ca:\n          path: ca/typo.crt\n          key: ca/typo.key\n",
        );
        let output = Output::new(Some(false));

        let error = certificate(&args(&[], &[], None, true), &project, &output).unwrap_err();
        assert!(
            error.to_string().contains("typo.crt does not exist."),
            "{error}"
        );
        assert!(!directory.path().join("ca").exists());
        assert!(!directory.path().join(".ceres/tls/server.crt").exists());
    }
}
