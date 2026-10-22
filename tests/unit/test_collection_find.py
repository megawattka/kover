from typing import TYPE_CHECKING
import unittest
from unittest.mock import AsyncMock, Mock

from typing_extensions import assert_type

from kover.collection import Collection
from kover.cursor import Cursor
from kover.database import Database
from kover.schema import Document
from kover.typings import JsonT

if TYPE_CHECKING:
    from kover.session import Transaction


class Item(Document):
    value: int


if TYPE_CHECKING:
    def check_transaction_types(
        collection: Collection,
        transaction: Transaction,
        cls: type[Item] | None,
    ) -> None:
        """Does check for certain types."""
        assert_type(collection.find(transaction=transaction), Cursor[JsonT])
        assert_type(
            collection.find(cls=Item, transaction=transaction), Cursor[Item],
        )
        assert_type(collection.find({}, Item, transaction), Cursor[Item])
        assert_type(
            collection.find(cls=cls), Cursor[Item] | Cursor[JsonT],
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
            assert_type(self.collection.find(), Cursor[JsonT]),
            assert_type(self.collection.find({}), Cursor[JsonT]),
            assert_type(self.collection.find(None), Cursor[JsonT]),
            assert_type(self.collection.find(cls=None), Cursor[JsonT]),
            assert_type(self.collection.find({}, cls=None), Cursor[JsonT]),
        )
        for cursor in cursors:
            documents = assert_type(await cursor.to_list(), list[JsonT])
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


if __name__ == "__main__":
    unittest.main()
