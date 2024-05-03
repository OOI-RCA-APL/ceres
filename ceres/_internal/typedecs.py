from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ceres.alert import Alert as __Alert__
    from ceres.component import Component as __Component__
    from ceres.component import ComponentSystem as __ComponentSystem__
    from ceres.database.database import Database as __Database__
    from ceres.logs import LogEntry as __LogEntry__
    from ceres.message import Message as __Message__
    from ceres.node import Node as __Node__
    from ceres.user import User as __User__
else:
    __Alert__ = object
    __Component__ = object
    __ComponentSystem__ = object
    __Database__ = object
    __LogEntry__ = object
    __Message__ = object
    __Node__ = object
    __User__ = object

__Entity__ = __Alert__ | __LogEntry__ | __Message__ | __User__
__Record__ = __Alert__ | __LogEntry__ | __Message__
__Item__ = __Alert__ | __LogEntry__ | __Message__
