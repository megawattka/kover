from typing import Any

class OperationFailure(Exception):
    def __init__(self, code: int, message: Any) -> None:
        self.code = code
        self.message = message
    
    def __repr__(self) -> str:
        return str(self.message)

    __str__ = __repr__
