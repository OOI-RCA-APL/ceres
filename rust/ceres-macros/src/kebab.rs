use proc_macro2::TokenStream;
use quote::quote;
use syn::{Data, DeriveInput, Fields, parse_quote};

/// Give every multi-word field a `serde` alias for its snake_case spelling.
pub(crate) fn expand_kebab_aliases(mut input: DeriveInput) -> syn::Result<TokenStream> {
    let Data::Struct(data) = &mut input.data else {
        return Err(syn::Error::new_spanned(
            &input,
            "only a struct carries configuration keys",
        ));
    };

    let Fields::Named(fields) = &mut data.fields else {
        return Err(syn::Error::new_spanned(
            &input,
            "only named fields carry configuration keys",
        ));
    };

    for field in &mut fields.named {
        let Some(identifier) = field.ident.as_ref() else {
            continue;
        };

        let name = identifier.to_string();
        if !name.contains('_') {
            continue;
        }

        field.attrs.push(parse_quote!(#[serde(alias = #name)]));
    }

    Ok(quote!(#input))
}
