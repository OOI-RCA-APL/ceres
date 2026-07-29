//! Implementation of the `python_config!` macro.

use proc_macro2::TokenStream;
use quote::{format_ident, quote};
use syn::parse::{Parse, ParseStream};
use syn::punctuated::Punctuated;
use syn::{Attribute, Ident, LitStr, Path, Result, Token, Type, parenthesized};

/// One class definition inside the macro invocation.
struct ClassDefinition {
    docs: Vec<Attribute>,
    name: Ident,
    inner: Path,
    raw: Path,
    fields: Vec<FieldDefinition>,
}

/// How a field's value crosses the Python boundary.
enum FieldKind {
    /// The value converts through the `PyFieldType` trait, keeping both directions typed.
    Value,
    /// The value is another generated class.
    Nested(Path),
    /// The value crosses as an untyped object, annotated in the stubs with the given type.
    Any(LitStr),
}

/// One field inside a class definition.
struct FieldDefinition {
    docs: Vec<Attribute>,
    kind: FieldKind,
    name: Ident,
    ty: Type,
    optional: bool,
}

impl Parse for ClassDefinition {
    fn parse(input: ParseStream) -> Result<Self> {
        let docs = input.call(Attribute::parse_outer)?;
        let name: Ident = input.parse()?;

        let paths;
        parenthesized!(paths in input);
        let inner: Path = paths.parse()?;
        paths.parse::<Token![,]>()?;
        let raw: Path = paths.parse()?;

        let body;
        syn::braced!(body in input);
        let fields: Punctuated<FieldDefinition, Token![,]> =
            body.parse_terminated(FieldDefinition::parse, Token![,])?;

        Ok(Self {
            docs,
            name,
            inner,
            raw,
            fields: fields.into_iter().collect(),
        })
    }
}

impl Parse for FieldDefinition {
    fn parse(input: ParseStream) -> Result<Self> {
        let attributes = input.call(Attribute::parse_outer)?;
        let name: Ident = input.parse()?;
        input.parse::<Token![:]>()?;
        let ty: Type = input.parse()?;

        let mut docs = Vec::new();
        let mut kind = FieldKind::Value;
        for attribute in attributes {
            if attribute.path().is_ident("doc") {
                docs.push(attribute);
            } else if attribute.path().is_ident("python") {
                attribute.parse_nested_meta(|meta| {
                    if meta.path.is_ident("nested") {
                        meta.input.parse::<Token![=]>()?;
                        kind = FieldKind::Nested(meta.input.parse()?);
                        Ok(())
                    } else if meta.path.is_ident("any") {
                        meta.input.parse::<Token![=]>()?;
                        kind = FieldKind::Any(meta.input.parse()?);
                        Ok(())
                    } else {
                        Err(meta.error("expected `nested = Class` or `any = \"type\"`"))
                    }
                })?;
            } else {
                return Err(syn::Error::new_spanned(
                    attribute,
                    "only doc comments and #[python(...)] are supported here",
                ));
            }
        }

        let optional = is_option(&ty);
        Ok(Self {
            docs,
            kind,
            name,
            ty,
            optional,
        })
    }
}

/// Return whether a type is spelled `Option<...>`.
fn is_option(ty: &Type) -> bool {
    let Type::Path(path) = ty else {
        return false;
    };

    path.path
        .segments
        .last()
        .is_some_and(|segment| segment.ident == "Option")
}

/// Return the `T` of a type spelled `Option<T>`, or the type itself.
fn strip_option(ty: &Type) -> &Type {
    let Type::Path(path) = ty else {
        return ty;
    };

    let Some(segment) = path.path.segments.last() else {
        return ty;
    };

    if segment.ident != "Option" {
        return ty;
    }

    let syn::PathArguments::AngleBracketed(arguments) = &segment.arguments else {
        return ty;
    };

    match arguments.args.first() {
        Some(syn::GenericArgument::Type(inner)) => inner,
        _ => ty,
    }
}

/// Expand every class definition in the macro input.
pub fn expand(input: TokenStream) -> Result<TokenStream> {
    struct Definitions(Vec<ClassDefinition>);

    impl Parse for Definitions {
        fn parse(input: ParseStream) -> Result<Self> {
            let mut definitions = Vec::new();
            while !input.is_empty() {
                definitions.push(input.parse()?);
            }

            Ok(Self(definitions))
        }
    }

    let definitions: Definitions = syn::parse2(input)?;
    let classes = definitions.0.iter().map(expand_class);
    Ok(quote! { #(#classes)* })
}

/// Expand one class definition into its pyclass and implementations.
fn expand_class(definition: &ClassDefinition) -> TokenStream {
    let ClassDefinition {
        docs,
        name,
        inner,
        raw,
        fields,
    } = definition;

    let parameters = fields.iter().map(|field| {
        let field_name = &field.name;
        let value = strip_option(&field.ty);
        match &field.kind {
            FieldKind::Nested(nested) => {
                let input = format_ident!("{}Input", nested.segments.last().unwrap().ident);
                quote! { #field_name: Option<#input<'_>> }
            }
            FieldKind::Any(_) => {
                quote! { #field_name: Option<::pyo3::Bound<'_, ::pyo3::types::PyAny>> }
            }
            FieldKind::Value => {
                quote! { #field_name: Option<<#value as crate::interop::PyFieldType>::Input> }
            }
        }
    });
    let parameters: Vec<TokenStream> = parameters.collect();

    let signature_entries = fields.iter().map(|field| {
        let field_name = &field.name;
        quote! { #field_name = None }
    });

    let raw_assignments = fields.iter().map(|field| {
        let field_name = &field.name;
        let value = strip_option(&field.ty);
        match &field.kind {
            FieldKind::Nested(_) => {
                quote! {
                    #field_name: match #field_name {
                        Some(value) => Some(value.into_raw()?),
                        None => None,
                    }
                }
            }
            FieldKind::Any(_) => {
                quote! {
                    #field_name: match #field_name {
                        Some(value) => Some(crate::interop::from_python(&value)?),
                        None => None,
                    }
                }
            }
            FieldKind::Value => {
                quote! {
                    #field_name: #field_name
                        .map(<#value as crate::interop::PyFieldType>::from_input)
                        .transpose()?
                }
            }
        }
    });

    let getters = fields.iter().map(|field| {
        let field_name = &field.name;
        let field_docs = &field.docs;
        match &field.kind {
            FieldKind::Nested(nested) => {
                let return_type = if field.optional {
                    quote! { Option<#nested> }
                } else {
                    quote! { #nested }
                };

                quote! {
                    #(#field_docs)*
                    #[getter]
                    fn #field_name(&self) -> #return_type {
                        crate::interop::ToPyValue::to_py_value(&self.inner.#field_name)
                    }
                }
            }
            FieldKind::Any(annotation) => {
                quote! {
                    #(#field_docs)*
                    #[getter]
                    #[gen_stub(override_return_type(type_repr = #annotation))]
                    fn #field_name(
                        &self,
                        py: ::pyo3::Python<'_>,
                    ) -> ::pyo3::PyResult<::pyo3::Py<::pyo3::types::PyAny>> {
                        crate::interop::to_python(py, &self.inner.#field_name)
                    }
                }
            }
            FieldKind::Value => {
                let ty = &field.ty;
                quote! {
                    #(#field_docs)*
                    #[getter]
                    fn #field_name(&self) -> <#ty as crate::interop::PyFieldType>::Py {
                        crate::interop::ToPyValue::to_py_value(&self.inner.#field_name)
                    }
                }
            }
        }
    });

    let input_ident = format_ident!("{name}Input");
    let input_annotation = format!("{name} | dict[str, typing.Any]");

    quote! {
        #(#docs)*
        #[::pyo3_stub_gen::derive::gen_stub_pyclass]
        #[::pyo3::pyclass(subclass, module = "ceres_core")]
        #[derive(Debug, Clone)]
        pub struct #name {
            pub(crate) inner: #inner,
        }

        impl crate::interop::ToPyValue<#name> for #inner {
            fn to_py_value(&self) -> #name {
                #name {
                    inner: self.clone(),
                }
            }
        }

        /// A constructor argument accepting an existing instance or a mapping of fields.
        #[derive(::pyo3::FromPyObject)]
        pub enum #input_ident<'py> {
            Instance(::pyo3::PyRef<'py, #name>),
            Mapping(::pyo3::Bound<'py, ::pyo3::types::PyDict>),
        }

        impl #input_ident<'_> {
            /// Convert the argument into the raw form, revalidating mappings.
            pub(crate) fn into_raw(self) -> ::pyo3::PyResult<#raw> {
                match self {
                    Self::Instance(instance) => crate::interop::reraw(&instance.inner),
                    Self::Mapping(mapping) => crate::interop::from_python(mapping.as_any()),
                }
            }
        }

        impl ::pyo3_stub_gen::PyStubType for #input_ident<'_> {
            fn type_output() -> ::pyo3_stub_gen::TypeInfo {
                ::pyo3_stub_gen::TypeInfo::builtin(#input_annotation)
            }
        }

        #[::pyo3_stub_gen::derive::gen_stub_pymethods]
        #[::pyo3::pymethods]
        impl #name {
            #[new]
            #[pyo3(signature = (*, #(#signature_entries),*))]
            #[allow(clippy::too_many_arguments)]
            fn new(#(#parameters,)*) -> ::pyo3::PyResult<Self> {
                let raw = #raw {
                    #(#raw_assignments,)*
                };
                let inner = <#inner as ::std::convert::TryFrom<#raw>>::try_from(raw)
                    .map_err(crate::interop::problems_to_error)?;
                Ok(Self { inner })
            }

            #(#getters)*

            /// Return the configuration as a plain dictionary of JSON-compatible values.
            ///
            /// Called through `ceres.data.to_dict` rather than directly.
            #[pyo3(name = "__to_dict__")]
            #[gen_stub(override_return_type(type_repr = "dict[str, typing.Any]"))]
            fn to_dict(
                &self,
                py: ::pyo3::Python<'_>,
            ) -> ::pyo3::PyResult<::pyo3::Py<::pyo3::types::PyAny>> {
                crate::interop::to_python(py, &self.inner)
            }

            /// Return the JSON Schema describing this configuration section.
            ///
            /// Called through `ceres.data.to_json_schema` rather than directly.
            #[staticmethod]
            #[pyo3(name = "__json_schema__")]
            #[gen_stub(override_return_type(type_repr = "dict[str, typing.Any]"))]
            fn json_schema(
                py: ::pyo3::Python<'_>,
            ) -> ::pyo3::PyResult<::pyo3::Py<::pyo3::types::PyAny>> {
                let schema = ::schemars::schema_for!(#raw);
                crate::interop::to_python(py, &schema)
            }

            fn __eq__(&self, other: &::pyo3::Bound<'_, ::pyo3::types::PyAny>) -> bool {
                match other.cast::<#name>() {
                    Ok(other) => self.inner == other.borrow().inner,
                    Err(_) => false,
                }
            }

            fn __repr__(&self) -> String {
                format!("{:?}", self.inner)
            }
        }
    }
}
