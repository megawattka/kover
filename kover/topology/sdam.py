"""SDAM topology transitions, shared by discovery and live monitors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models.address import Address
from ..network.uri_parser import parse_host
from .description import ServerDescription, ServerType, TopologyType


def _key(address: Address) -> tuple[str, int]:
    return address.host.lower(), address.port


if TYPE_CHECKING:
    from collections.abc import Sequence

    from .options import DiscoveryOptions


_REPLICA_TYPES = {
    ServerType.RS_PRIMARY,
    ServerType.RS_SECONDARY,
    ServerType.RS_ARBITER,
    ServerType.RS_OTHER,
}
_ELECTION_ID_FIRST_WIRE_VERSION = 17


def _parse_address(value: str) -> Address:
    host, port = parse_host(value)
    return Address(host=host, port=port or 27017)


class Topology:
    """Apply one observation at a time without yielding to the event loop."""

    def __init__(
        self,
        seeds: Sequence[Address],
        options: DiscoveryOptions,
    ) -> None:
        if not seeds:
            msg = "at least one seed is required"
            raise ValueError(msg)
        if options.direct_connection and len(seeds) != 1:
            msg = "directConnection requires exactly one seed"
            raise ValueError(msg)
        self.servers = {
            _key(seed): ServerDescription(address=seed, unavailable=True)
            for seed in seeds
        }
        self._single_seed = len(self.servers) == 1
        self.set_name = options.replica_set
        self.kind = TopologyType.UNKNOWN
        if options.direct_connection:
            self.kind = TopologyType.SINGLE
        elif self.set_name is not None:
            self.kind = TopologyType.RS_NO_PRIMARY
        self._max_election = b""
        self._max_set_version = -1

    def update(self, description: ServerDescription) -> bool:
        """Apply a current observation, ignoring removed or stale servers.

        Returns:
            Whether the observation was accepted.
        """
        key = _key(description.address)
        previous = self.servers.get(key)
        if previous is None:
            return False
        version = description.hello.topology_version
        if (
            version is not None
            and version.compare(previous.hello.topology_version) < 0
        ):
            return False

        role = description.server_type
        if self.kind is TopologyType.SINGLE:
            if (
                role is not ServerType.UNKNOWN
                and self.set_name is not None
                and self.set_name != description.hello.set_name
            ):
                description = self.unavailable(
                    description,
                    "replica set name does not match",
                )
            self.servers[key] = description
            return True

        if role in _REPLICA_TYPES and self.kind is not TopologyType.SHARDED:
            self._update_replica(description)
        else:
            self._update_non_replica(description)
        if self.kind in {
            TopologyType.RS_NO_PRIMARY,
            TopologyType.RS_WITH_PRIMARY,
        }:
            self.kind = (
                TopologyType.RS_WITH_PRIMARY
                if any(
                    server.server_type is ServerType.RS_PRIMARY
                    for server in self.servers.values()
                )
                else TopologyType.RS_NO_PRIMARY
            )
        return True

    def _update_non_replica(self, description: ServerDescription) -> None:
        key = _key(description.address)
        role = description.server_type
        if self.kind is TopologyType.UNKNOWN:
            if role is ServerType.MONGOS:
                self.kind = TopologyType.SHARDED
            elif role is ServerType.STANDALONE and self._single_seed:
                self.kind = TopologyType.SINGLE
        matches_topology = (
            self.kind is TopologyType.SINGLE
            or (
                role is ServerType.RS_GHOST
                and self.kind is not TopologyType.SHARDED
            )
            or (
                role is ServerType.MONGOS and self.kind is TopologyType.SHARDED
            )
        )
        if role is ServerType.UNKNOWN or matches_topology:
            self.servers[key] = description
        else:
            del self.servers[key]

    def _update_replica(self, description: ServerDescription) -> None:
        key = _key(description.address)
        hello = description.hello
        members = {
            _key(address): address
            for value in (*hello.hosts, *hello.passives, *hello.arbiters)
            if (address := _parse_address(value))
        }
        me = _key(_parse_address(hello.me)) if hello.me else key
        if self.set_name is None:
            self.set_name = hello.set_name
            self.kind = TopologyType.RS_NO_PRIMARY
        if hello.set_name != self.set_name:
            del self.servers[key]
            return
        if description.server_type is ServerType.RS_PRIMARY:
            self._update_primary(description, members)
            return
        if self.kind is TopologyType.RS_NO_PRIMARY:
            self._add_members(members)
        if me == key:
            self.servers[key] = description
        else:
            del self.servers[key]

    def _update_primary(
        self,
        description: ServerDescription,
        members: dict[tuple[str, int], Address],
    ) -> None:
        key = _key(description.address)
        if not self._accept_election(description):
            self.servers[key] = self.unavailable(
                description,
                "primary marked stale due to electionId/setVersion mismatch",
            )
            return
        self.servers[key] = description
        for other_key, server in self.servers.items():
            if (
                other_key != key
                and server.server_type is ServerType.RS_PRIMARY
            ):
                self.servers[other_key] = self.unavailable(
                    server,
                    "primary marked stale due to discovery of newer primary",
                )
        if members:
            # An omitted/empty list is not a usable membership advertisement.
            self._add_members(members)
            for removed in self.servers.keys() - members.keys():
                del self.servers[removed]

    def _add_members(self, members: dict[tuple[str, int], Address]) -> None:
        for key in members.keys() - self.servers.keys():
            self.servers[key] = ServerDescription(
                address=members[key],
                unavailable=True,
            )

    def _accept_election(self, description: ServerDescription) -> bool:
        hello = description.hello
        election = hello.election_id.binary if hello.election_id else b""
        version = hello.set_version if hello.set_version is not None else -1
        if (hello.max_wire_version or 0) >= _ELECTION_ID_FIRST_WIRE_VERSION:
            if (election, version) < (
                self._max_election,
                self._max_set_version,
            ):
                return False
            self._max_election, self._max_set_version = election, version
        else:
            if election and version >= 0:
                if (version, election) < (
                    self._max_set_version,
                    self._max_election,
                ):
                    return False
                self._max_election = election
            self._max_set_version = max(version, self._max_set_version)
        return True

    @staticmethod
    def unavailable(
        previous: ServerDescription,
        error: str,
    ) -> ServerDescription:
        """Retain hello metadata while removing a server from selection.

        Returns:
            A description classified as unavailable.
        """
        return previous.model_copy(
            update={"unavailable": True, "last_error": error},
        )
