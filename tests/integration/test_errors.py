from kover import Update
from kover.exceptions import OperationFailure
from tests.integration.base import MongoTestCase


class ErrorIntegrationTests(MongoTestCase):
    async def test_duplicate_key_preserves_connection(self) -> None:
        collection = await self.database.create_collection("items")
        await collection.insert_one({"_id": "duplicate"})
        with self.assertRaises(OperationFailure) as caught:
            await collection.insert_one({"_id": "duplicate"})

        error = caught.exception
        assert error.code == 11000
        assert error.details["ok"] == 1
        assert error.details["writeErrors"][0]["code"] == 11000
        assert await self.database.ping()

        assert await collection.count() == 1

    async def test_unordered_insert_reports_partial_failure(self) -> None:
        collection = self.database.get_collection("items")
        with self.assertRaises(OperationFailure) as caught:
            await collection.insert_many([
                {"_id": "duplicate"},
                {"_id": "duplicate"},
                {"_id": "after"},
            ], ordered=False)

        assert caught.exception.code == 11000
        assert caught.exception.details["n"] == 2
        assert caught.exception.details["writeErrors"][0]["index"] == 1
        assert await collection.find_one({"_id": "after"}) is not None

    async def test_validation_update_and_explicit_bypass(self) -> None:
        collection = await self.database.create_collection("items", params={
            "validator": {"$jsonSchema": {
                "bsonType": "object",
                "required": ["value"],
                "properties": {"value": {"bsonType": "int"}},
            }},
            "validationLevel": "strict",
            "validationAction": "error",
        })
        identifier = await collection.insert_one({"value": 1})
        with self.assertRaises(OperationFailure) as caught:
            await collection.update(Update(
                {"_id": identifier}, {"$set": {"value": "invalid"}},
            ))

        assert caught.exception.code == 121
        assert caught.exception.err_info is not None
        stored = await collection.find_one({"_id": identifier})
        assert stored is not None
        assert stored["value"] == 1
        bypassed = await collection.insert_one(
            {"value": "invalid"}, bypass_document_validation=True,
        )
        assert await collection.find_one({"_id": bypassed}) is not None

    async def test_command_error_preserves_connection(self) -> None:
        assert await self.database.ping()
        with self.assertRaises(OperationFailure) as caught:
            await self.database.command({"koverUnknownCommand": 1})

        assert caught.exception.code == 59
        assert caught.exception.code_name == "CommandNotFound"
        assert caught.exception.details["ok"] == 0
        assert await self.database.ping()

    async def test_write_concern_error_is_not_silenced(self) -> None:
        hello = await self.client.command({"hello": 1})
        if not hello.get("setName"):
            self.skipTest("This write concern test requires a replica set")
        collection = await self.database.create_collection("items")
        member_count = sum(
            len(hello.get(key, []))
            for key in ("hosts", "passives", "arbiters")
        )
        with self.assertRaises(OperationFailure) as caught:
            await self.database.command({
                "insert": collection.name,
                "documents": [{"_id": "written"}],
                "writeConcern": {"w": member_count + 1, "wtimeout": 100},
            })

        error = caught.exception
        assert error.details["ok"] == 1
        concern_error = error.details["writeConcernError"]
        assert error.code == concern_error["code"]
        assert error.err_info == concern_error.get("errInfo")
        assert await collection.find_one({"_id": "written"}) is not None
