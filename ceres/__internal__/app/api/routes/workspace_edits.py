from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import Query

from ceres.__internal__.app.api.routes.workspaces import build_can_view
from ceres.__internal__.app.shared import (
    SELF_OR_ADMIN,
    CurrentActor,
    CurrentEngine,
    Limit,
    Router,
    assert_found,
)
from ceres.__internal__.workspace_redaction import merge_redacted_widgets, redact_workspace_data
from ceres.data import DataObject, JSONSerializableDict, construct, to_dict
from ceres.workspace import WorkspaceEdit, WorkspaceEditCreate, WorkspaceEditFilter

if TYPE_CHECKING:
    from ceres.address import Address
    from ceres.engine import Engine

router = Router(tags=["workspace-edits"])


async def _redact_edit(
    engine: Engine,
    actor: CurrentActor,
    edit: WorkspaceEdit,
) -> WorkspaceEdit:
    """Return `edit` with widgets the acting user cannot view replaced by stubs.

    Admins receive the payload untouched.
    """
    if actor.admin or actor.user is None:
        return edit

    workspace = await engine.workspaces.where(id=edit.workspace_id).first()
    scope: Address | None = workspace.scope if workspace is not None else None

    can_view = await build_can_view(engine, actor.user)
    data = redact_workspace_data(edit.data, scope=scope, can_view=can_view)
    return construct(WorkspaceEdit, **{**to_dict(edit), "data": data})


@router.get(
    "/users/{user_id:uuid}/workspace-edits/{workspace_id:uuid}",
    dependencies=[SELF_OR_ADMIN],
)
async def get_workspace_edit(
    engine: CurrentEngine,
    actor: CurrentActor,
    user_id: UUID,
    workspace_id: UUID,
) -> WorkspaceEdit:
    """Return a single workspace edit for the given user and workspace.

    Raises:
        NotFoundError: If no matching workspace edit exists.
    """
    edit = assert_found(await engine.workspace_edits.get(user_id, workspace_id))
    return await _redact_edit(engine, actor, edit)


@router.get("/users/{user_id:uuid}/workspace-edits", dependencies=[SELF_OR_ADMIN])
async def get_workspace_edits(
    engine: CurrentEngine,
    actor: CurrentActor,
    user_id: UUID,
    filter: Annotated[WorkspaceEditFilter, Query(), Limit(1000)],
) -> list[WorkspaceEdit]:
    """Return workspace edits for the given user, filtered and capped at 1000 results."""
    results = await engine.workspace_edits.where(user_id=user_id, and__=filter)
    return [await _redact_edit(engine, actor, edit) for edit in results]


class CreateWorkspaceEditData(DataObject):
    """Request body for creating a workspace edit."""

    data: JSONSerializableDict


@router.post(
    "/users/{user_id:uuid}/workspace-edits/{workspace_id:uuid}",
    dependencies=[SELF_OR_ADMIN],
)
async def create_workspace_edit(
    engine: CurrentEngine,
    user_id: UUID,
    workspace_id: UUID,
    values: CreateWorkspaceEditData,
) -> WorkspaceEdit:
    """Create a new workspace edit for the given user and workspace."""
    return await engine.workspace_edits.create(
        WorkspaceEditCreate(
            user_id=user_id,
            workspace_id=workspace_id,
            data=values.data,
        )
    )


class AssignWorkspaceEditData(CreateWorkspaceEditData):
    """Request body for upserting a workspace edit. Identical to `CreateWorkspaceEditData`."""

    pass


@router.put(
    "/users/{user_id:uuid}/workspace-edits/{workspace_id:uuid}",
    dependencies=[SELF_OR_ADMIN],
)
async def assign_workspace_edit(
    engine: CurrentEngine,
    user_id: UUID,
    workspace_id: UUID,
    values: AssignWorkspaceEditData,
) -> WorkspaceEdit:
    """Create or replace a workspace edit for the given user and workspace via upsert.

    If an edit already exists, merge the incoming data against it first, so a redaction stub
    the caller received on a prior read can never overwrite real widget configuration already
    stored in the edit.
    """
    data = values.data
    existing = await engine.workspace_edits.get(user_id, workspace_id)
    if existing is not None:
        data = merge_redacted_widgets(existing.data, data)

    return await engine.workspace_edits.create(
        WorkspaceEditCreate(
            user_id=user_id,
            workspace_id=workspace_id,
            data=data,
        ),
        upsert=True,
    )


@router.delete(
    "/users/{user_id:uuid}/workspace-edits/{workspace_id:uuid}",
    dependencies=[SELF_OR_ADMIN],
)
async def delete_workspace_edit(
    engine: CurrentEngine,
    user_id: UUID,
    workspace_id: UUID,
) -> WorkspaceEdit:
    """Delete a workspace edit for the given user and workspace.

    Raises:
        NotFoundError: If no matching workspace edit exists.
    """
    return assert_found(
        await engine.workspace_edits.where(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        .delete()
        .first()
    )
