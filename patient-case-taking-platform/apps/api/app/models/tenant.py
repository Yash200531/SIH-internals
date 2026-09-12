
from pydantic import Field

from app.models.base import BaseRecord


class Tenant(BaseRecord):
    __tablename__ = "tenant"
    name: str
    slug: str
    is_active: bool = True
    settings: dict = Field(default_factory=dict)
