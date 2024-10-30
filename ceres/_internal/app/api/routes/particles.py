from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import Field
from pydantic import ValidationError as ValidationError
from starlette.exceptions import HTTPException as HTTPException

from ceres._internal.app.shared import CurrentEngine, CurrentSocket
from ceres.particle import Particle, ParticleFilter

router = APIRouter(prefix="/particles", tags=["particles"])


class GetParticlesQueryParameters(ParticleFilter):
    limit: int = Field(default=100, ge=0, le=5000)
    offset: int = Field(default=0, ge=0)


@router.get("")
async def get_particles(
    engine: CurrentEngine,
    filter: Annotated[GetParticlesQueryParameters, Query()],
) -> list[Particle]:
    return await engine.particles.get_all(filter)


class FollowParticlesQueryParameters(GetParticlesQueryParameters):
    pass


@router.websocket("")
async def follow_particles(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: Annotated[FollowParticlesQueryParameters, Query()],
) -> None:
    async for particle in engine.particles.follow(filter):
        await socket.send(particle)
