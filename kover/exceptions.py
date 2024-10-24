from typing import Any

class OperationFailure(Exception):
    def __init__(self, code: int, message: Any) -> None:
        self.code = code
        self.message = message
