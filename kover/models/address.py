"""Address model source file."""

from pydantic import BaseModel, ConfigDict, Field


class Address(BaseModel):
    """MongoDB server hostname and TCP port."""

    model_config = ConfigDict(frozen=True)

    host: str = Field(min_length=1)
    port: int = Field(default=27017, ge=1, le=65535)
