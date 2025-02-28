__import__("sys").path.append(
    str(__import__("pathlib").Path(__file__).parent.parent))

import unittest  # noqa: E402
from uuid import UUID  # noqa: E402
from typing import Literal, Union, List, Optional  # noqa: E402
from enum import Enum  # noqa: E402

from bson import ObjectId, Binary, Int64  # noqa: E402

from kover.schema import SchemaGenerator, Document  # noqa: E402
from kover.exceptions import SchemaGenerationException  # noqa: E402
from kover.typings import xJsonT  # type: ignore # noqa: E402, F401


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
    a: Union[Literal["12", "34"], int]


class B2(Document):
    a: Union[TEnum, float]


class B3(Document):
    a: Union[Sub, int, str]


class B4(Document):
    a: Union[List[Sub], List[int]]


class C(Document):
    a: Optional[Sub]
    b: Optional[Union[str, int, float]]
    c: Optional[TEnum]
    d: TEnum
    e: Sub
    f: Optional[Literal[b"a", None, "3"]]


class D(Document):
    a: List[Optional[Union[str, int]]]
    b: Union[List[str], int]
    c: Union[List[Sub], int]
    d: Union[UUID, Binary, Int64, ObjectId]


class D1(Document):
    c: List[List[List[List[List[str]]]]]


class SchemaTests(unittest.IsolatedAsyncioTestCase):
    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        self.generator = SchemaGenerator()

    async def test_A(self):
        schema = self.generator.generate(A)["$jsonSchema"]
        properties = schema["properties"]
        assert len(schema["required"]) == 4  # _id included

        for name, val in [
            ("a", ["int", "long"]),
            ("b", ["double"]),
            ("c", ["string"]),
            ("_id", ['objectId'])
        ]:
            assert properties[name]["bsonType"] == val
        assert not schema["additionalProperties"]

    async def test_invalid_mixed(self):
        classes: List[type[Document]] = [B1, B2, B3, B4]
        for cls in classes:
            with self.assertRaises(SchemaGenerationException):
                self.generator.generate(cls)

    async def test_C(self):
        schema = self.generator.generate(C)['$jsonSchema']
        rq = schema["required"]
        ps = schema["properties"]
        assert len(rq) == 7 and "".join(rq) == "abcdef_id"
        assert len(ps.keys()) == 7
        for name, val in [
            ("a", ['null', 'object']),
            ("b", ['int', 'double', 'long', 'null', 'string']),
            ("c", ['null', 'string']),
            ("d", ['string']),
            ("e", ['object']),
            ("f", ['null', 'binData', 'string']),
            ("_id", ['objectId'])
        ]:
            assert sorted(ps[name]["bsonType"]) == sorted(val)
        assert ps["d"]["enum"] == ['A', 'B', 'C']
        assert all(x in [None, '3', b'a'] for x in ps["f"]["enum"])
        assert len(ps["f"]["enum"]) == 3
        for x in ["a", "e"]:
            assert len(ps[x]["required"]) == 3

    async def test_D(self):
        schema = self.generator.generate(D)['$jsonSchema']
        assert len(schema["required"]) == 5
        ps = schema["properties"]
        for name, val in [
            ("a", ['array']),
            ("b", ['long', 'array', 'int']),
            ("c", ['long', 'array', 'int']),
            ("d", ['long', 'binData', 'objectId']),
            ("_id", ['objectId'])
        ]:
            assert sorted(ps[name]["bsonType"]) == sorted(val)
            for name, val in [("b", ['string']), ("c", ['object'])]:
                assert ps[name]["items"]["bsonType"] == val
        schema = self.generator.generate(D1)["$jsonSchema"]
        items = schema["properties"]["c"]["items"]["items"]
        assert items["items"]["items"]["items"]["bsonType"][0] == "string"


if __name__ == "__main__":
    unittest.main()
