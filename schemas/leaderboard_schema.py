from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LeaderboardRowOut(BaseModel):
    rank: int
    user_id: UUID
    username: str
    value: float


class LeaderboardSectionOut(BaseModel):
    xp: list[LeaderboardRowOut]
    equity: list[LeaderboardRowOut]
    equity_return_pct: list[LeaderboardRowOut]


class LeaderboardsOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    global_: LeaderboardSectionOut = Field(alias="global")
    friends: LeaderboardSectionOut
    generated_at: datetime
