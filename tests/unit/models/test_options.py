from __future__ import annotations

import json
import math

from pydantic import ValidationError
import pytest

from kover.models.concerns import ReadConcern, WriteConcern
from kover.models.options import DiscoveryOptions
from kover.models.read_preference import ReadPreference


def test_concern_models_serialize_defaults_and_optional_fields() -> None:
    assert WriteConcern().model_dump() == {"w": "majority"}
    assert WriteConcern(w=2, j=True, wtimeout=400).model_dump() == {
        "w": 2,
        "j": True,
        "wtimeout": 400,
    }
    assert ReadConcern().model_dump() == {"level": "local"}
    assert ReadConcern(level="snapshot").model_dump() == {"level": "snapshot"}
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
    first = preference.model_dump()
    assert first == {
        "mode": "nearest",
        "tags": [{"region": "west"}, {}],
        "maxStalenessSeconds": 90,
    }
    first["tags"][0]["region"] = "mutated"
    assert preference.model_dump()["tags"][0] == {"region": "west"}
    assert ReadPreference().model_dump() == {"mode": "primary"}
    with pytest.raises(ValidationError):
        ReadPreference(mode="primary", tag_sets=({"dc": "east"},))
    with pytest.raises(ValidationError):
        ReadPreference(mode="secondary", max_staleness_seconds=89)
    with pytest.raises(ValidationError):
        ReadPreference(mode="nearest", max_staleness_seconds=0)


@pytest.mark.parametrize(
    ("tag_sets", "expected_tags"),
    [
        (None, None),
        ((), []),
        ((dict[str, str](),), [dict[str, str]()]),
        (({"dc": "east"},), [{"dc": "east"}]),
    ],
)
def test_read_preference_serialization_modes_and_nesting(
    tag_sets: tuple[dict[str, str], ...] | None,
    expected_tags: list[dict[str, str]] | None,
) -> None:
    preference = ReadPreference(mode="secondary", tag_sets=tag_sets)
    expected: dict[str, object] = {"mode": "secondary"}
    if expected_tags is not None:
        expected["tags"] = expected_tags

    assert preference.model_dump() == expected
    assert preference.model_dump(mode="json") == expected
    assert json.loads(preference.model_dump_json()) == expected
    assert preference.to_dict() == expected
    options = DiscoveryOptions(read_preference=preference)
    assert options.model_dump()["read_preference"] == expected


def test_read_preference_serialization_respects_dump_options() -> None:
    preference = ReadPreference(
        mode="nearest",
        tag_sets=({"dc": "east"},),
        max_staleness_seconds=90,
    )
    assert preference.model_dump(include={"tag_sets"}) == {
        "tags": [{"dc": "east"}],
    }
    assert preference.model_dump(exclude={"tag_sets"}) == {
        "mode": "nearest",
        "maxStalenessSeconds": 90,
    }
    assert preference.model_dump(by_alias=False) == {
        "mode": "nearest",
        "tag_sets": [{"dc": "east"}],
        "max_staleness_seconds": 90,
    }
