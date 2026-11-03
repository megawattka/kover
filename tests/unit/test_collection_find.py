from typing import TYPE_CHECKING, assert_type
import unittest
from unittest.mock import AsyncMock, Mock

from kover.collection import Collection
from kover.cursor import Cursor
from kover.database import Database
from kover.schema.document import Document
from kover.typings import DictT

if TYPE_CHECKING:
    from kover.session import Session


class Item(Document):
    value: int


if TYPE_CHECKING:
    def check_session_types(
        collection: Collection,
        session: Session,
        cls: type[Item],
    ) -> None:
        """Does check for certain types."""
        assert_type(collection.find(session=session), Cursor[DictT])
        assert_type(
            collection.find(cls=Item, session=session), Cursor[Item],
        )
        assert_type(collection.find({}, Item, session), Cursor[Item])
        assert_type(
            collection.find(cls=cls), Cursor[Item],
        )


class CollectionFindTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.command = AsyncMock(return_value={
            "cursor": {"id": 0, "firstBatch": [{"value": 1}]},
        })
        database = Database("test", Mock())
        database.command = self.command
        self.collection = Collection("items", database)

    async def test_find_without_model_returns_documents(self) -> None:
        cursors = (
            assert_type(self.collection.find(), Cursor[DictT]),
            assert_type(self.collection.find({}), Cursor[DictT]),
            assert_type(self.collection.find(None), Cursor[DictT]),
            assert_type(self.collection.find(cls=None), Cursor[DictT]),
            assert_type(self.collection.find({}, cls=None), Cursor[DictT]),
        )
        for cursor in cursors:
            documents = assert_type(await cursor.to_list(), list[DictT])
            assert documents == [{"value": 1}]

    async def test_find_with_model_returns_items(self) -> None:
        cursors = (
            assert_type(self.collection.find(cls=Item), Cursor[Item]),
            assert_type(self.collection.find({}, cls=Item), Cursor[Item]),
            assert_type(self.collection.find(None, cls=Item), Cursor[Item]),
            assert_type(self.collection.find(
                filter_={}, cls=Item), Cursor[Item],
            ),
            assert_type(self.collection.find({}, Item), Cursor[Item]),
        )
        for cursor in cursors:
            items = assert_type(await cursor.to_list(), list[Item])
            assert len(items) == 1
            assert isinstance(items[0], Item)
            assert items[0].value == 1
