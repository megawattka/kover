"""Pure, schema-aware transformations from JSON Schema to MongoDB's dialect."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any, cast

from kover.exceptions import SchemaGenerationException

type Schema = dict[str, Any]
type Transform = Callable[[Schema, str], Schema]

_MAPS = {"properties", "patternProperties"}
_ARRAYS = {"allOf", "anyOf", "oneOf", "prefixItems"}
_SINGLES = {"additionalProperties", "additionalItems", "not", "items"}
_KEYWORDS = {
    "bsonType",
    "title",
    "description",
    "enum",
    "multipleOf",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minProperties",
    "maxProperties",
    "required",
    "dependencies",
    *_MAPS,
    *(_ARRAYS - {"prefixItems"}),
    *_SINGLES,
}
_BSON_TYPES = {
    "double",
    "string",
    "object",
    "array",
    "binData",
    "undefined",
    "objectId",
    "bool",
    "date",
    "null",
    "regex",
    "dbPointer",
    "javascript",
    "symbol",
    "javascriptWithScope",
    "int",
    "timestamp",
    "long",
    "decimal",
    "minKey",
    "maxKey",
    "number",
}


def _walk(node: Schema, path: str, transform: Transform) -> Schema:
    """Visit only schema positions: enum/default/property names are data.

    Returns:
        An independent schema with transformed schema children.
    """
    result: Schema = {}
    for key, value in node.items():
        child_path = f"{path}/{key}"
        if key in _MAPS:
            result[key] = {
                name: transform(child, f"{child_path}/{name}")
                for name, child in value.items()
            }
        elif key in _ARRAYS or (key == "items" and isinstance(value, list)):
            result[key] = [
                transform(child, f"{child_path}/{index}")
                for index, child in enumerate(cast("list[Schema]", value))
            ]
        elif key in _SINGLES and isinstance(value, dict):
            result[key] = transform(cast("Schema", value), child_path)
        elif key == "dependencies":
            result[key] = {
                name: transform(cast("Schema", child), f"{child_path}/{name}")
                if isinstance(child, dict)
                else deepcopy(child)
                for name, child in value.items()
            }
        else:
            result[key] = deepcopy(value)
    return result


def resolve_refs(schema: Schema) -> Schema:
    """Expand local refs independently, rejecting cycles and external refs.

    Returns:
        An independent schema with no references or definitions.
    """

    def resolve(
        node: Schema,
        path: str,
        active: tuple[str, ...] = (),
    ) -> Schema:
        reference = node.get("$ref")
        if reference is not None:
            if reference in active:
                raise SchemaGenerationException(
                    f"{path}: recursive $ref {reference!r} is unsupported.",
                )
            if not reference.startswith("#/"):
                raise SchemaGenerationException(
                    f"{path}: external $ref {reference!r} is unsupported.",
                )
            target = schema
            try:
                for part in reference[2:].split("/"):
                    target = target[part.replace("~1", "/").replace("~0", "~")]
            except (KeyError, TypeError) as error:
                raise SchemaGenerationException(
                    f"{path}: unresolved $ref {reference!r}.",
                ) from error
            resolved = resolve(target, path, (*active, reference))
            siblings = resolve(
                {key: value for key, value in node.items() if key != "$ref"},
                path,
                active,
            )
            # Sibling constraints are a conjunction, not an overriding update.
            return {"allOf": [resolved, siblings]} if siblings else resolved
        return _walk(
            {
                key: value
                for key, value in node.items()
                if key not in {"$defs", "definitions"}
            },
            path,
            lambda child, child_path: resolve(child, child_path, active),
        )

    return resolve(schema, "$")


def normalize_schema(schema: Schema) -> Schema:
    """Translate const, tuple prefixes and numeric exclusive bounds exactly.

    ``default`` is a non-validation annotation, not a lost constraint. MongoDB
    neither applies nor accepts it. All other unknown keywords remain present
    for the compatibility stage to reject.

    Returns:
        An independent normalized schema.
    """

    def normalize(node: Schema, path: str) -> Schema:
        result: Schema = _walk(node, path, normalize)
        result = {
            key: value for key, value in result.items() if key != "default"
        }
        if "const" in result:
            literal = {"enum": [result["const"]]}
            result = {
                key: value for key, value in result.items() if key != "const"
            }
            if "enum" in result:
                result = {"allOf": [result, literal]}
            else:
                result = {**result, **literal}
        if "prefixItems" in result:
            prefix = result["prefixItems"]
            tail = result.get("items", True)
            result = {
                key: value
                for key, value in result.items()
                if key not in {"prefixItems", "items"}
            }
            result = {**result, "items": prefix, "additionalItems": tail}
        for exclusive, inclusive in (
            ("exclusiveMinimum", "minimum"),
            ("exclusiveMaximum", "maximum"),
        ):
            bound = result.get(exclusive)
            if bound is not None and not isinstance(bound, bool):
                previous = result.get(inclusive)
                stricter = previous is not None and (
                    previous > bound
                    if inclusive == "minimum"
                    else previous < bound
                )
                result = {
                    **result,
                    inclusive: previous if stricter else bound,
                    exclusive: not stricter,
                }
        return result

    return normalize(schema, "$")


def map_types(schema: Schema) -> Schema:
    """Map JSON primitive types to BSON types, including type-array unions.

    Returns:
        An independent schema using BSON type names.
    """
    mapping = {
        "integer": ["int", "long"],
        "boolean": ["bool"],
        "number": ["double"],
        "string": ["string"],
        "object": ["object"],
        "array": ["array"],
        "null": ["null"],
    }

    def convert(node: Schema, path: str) -> Schema:
        result = _walk(node, path, convert)
        if "type" not in result:
            return result
        if "bsonType" in result:
            raise SchemaGenerationException(
                f"{path}: conflicting type and bsonType.",
            )
        source = result["type"]
        types = (
            cast("list[str]", source) if isinstance(source, list) else [source]
        )
        try:
            targets = list(
                dict.fromkeys(
                    target for item in types for target in mapping[item]
                ),
            )
        except KeyError as error:
            raise SchemaGenerationException(
                f"{path}: unsupported JSON type {source!r}.",
            ) from error
        return {
            **{key: value for key, value in result.items() if key != "type"},
            "bsonType": targets if len(targets) != 1 else targets[0],
        }

    return convert(schema, "$")


def validate_compatibility(schema: Schema) -> Schema:
    """Reject every keyword which MongoDB cannot enforce, with its path.

    Returns:
        An independent, compatible schema.
    """

    def validate(node: Schema, path: str) -> Schema:
        for key in node:
            if key not in _KEYWORDS:
                raise SchemaGenerationException(
                    f"{path}/{key}: unsupported MongoDB keyword {key!r}.",
                )
        bson_types = node.get("bsonType", [])
        if isinstance(bson_types, str):
            bson_types = [bson_types]
        for bson_type in bson_types:
            if bson_type not in _BSON_TYPES:
                raise SchemaGenerationException(
                    f"{path}/bsonType: unsupported BSON type {bson_type!r}.",
                )
        # JSON representation constraints must not silently become no-ops on
        # native BSON values (for example minLength on Binary or Code).
        constraint_types = {
            "minLength": {"string"},
            "maxLength": {"string"},
            "pattern": {"string"},
            "minimum": {"int", "long", "double", "decimal", "number"},
            "maximum": {"int", "long", "double", "decimal", "number"},
            "multipleOf": {"int", "long", "double", "decimal", "number"},
        }
        for keyword, applicable in constraint_types.items():
            if (
                keyword in node
                and bson_types
                and not (set(bson_types) & applicable)
            ):
                raise SchemaGenerationException(
                    f"{path}/{keyword}: constraint does not apply to "
                    f"BSON types {bson_types!r}.",
                )
        return _walk(node, path, validate)

    return validate(schema, "$")


def mongodb_schema(schema: Schema) -> Schema:
    """Run the pipeline and emit a validator, adding _id only at the root.

    Returns:
        A MongoDB collection validator independent of the input.

    Raises:
        SchemaGenerationException: If the root is not an object schema.
    """
    resolved = resolve_refs(schema)
    normalized = normalize_schema(resolved)
    mapped = map_types(normalized)
    compatible = validate_compatibility(mapped)
    if compatible.get("bsonType") != "object":
        raise SchemaGenerationException(
            "$: a MongoDB document must be object.",
        )
    properties = compatible.get("properties", {})
    return {
        "$jsonSchema": {
            **compatible,
            "properties": {"_id": {"bsonType": "objectId"}, **properties},
            "required": list(
                dict.fromkeys([*compatible.get("required", []), "_id"]),
            ),
        },
    }
