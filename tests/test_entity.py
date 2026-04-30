import pytest

from ceres.alert import Alert
from ceres.entity import EntityType
from ceres.logs import LogEntry
from ceres.message import Message
from ceres.particle import Particle
from ceres.setting import Setting
from ceres.user import User
from ceres.variable import Variable
from ceres.workspace import Workspace, WorkspaceEdit, WorkspaceMembership


def test_entity_type_member_count():
    assert len(EntityType) == 10


def test_entity_type_string_values():
    assert EntityType.MESSAGE == "message"
    assert EntityType.PARTICLE == "particle"
    assert EntityType.ALERT == "alert"
    assert EntityType.LOG_ENTRY == "log-entry"
    assert EntityType.USER == "user"
    assert EntityType.VARIABLE == "variable"
    assert EntityType.SETTING == "setting"
    assert EntityType.WORKSPACE == "workspace"
    assert EntityType.WORKSPACE_MEMBERSHIP == "workspace-membership"
    assert EntityType.WORKSPACE_EDIT == "workspace-edit"


EXPECTED_CLASSES: dict[EntityType, type] = {
    EntityType.MESSAGE: Message,
    EntityType.PARTICLE: Particle,
    EntityType.ALERT: Alert,
    EntityType.LOG_ENTRY: LogEntry,
    EntityType.USER: User,
    EntityType.VARIABLE: Variable,
    EntityType.SETTING: Setting,
    EntityType.WORKSPACE: Workspace,
    EntityType.WORKSPACE_MEMBERSHIP: WorkspaceMembership,
    EntityType.WORKSPACE_EDIT: WorkspaceEdit,
}


@pytest.mark.parametrize("entity_type", EntityType)
def test_cls_returns_correct_class(entity_type: EntityType):
    assert entity_type.cls is EXPECTED_CLASSES[entity_type]


@pytest.mark.parametrize("entity_type", EntityType)
def test_from_class_round_trips_with_cls(entity_type: EntityType):
    assert EntityType.from_class(entity_type.cls) is entity_type


def test_from_class_raises_for_unknown_class():
    with pytest.raises(ValueError, match="Unknown entity type"):
        EntityType.from_class(int)  # type: ignore[arg-type]


EXPECTED_ALIASES: dict[str, EntityType] = {
    "messages": EntityType.MESSAGE,
    "particles": EntityType.PARTICLE,
    "alerts": EntityType.ALERT,
    "log-entries": EntityType.LOG_ENTRY,
    "logs": EntityType.LOG_ENTRY,
    "users": EntityType.USER,
    "variables": EntityType.VARIABLE,
    "settings": EntityType.SETTING,
    "workspaces": EntityType.WORKSPACE,
    "workspace-memberships": EntityType.WORKSPACE_MEMBERSHIP,
    "workspace-edits": EntityType.WORKSPACE_EDIT,
}


@pytest.mark.parametrize("alias,expected", EXPECTED_ALIASES.items())
def test_alias_resolves_to_correct_member(alias: str, expected: EntityType):
    assert EntityType(alias) is expected


def test_passthrough_existing_member():
    assert EntityType(EntityType.MESSAGE) is EntityType.MESSAGE
