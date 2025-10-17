
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class Host(BaseModel):
    alias: str
    hostname: str
    port: int = 22
    user: str
    auth_method: Literal['password', 'key', 'agent']
    key_path: Optional[str] = None
    password: Optional[str] = None


class Session(BaseModel):
    id: str
    name: str
    windows: int
    attached: int
    created_at: datetime
