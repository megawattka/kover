from __future__ import annotations

import math

from pydantic import ValidationError
import pytest

from kover.models.concerns import ReadConcern, WriteConcern
from kover.models.options import DiscoveryOptions
from kover.models.read_preference import ReadPreference


def test_concern_models_serialize_defaults_and_optional_fields() -> None:
    assert WriteConcern().to_dict() == {"w": "majority"}
    assert WriteConcern(w=2, j=True, wtimeout=400).to_dict() == {
        "w": 2,
        "j": True,
        "wtimeout": 400,
    }
    assert ReadConcern().to_dict() == {"level": "local"}
    assert ReadConcern(level="snapshot").to_dict() == {"level": "snapshot"}
    with pytest.raises(ValidationError):
        ReadConcern(level="invalid")  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"server_selection_timeout": -1},
        {"server_selection_timeout": math.inf},
        {"server_selection_timeout": math.nan},
        {"connect_timeout": 0},
        {"connect_timeout": -1},
        {"connect_timeout": math.inf},
        {"replica_set": ""},
    ],
)
def test_discovery_options_reject_invalid_limits(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        DiscoveryOptions(**kwargs)  # pyright: ignore[reportArgumentType]


def test_discovery_options_accept_zero_and_disabled_timeout() -> None:
    options = DiscoveryOptions(
        server_selection_timeout=0,
        connect_timeout=None,
        replica_set="rs0",
        local_threshold=0.02,
    )
    assert options.server_selection_timeout == 0
    assert options.connect_timeout is None
    assert options.replica_set == "rs0"
    assert options.local_threshold == pytest.approx(0.02)


def test_read_preference_wire_data_is_fresh_and_validated() -> None:
    preference = ReadPreference(
        mode="nearest",
        tag_sets=({"region": "west"}, {}),
        max_staleness_seconds=90,
    )
    first = preference.to_dict()
    assert first == {
        "mode": "nearest",
        "tags": [{"region": "west"}, {}],
        "maxStalenessSeconds": 90,
    }
    first["tags"][0]["region"] = "mutated"
    assert preference.to_dict()["tags"][0] == {"region": "west"}
    assert ReadPreference().to_dict() == {"mode": "primary"}
    with pytest.raises(ValidationError):
        ReadPreference(mode="primary", tag_sets=({"dc": "east"},))
    with pytest.raises(ValidationError):
        ReadPreference(mode="secondary", max_staleness_seconds=89)
    with pytest.raises(ValidationError):
        ReadPreference(mode="nearest", max_staleness_seconds=0)
