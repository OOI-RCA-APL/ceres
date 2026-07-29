//! Procedural macros for the Ceres Python bindings.

mod python_config;

use proc_macro::TokenStream;

/// Define a Python class wrapping a validated configuration type.
///
/// The macro takes a declarative description of the class, its validated and raw types, and
/// its fields, and generates the whole binding surface: a pyclass holding the validated
/// value, a typed keyword constructor that validates through the raw form, typed getters,
/// `to_dict`, `json_schema`, equality, `repr`, and the conversions that let the class nest
/// inside other generated classes.
///
/// ```ignore
/// python_config! {
///     /// TLS configuration for the engine's HTTP server.
///     ServerSSLConfig(ceres_config::ServerSslConfig, ceres_config::RawServerSslConfig) {
///         /// Path to the server private key file.
///         key: Option<PathBuf>,
///     }
/// }
/// ```
///
/// Field types are the raw form's field types. `Option` fields become keyword arguments
/// defaulting to `None`, other fields are required keyword arguments. A field marked
/// `#[python(nested = NestedClass)]` crosses the boundary as another generated class, and a
/// field marked `#[python(any = "str | list[str]")]` crosses as an untyped value with the
/// given stub annotation.
#[proc_macro]
pub fn python_config(input: TokenStream) -> TokenStream {
    python_config::expand(input.into())
        .unwrap_or_else(|error| error.to_compile_error())
        .into()
}
