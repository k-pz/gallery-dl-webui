from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

from backend.dependencies import DbDep
from backend.targets import service
from backend.targets.exceptions import TargetNotFound
from backend.targets.models import Target

if TYPE_CHECKING:
    from backend.targets.poller import Poller


def get_poller(request: Request) -> Poller:
    return request.app.state.poller


async def valid_target_id(target_id: int, db: DbDep) -> Target:
    target = await service.get(db, target_id)
    if target is None:
        raise TargetNotFound()
    return target


PollerDep = Annotated["Poller", Depends(get_poller)]
TargetDep = Annotated[Target, Depends(valid_target_id)]
