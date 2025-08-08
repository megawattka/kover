from dns.asyncresolver import Resolver


class SrvResolver:
    """The SRV main resolver for Kover library."""

    def __init__(self) -> None:
        self._srv = "_mongodb"
        self._resolver = Resolver()

    async def get_nodes(self, fqdn: str) -> list[str]:
        """Get available SRV nodes for given fqdn."""
        resolvable = self._srv + "._tcp." + fqdn
        results = await self._resolver.resolve(resolvable, rdtype="SRV")
        return [node.to_text().split()[-1][:-1] for node in results]
