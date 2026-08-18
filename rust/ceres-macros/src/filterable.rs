//! Derive the filterable field surface from an entity struct.

use proc_macro2::TokenStream;
use quote::{format_ident, quote};
use syn::{Data, DeriveInput, Fields, LitStr};

use crate::last_segment;

/// Expand `#[derive(Filterable)]`.
///
/// Every named field whose type belongs to a filter family contributes one entry to
/// the entity's `FIELDS` table, keyed by its wire name, the `#[serde(rename)]` value
/// when one is present. The field's operation filters, the `contains`, `prefix`, and
/// `suffix` variants where its family carries them, are generated here too, each with
/// the kind it matches by. Fields of unfilterable types simply do not appear in
/// `FIELDS` or `COLUMNS`, though `WIRE_KEYS` still names them, because the wire format
/// carries every field regardless of what the filter can reach.
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
    let mut columns = Vec::new();
    let mut wire_keys = Vec::new();
    for field in &fields.named {
        let identifier = field.ident.as_ref().expect("named fields carry names");
        let key = wire_name(field)?.unwrap_or_else(|| identifier.to_string());
        wire_keys.push(key.clone());
        let family = match family_of(&field.ty) {
            Family::Address if marked(field, "plain") => Family::PlainAddress,
            Family::Text if marked(field, "email") => Family::Email,
            family => family,
        };

        // Every family expands to the like-named `FieldFamily` variant, `Values` alone
        // carries a payload.
        let entry = match &family {
            Family::Values(ty) => quote! {
                ceres_entities::FieldFamily::Values(
                    <#ty as ceres_entities::FilterValues>::VALUES,
                )
            },
            Family::Unfilterable => continue,
            family => {
                let variant = format_ident!("{}", format!("{family:?}"));
                quote! { ceres_entities::FieldFamily::#variant }
            }
        };

        let operations = if marked(field, "no_operations") {
            Vec::new()
        } else {
            operation_entries(
                &key,
                &family,
                marked(field, "bare_operations"),
                marked(field, "insensitive"),
            )
        };
        let doc = doc_text(field);
        let python = match python_override(field)? {
            Some(spelling) => quote! { Some(#spelling) },
            None => quote! { None },
        };
        let column = quote! {
            ceres_entities::FilterField {
                key: #key,
                family: #entry,
                operations: &[#(#operations),*],
                doc: #doc,
                python: #python,
            }
        };
        columns.push(column.clone());
        // A skipped field is still a column, it simply carries no filter surface.
        if !marked(field, "skip") {
            entries.push(column);
        }
    }

    let struct_doc = struct_doc_text(&input);
    Ok(quote! {
        impl ceres_entities::Filterable for #name {
            const FIELDS: &'static [ceres_entities::FilterField] = &[#(#entries),*];
            const COLUMNS: &'static [ceres_entities::FilterField] = &[#(#columns),*];
            const WIRE_KEYS: &'static [&'static str] = &[#(#wire_keys),*];
            const DOC: &'static str = #struct_doc;
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
#[derive(Debug)]
enum Family {
    Uuid,
    Address,
    Timestamp,
    Text,
    Email,
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
        Family::Text | Family::Email | Family::Bytes | Family::Json => variants
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
    let Some(segment) = last_segment(ty) else {
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
        || identifier == "PermissionTargetType"
        || identifier == "GrantLevel"
}

/// Whether a type path's tail is one bare identifier.
fn type_is(ty: &syn::Type, name: &str) -> bool {
    last_segment(ty).is_some_and(|segment| segment.ident == name && segment.arguments.is_none())
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

/// Whether the field carries the given `#[filterable(...)]` marker.
///
/// `skip` drops a field whose type would otherwise filter, for a column the Python
/// filter does not expose. `plain` takes an address out of the selector grammar.
/// `insensitive` folds case in the field's operation filters, which an email address's
/// do. `bare_operations` names those filters by the bare variant, `contains` rather
/// than `{key}_contains`. `no_operations` keeps a text field's own key while dropping
/// the `contains`, `prefix`, and `suffix` variants, which a permission target filters
/// without.
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

            // A name-value entry like `python = "..."` consumes its value so the scan
            // reaches the markers after it.
            if meta.input.peek(syn::Token![=]) {
                let _: syn::Expr = meta.value()?.parse()?;
            }

            Ok(())
        });
        if found {
            return true;
        }
    }

    false
}

/// The struct's doc comment, joined and trimmed, empty when there is none.
fn struct_doc_text(input: &DeriveInput) -> String {
    let mut lines = Vec::new();
    for attribute in &input.attrs {
        if !attribute.path().is_ident("doc") {
            continue;
        }

        if let syn::Meta::NameValue(pair) = &attribute.meta
            && let syn::Expr::Lit(literal) = &pair.value
            && let syn::Lit::Str(text) = &literal.lit
        {
            lines.push(text.value().trim().to_string());
        }
    }

    lines.join("\n")
}

/// The field's doc comment, joined and trimmed, empty when there is none.
fn doc_text(field: &syn::Field) -> String {
    let mut lines = Vec::new();
    for attribute in &field.attrs {
        if !attribute.path().is_ident("doc") {
            continue;
        }

        if let syn::Meta::NameValue(pair) = &attribute.meta
            && let syn::Expr::Lit(literal) = &pair.value
            && let syn::Lit::Str(text) = &literal.lit
        {
            lines.push(text.value().trim().to_string());
        }
    }

    lines.join("\n")
}

/// The `#[filterable(python = "...")]` spelling on a field, when present.
fn python_override(field: &syn::Field) -> syn::Result<Option<String>> {
    for attribute in &field.attrs {
        if !attribute.path().is_ident("filterable") {
            continue;
        }

        let mut spelling = None;
        attribute.parse_nested_meta(|meta| {
            if meta.path.is_ident("python") {
                let value: LitStr = meta.value()?.parse()?;
                spelling = Some(value.value());
            } else if meta.input.peek(syn::Token![=]) {
                let _: syn::Expr = meta.value()?.parse()?;
            }

            Ok(())
        })?;
        if spelling.is_some() {
            return Ok(spelling);
        }
    }

    Ok(None)
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
