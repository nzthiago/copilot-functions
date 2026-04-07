from __future__ import annotations

import re
from dataclasses import dataclass, field

from .arm import ArmClient


@dataclass
class ParsedParameter:
    name: str
    location: str  # "path", "query", "header", "body"
    type: str
    required: bool
    description: str
    format: str | None = None
    enum: list[str] | None = None
    default: object = None


@dataclass
class ParsedOperation:
    operation_id: str
    method: str
    path: str
    summary: str
    description: str
    parameters: list[ParsedParameter] = field(default_factory=list)
    body_properties: list[ParsedParameter] = field(default_factory=list)
    body_required_fields: list[str] = field(default_factory=list)


@dataclass
class ConnectionInfo:
    resource_id: str
    name: str
    api_name: str
    display_name: str
    status: str
    location: str
    operations: list[ParsedOperation] = field(default_factory=list)


def _resolve_ref(ref: str, root: dict) -> dict:
    """Resolve a $ref pointer like '#/definitions/Foo' against the swagger root."""
    parts = ref.lstrip("#/").split("/")
    result = root
    for part in parts:
        result = result.get(part, {})
    return result


def _resolve_schema(schema: dict, swagger: dict, depth: int = 0) -> dict:
    """Resolve a schema, following $ref if present."""
    if "$ref" in schema:
        return _resolve_ref(schema["$ref"], swagger)
    return schema


def _extract_body_properties(
    body_schema: dict, swagger: dict, max_depth: int = 2, depth: int = 0
) -> tuple[list[ParsedParameter], list[str]]:
    """Flatten body schema properties into a list of ParsedParameters."""
    resolved = _resolve_schema(body_schema, swagger)
    properties = resolved.get("properties", {})
    required_fields = resolved.get("required", [])
    params = []

    for prop_name, prop_schema in properties.items():
        prop_resolved = _resolve_schema(prop_schema, swagger)
        visibility = prop_resolved.get("x-ms-visibility", "")
        if visibility == "internal":
            continue

        prop_type = prop_resolved.get("type", "string")

        # Flatten nested objects: extract their properties with dot-separated names
        if prop_type == "object" and depth < max_depth:
            nested_props = prop_resolved.get("properties", {})
            nested_required = prop_resolved.get("required", [])
            if nested_props:
                for nested_name, nested_schema in nested_props.items():
                    nested_resolved = _resolve_schema(nested_schema, swagger)
                    nested_vis = nested_resolved.get("x-ms-visibility", "")
                    if nested_vis == "internal":
                        continue
                    nested_type = nested_resolved.get("type", "string")
                    if nested_type in ("object", "array") and depth + 1 >= max_depth:
                        nested_type = "string"
                    flat_name = f"{prop_name}.{nested_name}"
                    params.append(ParsedParameter(
                        name=flat_name,
                        location="body",
                        type=nested_type,
                        required=nested_name in nested_required,
                        description=nested_resolved.get("description", nested_resolved.get("x-ms-summary", nested_resolved.get("title", ""))),
                        format=nested_resolved.get("format"),
                        enum=nested_resolved.get("enum"),
                        default=nested_resolved.get("default"),
                    ))
                    if nested_name in nested_required:
                        required_fields.append(flat_name)
                continue

        if prop_type in ("object", "array") and depth >= max_depth:
            prop_type = "string"  # serialize as JSON string

        params.append(ParsedParameter(
            name=prop_name,
            location="body",
            type=prop_type,
            required=prop_name in required_fields,
            description=prop_resolved.get("description", prop_resolved.get("x-ms-summary", prop_resolved.get("title", ""))),
            format=prop_resolved.get("format"),
            enum=prop_resolved.get("enum"),
            default=prop_resolved.get("default"),
        ))

    return params, required_fields


async def _resolve_dynamic_schema(
    arm: ArmClient, resource_id: str, swagger: dict, dynamic_schema: dict, op: dict
) -> dict | None:
    """Resolve an x-ms-dynamic-schema by calling the referenced operation."""
    op_id = dynamic_schema.get("operationId")
    if not op_id:
        return None

    # Find the path for the referenced operation
    schema_path = None
    schema_method = None
    for p, methods in swagger.get("paths", {}).items():
        for m, o in methods.items():
            if isinstance(o, dict) and o.get("operationId") == op_id:
                schema_path = p
                schema_method = m
                break
        if schema_path:
            break

    if not schema_path:
        return None

    # Strip /{connectionId} from path
    invoke_path = re.sub(r"^/\{connectionId\}", "", schema_path, flags=re.IGNORECASE)

    # Build query/path params from the dynamic schema's parameters
    params = dynamic_schema.get("parameters", {})
    for param_name, param_val in params.items():
        if isinstance(param_val, dict) and "parameter" in param_val:
            ref_param = param_val["parameter"]
            defaults = {"poster": "User", "location": "Channel", "recipientType": "Channel"}
            param_val = defaults.get(ref_param, "")
        invoke_path = invoke_path.replace(f"{{{param_name}}}", str(param_val))

    try:
        result = await arm.post(
            f"{resource_id}/dynamicInvoke",
            body={"request": {"method": schema_method.upper(), "path": invoke_path}}
        )
        response = result.get("response", {})
        body = response.get("body", {})
        value_path = dynamic_schema.get("value-path", "schema")
        return body.get(value_path, body)
    except Exception:
        return None


async def _parse_operations(swagger: dict, arm: ArmClient, resource_id: str) -> list[ParsedOperation]:
    """Parse Swagger paths into a list of ParsedOperations."""
    paths = swagger.get("paths", {})
    operations: list[ParsedOperation] = []
    seen_families: dict[str, tuple[ParsedOperation, int]] = {}

    for path, methods in paths.items():
        if "$subscriptions" in path:
            continue

        for method, op in methods.items():
            if method in ("parameters", "x-ms-notification-content"):
                continue
            if not isinstance(op, dict):
                continue

            if op.get("x-ms-trigger"):
                continue
            if op.get("deprecated"):
                continue
            if method.lower() == "delete":
                continue

            visibility = op.get("x-ms-visibility", "")
            if visibility == "internal":
                continue

            operation_id = op.get("operationId", f"{method}_{path}")

            if operation_id.startswith("mcp_") or operation_id == "HttpRequest":
                continue

            summary = op.get("summary", "")
            description = op.get("description", "")

            params = []
            body_props = []
            body_required: list[str] = []

            for param in op.get("parameters", []):
                if "$ref" in param:
                    param = _resolve_ref(param["$ref"], swagger)

                param_in = param.get("in", "")
                if param_in == "body":
                    schema = param.get("schema", {})
                    resolved_schema = _resolve_schema(schema, swagger)
                    dynamic = resolved_schema.get("x-ms-dynamic-schema")
                    if dynamic and not resolved_schema.get("properties"):
                        dyn_schema = await _resolve_dynamic_schema(arm, resource_id, swagger, dynamic, op)
                        if dyn_schema:
                            body_props, body_required = _extract_body_properties(
                                {"properties": dyn_schema.get("properties", {}), "required": dyn_schema.get("required", [])},
                                swagger,
                            )
                        else:
                            body_props, body_required = _extract_body_properties(schema, swagger)
                    else:
                        body_props, body_required = _extract_body_properties(schema, swagger)
                    continue

                if param.get("name") == "connectionId":
                    continue

                param_visibility = param.get("x-ms-visibility", "")
                if param_visibility == "internal":
                    continue

                params.append(ParsedParameter(
                    name=param.get("name", ""),
                    location=param_in,
                    type=param.get("type", "string"),
                    required=param.get("required", False),
                    description=param.get("description", param.get("x-ms-summary", "")),
                    format=param.get("format"),
                    enum=param.get("enum"),
                    default=param.get("default"),
                ))

            parsed = ParsedOperation(
                operation_id=operation_id,
                method=method.upper(),
                path=path,
                summary=summary,
                description=description,
                parameters=params,
                body_properties=body_props,
                body_required_fields=body_required,
            )

            annotation = op.get("x-ms-api-annotation", {})
            family = annotation.get("family")
            new_rev = annotation.get("revision", 0)
            if family:
                existing = seen_families.get(family)
                if existing is None:
                    seen_families[family] = (parsed, new_rev)
                    operations.append(parsed)
                else:
                    existing_op, existing_rev = existing
                    if new_rev > existing_rev:
                        operations.remove(existing_op)
                        seen_families[family] = (parsed, new_rev)
                        operations.append(parsed)
            else:
                operations.append(parsed)

    return operations


def _parse_resource_id(resource_id: str) -> dict:
    """Extract subscription, resource group, and name from a connection resource ID."""
    pattern = (
        r"/subscriptions/(?P<subscription>[^/]+)"
        r"/resourceGroups/(?P<resource_group>[^/]+)"
        r"/providers/Microsoft\.Web/connections/(?P<name>[^/]+)"
    )
    match = re.search(pattern, resource_id, re.IGNORECASE)
    if not match:
        raise ValueError(f"Invalid connection resource ID: {resource_id}")
    return match.groupdict()


async def load_connection(arm: ArmClient, resource_id: str) -> ConnectionInfo:
    """Fetch connection metadata and its Swagger spec, return a ConnectionInfo with parsed operations."""
    conn_data = await arm.get(resource_id)
    props = conn_data.get("properties", {})
    api_name = props.get("api", {}).get("name", "")
    display_name = props.get("displayName", "")
    statuses = props.get("statuses") or [{}]
    status = props.get("overallStatus", statuses[0].get("status", "Unknown"))
    location = conn_data.get("location", "")

    parts = _parse_resource_id(resource_id)
    swagger_path = (
        f"/subscriptions/{parts['subscription']}"
        f"/providers/Microsoft.Web/locations/{location}"
        f"/managedApis/{api_name}"
    )
    api_data = await arm.get(swagger_path, params={"export": "true"})
    swagger = api_data.get("properties", {}).get("swagger", {})
    if not swagger.get("paths"):
        swagger = api_data

    operations = await _parse_operations(swagger, arm, resource_id)

    return ConnectionInfo(
        resource_id=resource_id,
        name=parts["name"],
        api_name=api_name,
        display_name=display_name,
        status=status,
        location=location,
        operations=operations,
    )
