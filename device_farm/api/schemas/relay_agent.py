from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class RelayAgentOut(BaseModel):
    relay_id:          str
    hostname:          str
    ip:                str
    version:           str
    serials:           list[str]
    status:            str
    connected_at:      datetime
    last_heartbeat_at: Optional[datetime] = None
    disconnected_at:   Optional[datetime] = None

    class Config:
        from_attributes = True


class RelayCommandOut(BaseModel):
    ok:        bool
    output:    str = ""
    exit_code: int = -1
    error:     str = ""


class BootstrapAllResult(BaseModel):
    relay_id: str
    total:    int
    ok:       int
    failed:   int
    results:  list[dict]
