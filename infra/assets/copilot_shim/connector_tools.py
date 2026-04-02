from __future__ import annotations

import json
import re
from urllib.parse import quote

from copilot import Tool, ToolInvocation, ToolResult

from .arm import ArmClient
from .connectors import ConnectionInfo, ParsedOperation, ParsedParameter


def _sanitize_name(name: str) -> str:
    """Sanitize parameter name to match ^[a-zA-Z0-9_.-]{1,64}$."""
    sanitized = re.sub(r"[^a-zA-Z0-9_.\-]", "_", name)
    return sanitized[:64]


def _to_snake_case(name: str) -> str:
    """Convert operationId to snake_case."""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    s = re.sub(r"[^a-zA-Z0-9]", "_", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_").lower()


def _param_to_json_schema(param: ParsedParameter) -> dict:
    """Convert a ParsedParameter to a JSON Schema property."""
    type_map = {"integer": "integer", "number": "number", "boolean": "boolean"}
    schema: dict = {"type": type_map.get(param.type, "string")}
    if param.description:
        schema["description"] = param.description
    if param.enum:
        schema["enum"] = param.enum
    if param.default is not None:
        schema["default"] = param.default
    return schema


def _build_invoke_path(op: ParsedOperation, args: dict, all_params: list[ParsedParameter]) -> str:
    """Build the dynamicInvoke path by stripping /{connectionId} and substituting path params."""
    path = re.sub(r"^/\{connectionId\}", "", op.path, flags=re.IGNORECASE)
    for param in all_params:
        if param.location == "path":
            sanitized = _sanitize_name(param.name)
            value = args.get(sanitized)
            if value is None:
                raise ValueError(f"Missing required path parameter: {param.name}")
            path = path.replace(f"{{{param.name}}}", quote(str(value), safe=""))
    return path


def generate_tools(arm: ArmClient, connection: ConnectionInfo) -> list[Tool]:
    """Generate Copilot SDK Tool objects for each operation in a connection."""
    tools = []
    api_name = connection.api_name

    for op in connection.operations:
        tool_name = f"{api_name}_{_to_snake_case(op.operation_id)}"
        tool_name = tool_name[:64]

        # Build JSON schema for parameters
        properties: dict = {}
        required: list[str] = []
        all_params = op.parameters + op.body_properties

        for param in op.parameters:
            key = _sanitize_name(param.name)
            properties[key] = _param_to_json_schema(param)
            if param.required:
                required.append(key)

        for param in op.body_properties:
            key = _sanitize_name(param.name)
            properties[key] = _param_to_json_schema(param)
            if param.required or param.name in op.body_required_fields:
                required.append(key)

        parameters_schema: dict = {"type": "object", "properties": properties}
        if required:
            parameters_schema["required"] = required

        # Build description
        desc_parts = [op.summary or op.operation_id]
        if op.description and op.description != op.summary:
            desc_parts.append(op.description)
        desc_parts.append(f"(via {connection.display_name})")
        if connection.status != "Connected":
            desc_parts.append(f"Connection status: {connection.status}")
        description = " — ".join(desc_parts)

        def make_handler(op=op, connection=connection, all_params=all_params):
            async def handler(invocation: ToolInvocation) -> ToolResult:
                args = invocation.arguments or {}

                invoke_path = _build_invoke_path(op, args, all_params)

                queries = {}
                for param in op.parameters:
                    if param.location == "query":
                        key = _sanitize_name(param.name)
                        if key in args:
                            queries[param.name] = args[key]

                body = {}
                for param in op.body_properties:
                    key = _sanitize_name(param.name)
                    if key in args:
                        value = args[key]
                        if param.type in ("object", "array") and isinstance(value, str):
                            try:
                                value = json.loads(value)
                            except (json.JSONDecodeError, ValueError):
                                pass
                        # Handle dot-separated names as nested objects
                        if "." in param.name:
                            parts = param.name.split(".", 1)
                            if parts[0] not in body:
                                body[parts[0]] = {}
                            body[parts[0]][parts[1]] = value
                        else:
                            body[param.name] = value

                request_body: dict = {
                    "request": {
                        "method": op.method,
                        "path": invoke_path,
                    }
                }
                if queries:
                    request_body["request"]["queries"] = queries
                if body:
                    request_body["request"]["body"] = body

                try:
                    result = await arm.post(
                        f"{connection.resource_id}/dynamicInvoke",
                        body=request_body,
                    )
                    response = result.get("response", {})
                    response_body = response.get("body", result)
                    try:
                        status_code = int(response.get("statusCode", 200))
                    except (ValueError, TypeError):
                        status_code = 200

                    if status_code >= 400:
                        return ToolResult(
                            text_result_for_llm=f"Error ({status_code}): {json.dumps(response_body)}",
                            result_type="error",
                        )

                    return ToolResult(
                        text_result_for_llm=json.dumps(response_body, indent=2, default=str),
                        result_type="success",
                    )
                except Exception as e:
                    error_type = type(e).__name__
                    return ToolResult(
                        text_result_for_llm=f"Error invoking {op.operation_id}: {error_type}: {e}",
                        result_type="error",
                    )

            return handler

        tools.append(Tool(
            name=tool_name,
            description=description,
            parameters=parameters_schema,
            handler=make_handler(),
        ))

    return tools
