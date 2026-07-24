from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import Query

from ceres.__internal__.app.shared import (
    SELF_OR_ADMIN,
    Actor,
    CurrentActor,
    CurrentEngine,
    Limit,
    RequireAuthenticated,
    Router,
    assert_found,
    build_address_chain,
    get_component_access,
)
from ceres.__internal__.workspace_redaction import redact_workspace_data
from ceres.access import fetch_access_grants, resolve_access_from
from ceres.config import ComponentAccessLevel
from ceres.data import construct, to_dict
from ceres.error import NotFoundError, NotPermittedError
from ceres.workspace import (
    Workspace,
    WorkspaceCreate,
    WorkspaceFilter,
    WorkspaceMembershipCreate,
    WorkspaceMembershipRole,
    WorkspaceUpdate,
)

if TYPE_CHECKING:
    from ceres.address import Address
    from ceres.engine import Engine
    from ceres.user import User

router = Router(tags=["workspaces"])


async def build_can_view(engine: Engine, user: User) -> Callable[[Address], bool]:
    """Build a per-request predicate testing view access on a component address.

    Fetch the user's access grants once so the returned predicate can be called repeatedly
    without re-querying the database.
    """
    grants = await fetch_access_grants(engine.database, user)

    def can_view(address: Address) -> bool:
        component = engine.get_component(address)
        if component is None:
            # There is no live component to protect, so nothing to hide.
            return True

        system = component.system
        access = resolve_access_from(
            grants,
            address_chain=build_address_chain(system),
            resolved_access=system.get_resolved_access(),
            inherited_tags=system.get_inherited_tags(),
        )
        return access is not None and access >= ComponentAccessLevel.VIEW

    return can_view


async def redact_workspace(
    engine: Engine,
    actor: Actor,
    user: User | None,
    workspace: Workspace,
) -> Workspace:
    """Return `workspace` with widgets the caller cannot view replaced by stubs.

    Admins receive the payload untouched. The copy skips validation, because a workspace may
    hold field combinations that predate a validator and would otherwise fail on reconstruction.
    """
    if actor.admin or user is None:
        return workspace

    can_view = await build_can_view(engine, user)
    data = redact_workspace_data(workspace.data, scope=workspace.scope, can_view=can_view)
    return construct(Workspace, **{**to_dict(workspace), "data": data})


async def require_scope_access(
    engine: Engine,
    actor: Actor,
    user: User | None,
    scope: Address,
    minimum: ComponentAccessLevel,
) -> None:
    """Raise unless the caller holds at least `minimum` access on the scope component.

    Raises:
        NotFoundError: If the scope component is missing, or the caller cannot even view it,
            hiding the workspace's existence.
        NotPermittedError: If the caller can view the scope but lacks `minimum`.
    """
    if actor.admin:
        return

    component = engine.get_component(scope)
    if component is None:
        raise NotFoundError()

    access = await get_component_access(engine, user, component)
    if access is None or access < ComponentAccessLevel.VIEW:
        raise NotFoundError()
    if access < minimum:
        raise NotPermittedError()


@router.get("/workspaces/{id:uuid}")
async def get_workspace(
    engine: CurrentEngine,
    actor: CurrentActor,
    user: RequireAuthenticated,
    id: UUID,
) -> Workspace:
    """Return a single workspace by ID.

    Global workspaces are visible to members and per general access. Scoped workspaces are
    visible to anyone with view access on their scope component.

    Raises:
        NotFoundError: If the workspace does not exist or the caller cannot view it.
    """
    workspace = assert_found(await engine.workspaces.where(id=id).first())
    if workspace.scope is not None:
        await require_scope_access(engine, actor, user, workspace.scope, ComponentAccessLevel.VIEW)
        return await redact_workspace(engine, actor, user, workspace)

    if user is not None and not actor.admin:
        if not await engine.workspaces.where(id=id, viewable_by=user.id).any():
            raise NotFoundError()

    return await redact_workspace(engine, actor, user, workspace)


async def filter_viewable_scoped(
    engine: Engine, user: User, workspaces: list[Workspace]
) -> list[Workspace]:
    """Return the subset of `workspaces` whose scope component `user` can view.

    Every workspace in `workspaces` must be scoped. A workspace whose scope component no longer
    exists is dropped, since there is nothing left to check access against.
    """
    visible: list[Workspace] = []
    for workspace in workspaces:
        assert workspace.scope is not None
        component = engine.get_component(workspace.scope)
        if component is None:
            continue

        access = await get_component_access(engine, user, component)
        if access is not None and access >= ComponentAccessLevel.VIEW:
            visible.append(workspace)

    return visible


@router.get("/workspaces")
async def get_workspaces(
    engine: CurrentEngine,
    actor: CurrentActor,
    user: RequireAuthenticated,
    filter: Annotated[WorkspaceFilter, Query(), Limit(1000)],
) -> list[Workspace]:
    """Return workspaces matching the given filter, capped at 1000 results.

    Non-admin callers see global workspaces they can view plus scoped workspaces whose scope
    component they can view.
    """
    scope = WorkspaceFilter.model_validate(filter, from_attributes=True)
    if user is None or actor.admin:
        return await engine.workspaces.where(scope)

    visible_global = await engine.workspaces.where(
        scope & WorkspaceFilter(scoped=False, viewable_by=user.id)
    )
    candidates = await engine.workspaces.where(scope & WorkspaceFilter(scoped=True))
    visible_scoped = await filter_viewable_scoped(engine, user, candidates)

    results = [*visible_global, *visible_scoped]
    return [await redact_workspace(engine, actor, user, workspace) for workspace in results]


@router.get("/users/{user_id:uuid}/workspaces", dependencies=[SELF_OR_ADMIN])
async def get_workspaces_for_user(
    engine: CurrentEngine,
    actor: CurrentActor,
    user_id: UUID,
    filter: Annotated[WorkspaceFilter, Query()],
) -> list[Workspace]:
    """Return workspaces that a specific user has joined, filtered by the given criteria.

    Non-admin callers only see joined scoped workspaces whose scope component they can still
    view. A membership alone does not guarantee visibility once a workspace gains a scope, and a
    stale membership can otherwise linger from before the workspace was scoped.
    """
    results = await engine.workspaces.where(joined_by=user_id, and__=filter)
    if not actor.admin and actor.user is not None:
        global_results = [workspace for workspace in results if workspace.scope is None]
        scoped_results = [workspace for workspace in results if workspace.scope is not None]
        visible_scoped = await filter_viewable_scoped(engine, actor.user, scoped_results)
        results = [*global_results, *visible_scoped]

    return [await redact_workspace(engine, actor, actor.user, workspace) for workspace in results]


@router.post("/workspaces")
async def create_workspace(
    engine: CurrentEngine,
    actor: CurrentActor,
    user: RequireAuthenticated,
    workspace: WorkspaceCreate,
) -> Workspace:
    """Create a new workspace.

    Creating a scoped workspace requires manage access on the scope component. Creating a
    global workspace grants the creating user a manager membership in it.

    Raises:
        NotFoundError: If the scope component is missing or invisible to the caller.
        NotPermittedError: If the caller lacks manage access on the scope.
    """
    if workspace.scope is not None:
        await require_scope_access(
            engine, actor, user, workspace.scope, ComponentAccessLevel.MANAGE
        )

    created = await engine.workspaces.create(workspace)
    if workspace.scope is None and user is not None:
        await engine.workspace_memberships.create(
            WorkspaceMembershipCreate(
                user_id=user.id,
                workspace_id=created.id,
                role=WorkspaceMembershipRole.MANAGER,
            )
        )

    return await redact_workspace(engine, actor, user, created)


@router.patch("/workspaces/{id:uuid}")
async def update_workspace(
    engine: CurrentEngine,
    actor: CurrentActor,
    user: RequireAuthenticated,
    id: UUID,
    update: WorkspaceUpdate,
) -> Workspace:
    """Partially update a workspace. Changing name, scope, or viewership/managership settings
    requires manager-level access. Other updates require editor-level access.

    Raises:
        NotFoundError: If the workspace does not exist.
        NotPermittedError: If the caller lacks permission.
    """
    workspace = assert_found(await engine.workspaces.where(id=id).first())

    new_scope = update["scope"] if "scope" in update else workspace.scope
    rescoping = new_scope != workspace.scope
    if rescoping and new_scope is not None:
        # Setting or changing the scope always requires manage access on the target component,
        # regardless of whether the workspace is currently global or scoped.
        await require_scope_access(engine, actor, user, new_scope, ComponentAccessLevel.MANAGE)

    if workspace.scope is not None:
        await require_scope_access(
            engine, actor, user, workspace.scope, ComponentAccessLevel.MANAGE
        )
        updated = assert_found(await engine.workspaces.where(id=id).update(update).first())
        if rescoping and new_scope is None and user is not None:
            # Unscoping would otherwise leave the workspace without any accessible membership.
            await engine.workspace_memberships.create(
                WorkspaceMembershipCreate(
                    user_id=user.id,
                    workspace_id=updated.id,
                    role=WorkspaceMembershipRole.MANAGER,
                )
            )

        return await redact_workspace(engine, actor, user, updated)

    if user is not None and not actor.admin:
        if not await engine.workspaces.where(id=id, viewable_by=user.id).any():
            raise NotFoundError()

        if (
            "name" in update
            or "scope" in update
            or "general_viewership" in update
            or "general_editorship" in update
            or "general_managership" in update
        ):
            # Only managers and admins can change these workspace settings.
            membership = await engine.workspace_memberships.get(user.id, id)
            if membership is None or membership.role < WorkspaceMembershipRole.MANAGER:
                raise NotPermittedError()
        elif not await engine.workspaces.where(id=id, editable_by=user.id).any():
            # Only editors of this workspace can update it.
            raise NotPermittedError()

    updated = assert_found(await engine.workspaces.where(id=id).update(update).first())
    if rescoping and new_scope is not None:
        # A scoped workspace derives access from its component and does not support memberships,
        # so a leftover membership must not be allowed to linger and leak visibility.
        await engine.workspace_memberships.where(workspace_id=id).delete()

    return await redact_workspace(engine, actor, user, updated)


@router.delete("/workspaces/{id:uuid}")
async def delete_workspace(
    engine: CurrentEngine,
    actor: CurrentActor,
    user: RequireAuthenticated,
    id: UUID,
) -> Workspace:
    """Delete a workspace by ID. Only workspace managers and admins can delete workspaces.

    Raises:
        NotFoundError: If the workspace does not exist.
        NotPermittedError: If the caller lacks permission.
    """
    workspace = assert_found(await engine.workspaces.where(id=id).first())
    if workspace.scope is not None:
        await require_scope_access(
            engine, actor, user, workspace.scope, ComponentAccessLevel.MANAGE
        )
        deleted = assert_found(await engine.workspaces.where(id=id).delete().first())
        return await redact_workspace(engine, actor, user, deleted)

    if user is not None and not actor.admin:
        if not await engine.workspaces.where(id=id, viewable_by=user.id).any():
            raise NotFoundError()
        if not await engine.workspaces.where(id=id, manageable_by=user.id).any():
            # Only workspace managers and admins can delete a workspaces.
            raise NotPermittedError()

    deleted = assert_found(await engine.workspaces.where(id=id).delete().first())
    return await redact_workspace(engine, actor, user, deleted)
