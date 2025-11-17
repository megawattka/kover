"""Build hook for Hatch that compiles Rust extensions using PyO3/maturin."""

import logging
from typing import Any

from hatchling.builders.config import BuilderConfig
from hatchling.builders.hooks.plugin.interface import BuildHookInterface

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class CustomBuildHook(BuildHookInterface[BuilderConfig]):
    """The build hook interface."""

    def initialize(
        self,
        version: str,
        build_data: dict[str, Any],
    ) -> None:
        """Fired when build starts."""
