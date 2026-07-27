from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import Query

from ceres.__internal__.app.shared import (
    Actor,
    CurrentActor,
    CurrentEngine,
    Limit,
    RequireAuthenticated,
    Router,
    assert_found,
    build_address_chain,
    get_component_access,
    get_components_access,
    get_engine_access,
)
from ceres.__internal__.workspace_redaction import merge_redacted_widgets, redact_workspace_data
from ceres.access import fetch_access_grants, resolve_access_from
from ceres.address import Address
from ceres.config import ComponentAccessLevel
from ceres.data import construct, to_dict
from ceres.error import NotFoundError, NotPermittedError
from ceres.workspace import (
    Workspace,
    WorkspaceCreate,
    WorkspaceFilter,
    WorkspaceUpdate,
)

if TYPE_CHECKING:
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


async def resolve_placement_level(
    engine: Engine, actor: Actor, user: User | None, scope: Address
) -> ComponentAccessLevel | None:
    """Resolve the caller's access on a workspace's placement.

    A workspace is placed on the engine root or on a component, and each resolves its access a
    different way. Everything else about a workspace's permissions follows from this one answer.

    Returns:
        The effective level, or `None` where the caller has no access or the placement component
        no longer exists.
    """
    if actor.admin:
        return ComponentAccessLevel.MANAGE

    if scope.is_engine:
        return await get_engine_access(engine, user)

    component = engine.get_component(scope)
    if component is None:
        return None

    return await get_component_access(engine, user, component)


async def resolve_placement_levels(
    engine: Engine, actor: Actor, user: User | None, scopes: Iterable[Address]
) -> dict[Address, ComponentAccessLevel | None]:
    """Resolve the caller's access on each distinct placement in `scopes`, reading grants once.

    Resolving one placement at a time re-reads the caller's grants for every one of them, which
    costs a handful of queries per workspace on a listing. Listings resolve their placements
    through here so the grants are read once for the whole response.
    """
    distinct = set(scopes)
    if actor.admin:
        return {scope: ComponentAccessLevel.MANAGE for scope in distinct}

    levels: dict[Address, ComponentAccessLevel | None] = {}
    components = []
    for scope in distinct:
        if scope.is_engine:
            levels[scope] = await get_engine_access(engine, user)
            continue

        component = engine.get_component(scope)
        if component is None:
            levels[scope] = None
        else:
            components.append(component)

    levels.update(await get_components_access(engine, user, components))
    return levels


async def require_placement_access(
    engine: Engine,
    actor: Actor,
    user: User | None,
    scope: Address,
    minimum: ComponentAccessLevel,
) -> None:
    """Raise unless the caller holds at least `minimum` access on a workspace's placement.

    Raises:
        NotFoundError: If the placement is missing, or the caller cannot even view it, which
            hides the workspace's existence.
        NotPermittedError: If the caller can view the placement but lacks `minimum`.
    """
    access = await resolve_placement_level(engine, actor, user, scope)
    if access is None or access < ComponentAccessLevel.VIEW:
        raise NotFoundError()
    if access < minimum:
        raise NotPermittedError()


async def require_engine_manage(engine: Engine, actor: Actor, user: User | None) -> None:
    """Raise unless the caller may manage the engine root.

    The logged-out marker decides what an anonymous visitor sees, which is an engine-wide question
    however the workspace carrying it is placed.

    Raises:
        NotPermittedError: If the caller lacks manage on the engine root.
    """
    await require_placement_access(engine, actor, user, Address.ENGINE, ComponentAccessLevel.MANAGE)


def is_visible(user: User | None, workspace: Workspace, level: ComponentAccessLevel | None) -> bool:
    """Whether the caller may see `workspace`, given their resolved access on its placement.

    A private workspace belongs to exactly one user, and administrators do not bypass that. The
    owner must still hold view access on the placement, so losing access to a component also
    removes the private workspaces placed on it.
    """
    if workspace.owner_id is not None and (user is None or workspace.owner_id != user.id):
        return False

    return level is not None and level >= ComponentAccessLevel.VIEW


async def require_visible(
    engine: Engine,
    actor: Actor,
    user: User | None,
    workspace: Workspace,
) -> None:
    """Raise unless the caller may see `workspace` at all, per `is_visible`.

    Raises:
        NotFoundError: If the workspace is private to somebody else, or its placement is not
            viewable by the caller.
    """
    level = await resolve_placement_level(engine, actor, user, workspace.scope)
    if not is_visible(user, workspace, level):
        raise NotFoundError()


async def require_writable(
    engine: Engine,
    actor: Actor,
    user: User | None,
    workspace: Workspace,
) -> None:
    """Raise unless the caller may edit and manage `workspace`.

    An owner has full rights over their own private workspace, whatever their access on the
    placement, since nobody else can see it. A shared workspace requires manage on its placement.

    Raises:
        NotFoundError: If the workspace is not visible to the caller.
        NotPermittedError: If it is visible but not writable.
    """
    await require_visible(engine, actor, user, workspace)
    if workspace.owner_id is not None:
        return

    await require_placement_access(
        engine, actor, user, workspace.scope, ComponentAccessLevel.MANAGE
    )


@router.get("/workspaces/{id:uuid}")
async def get_workspace(
    engine: CurrentEngine,
    actor: CurrentActor,
    user: RequireAuthenticated,
    id: UUID,
) -> Workspace:
    """Return a single workspace by ID.

    A workspace is visible when the caller can view its placement, and, for a private workspace,
    only to its owner.

    Raises:
        NotFoundError: If the workspace does not exist or the caller cannot view it.
    """
    workspace = assert_found(await engine.workspaces.where(id=id).first())
    await require_visible(engine, actor, user, workspace)
    return await redact_workspace(engine, actor, user, workspace)


async def filter_visible(
    engine: Engine, actor: Actor, user: User | None, workspaces: list[Workspace]
) -> list[Workspace]:
    """Return the subset of `workspaces` the caller may see.

    A workspace whose placement component no longer exists is dropped, since there is nothing
    left to check access against.
    """
    levels = await resolve_placement_levels(
        engine, actor, user, (workspace.scope for workspace in workspaces)
    )
    return [
        workspace
        for workspace in workspaces
        if is_visible(user, workspace, levels.get(workspace.scope))
    ]


@router.get("/workspaces")
async def get_workspaces(
    engine: CurrentEngine,
    actor: CurrentActor,
    user: RequireAuthenticated,
    filter: Annotated[WorkspaceFilter, Query(), Limit(1000)],
) -> list[Workspace]:
    """Return workspaces matching the given filter, capped at 1000 results.

    Callers see the workspaces whose placement they can view, plus the private ones they own.
    Administrators do not see other users' private workspaces.
    """
    scope = WorkspaceFilter.model_validate(filter, from_attributes=True)
    candidates = await engine.workspaces.where(scope)
    visible = await filter_visible(engine, actor, user, candidates)
    return [await redact_workspace(engine, actor, user, workspace) for workspace in visible]


@router.post("/workspaces")
async def create_workspace(
    engine: CurrentEngine,
    actor: CurrentActor,
    user: RequireAuthenticated,
    workspace: WorkspaceCreate,
) -> Workspace:
    """Create a new workspace.

    A private workspace needs only view access on its placement, since nobody else will see it. A
    shared one needs manage, because it appears for everybody who can see that placement.

    Raises:
        NotFoundError: If the placement is missing or invisible to the caller.
        NotPermittedError: If the caller lacks the access their choice of workspace requires, or
            tries to create a workspace owned by somebody else.
    """
    minimum = (
        ComponentAccessLevel.VIEW if workspace.owner_id is not None else ComponentAccessLevel.MANAGE
    )
    await require_placement_access(engine, actor, user, workspace.scope, minimum)

    if workspace.owner_id is not None and user is not None and workspace.owner_id != user.id:
        # A caller may only claim ownership for themselves.
        raise NotPermittedError()

    if workspace.show_when_logged_out:
        await require_engine_manage(engine, actor, user)

    created = await engine.workspaces.create(workspace)
    return await redact_workspace(engine, actor, user, created)


@router.patch("/workspaces/{id:uuid}")
async def update_workspace(
    engine: CurrentEngine,
    actor: CurrentActor,
    user: RequireAuthenticated,
    id: UUID,
    update: WorkspaceUpdate,
) -> Workspace:
    """Partially update a workspace.

    Ownership only ever moves one way, from an owner to nobody, which is what publishing a
    private workspace means. Taking a shared workspace private would remove a tab other people
    may have open and hold working copies against, so it is refused.

    Writing a workspace is not enough to change what a logged-out visitor sees, so the logged-out
    marker takes manage on the engine root on top of whatever the workspace itself requires.

    Raises:
        NotFoundError: If the workspace does not exist or is not visible to the caller.
        NotPermittedError: If the caller lacks permission for the change they asked for.
    """
    workspace = assert_found(await engine.workspaces.where(id=id).first())

    if "data" in update:
        # Never trust the client's copy of a restricted stub. Merge it against the stored data
        # so a stub can never overwrite a widget's real configuration.
        update["data"] = merge_redacted_widgets(workspace.data, update["data"])

    await require_writable(engine, actor, user, workspace)

    if "owner_id" in update and update["owner_id"] != workspace.owner_id:
        if workspace.owner_id is None or update["owner_id"] is not None:
            raise NotPermittedError()

        await require_placement_access(
            engine, actor, user, workspace.scope, ComponentAccessLevel.MANAGE
        )

    if (
        "show_when_logged_out" in update
        and update["show_when_logged_out"] != workspace.show_when_logged_out
    ):
        await require_engine_manage(engine, actor, user)

    if "scope" in update and update["scope"] != workspace.scope:
        # Moving a workspace requires manage on where it is going, not just where it came from.
        await require_placement_access(
            engine, actor, user, update["scope"], ComponentAccessLevel.MANAGE
        )

    updated = assert_found(await engine.workspaces.where(id=id).update(update).first())
    return await redact_workspace(engine, actor, user, updated)


@router.delete("/workspaces/{id:uuid}")
async def delete_workspace(
    engine: CurrentEngine,
    actor: CurrentActor,
    user: RequireAuthenticated,
    id: UUID,
) -> Workspace:
    """Delete a workspace by ID.

    An owner may delete their own private workspace. Deleting a shared one requires manage access
    on its placement.

    Raises:
        NotFoundError: If the workspace does not exist or is not visible to the caller.
        NotPermittedError: If the caller lacks permission.
    """
    workspace = assert_found(await engine.workspaces.where(id=id).first())
    await require_writable(engine, actor, user, workspace)
    deleted = assert_found(await engine.workspaces.where(id=id).delete().first())
    return await redact_workspace(engine, actor, user, deleted)
