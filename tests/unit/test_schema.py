from enum import Enum
from typing import Literal
import unittest
from uuid import UUID

from bson import Binary, Int64, ObjectId  # ruff: ignore[typing-only-third-party-import]

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
    f: Literal[b"a", None, "3"] | None  # noqa: PYI061


class D(Document):
    a: list[str | int | None]
    b: list[str] | int
    c: list[Sub] | int
    d: UUID | Binary | Int64 | ObjectId


class D1(Document):
    c: list[list[list[list[list[str]]]]]


class SchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = SchemaGenerator()

    def test_primitive_types(self):
        schema = self.generator.generate(A)["$jsonSchema"]
        properties = schema["properties"]
        self.assertEqual(len(schema["required"]), 4)  # _id included

        for name, val in [
            ("a", ["int", "long"]),
            ("b", ["double"]),
            ("c", ["string"]),
            ("_id", ["objectId"]),
        ]:
            self.assertEqual(properties[name]["bsonType"], val)
        self.assertFalse(schema["additionalProperties"])

    def test_invalid_mixed(self):
        classes: list[type[Document]] = [B1, B2, B3, B4]
        for cls in classes:
            with self.subTest(model=cls.__name__), self.assertRaises(
                SchemaGenerationException,
            ):
                self.generator.generate(cls)

    def test_nullable_nested_enum_and_literal(self):
        schema = self.generator.generate(C)["$jsonSchema"]
        rq = schema["required"]
        ps = schema["properties"]
        self.assertEqual(rq, ["a", "b", "c", "d", "e", "f", "_id"])
        self.assertEqual(len(ps), 7)
        for name, val in [
            ("a", ["null", "object"]),
            ("b", ["int", "double", "long", "null", "string"]),
            ("c", ["null", "string"]),
            ("d", ["string"]),
            ("e", ["object"]),
            ("f", ["null", "binData", "string"]),
            ("_id", ["objectId"]),
        ]:
            self.assertCountEqual(ps[name]["bsonType"], val)
        self.assertEqual(ps["d"]["enum"], ["A", "B", "C"])
        self.assertCountEqual(ps["f"]["enum"], [None, "3", b"a"])
        for x in ["a", "e"]:
            self.assertEqual(len(ps[x]["required"]), 3)

    def test_arrays_and_bson_types(self):
        schema = self.generator.generate(D)["$jsonSchema"]
        self.assertEqual(len(schema["required"]), 5)
        ps = schema["properties"]
        for name, val in [
            ("a", ["array"]),
            ("b", ["long", "array", "int"]),
            ("c", ["long", "array", "int"]),
            ("d", ["long", "binData", "objectId"]),
            ("_id", ["objectId"]),
        ]:
            self.assertCountEqual(ps[name]["bsonType"], val)
        for name, val in [("b", ["string"]), ("c", ["object"])]:
            self.assertEqual(ps[name]["items"]["bsonType"], val)
        schema = self.generator.generate(D1)["$jsonSchema"]
        items = schema["properties"]["c"]["items"]["items"]
        self.assertEqual(
            items["items"]["items"]["items"]["bsonType"], ["string"],
        )


if __name__ == "__main__":
    unittest.main()
