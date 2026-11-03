from pydantic import ValidationError
import pytest

from kover.enums import PoolState
from kover.models.network import DriverOptions, PoolOptions, PoolStats


def test_pool_stats_accept_python_names_and_serialize_aliases() -> None:
    stats = PoolStats(
        state=PoolState.READY, idle=1, connecting=0, waiters=0, checked_out=2,
    )
    assert stats.checked_out == 2
    assert stats.to_dict() == {
        "state": PoolState.READY.value, "idle": 1, "connecting": 0,
        "waiters": 0, "checkedOut": 2,
    }
    assert PoolStats.model_validate(stats.to_dict()) == stats


def test_pool_options_accept_names_and_aliases_with_same_validation() -> None:
    options = PoolOptions(max_size=3, min_size=1, max_connecting=2)
    assert options.max_size == 3
    assert options.min_size == 1
    assert PoolOptions.model_validate(options.to_dict()) == options
    with pytest.raises(ValidationError, match="min_size"):
        PoolOptions(max_size=1, min_size=2)
    with pytest.raises(ValidationError, match="min_size"):
        PoolOptions.model_validate({"maxSize": 1, "minSize": 2})


@pytest.mark.parametrize(
    "field",
    ["max_size", "maxSize", "max_connecting", "maxConnecting"],
)
def test_pool_limits_cannot_bypass_validation_using_field_names(
    field: str,
) -> None:
    with pytest.raises(ValidationError):
        PoolOptions.model_validate({field: 0})


@pytest.mark.parametrize("field", ["load_balanced", "loadBalanced"])
def test_load_balancing_rejected_with_either_spelling(field: str) -> None:
    with pytest.raises(ValidationError, match="not supported"):
        DriverOptions.model_validate({field: True})
