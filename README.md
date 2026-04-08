# copilot-functions (Experimental)

> **⚠️ This is an experimental package.** The APIs described here are under active development and subject to change.

A markdown-first programming model for building AI agents on Azure Functions with the [GitHub Copilot SDK](https://github.com/github/copilot-sdk).

Define your agent's behavior in a `.agent.md` file, add skills as knowledge modules, connect to external services via triggers and connectors, give your agent custom tools in plain Python, and extend it with external MCP servers. The runtime handles LLM orchestration, tool invocation, session management, and scaling.

## Installation

### From a GitHub release (`.whl`)

Install directly from the release URL:

```bash
pip install https://github.com/anthonychu/copilot-functions/releases/download/v0.2.1/copilot_functions-0.2.1-py3-none-any.whl
```

### From the GitHub repo

```bash
pip install copilot-functions @ git+https://github.com/anthonychu/copilot-functions.git
```

### With connector tools support

Connector tools (Teams, Office 365, SQL, Salesforce, etc.) require an optional extra:

```bash
# From release URL
pip install "copilot-functions[connectors] @ https://github.com/anthonychu/copilot-functions/releases/download/v0.2.1/copilot_functions-0.2.1-py3-none-any.whl"

# From repo
pip install "copilot-functions[connectors] @ git+https://github.com/anthonychu/copilot-functions.git"
```

## Quick Start

### 1. Create the agent file

Create `main.agent.md`:

```markdown
---
name: My Agent
description: A helpful assistant
---

You are a helpful assistant. Answer questions concisely.
```

### 2. Create the function app entry point

Create `function_app.py`:

```python
from copilot_functions import create_function_app

app = create_function_app()
```

> The app root is auto-detected from `AzureWebJobsScriptRoot` (set by `func start` and the Azure Functions host). You can override it with `create_function_app(app_root=Path(__file__).parent)` or the `COPILOT_APP_ROOT` env var.

### 3. Create `host.json`

```json
{
  "version": "2.0",
  "extensionBundle": {
    "id": "Microsoft.Azure.Functions.ExtensionBundle",
    "version": "[4.*, 5.0.0)"
  }
}
```

### 4. Create `requirements.txt`

```
https://github.com/anthonychu/copilot-functions/releases/download/v0.2.1/copilot_functions-0.2.1-py3-none-any.whl
```

Or use any other install method from the [Installation](#installation) section.

### 5. Start Azurite (local storage emulator)

The MCP server endpoint and non-HTTP triggers (timer, queue, blob, etc.) require a storage account. Locally, use [Azurite](https://learn.microsoft.com/azure/storage/common/storage-use-azurite) via Docker:

```bash
docker run -d -p 10000:10000 -p 10001:10001 -p 10002:10002 \
  mcr.microsoft.com/azure-storage/azurite \
  azurite --skipApiVersionCheck
```

Then set the storage connection string in `local.settings.json`:

```json
{
  "IsEncrypted": false,
  "Values": {
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "AzureWebJobsStorage": "UseDevelopmentStorage=true"
  }
}
```

> If you only need HTTP chat endpoints (no MCP, no triggers), you can skip Azurite and set `AzureWebJobsStorage` to `""`.

### 6. Run locally

```bash
func start
```

Your agent is now running at `http://localhost:7071/` with a built-in chat UI, HTTP API (`/agent/chat`, `/agent/chatstream`), and MCP server (`/runtime/webhooks/mcp`).

## Features

- **Markdown-first** — agent instructions, trigger config, and tool bindings in `.agent.md` files
- **Multi-function** — each `.agent.md` file becomes an Azure Function that runs the agent when triggered. `main.agent.md` creates HTTP/MCP endpoints; other files create event-triggered functions (timer, queue, Teams, blob, etc.)
- **HTTP APIs** — `POST /agent/chat` and `POST /agent/chatstream`
- **MCP server** — `/runtime/webhooks/mcp`
- **Chat UI** — built-in single-page UI at the app root
- **Skills** — reusable prompt modules from `SKILL.md` files
- **Custom tools** — drop a `.py` file in `tools/` and it becomes a callable tool
- **Connector tools** — dynamically generated tools from Azure API Connections
- **Sandbox environment with Playwright web browsing support** — code execution tool powered by Azure Container Apps dynamic sessions to run Python code and automate web browsing in a secure sandbox
- **Event triggers** — timer, queue, blob, Event Hub, Service Bus, Cosmos DB, Teams, Office 365, etc.
- **Session persistence** — Azure Files for multi-turn conversations

## Agent File Format (`.agent.md`)

Agent files use YAML frontmatter + markdown body:

```yaml
---
name: Agent Name
description: What this agent does

# Optional: connector tools
tools_from_connections:
  - connection_id: $SQL_CONNECTION_ID
    prefix: sales_db      # optional

# Optional: code interpreter
execution_sandbox:
  session_pool_management_endpoint: $ACA_SESSION_POOL_ENDPOINT

# For triggered agents only (not `main.agent.md`):
trigger:
  type: timer_trigger      # or queue_trigger, teams.new_channel_message_trigger, etc.
  schedule: "0 0 9 * * *"  # trigger-specific params passed as kwargs

logger: true               # optional, default true
---

Agent instructions in markdown...
```

### Multiple functions from markdown

- **`main.agent.md`** — creates HTTP chat, MCP, and UI endpoints. No other triggers are supported in this file.
- **`<name>.agent.md`** — creates an event-triggered Azure Function. Exactly one trigger per file. The filename (minus `.agent.md`) becomes the function name.

When a triggered function runs, the agent's markdown body is used as the system instructions. The prompt sent to the agent includes the trigger type and the serialized binding data:

```
Triggered by: service_bus_queue_trigger

Trigger data:
```json
{"body": "...", "message_id": "...", ...}
```​
```

This applies to all trigger types, including timers (whose data includes fields like `past_due`).

### Trigger type resolution

| Format | Resolves to | Example |
|---|---|---|
| No dots | `app.<type>(...)` | `timer_trigger`, `queue_trigger` |
| Dots | Connector library method | `teams.new_channel_message_trigger` |
| `connectors.` prefix | Explicit connector method | `connectors.generic_trigger` |

### Environment variable substitution

String values in `trigger.*` (except `type`), `tools_from_connections[].connection_id`, and `execution_sandbox.session_pool_management_endpoint` support `$VAR` or `%VAR%` syntax (full-string match only).

## What `main.agent.md` Enables

When a `main.agent.md` file exists in your app root, the runtime automatically registers:

### Chat UI

A built-in single-page chat interface served at the app root (`/`). No frontend code needed — just open `http://localhost:7071/` locally or `https://<your-app>.azurewebsites.net/` when deployed.

On first load, you'll be prompted for the base URL and a function key (for deployed apps). These are stored in browser local storage and can be changed via the gear icon.

### HTTP Chat API

Two POST endpoints for programmatic access:

- **`POST /agent/chat`** — JSON request/response. Returns `session_id`, `response`, and `tool_calls`.
- **`POST /agent/chatstream`** — streaming Server-Sent Events (SSE). Returns incremental text chunks, tool execution events, and a final message.

Pass `x-ms-session-id` header to continue a conversation across requests. If omitted, a new session is created automatically.

### MCP Server

An MCP-compatible endpoint at `/runtime/webhooks/mcp` that any MCP client (VS Code, Claude Desktop, etc.) can connect to. Requires the MCP extension system key in the `x-functions-key` header when deployed.

> **Storage required:** The MCP server and non-HTTP triggers require Azure Storage. Locally, run [Azurite](#5-start-azurite-local-storage-emulator). If you only need the HTTP chat endpoints, you can skip storage by setting `AzureWebJobsStorage` to `""`.

### Without `main.agent.md`

If there's no `main.agent.md`, the HTTP chat, MCP, and UI endpoints are all disabled. The app only runs triggered functions.

## MCP Server Configuration

You can give your agent access to external MCP servers by creating an `mcp.json` file (or `.vscode/mcp.json`) in the app root. Only **HTTP remote servers** are supported.

```json
{
  "servers": {
    "microsoft-learn": {
      "type": "http",
      "url": "https://learn.microsoft.com/api/mcp"
    }
  }
}
```

Tools from configured MCP servers are automatically available to the agent at runtime. Each server entry supports:

- **`type`** — `"http"` (required)
- **`url`** — the MCP server endpoint URL
- **`headers`** — optional HTTP headers (e.g. for authentication)
- **`tools`** — optional array of tool name patterns to allow (default: `["*"]`)

## Samples

See the [`samples/`](samples/) directory for complete, deployable example apps.

## Development

```bash
# Clone the repo
git clone https://github.com/anthonychu/copilot-functions.git
cd copilot-functions

# Install in development mode
pip install -e ".[connectors]"

# Build a wheel
pip install build
python -m build --wheel
# Output: dist/copilot_functions-0.2.1-py3-none-any.whl
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE.md](LICENSE.md).
