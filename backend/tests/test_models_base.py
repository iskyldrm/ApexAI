from datetime import datetime
from uuid import UUID

from app.models.base import BaseModel


def test_base_model_has_uuid_and_timestamps():
    class TestModel(BaseModel, table=True):
        __tablename__ = "test_base_model"
        name: str

    instance = TestModel(name="test")
    assert isinstance(instance.id, UUID)
    assert isinstance(instance.created_at, datetime)
    assert isinstance(instance.updated_at, datetime)


def test_base_model_ids_are_unique():
    class TestModel(BaseModel, table=True):
        __tablename__ = "test_base_model_unique"
        name: str

    a = TestModel(name="a")
    b = TestModel(name="b")
    assert a.id != b.id
