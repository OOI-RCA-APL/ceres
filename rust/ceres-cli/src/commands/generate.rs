//! The `generate` command group, rendering project resources.

use crate::cli::{OpenapiArgs, SchemaFormat};
use crate::error::{Exit, Result};

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
