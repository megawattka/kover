import itertools
from typing import (
    Iterable,
    List,
    TypeVar,
    Any,
    get_origin,
    Optional,
    Union,
    runtime_checkable,
    Protocol
)

from .typings import xJsonT

T = TypeVar("T")


@runtime_checkable
class HasToDict(Protocol):
    def to_dict(self) -> xJsonT:
        ...


def chain(iterable: Iterable[Iterable[T]]) -> List[T]:
    return [*itertools.chain.from_iterable(iterable)]


def filter_non_null(doc: xJsonT) -> xJsonT:
    return {
        k: v for k, v in doc.items() if v is not None
    }


def isinstance_ex(attr_t: Any, argument: Any) -> bool:
    return isinstance(attr_t, type) and issubclass(attr_t, argument)


def is_origin_ex(attr_t: Any, argument: Any) -> bool:
    return get_origin(attr_t) is argument


def maybe_to_dict(
    obj: Optional[Union[HasToDict, xJsonT]]
) -> Optional[xJsonT]:
    if (obj is not None and isinstance(obj, dict)) or obj is None:
        return obj
    return obj.to_dict()
