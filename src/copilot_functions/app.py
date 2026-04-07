"""
Azure Functions + GitHub Copilot SDK — app factory.

Call ``create_function_app()`` to build a fully-configured FunctionApp
with HTTP routes, MCP tool, and dynamic triggers from AGENTS.md.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

import azure.functions as func
import frontmatter

from .connector_tool_cache import _resolve_env_var, configure_connector_tools
from .runner import run_copilot_agent, run_copilot_agent_stream
from azurefunctions.extensions.http.fastapi import Request, Response, StreamingResponse

# Resolve the application root (parent of this package directory, i.e. ``src/``)
_APP_ROOT = Path(__file__).resolve().parent.parent

_MCP_AGENT_TOOL_PROPERTIES = json.dumps(
    [
        {
            "propertyName": "prompt",
            "propertyType": "string",
            "description": "Prompt text sent to the agent.",
            "isRequired": True,
            "isArray": False,
        },
    ]
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_agents_frontmatter_metadata() -> Dict[str, Any]:
    """Load AGENTS.md frontmatter metadata as a dictionary."""
    agents_md_path = _APP_ROOT / "AGENTS.md"
    if not agents_md_path.exists():
        return {}

    try:
        raw_content = agents_md_path.read_text(encoding="utf-8")
        parsed = frontmatter.loads(raw_content)
        metadata = parsed.metadata if isinstance(parsed.metadata, dict) else {}
        return metadata
    except Exception as exc:
        logging.warning(f"Failed to parse AGENTS.md frontmatter: {exc}")
        return {}


def _safe_mcp_tool_name(raw_name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]", "_", raw_name).strip("_").lower()
    if not normalized:
        return "agent_chat"
    if normalized[0].isdigit():
        return f"agent_{normalized}"
    return normalized


def _extract_mcp_session_id(payload: Dict[str, Any]) -> str | None:
    """Extract MCP session id from top-level context payload only."""
    value = payload.get("sessionId") or payload.get("sessionid")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _load_agents_functions_from_frontmatter(metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Load optional function definitions from AGENTS.md frontmatter."""
    if not metadata:
        logging.info("AGENTS.md not found or has no parseable frontmatter. No dynamic functions registered.")
        return []

    functions = metadata.get("functions")
    if functions is None:
        logging.info("AGENTS.md frontmatter has no 'functions' section. No dynamic functions registered.")
        return []

    if not isinstance(functions, list):
        logging.warning("AGENTS.md frontmatter 'functions' must be an array. Ignoring dynamic functions.")
        return []

    return [item for item in functions if isinstance(item, dict)]


def _normalize_timer_schedule(schedule: str) -> str:
    """Accept 5-part cron by prepending seconds; keep 6-part schedules unchanged."""
    schedule_parts = schedule.strip().split()
    if len(schedule_parts) == 5:
        return f"0 {schedule.strip()}"
    return schedule.strip()


def _is_valid_timer_schedule(schedule: str) -> bool:
    return len(schedule.strip().split()) == 6


def _to_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return default


def _safe_timer_name(raw_name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]", "_", raw_name).strip("_")
    if not name:
        return "timer_agent"
    if name[0].isdigit():
        return f"timer_{name}"
    return name


def _safe_function_name(raw_name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]", "_", raw_name).strip("_")
    if not name:
        return "agent_function"
    if name[0].isdigit():
        return f"fn_{name}"
    return name


# ---------------------------------------------------------------------------
# Dynamic function registration
# ---------------------------------------------------------------------------

def _register_dynamic_functions(
    app: func.FunctionApp,
    metadata: Dict[str, Any],
) -> None:
    function_specs = _load_agents_functions_from_frontmatter(metadata)
    if not function_specs:
        return

    registered_names: set = set()
    connector_trigger_specs: List[tuple] = []

    for index, spec in enumerate(function_specs, start=1):
        trigger_value = spec.get("trigger", "timer")
        trigger = str(trigger_value).strip().lower()

        if trigger == "timer":
            _register_timer_function(app, spec, index, registered_names)
        elif trigger == "teams_new_channel_message":
            connector_trigger_specs.append((index, spec))
        else:
            logging.warning(
                f"Rejected AGENTS function #{index}: unsupported trigger '{trigger}' (raw={trigger_value!r})."
            )
            continue

    # Register connector triggers (Teams, etc.) if any are present
    if connector_trigger_specs:
        _register_connector_triggers(app, connector_trigger_specs, registered_names)


def _register_timer_function(
    app: func.FunctionApp,
    spec: Dict[str, Any],
    index: int,
    registered_names: set,
) -> None:
    """Register a single timer-triggered function from the spec."""
    schedule_raw = spec.get("schedule")
    prompt_raw = spec.get("prompt")

    if not isinstance(schedule_raw, str) or not schedule_raw.strip():
        logging.warning(f"Skipping AGENTS function #{index}: missing required 'schedule'")
        return

    if not isinstance(prompt_raw, str) or not prompt_raw.strip():
        logging.warning(f"Skipping AGENTS function #{index}: missing required 'prompt'")
        return

    schedule = _normalize_timer_schedule(schedule_raw)
    if not _is_valid_timer_schedule(schedule):
        logging.warning(
            f"Skipping AGENTS function #{index}: invalid schedule '{schedule_raw}' after normalization '{schedule}'"
        )
        return

    base_name = _safe_timer_name(str(spec.get("name") or f"timer_agent_{index}"))
    function_name = base_name
    suffix = 2
    while function_name in registered_names:
        function_name = f"{base_name}_{suffix}"
        suffix += 1
    registered_names.add(function_name)

    prompt = prompt_raw.strip()
    should_log_response = _to_bool(spec.get("logger", True), default=True)

    def _make_timer_handler(
        timer_function_name: str,
        timer_schedule: str,
        timer_prompt: str,
        log_response: bool,
    ):
        async def _timer_handler(timer_request: func.TimerRequest) -> None:
            if timer_request.past_due:
                logging.info(f"Timer '{timer_function_name}' is past due.")

            logging.info(f"Timer '{timer_function_name}' running with schedule '{timer_schedule}'")

            try:
                result = await run_copilot_agent(timer_prompt)
                if log_response:
                    logging.info(
                        "Timer '%s' agent response: %s",
                        timer_function_name,
                        json.dumps(
                            {
                                "session_id": result.session_id,
                                "response": result.content,
                                "response_intermediate": result.content_intermediate,
                                "tool_calls": result.tool_calls,
                            },
                            ensure_ascii=False,
                            default=str,
                        ),
                    )
            except Exception as exc:
                logging.exception(f"Timer '{timer_function_name}' failed: {exc}")

        _timer_handler.__name__ = f"timer_handler_{timer_function_name}"
        return _timer_handler

    handler = _make_timer_handler(function_name, schedule, prompt, should_log_response)
    decorated = app.timer_trigger(
        schedule=schedule,
        arg_name="timer_request",
        run_on_startup=False,
    )(handler)
    app.function_name(name=function_name)(decorated)

    logging.info(
        f"Registered dynamic timer function '{function_name}' from AGENTS.md (schedule='{schedule}', logger={should_log_response})"
    )


def _register_connector_triggers(
    app: func.FunctionApp,
    trigger_specs: List[tuple],
    registered_names: set,
) -> None:
    """Register connector-based triggers (e.g., Teams new channel message)."""
    try:
        import azure.functions_connectors as fc
    except ImportError:
        logging.error(
            "azure-functions-connectors package not installed. "
            "Cannot register connector triggers. "
            "Install from: https://github.com/anthonychu/azure-functions-connectors-python"
        )
        return

    connectors = fc.FunctionsConnectors(app)

    for index, spec in trigger_specs:
        trigger = str(spec.get("trigger", "")).strip().lower()

        if trigger == "teams_new_channel_message":
            _register_teams_trigger(connectors, spec, index, registered_names)
        else:
            logging.warning(f"Skipping AGENTS function #{index}: unsupported connector trigger '{trigger}'")


def _register_teams_trigger(
    connectors,
    spec: Dict[str, Any],
    index: int,
    registered_names: set,
) -> None:
    """Register a Teams new channel message trigger."""
    connection_id_raw = spec.get("connection_id")
    team_id_raw = spec.get("team_id")
    channel_id_raw = spec.get("channel_id")

    if not connection_id_raw:
        logging.warning(f"Skipping AGENTS function #{index}: missing required 'connection_id' for teams_new_channel_message")
        return
    if not team_id_raw:
        logging.warning(f"Skipping AGENTS function #{index}: missing required 'team_id' for teams_new_channel_message")
        return
    if not channel_id_raw:
        logging.warning(f"Skipping AGENTS function #{index}: missing required 'channel_id' for teams_new_channel_message")
        return

    connection_id = _resolve_env_var(str(connection_id_raw))
    team_id = _resolve_env_var(str(team_id_raw))
    channel_id = _resolve_env_var(str(channel_id_raw))

    # Optional polling interval overrides
    min_interval = spec.get("min_interval")
    max_interval = spec.get("max_interval")

    base_name = _safe_function_name(str(spec.get("name") or f"teams_agent_{index}"))
    function_name = base_name
    suffix = 2
    while function_name in registered_names:
        function_name = f"{base_name}_{suffix}"
        suffix += 1
    registered_names.add(function_name)

    should_log_response = _to_bool(spec.get("logger", True), default=True)

    def _make_teams_handler(handler_function_name: str, log_response: bool):
        async def _teams_handler(message):
            logging.info(f"Teams trigger '{handler_function_name}' received new channel message")

            try:
                # Serialize the full trigger payload as prompt
                if hasattr(message, "to_dict"):
                    payload = message.to_dict()
                elif hasattr(message, "model_dump"):
                    payload = message.model_dump()
                elif isinstance(message, dict):
                    payload = message
                else:
                    payload = {"raw": str(message)}

                prompt = json.dumps(payload, ensure_ascii=False, default=str)
                result = await run_copilot_agent(prompt)

                if log_response:
                    logging.info(
                        "Teams trigger '%s' agent response: %s",
                        handler_function_name,
                        json.dumps(
                            {
                                "session_id": result.session_id,
                                "response": result.content,
                                "response_intermediate": result.content_intermediate,
                                "tool_calls": result.tool_calls,
                            },
                            ensure_ascii=False,
                            default=str,
                        ),
                    )
            except Exception as exc:
                logging.exception(f"Teams trigger '{handler_function_name}' failed: {exc}")

        _teams_handler.__name__ = f"teams_handler_{handler_function_name}"
        return _teams_handler

    handler = _make_teams_handler(function_name, should_log_response)

    try:
        trigger_kwargs = {
            "connection_id": connection_id,
            "team_id": team_id,
            "channel_id": channel_id,
        }
        if min_interval is not None:
            trigger_kwargs["min_interval"] = int(min_interval)
        if max_interval is not None:
            trigger_kwargs["max_interval"] = int(max_interval)

        connectors.teams.new_channel_message_trigger(**trigger_kwargs)(handler)

        logging.info(
            f"Registered Teams channel message trigger '{function_name}' from AGENTS.md "
            f"(team_id='{team_id}', channel_id='{channel_id}'"
            f"{f', min_interval={min_interval}' if min_interval is not None else ''}"
            f"{f', max_interval={max_interval}' if max_interval is not None else ''})"
        )
    except Exception as exc:
        logging.error(f"Failed to register Teams trigger '{function_name}': {exc}")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_function_app() -> func.FunctionApp:
    """Build and return a fully-configured Azure Functions app."""

    app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

    # ---- Load AGENTS.md frontmatter ----
    metadata = _load_agents_frontmatter_metadata()

    mcp_tool_name = _safe_mcp_tool_name(
        str(metadata.get("name") or "agent_chat")
    )
    mcp_tool_description = str(
        metadata.get("description") or "Run an agent chat turn with a prompt."
    ).strip() or "Run an agent chat turn with a prompt."

    # ---- Register dynamic functions (timer, Teams) ----
    _register_dynamic_functions(app, metadata)

    # ---- Configure connector tools from frontmatter ----
    tools_from_connections = metadata.get("tools_from_connections")
    if isinstance(tools_from_connections, list):
        configure_connector_tools(tools_from_connections)

    # ---- HTTP routes ----

    @app.route(
        route="{*ignored}",
        methods=["GET"],
        auth_level=func.AuthLevel.ANONYMOUS,
    )
    def root_chat_page(req: Request) -> Response:
        """Serve the chat UI at the root route."""
        ignored = (req.path_params or {}).get("ignored", "")
        if ignored:
            return Response("Not found", status_code=404)

        index_path = _APP_ROOT / "public" / "index.html"
        if not index_path.exists():
            return Response("index.html not found", status_code=404)

        return Response(
            index_path.read_text(encoding="utf-8"),
            status_code=200,
            media_type="text/html",
        )

    @app.route(route="agent/chat", methods=["POST"])
    async def chat(req: Request) -> Response:
        """
        Chat endpoint - send a prompt, get a response.

        POST /agent/chat
        Headers:
            x-ms-session-id (optional): Session ID for resuming a previous session
        Body:
        {
            "prompt": "What is 2+2?"
        }
        """
        try:
            body = await req.json()
            prompt = body.get("prompt")

            if not prompt:
                return Response(
                    json.dumps({"error": "Missing 'prompt'"}),
                    status_code=400,
                    media_type="application/json",
                )

            session_id = req.headers.get("x-ms-session-id")
            result = await run_copilot_agent(prompt, session_id=session_id)

            response = Response(
                json.dumps(
                    {
                        "session_id": result.session_id,
                        "response": result.content,
                        "response_intermediate": result.content_intermediate,
                        "tool_calls": result.tool_calls,
                    }
                ),
                media_type="application/json",
                headers={"x-ms-session-id": result.session_id},
            )
            return response

        except Exception as e:
            error_msg = str(e) if str(e) else f"{type(e).__name__}: {repr(e)}"
            logging.error(f"Chat error: {error_msg}")
            return Response(
                json.dumps({"error": error_msg}), status_code=500, media_type="application/json"
            )

    @app.route(route="agent/chatstream", methods=["POST"])
    async def chat_stream(req: Request) -> StreamingResponse:
        """
        Streaming chat endpoint - send a prompt, receive SSE events.

        POST /agent/chat/stream
        Headers:
            x-ms-session-id (optional): Session ID for resuming a previous session
        Body:
        {
            "prompt": "What is 2+2?"
        }

        Response: text/event-stream with events:
            data: {"type": "session", "session_id": "..."}
            data: {"type": "delta", "content": "partial text"}
            data: {"type": "tool_start", "tool_name": "...", "tool_call_id": "..."}
            data: {"type": "message", "content": "full message"}
            data: {"type": "done"}
        """
        try:
            body = await req.json()
            prompt = body.get("prompt")

            if not prompt:
                async def error_gen():
                    yield f"data: {json.dumps({'type': 'error', 'content': 'Missing prompt'})}\n\n"
                return StreamingResponse(error_gen(), media_type="text/event-stream")

            session_id = req.headers.get("x-ms-session-id")
            return StreamingResponse(
                run_copilot_agent_stream(prompt, session_id=session_id),
                media_type="text/event-stream",
            )

        except Exception as e:
            error_msg = str(e) if str(e) else f"{type(e).__name__}: {repr(e)}"
            logging.error(f"Chat stream error: {error_msg}")
            async def error_gen():
                yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
            return StreamingResponse(error_gen(), media_type="text/event-stream")

    # ---- MCP tool ----

    @app.mcp_tool_trigger(
        arg_name="context",
        tool_name=mcp_tool_name,
        description=mcp_tool_description,
        tool_properties=_MCP_AGENT_TOOL_PROPERTIES,
    )
    async def mcp_agent_chat(context: str) -> str:
        """MCP tool endpoint that runs the same agent workflow as /agent/chat."""
        try:
            payload = json.loads(context) if context else {}
            arguments = payload.get("arguments", {}) if isinstance(payload, dict) else {}

            prompt = arguments.get("prompt") if isinstance(arguments, dict) else None
            if not isinstance(prompt, str) or not prompt.strip():
                return json.dumps({"error": "Missing 'prompt'"})

            session_id = _extract_mcp_session_id(payload) if isinstance(payload, dict) else None

            result = await run_copilot_agent(prompt.strip(), session_id=session_id)

            return json.dumps(
                {
                    "session_id": result.session_id,
                    "response": result.content,
                    "response_intermediate": result.content_intermediate,
                    "tool_calls": result.tool_calls,
                }
            )
        except Exception as exc:
            error_msg = str(exc) if str(exc) else f"{type(exc).__name__}: {repr(exc)}"
            logging.error(f"MCP tool error: {error_msg}")
            return json.dumps({"error": error_msg})

    return app
