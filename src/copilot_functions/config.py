import logging
import os
import re
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Application root resolution
# ---------------------------------------------------------------------------

def get_app_root() -> Path:
    """Return the root directory of the user's agent project.

    This is the directory containing ``AGENTS.md``, ``tools/``,
    ``.vscode/mcp.json``, skills directories, etc.  By default it is
    the parent of the ``copilot_functions`` package directory (i.e. the
    Azure Functions ``src/`` folder).

    Override with the ``COPILOT_APP_ROOT`` environment variable when
    ``copilot_functions`` is installed as a standalone package and the
    project root is elsewhere.
    """
    explicit = os.environ.get("COPILOT_APP_ROOT")
    if explicit:
        return Path(explicit).resolve()
    return Path(__file__).resolve().parent.parent

# Default session state directory used by the Copilot CLI
_DEFAULT_CONFIG_DIR = os.path.expanduser("~/.copilot")
_REMOTE_CONFIG_DIR = "/code-assistant-session"


def resolve_config_dir() -> Optional[str]:
    """
    Resolve the config directory for session state persistence.

    Priority:
    1. CODE_ASSISTANT_CONFIG_PATH env var (explicit override)
    2. CONTAINER_NAME env var is set → /code-assistant-session (remote/Azure Functions mode)
    3. Neither set → None (SDK default ~/.copilot/ is used)
    """
    explicit_path = os.environ.get("CODE_ASSISTANT_CONFIG_PATH")
    if explicit_path:
        logging.info(f"Using CODE_ASSISTANT_CONFIG_PATH: {explicit_path}")
        return explicit_path

    container_name = os.environ.get("CONTAINER_NAME")
    if container_name:
        logging.info(f"Remote mode detected (CONTAINER_NAME={container_name}), using {_REMOTE_CONFIG_DIR}")
        return _REMOTE_CONFIG_DIR

    return None


def session_exists(config_dir: Optional[str], session_id: str) -> bool:
    """
    Check if a session exists on disk by looking for its directory.

    Session state is stored under {config_dir}/session-state/{sessionId}/.
    Falls back to ~/.copilot/session-state/{sessionId}/ if config_dir is None.
    """
    base = config_dir if config_dir else _DEFAULT_CONFIG_DIR
    session_path = os.path.join(base, "session-state", session_id)
    exists = os.path.isdir(session_path)
    logging.info(f"Session '{session_id}' exists at {session_path}: {exists}")
    return exists


# ---------------------------------------------------------------------------
# Environment variable substitution for AGENTS.md frontmatter values
# ---------------------------------------------------------------------------

_PERCENT_PATTERN = re.compile(r"^%([^%]+)%$")
_DOLLAR_PATTERN = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)$")


def resolve_env_var(value: str) -> str:
    """Resolve a frontmatter value that is a single env-var reference.

    Supported syntaxes (full-string match only — partial substitution
    such as ``prefix$VAR`` is intentionally **not** supported):

      - ``%VAR_NAME%`` — value is entirely ``%…%``
      - ``$VAR_NAME``  — value is entirely ``$IDENT``

    If the value does not match either pattern, or the referenced
    environment variable is not set, the original string is returned
    unchanged.

    The following AGENTS.md frontmatter fields are resolved through
    this function (all represent external resource identifiers or
    endpoints):

      - ``functions[].connection_id``
      - ``functions[].team_id``
      - ``functions[].channel_id``
      - ``tools_from_connections[].connection_id``
      - ``execution_sandbox.session_pool_management_endpoint``

    Fields that should **not** use substitution (identifiers, literals,
    or user-facing text): ``name``, ``description``, ``trigger``,
    ``schedule``, ``prompt``, ``min_interval``, ``max_interval``,
    ``logger``.
    """
    stripped = value.strip()
    m = _PERCENT_PATTERN.match(stripped) or _DOLLAR_PATTERN.match(stripped)
    if m:
        return os.environ.get(m.group(1), value)
    return value
