# Documents and serialization

`Document` is a Pydantic v2 `BaseModel` with MongoDB schema generation. It
forbids extra fields, stores enum values, and serializes using field aliases
by default. Use the standard Pydantic `model_validate()` and `model_dump()`
APIs for reading and writing documents.

## Fields, aliases, and IDs

```python
from bson import ObjectId
from pydantic import Field

from kover import Document


class User(Document):
    name: str
    display_name: str = Field(alias="displayName")


user = User(name="alice", displayName="Alice")
assert user.object_id is None
assert user.model_dump() == {"name": "alice", "displayName": "Alice"}

identifier = ObjectId()
stored = User.model_validate({"_id": identifier, **user.model_dump()})
assert stored.object_id == identifier
assert stored.model_dump()["_id"] == identifier
assert User.model_validate(stored.model_dump()) == stored

stored.object_id = ObjectId()
without_id = stored.model_dump(exclude={"object_id"})
assert "_id" not in without_id
```

MongoDB's `_id` is the alias of the regular `object_id` field, not a private
attribute. Its type accepts `ObjectId` or `None`, and its default is `None`.
Construct or validate MongoDB payloads using the `_id` key; access or assign
the value in Python as `document.object_id`.

An unset ID is omitted automatically, including in nested documents. Other
nullable fields are not automatically omitted: use Pydantic's `exclude_none`
or field-specific `exclude_if` rules when appropriate. Field names are not
automatically converted to camelCase; declare aliases explicitly.

`include` and `exclude` use Python field names, so excluding the ID requires
`exclude={"object_id"}`, not `exclude={"_id"}`. Passing `by_alias=False` uses
Python names in the output; that output is not the default MongoDB wire shape.

## Collection reads and writes

The following example assumes a connected `client` and the `User` model above:

```python
users = client.demo.users
user = User(name="alice", displayName="Alice")
identifier = await users.insert_one(user)
assert user.object_id is None

# Inserts return IDs without mutating the input model.
user.object_id = identifier

loaded = await users.find_one({"_id": identifier}, cls=User)
assert loaded is not None
assert loaded.object_id == identifier

async with users.find({}, cls=User) as cursor:
    async for item in cursor:
        print(item.object_id, item.name)
```

Insert helpers accept either a `Document` or its `model_dump()` result.
With `cls=User`, collection reads call `User.model_validate()`; without `cls`,
they return dictionaries. A projection that omits `_id` leaves `object_id`
as `None`, but all other required model fields must still be present.

## BSON versus JSON

Use `model_dump()` (Python mode) for MongoDB writes. It preserves native BSON
values such as `ObjectId` and `Decimal128`, and leaves UUIDs as UUID objects.
`model_dump(mode="json")` and `model_dump_json()` are for JSON output, not BSON
encoding. UUIDs require an explicit BSON representation, and Python `Decimal`
values require a codec or explicit conversion. See the
[README's BSON guidance](../README.md#typed-documents-and-bson).

## MongoDB validation

```python
validator = User.model_mongodb_schema()
schema = validator["$jsonSchema"]
assert schema["properties"]["_id"] == {"bsonType": "objectId"}
assert "_id" in schema["required"]
```

Apply the validator with `await users.set_validator(validator)`. The root `_id`
is required in stored documents. `None` is an application-side placeholder for
an unset ID: it is excluded from dumps and, through `SkipJsonSchema[None]`,
does not produce a `null` branch in the ID schema. Other nullable fields retain
their nullable schemas.

Nested `Document` subclasses inherit the same ID field, but it is optional in
their MongoDB schemas. An unset nested ID is omitted from serialization. Use a
plain Pydantic `BaseModel` for embedded models that should not declare an ID
field at all. The generator does not inject IDs into plain nested models.

Schema generation does not change Python validation or apply defaults on the
server. Unsupported constraints raise `SchemaGenerationException`. See the
[schema validation overview](../README.md#mongodb-schema-validation) and the
[runnable schema example](../examples/schema.py).