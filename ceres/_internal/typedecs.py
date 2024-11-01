from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ceres.alert import Alert as __Alert__
    from ceres.component import Component as __Component__
    from ceres.component import ComponentSystem as __ComponentSystem__
    from ceres.database import Database as __Database__
    from ceres.engine import Engine as __Engine__
    from ceres.logs import LogEntry as __LogEntry__
    from ceres.message import Message as __Message__
    from ceres.node import Node as __Node__
    from ceres.particle import Particle as _Particle
    from ceres.reference import Reference as __Reference__
    from ceres.sieve import DynamicSieve as __DynamicSieve__
    from ceres.user import User as __User__
    from ceres.variable import Variable as __Variable__

    __Particle__ = _Particle[Any]
else:
    __Alert__ = object
    __Component__ = object
    __ComponentSystem__ = object
    __Database__ = object
    __Engine__ = object
    __LogEntry__ = object
    __Message__ = object
    __Node__ = object
    __Particle__ = object
    __Reference__ = object
    __User__ = object
    __Variable__ = object
    __DynamicSieve__ = object

__Entity__ = __Alert__ | __LogEntry__ | __Message__ | __User__ | __Variable__ | __Particle__
__Item__ = __Alert__ | __LogEntry__ | __Message__ | __Variable__ | __Particle__
__Record__ = __Alert__ | __LogEntry__ | __Message__ | __Particle__
