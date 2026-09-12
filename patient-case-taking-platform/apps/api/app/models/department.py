from uuid import UUID

from app.models.base import BaseRecord


class Department(BaseRecord):
    __tablename__ = "department"
    facility_id: UUID
    name: str
    is_active: bool = True
