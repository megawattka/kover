from typing import Any


class OperationFailure(Exception):
    def __init__(self, code: int, message: Any) -> None:
        self.code = code
        self.message = message


class SchemaGenerationException(Exception):
    pass


class CorruptedDocument(Exception):
    def __init__(self, missing_field: str) -> None:
        super().__init__(
            "Schema was updated but document in collection is not. " +
            f'Missing field is: "{missing_field}"'
        )
