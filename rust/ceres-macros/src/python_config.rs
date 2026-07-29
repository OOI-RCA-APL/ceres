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
    /// The generated class this one extends, written as `Name(...): Parent { ... }`. The
    /// parent's validated type must implement `From<&ChildInner>`.
    parent: Option<Path>,
    /// The raw type holding fields marked `#[python(shared)]`, flattened into the raw form
    /// under a `shared` field.
    shared: Option<Path>,
    /// A wrapping function the validated value passes through before `__to_dict__`
    /// serialization, typically a tagged union's variant constructor.
    serialize_as: Option<Path>,
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
    /// Whether the field lives in the raw and validated forms' flattened `shared` struct.
    shared: bool,
}

impl Parse for ClassDefinition {
    fn parse(input: ParseStream) -> Result<Self> {
        let attributes = input.call(Attribute::parse_outer)?;
        let mut docs = Vec::new();
        let mut shared = None;
        let mut serialize_as = None;
        for attribute in attributes {
            if attribute.path().is_ident("doc") {
                docs.push(attribute);
            } else if attribute.path().is_ident("python") {
                attribute.parse_nested_meta(|meta| {
                    if meta.path.is_ident("shared") {
                        shared = Some(meta.value()?.parse()?);
                        Ok(())
                    } else if meta.path.is_ident("serialize_as") {
                        serialize_as = Some(meta.value()?.parse()?);
                        Ok(())
                    } else {
                        Err(meta.error("expected `shared = RawType` or `serialize_as = path`"))
                    }
                })?;
            } else {
                return Err(syn::Error::new_spanned(
                    attribute,
                    "only doc comments and #[python(...)] are supported here",
                ));
            }
        }

        let name: Ident = input.parse()?;

        let paths;
        parenthesized!(paths in input);
        let inner: Path = paths.parse()?;
        paths.parse::<Token![,]>()?;
        let raw: Path = paths.parse()?;

        let parent = if input.peek(Token![:]) {
            input.parse::<Token![:]>()?;
            Some(input.parse()?)
        } else {
            None
        };

        let body;
        syn::braced!(body in input);
        let fields: Punctuated<FieldDefinition, Token![,]> =
            body.parse_terminated(FieldDefinition::parse, Token![,])?;

        Ok(Self {
            docs,
            name,
            inner,
            raw,
            parent,
            shared,
            serialize_as,
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
        let mut shared = false;
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
                    } else if meta.path.is_ident("shared") {
                        shared = true;
                        Ok(())
                    } else {
                        Err(meta.error("expected `nested = Class`, `any = \"type\"`, or `shared`"))
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
            shared,
        })
    }
}

/// Widen a stub annotation to also accept `None`, for optional constructor arguments.
fn optional_annotation(annotation: &LitStr) -> LitStr {
    let value = annotation.value();
    if value.ends_with("| None") {
        annotation.clone()
    } else {
        LitStr::new(&format!("{value} | None"), annotation.span())
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
        parent,
        shared,
        serialize_as,
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
            FieldKind::Any(annotation) => {
                let parameter_annotation = optional_annotation(annotation);
                quote! {
                    #[gen_stub(override_type(type_repr = #parameter_annotation))]
                    #field_name: Option<::pyo3::Bound<'_, ::pyo3::types::PyAny>>
                }
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

    let raw_assignment = |field: &FieldDefinition| {
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
    };

    // Fields marked shared live in the raw form's flattened `shared` struct rather than on
    // the raw form directly.
    let direct_assignments = fields
        .iter()
        .filter(|field| !field.shared)
        .map(raw_assignment);
    let shared_assignments = fields
        .iter()
        .filter(|field| field.shared)
        .map(raw_assignment);
    let shared_entry = shared.as_ref().map(|shared_raw| {
        quote! { shared: #shared_raw { #(#shared_assignments,)* }, }
    });

    let getters = fields.iter().map(|field| {
        let field_name = &field.name;
        let field_docs = &field.docs;
        let access = if field.shared {
            quote! { self.inner.shared.#field_name }
        } else {
            quote! { self.inner.#field_name }
        };

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
                        crate::interop::ToPyValue::to_py_value(&#access)
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
                        crate::interop::to_python(py, &#access)
                    }
                }
            }
            FieldKind::Value => {
                let ty = &field.ty;
                quote! {
                    #(#field_docs)*
                    #[getter]
                    fn #field_name(&self) -> <#ty as crate::interop::PyFieldType>::Py {
                        crate::interop::ToPyValue::to_py_value(&#access)
                    }
                }
            }
        }
    });

    let input_ident = format_ident!("{name}Input");
    let input_annotation = format!("{name} | dict[str, typing.Any]");

    // A class with a parent extends it natively, so its constructor also builds the parent
    // portion of the object from the same validated value.
    let extends = parent.as_ref().map(|parent| quote! { extends = #parent, });
    // The stub generator names the constructor's written return type inside a static, where
    // `Self` cannot appear, so the extends form spells the class name out.
    let new_return = match parent {
        Some(parent) => quote! { (#name, #parent) },
        None => quote! { Self },
    };
    let new_result = match parent {
        Some(parent) => quote! {
            let parent = #parent {
                inner: (&inner).into(),
            };
            Ok((Self { inner }, parent))
        },
        None => quote! { Ok(Self { inner }) },
    };

    let serialized = match serialize_as {
        Some(wrap) => quote! { &#wrap(self.inner.clone()) },
        None => quote! { &self.inner },
    };

    quote! {
        #(#docs)*
        #[::pyo3_stub_gen::derive::gen_stub_pyclass]
        #[::pyo3::pyclass(subclass, #extends module = "ceres_core")]
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
            fn new(#(#parameters,)*) -> ::pyo3::PyResult<#new_return> {
                let raw = #raw {
                    #(#direct_assignments,)*
                    #shared_entry
                };
                let inner = <#inner as ::std::convert::TryFrom<#raw>>::try_from(raw)
                    .map_err(crate::interop::problems_to_error)?;
                #new_result
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
                crate::interop::to_python(py, #serialized)
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
