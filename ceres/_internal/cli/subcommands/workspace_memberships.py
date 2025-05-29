from __future__ import annotations

from ceres._internal.cli.shared import create_entity_command
from ceres.workspace import WorkspaceMembership

WorkspaceMembershipsCommand = create_entity_command(WorkspaceMembership)
