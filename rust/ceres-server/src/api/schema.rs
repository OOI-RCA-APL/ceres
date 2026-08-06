//! The OpenAPI document.
//!
//! Built from the same declarations the router registers, so a route cannot appear in
//! one and not the other. Every entry carries its method, path, parameters, security,
//! and tag. Request and response bodies stay undescribed, because the engine validates
//! them through its own models rather than through a schema declared here.

use utoipa::openapi::path::{Operation, ParameterBuilder, ParameterIn, PathItemBuilder};
use utoipa::openapi::security::{Http, HttpAuthScheme, SecurityScheme};
use utoipa::openapi::{
    ComponentsBuilder, HttpMethod, InfoBuilder, OpenApi, OpenApiBuilder, PathsBuilder, Required,
    ResponseBuilder, ResponsesBuilder, Tag,
};

/// One documented route.
pub(crate) struct Documented {
    pub method: HttpMethod,
    pub path: &'static str,
    /// The route's own documentation, joined from its doc comment lines.
    pub summary: &'static str,
    /// The path's captures, in the order they appear.
    pub parameters: &'static [&'static str],
    /// Whether the route requires a token.
    pub secured: bool,
    pub tag: &'static str,
}

/// The method one of the typed registration helpers registers.
pub(crate) fn method_of(registration: &str) -> HttpMethod {
    match registration {
        "typed_post" => HttpMethod::Post,
        "typed_put" => HttpMethod::Put,
        "typed_patch" => HttpMethod::Patch,
        "typed_delete" => HttpMethod::Delete,
        _ => HttpMethod::Get,
    }
}

/// Build the document describing every route the server serves.
pub fn document(version: &str) -> OpenApi {
    let mut paths = PathsBuilder::new();
    let mut tags: Vec<&str> = Vec::new();

    // Several methods can share one path, so operations group by path before building.
    let mut grouped: Vec<(&'static str, Vec<(HttpMethod, Operation)>)> = Vec::new();
    for route in crate::api::documented_routes() {
        if !tags.contains(&route.tag) {
            tags.push(route.tag);
        }

        let mut operation = Operation::new();
        operation.summary = Some(
            route
                .summary
                .split_whitespace()
                .collect::<Vec<_>>()
                .join(" "),
        );
        operation.tags = Some(vec![route.tag.to_string()]);
        operation.responses = ResponsesBuilder::new()
            .response(
                "200",
                ResponseBuilder::new().description("The request succeeded."),
            )
            .response(
                "default",
                ResponseBuilder::new().description("The request failed, carrying an error."),
            )
            .build();
        if !route.parameters.is_empty() {
            operation.parameters = Some(
                route
                    .parameters
                    .iter()
                    .map(|name| {
                        ParameterBuilder::new()
                            .name(name.to_string())
                            .parameter_in(ParameterIn::Path)
                            .required(Required::True)
                            .build()
                    })
                    .collect(),
            );
        }

        if route.secured {
            operation.security = Some(vec![utoipa::openapi::security::SecurityRequirement::new(
                "bearer",
                Vec::<String>::new(),
            )]);
        }

        match grouped.iter_mut().find(|(path, _)| *path == route.path) {
            Some((_, operations)) => operations.push((route.method, operation)),
            None => grouped.push((route.path, vec![(route.method, operation)])),
        }
    }

    for (path, operations) in grouped {
        let mut item = PathItemBuilder::new();
        for (method, operation) in operations {
            item = item.operation(method, operation);
        }

        paths = paths.path(path, item.build());
    }

    OpenApiBuilder::new()
        .info(
            InfoBuilder::new()
                .title("Ceres")
                .version(version)
                .description(Some("The Ceres engine's HTTP API."))
                .build(),
        )
        .paths(paths.build())
        .components(Some(
            ComponentsBuilder::new()
                .security_scheme(
                    "bearer",
                    SecurityScheme::Http(Http::new(HttpAuthScheme::Bearer)),
                )
                .build(),
        ))
        .tags(Some(tags.into_iter().map(Tag::new).collect::<Vec<_>>()))
        .build()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_document_covers_the_routes() {
        let document = document("1.2.3");
        let serialized = document.to_json().unwrap();

        assert!(serialized.contains("\"/api/alive\""));
        assert!(serialized.contains("\"/api/auth/login\""));
        assert!(serialized.contains("\"/api/particles/{id}\""));
        assert!(serialized.contains("/procedures/{second}/call"));
        assert!(serialized.contains("bearer"));
        assert!(serialized.contains("1.2.3"));
    }
}
