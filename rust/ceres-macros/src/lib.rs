//! Procedural macros for the Ceres native crates.
//!
//! Doc comments here use plain code spans rather than intra-doc links. The types the
//! macros generate code against live in crates that depend on this one so no path
//! from here can resolve to them.

mod filterable;
mod kebab;
mod python_config;

use proc_macro::TokenStream;
use syn::{DeriveInput, PathSegment, Type, parse_macro_input};

/// The last segment of a type's path, `None` for any other type shape.
pub(crate) fn last_segment(ty: &Type) -> Option<&PathSegment> {
    match ty {
        Type::Path(path) => path.path.segments.last(),
        _ => None,
    }
}

/// Derive the filterable field surface of a record entity from its struct.
///
/// Each named field whose type belongs to a filter family, UUIDs, addresses,
/// timestamps, text, levels, and `FilterValues` enums, contributes its wire key and
/// family to the entity's `FIELDS` table, honoring `#[serde(rename)]`. The native
/// filter subset reads that table so the filterable surface follows the entity
/// definition at compile time rather than being written out anywhere else.
#[proc_macro_derive(Filterable, attributes(filterable))]
pub fn filterable(input: TokenStream) -> TokenStream {
    let input = parse_macro_input!(input as DeriveInput);
    filterable::expand_filterable(input)
        .unwrap_or_else(|error| error.to_compile_error())
        .into()
}

/// Accept the snake_case spelling of every multi-word field this struct deserializes.
///
/// A configuration file is written in kebab-case, declared with `rename_all`, and this
/// restores the snake_case spelling alongside it. Applying it to the struct rather than
/// per field keeps a later field from silently accepting only one spelling.
///
/// Place it above the `derive` so the aliases attach before serde expands. Only
/// deserialization is affected.
#[proc_macro_attribute]
pub fn kebab_aliases(_arguments: TokenStream, input: TokenStream) -> TokenStream {
    let input = parse_macro_input!(input as DeriveInput);
    kebab::expand_kebab_aliases(input)
        .unwrap_or_else(|error| error.to_compile_error())
        .into()
}

/// Derive the admissible wire values of a plain enum from its variants.
#[proc_macro_derive(FilterValues)]
pub fn filter_values(input: TokenStream) -> TokenStream {
    let input = parse_macro_input!(input as DeriveInput);
    filterable::expand_filter_values(input)
        .unwrap_or_else(|error| error.to_compile_error())
        .into()
}

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
