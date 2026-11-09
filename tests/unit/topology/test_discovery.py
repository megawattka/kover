from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from kover.models.address import Address
from kover.models.hello import HelloResult
from kover.models.options import DiscoveryOptions
from kover.models.topology import ServerDescription
from kover.topology.discovery import ServerDiscovery
from kover.topology.protocols import IServerProbe


def member(host: str, *, primary: bool = False) -> ServerDescription:
    return ServerDescription(
        address=Address(host=host),
        hello=HelloResult(
            setName="rs",
            isWritablePrimary=primary,
            secondary=not primary,
            hosts=["seed:27017", "member:27017"],
        ),
    )


@pytest.mark.parametrize("member_initially_available", [False, True])
async def test_discovery_remembers_members_when_seed_is_unavailable(
    *,
    member_initially_available: bool,
) -> None:
    seed = member("seed", primary=True)
    secondary = member("member")
    available = {seed.address.host: seed}
    if member_initially_available:
        available[secondary.address.host] = secondary

    def probe_address(
        address: Address,
        *,
        deadline: float | None = None,
    ) -> ServerDescription:
        assert deadline is not None
        if address.host not in available:
            raise OSError("server unavailable")
        return available[address.host]

    probe = AsyncMock(spec=IServerProbe)
    probe.probe.side_effect = probe_address
    discovery = ServerDiscovery(
        [seed.address],
        options=DiscoveryOptions(replica_set="rs"),
        probe=probe,
    )
    first = await discovery.scan()
    assert {item.address.host for item in first} == set(available)

    # An empty snapshot must not erase the addresses to try next time.
    available.clear()
    assert await discovery.scan() == ()

    replacement = member("member", primary=True)
    available[replacement.address.host] = replacement
    probe.probe.reset_mock()
    assert await discovery.scan() == (replacement,)
    assert {call.args[0].host for call in probe.probe.await_args_list} == {
        "seed",
        "member",
    }


async def test_direct_discovery_does_not_follow_advertised_members() -> None:
    seed = member("seed", primary=True)
    probe = AsyncMock(spec=IServerProbe)
    probe.probe.return_value = seed
    discovery = ServerDiscovery(
        [seed.address],
        options=DiscoveryOptions(replica_set="rs", direct_connection=True),
        probe=probe,
    )
    assert await discovery.scan() == (seed,)

    probe.probe.reset_mock()
    probe.probe.side_effect = OSError("seed unavailable")
    assert await discovery.scan() == ()
    probe.probe.assert_awaited_once()
    assert probe.probe.await_args.args[0] == seed.address
