"""kover schema generator module."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, override

from pydantic.json_schema import (
    DEFAULT_REF_TEMPLATE,
    GenerateJsonSchema,
)

if TYPE_CHECKING:
    from pydantic.annotated_handlers import CoreSchemaOrField
    from pydantic.json_schema import (
        JsonSchemaMode,
    )
    from pydantic_core import CoreSchema
    from pydantic_core.core_schema import (
        BytesSchema,
        DateSchema,
        DatetimeSchema,
        DecimalSchema,
        ModelField,
    )

    from ..typings import JsonT


class MongoDBSchemaGenerator(GenerateJsonSchema):
    """Generate MongoDB-compatible JSON Schema validators from Pydantic models.

    The generator adapts Pydantic's JSON Schema output to MongoDB's
    ``$jsonSchema`` dialect by converting JSON Schema types to BSON types,
    translating numeric exclusivity constraints, preserving field metadata,
    and adapting nested schemas, unions, enums, arrays, and mappings.

    The generated schema is intended to be passed directly to MongoDB as a
    collection validator.

    Notes:
        MongoDB's schema dialect is not identical to the JSON Schema dialect
        emitted by Pydantic. Features unsupported by MongoDB, such as
        ``$ref``, ``$defs``, and ``prefixItems``, must be resolved or
        converted by the generator.

        BSON subtypes, such as UUID ``binData`` subtype 4, cannot be enforced
        using MongoDB's ``$jsonSchema`` validator and must be handled by the
        application.

    Example:
        >>> schema = User.model_json_schema(
        ...     by_alias=True,
        ...     schema_generator=MongoDBSchemaGenerator,
        ... )
        >>> collection = database.create_collection(
        ...     "users",
        ...     validator=schema,
        ... )
    """
    def __init__(
        self,
        *,
        by_alias: bool = True,
        ref_template: str = DEFAULT_REF_TEMPLATE,
        union_format: Literal[
            "any_of",
            "primitive_type_array",
        ] = "any_of",
    ) -> None:
        super().__init__(
            by_alias=by_alias,
            ref_template=ref_template,
            union_format=union_format,
        )

        self._changed_refs: dict[str, JsonT] = {}

    def _get_cached_ref(self, ref: JsonT) -> JsonT | None:
        extracted = ref["$ref"]
        return self._changed_refs.get(extracted)

    @override
    def bytes_schema(self, schema: BytesSchema) -> JsonT:
        """Generates a JSON schema that matches a bytes value.

        Args:
            schema: The core schema.

        Returns:
            The generated JSON schema.
        """
        return {"bsonType": "binData"}

    def generate(
        self,
        schema: CoreSchema,
        mode: JsonSchemaMode = "validation",
    ) -> JsonT:
        """Generates a JSON schema for a specified schema in a specified mode.

        Args:
            schema: A Pydantic model.
            mode: The mode in which to generate the schema.

        Returns:
            A JSON schema representing the specified schema.

        Raises:
            ValueError: If mode is serialization.
        """
        if mode != "validation":
            raise ValueError(
                "Unsupported mode. Only validation mode is supported.",
            )

        result = super().generate(schema=schema, mode=mode)
        if "$defs" in result:
            del result["$defs"]

        # result — схема корневой модели
        result.setdefault("properties", {})["_id"] = {
            "bsonType": "objectId",
        }

        required = result.setdefault("required", [])
        if "_id" not in required:
            required.append("_id")

        del result["type"]
        result["bsonType"] = "object"

        return {"$jsonSchema": result}

    def _resolve_ref_and_cache(self, field: JsonT) -> JsonT:
        ref = field["$ref"]
        cached = self._get_cached_ref(field)
        if cached is not None:
            return cached
        field = self.resolve_ref_schema(field)
        self._changed_refs[ref] = field
        return field

    def get_flattened_anyof(self, schemas: list[JsonT]) -> JsonT:
        """Flatten unions and nullables into mongodb fields.

        Returns:
            Flattened object.
        """
        arr = super().get_flattened_anyof(schemas)

        for idx in range(len(arr["anyOf"])):
            arr["anyOf"][idx] = self._construct_field(arr["anyOf"][idx], {})

        return arr

    @staticmethod
    def _should_skip_field(field: JsonT, schema: JsonT | ModelField) -> bool:
        return any([
            "anyOf" in field,
            "type" not in field and schema.get("schema", {}).get("type") == "any",  # ruff: ignore[line-too-long]
            "enum" in field,
        ])

    def _parse_pattern_properties(self, field: JsonT) -> None:
        pprops = field.get("patternProperties", None)
        if pprops is not None:
            for key in pprops:
                pprops[key] = self._construct_field(pprops[key], {"a": 4})

    def _apply_array_transform(self, field: JsonT) -> None:
        if "items" not in field:
            prefix_items = field.pop("prefixItems")
            field["items"] = [
                self._construct_field(x, {}) for x in prefix_items
            ]
        else:
            items = field["items"]
            if "$ref" in items:
                field["items"] = self._resolve_ref_and_cache(
                    field["items"],
                )
            else:
                field["items"] = self._construct_field(items, {})

    def _parse_additiona_properties(
        self,
        field: JsonT,
    ) -> None:
        additional = field.get("additionalProperties", None)
        if additional is not None and not isinstance(additional, bool):
            if "$ref" in additional:
                field["additionalProperties"] = self._resolve_ref_and_cache(
                    additional,
                )
            else:
                field["additionalProperties"] = self._construct_field(
                    additional, {},
                )

    @staticmethod
    def _apply_type_transform(field: JsonT) -> None:
        if "bsonType" not in field:  # if already cached
            field["bsonType"] = field.pop("type")

        if field["bsonType"] == "integer":
            field["bsonType"] = ["int", "long"]

        elif field["bsonType"] == "boolean":
            field["bsonType"] = "bool"

        elif field["bsonType"] == "number":
            field["bsonType"] = "double"

    @staticmethod
    def _apply_title(field: JsonT, schema: JsonT | ModelField) -> None:
        metadata = schema.get("metadata", {}).get("pydantic_js_updates", {})
        if "title" in metadata:
            field["title"] = metadata["title"]

        elif "title" in field:
            del field["title"]

    def _construct_field(
        self,
        field: JsonT,
        schema: JsonT | ModelField,
    ) -> JsonT:
        for kw in ("transform", "format", "default"):
            if kw in field:
                del field[kw]

        if self._should_skip_field(field, schema):
            return field

        if "$ref" in field:
            field = self._resolve_ref_and_cache(field)

        if field.get("type") == "array":
            self._apply_array_transform(field)

        if "const" in field:
            field["enum"] = [field.pop("const")]

        self._parse_additiona_properties(field)
        self._parse_pattern_properties(field)
        self._apply_type_transform(field)

        for ex, rm in [
            ("exclusiveMinimum", "minimum"),
            ("exclusiveMaximum", "maximum"),
        ]:  # transform exclusive min/max to match older draft version
            if ex in field:
                field[rm] = field[ex]
                field[ex] = True

        self._apply_title(field, schema=schema)

        return field

    @override
    def decimal_schema(self, schema: DecimalSchema) -> JsonT:
        """Generates a JSON schema that matches a decimal value.

        Args:
            schema: The core schema.

        Returns:
            The generated JSON schema.
        """
        return {"bsonType": "decimal"}

    def model_field_schema(self, schema: ModelField) -> JsonT:
        """Generates a JSON schema.

        Args:
            schema: The core schema.

        Returns:
            The generated JSON schema.
        """
        result = super().model_field_schema(schema)
        if "oneOf" in result:
            return {"oneOf": [
                self._construct_field(x, schema) for x in result["oneOf"]
            ]}

        return self._construct_field(result, schema)

    @override
    def field_title_should_be_set(self, schema: CoreSchemaOrField) -> bool:
        """Returns true if a title should be set.

        Intuitively, we want this to return true for schemas
        that wouldn't otherwise provide their own title
        (e.g., int, float, str), and false for those that would
        (e.g., BaseModel subclasses).

        Args:
            schema: The schema to check.

        Returns:
            `True` if the field should have a title set, `False` otherwise.
        """
        return False

    @override
    def datetime_schema(self, schema: DatetimeSchema) -> dict[str, Any]:
        return {"bsonType": "date"}

    @override
    def date_schema(self, schema: DateSchema) -> dict[str, Any]:
        raise TypeError("datetime.date cannot be used as annotation.")
