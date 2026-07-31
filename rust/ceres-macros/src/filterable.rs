//! Derive the filterable field surface from an entity struct.

use proc_macro2::TokenStream;
use quote::quote;
use syn::{Data, DeriveInput, Fields, LitStr};

/// Expand `#[derive(Filterable)]`.
///
/// Every named field whose type belongs to a filter family contributes one entry to
/// the entity's `FIELDS` table, keyed by its wire name, the `#[serde(rename)]` value
/// when one is present. The field's operation filters, the `contains`, `prefix`, and
/// `suffix` variants where its family carries them, are generated here too, each with
/// the kind it matches by. Fields of unfilterable types simply do not appear.
pub fn expand_filterable(input: DeriveInput) -> syn::Result<TokenStream> {
    let name = &input.ident;
    let Data::Struct(data) = &input.data else {
        return Err(syn::Error::new_spanned(
            &input.ident,
            "Filterable derives on structs",
        ));
    };
    let Fields::Named(fields) = &data.fields else {
        return Err(syn::Error::new_spanned(
            &input.ident,
            "Filterable derives on named fields",
        ));
    };

    let mut entries = Vec::new();
    for field in &fields.named {
        if marked(field, "skip") {
            continue;
        }

        let identifier = field.ident.as_ref().expect("named fields carry names");
        let key = wire_name(field)?.unwrap_or_else(|| identifier.to_string());
        let family = match family_of(&field.ty) {
            Family::Address if marked(field, "plain") => Family::PlainAddress,
            family => family,
        };

        let entry = match &family {
            Family::Uuid => quote! { ceres_entities::FieldFamily::Uuid },
            Family::Address => quote! { ceres_entities::FieldFamily::Address },
            Family::Timestamp => quote! { ceres_entities::FieldFamily::Timestamp },
            Family::Text => quote! { ceres_entities::FieldFamily::Text },
            Family::Values(ty) => quote! {
                ceres_entities::FieldFamily::Values(
                    <#ty as ceres_entities::FilterValues>::VALUES,
                )
            },
            Family::Level => quote! { ceres_entities::FieldFamily::Level },
            Family::Bytes => quote! { ceres_entities::FieldFamily::Bytes },
            Family::Json => quote! { ceres_entities::FieldFamily::Json },
            Family::Boolean => quote! { ceres_entities::FieldFamily::Boolean },
            Family::JsonValue => quote! { ceres_entities::FieldFamily::JsonValue },
            Family::PlainAddress => quote! { ceres_entities::FieldFamily::PlainAddress },
            Family::Unfilterable => continue,
        };

        let operations = operation_entries(
            &key,
            &family,
            bare_operations(field),
            marked(field, "insensitive"),
        );
        entries.push(quote! {
            ceres_entities::FilterField {
                key: #key,
                family: #entry,
                operations: &[#(#operations),*],
            }
        });
    }

    Ok(quote! {
        impl ceres_entities::Filterable for #name {
            const FIELDS: &'static [ceres_entities::FilterField] = &[#(#entries),*];
        }
    })
}

/// Expand `#[derive(FilterValues)]` on a plain enum.
///
/// The admissible wire values are the variant names in declaration order, lowercased
/// the way `#[serde(rename_all = "lowercase")]` serializes them.
pub fn expand_filter_values(input: DeriveInput) -> syn::Result<TokenStream> {
    let name = &input.ident;
    let Data::Enum(data) = &input.data else {
        return Err(syn::Error::new_spanned(
            &input.ident,
            "FilterValues derives on enums",
        ));
    };

    let values: Vec<String> = data
        .variants
        .iter()
        .map(|variant| variant.ident.to_string().to_lowercase())
        .collect();

    Ok(quote! {
        impl ceres_entities::FilterValues for #name {
            const VALUES: &'static [&'static str] = &[#(#values),*];
        }
    })
}

/// The filter family a field's type maps to.
enum Family {
    Uuid,
    Address,
    Timestamp,
    Text,
    Level,
    Values(Box<syn::Type>),
    Bytes,
    Json,
    Boolean,
    JsonValue,
    PlainAddress,
    Unfilterable,
}

/// The operation filters a family carries, generated as literal entries so the tables
/// stay `'static`.
fn operation_entries(
    key: &str,
    family: &Family,
    bare: bool,
    insensitive: bool,
) -> Vec<TokenStream> {
    let variants = [
        (
            "contains",
            quote! { ceres_entities::OperationKind::Contains },
        ),
        ("prefix", quote! { ceres_entities::OperationKind::Prefix }),
        ("suffix", quote! { ceres_entities::OperationKind::Suffix }),
    ];
    match family {
        Family::Text | Family::Bytes | Family::Json => variants
            .iter()
            .map(|(variant, kind)| {
                let operation_key = if bare {
                    (*variant).to_string()
                } else {
                    format!("{key}_{variant}")
                };
                quote! {
                    ceres_entities::FieldOperation {
                        key: #operation_key,
                        kind: #kind,
                        insensitive: #insensitive,
                    }
                }
            })
            .collect(),
        _ => Vec::new(),
    }
}

/// Map a field type to its family by the tail of its path.
///
/// `Option<String>` filters like `String`, absence simply never matches equality. An
/// unrecognized type is not an error, its field is not filterable natively.
fn family_of(ty: &syn::Type) -> Family {
    let syn::Type::Path(path) = ty else {
        return Family::Unfilterable;
    };
    let Some(segment) = path.path.segments.last() else {
        return Family::Unfilterable;
    };

    match segment.ident.to_string().as_str() {
        "Uuid" => Family::Uuid,
        "Address" => Family::Address,
        "Timestamp" => Family::Timestamp,
        "String" => Family::Text,
        "Level" => Family::Level,
        "Vec" => match first_type_argument(segment) {
            Some(inner) if type_is(&inner, "u8") => Family::Bytes,
            _ => Family::Unfilterable,
        },
        "Map" => Family::Json,
        "bool" => Family::Boolean,
        // A bare JSON value filters by equality on its serialized text.
        "Value" => Family::JsonValue,
        "Option" => match first_type_argument(segment) {
            Some(inner) => family_of(&inner),
            None => Family::Unfilterable,
        },
        // Any other bare path is a candidate enum, admitted when it implements
        // `FilterValues`, which the entity author derives on it.
        _ if segment.arguments.is_none() && known_enum(&segment.ident) => {
            Family::Values(Box::new(ty.clone()))
        }
        _ => Family::Unfilterable,
    }
}

/// Whether an unrecognized type is one of the filterable enums.
///
/// The derive cannot probe trait implementations, so the enums that filter are named
/// here, and referencing one that stops implementing `FilterValues` fails to compile.
fn known_enum(identifier: &syn::Ident) -> bool {
    identifier == "MessageDirection"
}

/// Whether a type path's tail is one bare identifier.
fn type_is(ty: &syn::Type, name: &str) -> bool {
    let syn::Type::Path(path) = ty else {
        return false;
    };

    path.path
        .segments
        .last()
        .is_some_and(|segment| segment.ident == name && segment.arguments.is_none())
}

/// The first generic type argument of a path segment, `Option<T>`'s `T`.
fn first_type_argument(segment: &syn::PathSegment) -> Option<syn::Type> {
    let syn::PathArguments::AngleBracketed(arguments) = &segment.arguments else {
        return None;
    };

    arguments.args.iter().find_map(|argument| match argument {
        syn::GenericArgument::Type(ty) => Some(ty.clone()),
        _ => None,
    })
}

/// Whether the field carries `#[filterable(bare_operations)]`.
fn bare_operations(field: &syn::Field) -> bool {
    marked(field, "bare_operations")
}

/// Whether the field carries the given `#[filterable(...)]` marker.
///
/// `skip` drops a field whose type would otherwise filter, for a column the Python
/// filter does not expose. `plain` takes an address out of the selector grammar.
/// `insensitive` folds case in the field's operation filters, which an email address's
/// do.
fn marked(field: &syn::Field, name: &str) -> bool {
    for attribute in &field.attrs {
        if !attribute.path().is_ident("filterable") {
            continue;
        }

        let mut found = false;
        let _ = attribute.parse_nested_meta(|meta| {
            if meta.path.is_ident(name) {
                found = true;
            }

            Ok(())
        });
        if found {
            return true;
        }
    }

    false
}

/// The `#[serde(rename = "...")]` value on a field, when present.
fn wire_name(field: &syn::Field) -> syn::Result<Option<String>> {
    for attribute in &field.attrs {
        if !attribute.path().is_ident("serde") {
            continue;
        }

        let mut rename = None;
        // Serde attributes hold arbitrary content, so anything but `rename` is skipped
        // rather than parsed.
        let _ = attribute.parse_nested_meta(|meta| {
            if meta.path.is_ident("rename") {
                let value: LitStr = meta.value()?.parse()?;
                rename = Some(value.value());
            } else if meta.input.peek(syn::Token![=]) {
                let _: syn::Expr = meta.value()?.parse()?;
            }

            Ok(())
        });
        if let Some(rename) = rename {
            return Ok(Some(rename));
        }
    }

    Ok(None)
}
