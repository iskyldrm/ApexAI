from pydantic import BaseModel

from app.enums import SettingScope


class SettingSetRequest(BaseModel):
    scope: SettingScope
    scope_id: str | None = None
    value: dict
    enforced_by_admin: bool = False


class SettingResponse(BaseModel):
    scope: str
    scope_id: str | None
    key: str
    value: dict
    enforced_by_admin: bool
    updated_by: str | None
    updated_at: datetime | None = None


from datetime import datetime