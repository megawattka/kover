from enum import Enum
from typing import Literal
import unittest
from uuid import UUID

from kover.bson import Binary, Int64, ObjectId
from kover.exceptions import SchemaGenerationException
from kover.schema import Document, SchemaGenerator


class Sub(Document):
    name: str
    age: int
    balance: float


class TEnum(Enum):
    A = "A"
    B = "B"
    C = "C"


class A(Document):
    a: int
    b: float
    c: str


class B1(Document):
    a: Literal["12", "34"] | int


class B2(Document):
    a: TEnum | float


class B3(Document):
    a: Sub | int | str


class B4(Document):
    a: list[Sub] | list[int]


class C(Document):
    a: Sub | None
    b: str | int | float | None
    c: TEnum | None
    d: TEnum
    e: Sub
    f: Literal[b"a", "3"] | None


class D(Document):
    a: list[str | int | None]
    b: list[str] | int
    c: list[Sub] | int
    d: UUID | Binary | Int64 | ObjectId


class D1(Document):
    c: list[list[list[list[list[str]]]]]


class SchemaTests(unittest.IsolatedAsyncioTestCase):
    def __init__(self, *args: str, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.generator = SchemaGenerator()

    async def test_A(self) -> None:
        schema = self.generator.generate(A)["$jsonSchema"]
        properties = schema["properties"]
        assert len(schema["required"]) == 4  # _id included

        for name, val in [
            ("a", ["int", "long"]),
            ("b", ["double"]),
            ("c", ["string"]),
            ("_id", ["objectId"]),
        ]:
            assert properties[name]["bsonType"] == val
        assert not schema["additionalProperties"]

    async def test_invalid_mixed(self) -> None:
        classes: list[type[Document]] = [B1, B2, B3, B4]
        for cls in classes:
            with self.assertRaises(SchemaGenerationException):
                self.generator.generate(cls)

    async def test_C(self) -> None:
        schema = self.generator.generate(C)["$jsonSchema"]
        rq = schema["required"]
        ps = schema["properties"]
        assert len(rq) == 7
        assert "".join(rq) == "abcdef_id"
        assert len(ps.keys()) == 7
        for name, val in [
            ("a", ["null", "object"]),
            ("b", ["int", "double", "long", "null", "string"]),
            ("c", ["null", "string"]),
            ("d", ["string"]),
            ("e", ["object"]),
            ("f", ["null", "binData", "string"]),
            ("_id", ["objectId"]),
        ]:
            assert sorted(ps[name]["bsonType"]) == sorted(val)
        assert ps["d"]["enum"] == ["A", "B", "C"]
        assert all(x in {None, "3", b"a"} for x in ps["f"]["enum"])
        assert len(ps["f"]["enum"]) == 3
        for x in ["a", "e"]:
            assert len(ps[x]["required"]) == 3

    async def test_D(self) -> None:
        schema = self.generator.generate(D)["$jsonSchema"]
        assert len(schema["required"]) == 5
        ps = schema["properties"]
        for name1, val1 in [
            ("a", ["array"]),
            ("b", ["long", "array", "int"]),
            ("c", ["long", "array", "int"]),
            ("d", ["long", "binData", "objectId"]),
            ("_id", ["objectId"]),
        ]:
            assert sorted(ps[name1]["bsonType"]) == sorted(val1)
            for name2, val2 in [("b", ["string"]), ("c", ["object"])]:
                assert ps[name2]["items"]["bsonType"] == val2
        schema = self.generator.generate(D1)["$jsonSchema"]
        items = schema["properties"]["c"]["items"]["items"]
        assert items["items"]["items"]["items"]["bsonType"][0] == "string"


if __name__ == "__main__":
    unittest.main()
