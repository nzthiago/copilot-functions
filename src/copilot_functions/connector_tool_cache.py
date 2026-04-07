from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from .arm import ArmClient
from .config import resolve_env_var
from .connectors import load_connection
from .connector_tools import generate_tools


class _ConnectorToolCache:
    """Lazy-init singleton cache for connector tools discovered from ARM API."""

    def __init__(self):
        self._tools: list | None = None
        self._arm: ArmClient | None = None
        self._lock = asyncio.Lock()
        self._connection_specs: List[Dict[str, Any]] = []

    def set_connection_specs(self, specs: List[Dict[str, Any]]) -> None:
        """Set the tools_from_connections specs from AGENTS.md frontmatter."""
        self._connection_specs = specs or []

    async def get_tools(self) -> list:
        """Return cached connector tools, discovering them on first call."""
        if self._tools is not None:
            return self._tools

        async with self._lock:
            # Double-check after acquiring lock
            if self._tools is not None:
                return self._tools

            if not self._connection_specs:
                self._tools = []
                return self._tools

            self._arm = ArmClient()
            all_tools = []

            for spec in self._connection_specs:
                raw_connection_id = spec.get("connection_id", "")
                if not raw_connection_id:
                    logging.warning("tools_from_connections entry missing 'connection_id', skipping")
                    continue

                connection_id = resolve_env_var(str(raw_connection_id))
                if not connection_id or connection_id.startswith("%") or connection_id.startswith("$"):
                    logging.warning(f"tools_from_connections: could not resolve connection_id '{raw_connection_id}', skipping")
                    continue

                try:
                    connection = await load_connection(self._arm, connection_id)
                    tools = generate_tools(self._arm, connection)
                    all_tools.extend(tools)
                    logging.info(
                        f"Connector tools discovered: {connection.display_name} ({connection.api_name}): "
                        f"{len(tools)} tools [{connection.status}]"
                    )
                    for tool in tools:
                        logging.info(f"  - {tool.name}: {tool.description[:100]}")
                except Exception as e:
                    logging.warning(f"Failed to load connector tools for '{connection_id}': {e}")

            self._tools = all_tools
            return self._tools


_cache = _ConnectorToolCache()


def configure_connector_tools(tools_from_connections: List[Dict[str, Any]]) -> None:
    """Configure the connector tool cache with specs from AGENTS.md frontmatter.

    Called once at module load time from function_app.py.
    """
    _cache.set_connection_specs(tools_from_connections)


async def get_connector_tools() -> list:
    """Get cached connector tools (lazy-discovers on first call)."""
    return await _cache.get_tools()
