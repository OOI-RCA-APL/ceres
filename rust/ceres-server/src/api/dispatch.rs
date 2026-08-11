//! Host-dispatched routes.
//!
//! Most of the API is one entry in the [`host_routes!`] table, which emits a typed path
//! per route and registers a handler forwarding to the host. The handler parses path
//! parameters with the contract's semantics, a UUID that fails to
//! parse means the route never matched, gates the actor, and forwards one arguments
//! object to the host, `{"actor", "path", "query", "body"}`. Validation of queries and
//! bodies stays with the host so every filter and model keeps its exact behavior.

use std::sync::Arc;

use axum::Router;
use axum::body::Bytes;
use axum::extract::{RawQuery, State};
use axum::http::{HeaderMap, StatusCode, header};
use axum::response::{IntoResponse, Response};
use axum_extra::routing::{RouterExt, TypedPath};
use serde::Deserialize;
use serde_json::{Map, Value, json};
use uuid::Uuid;

use crate::app::{AppState, Resolution};
use crate::auth::{Actor, Gate};
use crate::error::{ApiError, Problem};
use crate::host::Answer;

/// How a path parameter forwards to the host.
#[derive(Clone, Copy, PartialEq)]
enum Kind {
    /// Passed through as text, the host validates it.
    Raw,
    /// Must parse as a UUID, otherwise the route never matched.
    Uuid,
}

/// One forwarded path parameter, `(host name, value, kind)`.
type PathValue = (&'static str, String, Kind);

/// Emit one typed path struct, with or without captures.
macro_rules! path_struct {
    ($(#[$doc:meta])* $name:ident, $path:literal, []) => {
        $(#[$doc])*
        #[derive(TypedPath, Deserialize)]
        #[typed_path($path)]
        pub(crate) struct $name;
    };
    ($(#[$doc:meta])* $name:ident, $path:literal, [$($field:ident),+]) => {
        $(#[$doc])*
        #[derive(TypedPath, Deserialize)]
        #[typed_path($path)]
        pub(crate) struct $name {
            $($field: String,)+
        }
    };
}

/// Declare the host-dispatched routes.
///
/// Each row emits a [`TypedPath`] struct named for the route so the path lives on the
/// type axum-extra checks against the struct's captures, and registers a handler
/// forwarding to [`Dispatch::respond`]. Rows name their gate, host operation, forwarded
/// parameters, and whether a request body forwards too.
macro_rules! host_routes {
    ($(
        $(#[doc = $doc:literal])*
        $name:ident: $method:ident $path:literal => $gate:expr, $operation:literal
            $(, params($($field:ident => $host:literal: $kind:ident),+))?
            $(, body: $body:literal)?
            $(, status: $status:literal)?
            $(, scrub: $scrub:literal)?
        ;
    )*) => {
        $(path_struct!($(#[doc = $doc])* $name, $path, [$($($field),+)?]);)*

        /// Describe every declared route for the OpenAPI document.
        pub(crate) fn documented() -> Vec<crate::api::schema::Documented> {
            vec![$(crate::api::schema::Documented {
                method: crate::api::schema::method_of(stringify!($method)),
                path: $path,
                summary: concat!($($doc),*),
                parameters: &[$($(stringify!($field)),+)?],
                secured: !matches!($gate, Gate::Open),
                tag: $operation.split('.').next().unwrap_or($operation),
            }),*]
        }

        /// Register every declared route.
        pub(crate) fn register(router: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
            $(let router = router.$method(
                #[allow(unused_variables)]
                |path: $name,
                 State(state): State<Arc<AppState>>,
                 headers: HeaderMap,
                 RawQuery(query): RawQuery,
                 bytes: Bytes| async move {
                    Dispatch {
                        gate: $gate,
                        operation: $operation,
                        parameters: vec![$($(($host, path.$field, Kind::$kind)),+)?],
                        body: (false $(|| $body)?).then_some(bytes),
                        status: 200 $(- 200 + $status)?,
                        scrub: false $(|| $scrub)?,
                    }
                    .respond(&state, &headers, query)
                    .await
                },
            );)*

            router
        }
    };
}

host_routes! {
    /// Reload the engine's configuration, which returns it and so scrubs it.
    ReloadEngine: typed_post "/api/reload" => Gate::Admin, "engine.reload", scrub: true;
    /// Start matching components.
    StartComponents: typed_post "/api/start" => Gate::Authenticated, "engine.start", body: true;
    /// Stop matching components.
    StopComponents: typed_post "/api/stop" => Gate::Authenticated, "engine.stop", body: true;
    /// Enable matching components.
    EnableComponents: typed_post "/api/enable" => Gate::Authenticated, "engine.enable", body: true;
    /// Disable matching components.
    DisableComponents: typed_post "/api/disable" => Gate::Authenticated, "engine.disable",
        body: true;
    /// Enable and start matching components.
    UpComponents: typed_post "/api/up" => Gate::Authenticated, "engine.up", body: true;
    /// Disable and stop matching components.
    DownComponents: typed_post "/api/down" => Gate::Authenticated, "engine.down", body: true;

    /// List users.
    UsersCollection: typed_get "/api/users" => Gate::Authenticated, "users.list";
    /// Count users.
    UsersCount: typed_get "/api/users/count" => Gate::Authenticated, "users.count";
    /// Fetch one user.
    UsersMember: typed_get "/api/users/{id}" => Gate::Authenticated, "users.get",
        params(id => "id": Uuid);
    /// Create a user.
    UsersCreate: typed_post "/api/users" => Gate::Admin, "users.create", body: true, status: 201;
    /// Update a user.
    UsersUpdate: typed_patch "/api/users/{id}" => Gate::SelfOrAdmin("id"), "users.update",
        params(id => "id": Uuid), body: true;
    /// Delete a user.
    UsersDelete: typed_delete "/api/users/{id}" => Gate::Admin, "users.delete",
        params(id => "id": Uuid);

    /// List groups.
    GroupsCollection: typed_get "/api/groups" => Gate::Authenticated, "groups.list";
    /// Count groups.
    GroupsCount: typed_get "/api/groups/count" => Gate::Authenticated, "groups.count";
    /// Fetch one group.
    GroupsMember: typed_get "/api/groups/{id}" => Gate::Authenticated, "groups.get",
        params(id => "id": Uuid);
    /// Create a group.
    GroupsCreate: typed_post "/api/groups" => Gate::Admin, "groups.create", body: true;
    /// Update a group.
    GroupsUpdate: typed_patch "/api/groups/{id}" => Gate::Admin, "groups.update",
        params(id => "id": Uuid), body: true;
    /// Delete a group.
    GroupsDelete: typed_delete "/api/groups/{id}" => Gate::Admin, "groups.delete",
        params(id => "id": Uuid);
    /// List a group's memberships.
    GroupMembers: typed_get "/api/groups/{id}/members" => Gate::Authenticated, "groups.members",
        params(id => "id": Uuid);
    /// Add a member to a group.
    GroupMembersAdd: typed_post "/api/groups/{id}/members" => Gate::Admin, "groups.add_member",
        params(id => "id": Uuid), body: true;
    /// Remove a member from a group.
    GroupMembersRemove: typed_delete "/api/groups/{id}/members/{second}" => Gate::Admin,
        "groups.remove_member", params(id => "id": Uuid, second => "user_id": Uuid);
    /// List a user's group memberships.
    MembershipsCollection: typed_get "/api/users/{id}/group-memberships" => Gate::Authenticated,
        "memberships.list", params(id => "user_id": Uuid);
    /// Add a user to a group.
    MembershipsAdd: typed_post "/api/users/{id}/group-memberships/{second}" => Gate::Admin,
        "memberships.add", params(id => "user_id": Uuid, second => "group_id": Uuid);
    /// Remove a user from a group.
    MembershipsRemove: typed_delete "/api/users/{id}/group-memberships/{second}" => Gate::Admin,
        "memberships.remove", params(id => "user_id": Uuid, second => "group_id": Uuid);

    /// List a user's permissions.
    UserPermissions: typed_get "/api/permissions/user/{id}" => Gate::SelfOrAdmin("user_id"),
        "permissions.user", params(id => "user_id": Uuid);
    /// List a group's permissions.
    GroupPermissions: typed_get "/api/permissions/group/{id}" => Gate::Admin,
        "permissions.group", params(id => "group_id": Uuid);
    /// Assign a user permission.
    UserPermissionsAssign: typed_put "/api/permissions/user/{id}" => Gate::Admin,
        "permissions.assign_user", params(id => "user_id": Uuid), body: true;
    /// Delete a user permission, the target named in the request body.
    UserPermissionsDelete: typed_delete "/api/permissions/user/{id}" => Gate::Admin,
        "permissions.delete_user", params(id => "user_id": Uuid), body: true;
    /// Assign a group permission.
    GroupPermissionsAssign: typed_put "/api/permissions/group/{id}" => Gate::Admin,
        "permissions.assign_group", params(id => "group_id": Uuid), body: true;
    /// Delete a group permission, the target named in the request body.
    GroupPermissionsDelete: typed_delete "/api/permissions/group/{id}" => Gate::Admin,
        "permissions.delete_group", params(id => "group_id": Uuid), body: true;
    /// List a user's effective access across every component.
    EffectiveAccess: typed_get "/api/permissions/effective/{id}" => Gate::SelfOrAdmin("user_id"),
        "permissions.effective", params(id => "user_id": Uuid);
    /// Resolve a user's effective access at one address.
    EffectiveAccessAt: typed_get "/api/permissions/effective/{id}/{*address}" =>
        Gate::SelfOrAdmin("user_id"), "permissions.effective_at",
        params(id => "user_id": Uuid, address => "address": Raw);

    /// List workspaces.
    WorkspacesCollection: typed_get "/api/workspaces" => Gate::Authenticated, "workspaces.list";
    /// Fetch one workspace.
    WorkspacesMember: typed_get "/api/workspaces/{id}" => Gate::Authenticated, "workspaces.get",
        params(id => "id": Uuid);
    /// Create a workspace.
    WorkspacesCreate: typed_post "/api/workspaces" => Gate::Authenticated, "workspaces.create",
        body: true;
    /// Update a workspace.
    WorkspacesUpdate: typed_patch "/api/workspaces/{id}" => Gate::Authenticated,
        "workspaces.update", params(id => "id": Uuid), body: true;
    /// Delete a workspace.
    WorkspacesDelete: typed_delete "/api/workspaces/{id}" => Gate::Authenticated,
        "workspaces.delete", params(id => "id": Uuid);
    /// List a user's workspace edits.
    EditsCollection: typed_get "/api/users/{id}/workspace-edits" => Gate::SelfOrAdmin("user_id"),
        "edits.list", params(id => "user_id": Uuid);
    /// Fetch one workspace edit.
    EditsMember: typed_get "/api/users/{id}/workspace-edits/{second}" =>
        Gate::SelfOrAdmin("user_id"), "edits.get",
        params(id => "user_id": Uuid, second => "workspace_id": Uuid);
    /// Create a workspace edit.
    EditsCreate: typed_post "/api/users/{id}/workspace-edits/{second}" =>
        Gate::SelfOrAdmin("user_id"), "edits.create",
        params(id => "user_id": Uuid, second => "workspace_id": Uuid), body: true;
    /// Assign a workspace edit, creating or replacing it.
    EditsAssign: typed_put "/api/users/{id}/workspace-edits/{second}" =>
        Gate::SelfOrAdmin("user_id"), "edits.assign",
        params(id => "user_id": Uuid, second => "workspace_id": Uuid), body: true;
    /// Delete a workspace edit.
    EditsDelete: typed_delete "/api/users/{id}/workspace-edits/{second}" =>
        Gate::SelfOrAdmin("user_id"), "edits.delete",
        params(id => "user_id": Uuid, second => "workspace_id": Uuid);

    /// Fetch one setting, the operation applying its own actor rules.
    SettingsMember: typed_get "/api/settings/{id}/{second}" => Gate::Open, "settings.get",
        params(id => "user_id": Raw, second => "name": Raw);
    /// Assign a setting, the operation applying its own actor rules.
    SettingsAssign: typed_put "/api/settings" => Gate::Open, "settings.assign", body: true;
    /// List alert statistics.
    StatisticsCollection: typed_get "/api/statistics" => Gate::Authenticated, "statistics.list";
    /// Fetch one component's status.
    StatusesMember: typed_get "/api/statuses/{id}" => Gate::Authenticated, "statuses.get",
        params(id => "address": Raw);

    /// Describe every component the caller may view.
    ComponentsCollection: typed_get "/api/components" => Gate::Authenticated, "components.list";
    /// Describe one component and its children.
    ComponentsMember: typed_get "/api/components/{id}" => Gate::Authenticated, "components.get",
        params(id => "address": Raw);
    /// Fetch one component's configuration.
    ComponentsConfig: typed_get "/api/components/{id}/config" => Gate::Authenticated,
        "components.config", params(id => "address": Raw);
    /// List one component's connections with their connectivity.
    ComponentsConnections: typed_get "/api/components/{id}/connections" => Gate::Authenticated,
        "components.connections", params(id => "address": Raw);
    /// List one component's scheduled jobs.
    ComponentsJobs: typed_get "/api/components/{id}/jobs" => Gate::Authenticated,
        "components.jobs", params(id => "address": Raw);
    /// List the particle types one component declares.
    ComponentsParticleTypes: typed_get "/api/components/{id}/particle-types" =>
        Gate::Authenticated, "components.particle_types", params(id => "address": Raw);
    /// List one component's procedures.
    ProceduresCollection: typed_get "/api/components/{id}/procedures" => Gate::Authenticated,
        "procedures.list", params(id => "address": Raw);
    /// Fetch one procedure binding.
    ProceduresMember: typed_get "/api/components/{id}/procedures/{second}" =>
        Gate::Authenticated, "procedures.get",
        params(id => "address": Raw, second => "name": Raw);
    /// List one component's queries.
    QueriesCollection: typed_get "/api/components/{id}/queries" => Gate::Authenticated,
        "queries.list", params(id => "address": Raw);
    /// Fetch one query binding.
    QueriesMember: typed_get "/api/components/{id}/queries/{second}" => Gate::Authenticated,
        "queries.get", params(id => "address": Raw, second => "name": Raw);
    /// List one component's actions.
    ActionsCollection: typed_get "/api/components/{id}/actions" => Gate::Authenticated,
        "actions.list", params(id => "address": Raw);
    /// Fetch one action binding.
    ActionsMember: typed_get "/api/components/{id}/actions/{second}" => Gate::Authenticated,
        "actions.get", params(id => "address": Raw, second => "name": Raw);
    /// Call a procedure with body arguments, access checked by the operation.
    ProceduresCall: typed_post "/api/components/{id}/procedures/{second}/call" => Gate::Open,
        "procedures.call", params(id => "address": Raw, second => "name": Raw), body: true;
    /// Call a procedure with query arguments, access checked by the operation.
    ProceduresCallByGet: typed_get "/api/components/{id}/procedures/{second}/call" => Gate::Open,
        "procedures.call_get", params(id => "address": Raw, second => "name": Raw);
    /// Call a query with body arguments, access checked by the operation.
    QueriesCall: typed_post "/api/components/{id}/queries/{second}/call" => Gate::Open,
        "queries.call", params(id => "address": Raw, second => "name": Raw), body: true;
    /// Call a query with query arguments, access checked by the operation.
    QueriesCallByGet: typed_get "/api/components/{id}/queries/{second}/call" => Gate::Open,
        "queries.call_get", params(id => "address": Raw, second => "name": Raw);
    /// Call an action with body arguments, access checked by the operation.
    ActionsCall: typed_post "/api/components/{id}/actions/{second}/call" => Gate::Open,
        "actions.call", params(id => "address": Raw, second => "name": Raw), body: true;
    /// Send data over one component connection.
    ComponentsSend: typed_post "/api/components/{id}/connections/{second}/send" =>
        Gate::Authenticated, "components.send",
        params(id => "address": Raw, second => "connection": Raw), body: true;
}

impl Actor {
    /// The actor's form in operation arguments.
    fn to_arguments(&self) -> Value {
        json!({
            "user": self.user.as_ref().map(|user| user.id.to_string()),
            "admin": self.admin(),
            "unrestricted": self.unrestricted,
        })
    }
}

/// One request bound for a host operation, as the route table declared it.
struct Dispatch {
    gate: Gate,
    operation: &'static str,
    parameters: Vec<PathValue>,
    /// The request body, `None` on routes that take none.
    body: Option<Bytes>,
    /// The success status, 201 on the routes that create.
    status: u16,
    /// Whether the payload drops credential fields before serving.
    scrub: bool,
}

impl Dispatch {
    /// Gate, assemble, and forward the request, serving what the operation answers.
    async fn respond(
        self,
        state: &AppState,
        headers: &HeaderMap,
        query: Option<String>,
    ) -> Result<Response, ApiError> {
        // Path parameters first, a UUID that fails to parse means no route matched.
        let mut path = Map::new();
        for (host_name, value, kind) in &self.parameters {
            if *kind == Kind::Uuid && value.parse::<Uuid>().is_err() {
                return Err(ApiError::not_found());
            }

            path.insert((*host_name).to_string(), Value::String(value.clone()));
        }

        let actor = state.actor(headers, Resolution::Full).await?;
        self.gate.admit(
            &actor,
            self.parameters
                .iter()
                .map(|(host_name, value, _)| (*host_name, value.as_str())),
        )?;

        let body = match self.body.as_deref() {
            None | Some([]) => Value::Null,
            Some(bytes) => serde_json::from_slice(bytes).map_err(|error| {
                ApiError::validation(vec![Problem::new(
                    "json_invalid",
                    &["body"],
                    format!("Invalid JSON: {error}"),
                )])
            })?,
        };

        let arguments = json!({
            "actor": actor.to_arguments(),
            "path": Value::Object(path),
            "query": crate::api::query_pairs(query),
            "body": body,
        });

        match state.host.operate(self.operation, arguments).await? {
            Answer::Payload(payload) => {
                // An operation answering with configuration drops its credentials
                // because reading the configuration is not permission to take the
                // signing secret.
                let payload = if self.scrub {
                    crate::scrub::scrub_json(&payload)
                } else {
                    payload
                };
                Ok((
                    StatusCode::from_u16(self.status).unwrap_or(StatusCode::OK),
                    [(header::CONTENT_TYPE, "application/json")],
                    payload,
                )
                    .into_response())
            }
            // A described response carries the status the output declared so a route's
            // own created-status override does not apply to it.
            Answer::Served(served) => Ok(served.serve(&state.host).await),
        }
    }
}
