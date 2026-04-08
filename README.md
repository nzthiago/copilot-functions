# Markdown Agents for Azure Functions (Experimental)

> **⚠️ This is an experimental feature.** The agent runtime, programming model, and APIs described here are under active development and subject to change.

Build AI agents on Azure Functions using markdown. Define your agent's behavior in a `.agent.md` file, add skills as knowledge modules, connect to external services via triggers and connectors, and give your agent custom tools in plain Python. The runtime handles the rest — LLM orchestration, tool invocation, session management, and scaling.

**Key features**

- **Markdown-first programming model** — agent instructions, trigger configuration, and tool/connector bindings defined in `.agent.md` files
- **Multi-agent support** — a main agent for HTTP/MCP access, plus any number of event-triggered agents (timer, queue, Teams, blob, etc.)
- **Built-in HTTP APIs** for chatting with your agent (`POST /agent/chat`, `POST /agent/chatstream`)
- **Built-in MCP server** endpoint for remote MCP clients (`/runtime/webhooks/mcp`)
- **Built-in chat UI** at the app root
- **Skills** — reusable prompt modules loaded from `SKILL.md` files
- **Custom Python tools** — drop a `.py` file in `tools/` and it becomes a tool the agent can call
- **Azure connector tools** — dynamically generate tools from Azure API Connections (Teams, Office 365, SQL, Salesforce, etc.)
- **Execution sandbox** — give your agent a sandboxed Python environment for computation and web browsing
- **Event-driven triggers** — map any Azure Functions trigger (timer, queue, blob, Event Hub, Service Bus, Cosmos DB) or connector trigger (Teams, Office 365, SharePoint) to an agent
- **Session persistence** with Azure Files for multi-turn conversations
- **Model choice** — GitHub models (Copilot API) or Microsoft Foundry models (your own Azure deployment)

**How it works**

Azure Functions is a serverless compute platform that supports runtimes like JavaScript, Python, and .NET. This experiment adds an agent programming model on top of the Python runtime: you write markdown and YAML, the runtime turns it into a fully-hosted agent with HTTP endpoints, event triggers, and tool orchestration powered by the [GitHub Copilot SDK](https://github.com/github/copilot-sdk).

```
main.agent.md          →  HTTP chat API + MCP server + chat UI
daily_report.agent.md  →  Timer-triggered agent (runs on schedule)
email_handler.agent.md →  Connector-triggered agent (reacts to new emails)
tools/*.py             →  Custom tools the agents can call
skills/*/SKILL.md      →  Reusable knowledge modules
```

## Project Structure

```
src/                           # Self-contained Azure Functions app
├── function_app.py            # Thin entry point (imports copilot_functions)
├── main.agent.md              # Main agent (chat endpoints, MCP, UI)
├── *.agent.md                 # Additional triggered agents (one trigger each)
├── host.json                  # Azure Functions host configuration
├── requirements.txt           # Python dependencies
├── .funcignore                # Files to exclude from deployment
├── skills/                    # Skills (reusable prompt modules with SKILL.md)
├── tools/                     # Custom tools written in plain Python
│   ├── start_article_creation.py
│   └── get_article_creation_status.py
└── copilot_functions/         # Library: Azure Functions + Copilot SDK integration
    ├── app.py                 # create_function_app() factory
    ├── runner.py              # Agent execution and session management
    ├── tools.py               # Dynamic tool discovery + built-in file tools
    ├── connector_tools.py     # Azure connector → Copilot tool generation
    ├── connectors.py          # ARM connector Swagger parsing
    ├── connector_tool_cache.py
    ├── client_manager.py      # CopilotClient singleton
    ├── sandbox.py             # ACA dynamic sessions (execute_python tool)
    ├── arm.py                 # ARM API client
    ├── config.py              # App root resolution, env var substitution, session config
    ├── mcp.py                 # MCP server config loading
    ├── skills.py              # Skill directory discovery
    └── public/
        └── index.html         # Built-in chat UI
```

The `src` folder is a complete Azure Functions Python app. `function_app.py` is a thin entry point — the `copilot_functions` library handles agent loading, tool discovery, trigger registration, and LLM orchestration.

### Multi-agent architecture

Agents are defined as markdown files in the `src` folder:

- **`main.agent.md`** — The primary agent. Accessible via HTTP chat endpoints (`/agent/chat`, `/agent/chatstream`), MCP, and the built-in chat UI. If this file doesn't exist, those endpoints are disabled. Has no trigger — it responds to HTTP requests.
- **`<name>.agent.md`** — Triggered agents. Each defines exactly **one trigger** (timer, queue, Teams message, etc.) and runs automatically when that event fires. The filename (minus `.agent.md`) becomes the Azure Functions function name.

All agents share the same `tools/`, `skills/`, and `copilot_functions/` library. Each agent can independently configure `tools_from_connections` and `execution_sandbox`.

## Running Locally

The agent can be run locally using Azure Functions Core Tools:

```bash
cd src
func start
```

This starts the Azure Functions host, registers all agents and triggers, and serves the chat UI at `http://localhost:7071/`.

Note: Connector triggers and connector tools require Azure API Connections and managed identity, so they only work when deployed to Azure. Timer triggers and the HTTP chat endpoints work locally.

## Deploying to Azure Functions

### Prerequisites: Create a GitHub Personal Access Token

The runtime uses the [GitHub Copilot SDK](https://github.com/github/copilot-sdk) for LLM orchestration, which requires a GitHub token for authentication and session persistence. If you choose a GitHub model (see [Model Selection](#model-selection)), the token is also used for model access.

1. Go to https://github.com/settings/personal-access-tokens/new
2. Under **Permissions**, click **+ Add permissions**
3. In the **Select account permissions** dropdown, check **Copilot Requests** (Read-only)
4. Click **Generate token** and save it securely

### Deploy with Azure Developer CLI

From the terminal, run the following command:

```bash
azd up
```

Within minutes, you have a fully deployed agent behind an HTTP API and a built-in chat UI. The same source code that runs locally in Copilot Chat now runs remotely on Azure Functions.

During deployment, you'll be prompted for:

| Prompt | Description |
|--------|-------------|
| **Azure Location** | Azure region for deployment |
| **GitHub Token** | Your GitHub PAT with Copilot Requests permission (required — used for session persistence and GitHub model access) |
| **Model Selection** | Which model to use (see below) |
| **VNet Enabled** | Whether to deploy with VNet integration |

You can also configure optional environment variables for Teams connector integration:

```bash
azd env set TEAMS_CONNECTION_ID "/subscriptions/.../providers/Microsoft.Web/connections/teams"
azd env set TEAMS_TEAM_ID "<team-guid>"
azd env set TEAMS_CHANNEL_ID "<channel-id>"
```

For the execution sandbox (code interpreter), configure:

```bash
azd env set ACA_SESSION_POOL_ENDPOINT "https://<region>.dynamicsessions.io/subscriptions/<sub-id>/resourceGroups/<rg>/sessionPools/<pool-name>"
```

#### Model Selection

You can choose from two categories of models:

- **GitHub models** (`github:` prefix) — Use the GitHub Copilot model API. No additional Azure infrastructure is deployed. Examples: `github:claude-sonnet-4.6`, `github:claude-opus-4.6`, `github:gpt-5.2`
- **Microsoft Foundry models** (`foundry:` prefix) — Deploys a Microsoft Foundry account and model in your subscription. Examples: `foundry:gpt-4.1-mini`, `foundry:claude-opus-4-6`, `foundry:o4-mini`

To change the model after initial deployment:

```bash
azd env set MODEL_SELECTION "github:gpt-5.2"
azd up
```

### Session Persistence

When running in Azure, agent sessions are automatically persisted to an Azure Files share mounted into the function app. This means conversation state survives across function app restarts and is shared across all instances, enabling multi-turn conversations with session resumption.

Locally, sessions are stored in `~/.copilot/session-state/`.

## Triggered Agents

Each `<name>.agent.md` file (other than `main.agent.md`) defines an event-driven agent with exactly one trigger. The trigger fires an Azure Function that runs the agent with the event data as the prompt.

### Frontmatter Structure

```yaml
---
name: Human-readable agent name
description: What this agent does
trigger:
  type: <trigger_type>
  # ... trigger-specific parameters (passed 1:1 to the decorator)
logger: true                   # optional, default true — log full agent responses
tools_from_connections:        # optional — same as main agent
  - connection_id: $CONNECTION_ID
execution_sandbox:             # optional — same as main agent
  session_pool_management_endpoint: $ACA_SESSION_POOL_ENDPOINT
---

Agent instructions go here...
```

The `trigger` section maps directly to an Azure Functions trigger decorator:
- `type` selects the decorator method
- All other fields are passed as keyword arguments
- `arg_name` is auto-generated (never specified in frontmatter)

### Trigger Type Resolution

| `type` format | Resolves to | Example |
|---|---|---|
| No dots (e.g. `timer_trigger`) | `app.timer_trigger(...)` | Built-in Azure Functions triggers |
| Dots (e.g. `teams.new_channel_message_trigger`) | Connector library method chain | [azure-functions-connectors](https://github.com/anthonychu/azure-functions-connectors-python) triggers |
| `connectors.` prefix (e.g. `connectors.generic_trigger`) | `connectors.generic_trigger(...)` | Disambiguates from built-in `generic_trigger` |

New triggers added to either library are automatically supported — no code changes needed.

### Timer Trigger

```yaml
---
name: Daily report
description: Generates a daily summary report
trigger:
  type: timer_trigger
  schedule: "0 0 9 * * *"
  run_on_startup: false
logger: true
---
```

### Teams Channel Message Trigger

```yaml
---
name: Teams chat agent
description: Responds to messages on a Teams channel
trigger:
  type: teams.new_channel_message_trigger
  connection_id: $TEAMS_CONNECTION_ID
  team_id: $TEAMS_TEAM_ID
  channel_id: $TEAMS_CHANNEL_ID
  min_interval: 30
  max_interval: 90
---
```

### Queue Trigger

```yaml
---
name: Order processor
description: Processes new orders from a queue
trigger:
  type: queue_trigger
  queue_name: new-orders
  connection: AzureWebJobsStorage
---
```

### Blob Trigger

```yaml
---
name: Document analyzer
description: Analyzes uploaded documents
trigger:
  type: blob_trigger
  path: uploads/{name}
  connection: AzureWebJobsStorage
---
```

### Event Hub Trigger

```yaml
---
name: Telemetry processor
description: Processes telemetry events
trigger:
  type: event_hub_message_trigger
  connection: EventHubConnection
  event_hub_name: telemetry
  consumer_group: $Default
---
```

### Service Bus Queue Trigger

```yaml
---
name: Task worker
description: Processes tasks from a Service Bus queue
trigger:
  type: service_bus_queue_trigger
  connection: ServiceBusConnection
  queue_name: tasks
---
```

### Cosmos DB Trigger

```yaml
---
name: Change feed processor
description: Reacts to Cosmos DB changes
trigger:
  type: cosmos_db_trigger_v3
  database_name: mydb
  collection_name: items
  connection_string_setting: CosmosDBConnection
---
```

### Generic Connector Trigger

Works with any Azure managed connector:

```yaml
---
name: Salesforce lead handler
description: Processes new Salesforce leads
trigger:
  type: connectors.generic_trigger
  connection_id: $SALESFORCE_CONNECTION_ID
  trigger_path: /trigger/datasets/default/tables/Lead/onnewitems
  min_interval: 60
  max_interval: 300
---
```

### Office 365 New Email Trigger

```yaml
---
name: Email processor
description: Processes incoming emails
trigger:
  type: office365.new_email_trigger
  connection_id: $OFFICE365_CONNECTION_ID
  folder: Inbox
---
```

### Common Behavior

- The agent's markdown body is used as system instructions.
- When a trigger fires, the event data is serialized to JSON and passed as the agent's prompt.
- `logger` defaults to `true`. When enabled, the agent's full output is logged including `session_id`, `response`, `response_intermediate`, and `tool_calls`.
- Each triggered agent can have its own `tools_from_connections` and `execution_sandbox` configuration.
- All triggered agents share the same custom tools from `tools/` and skills from `skills/`.

### Prerequisites for Connector Triggers

1. An Azure API Connection resource (e.g., Teams, Office 365) — created and authenticated via Azure Portal or CLI
2. The function app's managed identity must have `Microsoft.Web/connections/dynamicInvoke/action` and `Microsoft.Web/connections/read` permissions on the connection
3. `AZURE_CLIENT_ID` app setting must be set to the managed identity's client ID (automatically configured by the included Bicep templates)
4. Azure Storage Queue and Table endpoints must be enabled (automatically configured by the included Bicep templates)

### Environment Variable Substitution

Certain frontmatter fields support `%ENV_VAR%` or `$ENV_VAR` syntax to reference environment variables (app settings). Substitution is **full-string only** — the entire value must be a single variable reference (partial substitution like `prefix$VAR` is not supported).

All **string** values in the `trigger` section (except `type`) support substitution. Non-string values (booleans, integers) are passed through as-is.

Other fields that support substitution:

| Section | Field |
|---------|-------|
| `tools_from_connections[]` | `connection_id` |
| `execution_sandbox` | `session_pool_management_endpoint` |

Fields like `name`, `description`, `trigger.type`, and `logger` do **not** support substitution.

If an environment variable is not set, the original string is returned unchanged and a warning is logged.

## Dynamic Tools from Azure Connectors

You can give your agent tools that are dynamically discovered from Azure API Connections (managed connectors). Add a `tools_from_connections` section to your agent's frontmatter:

```yaml
---
tools_from_connections:
  - connection_id: /subscriptions/.../providers/Microsoft.Web/connections/teams
  - connection_id: /subscriptions/.../providers/Microsoft.Web/connections/office365
---
```

At startup (on first request), the runtime:

1. Fetches each connection's metadata and Swagger/OpenAPI spec from the ARM API
2. Parses all non-trigger, non-deprecated operations into tool definitions
3. Registers them as Copilot SDK tools with parameter schemas and descriptions
4. Each tool invokes its connector action via the ARM `dynamicInvoke` API

For example, a Teams connector generates ~30 tools including `teams_post_message_to_conversation`, `teams_reply_with_message_to_conversation`, `teams_create_channel`, `teams_list_members`, and more.

**Prerequisites:** Same RBAC and identity requirements as connector triggers (see above).

Connector tools are cached for the lifetime of the function app instance. If a connection fails to load, it logs a warning and continues with remaining connections.

## Execution Sandbox (Code Interpreter)

You can give your agent the ability to execute Python code in a sandboxed environment by adding an `execution_sandbox` section to your agent's frontmatter:

```yaml
---
execution_sandbox:
  session_pool_management_endpoint: $ACA_SESSION_POOL_ENDPOINT
---
```

When configured, the runtime registers an `execute_python` tool that executes code in [Azure Container Apps dynamic sessions](https://learn.microsoft.com/azure/container-apps/sessions). The sandbox provides:

- A persistent Jupyter kernel with common packages (numpy, pandas, matplotlib, scikit-learn, etc.)
- Playwright browser automation (a `launch_browser()` helper is pre-loaded)
- File storage at `/mnt/data/`
- 60-second execution timeout per call

Each tool invocation runs in a fresh session — state does not persist across calls.

**Prerequisites:**

1. An ACA session pool (code interpreter type) — create one in the Azure Portal or via CLI
2. The function app's managed identity must have the `Azure ContainerApps Session Executor` role on the session pool
3. Set the `ACA_SESSION_POOL_ENDPOINT` environment variable to the pool management endpoint URL

## Building Custom Tools with Python

You can add custom tools by dropping plain Python files into `src/tools/`.

Example:

```python
from pydantic import BaseModel, Field


class CostEstimatorParams(BaseModel):
    unit_price: float = Field(description="Retail price per unit")
    unit_of_measure: str = Field(description="Unit of measure, e.g. '1 Hour'")
    quantity: float = Field(description="Monthly quantity")


async def cost_estimator(params: CostEstimatorParams) -> str:
    """Estimate monthly and annual costs from unit price and usage."""
    monthly_cost = params.unit_price * params.quantity
    annual_cost = monthly_cost * 12
    return f"Monthly: ${monthly_cost:.4f} | Annual: ${annual_cost:.4f}"
```

How tool discovery works:

- At runtime, the function app scans `tools/*.py` for tool definitions.
- It loads module-level functions defined in that module and filters out names that start with `_`.
- The function docstring becomes the tool description (fallback: `Tool: <function_name>` if no docstring).
- It registers only one function per file (the first function returned from discovery, which is name-sorted).
- If a tool module fails to import/load, the runtime logs the error and continues.

Guidelines:

- Keep tool functions focused and deterministic.
- Prefer a typed params model (for example, a Pydantic `BaseModel`) and pass it as the function argument.
- Use clear type hints and docstrings.
- Add any Python dependencies your tools need to `src/requirements.txt`.

Important: custom Python tools run in the cloud runtime (Azure Functions). They are not executed in local Copilot Chat.

## Using the Chat UI (Root Route)

After deployment, open your function app root URL:

```text
https://<your-app>.azurewebsites.net/
```

The root route serves a built-in single-page chat UI.

At first load, enter:

- Base URL (typically your function app URL)
- Chat function key (see next section for how to get this)

These values are stored in browser local storage. You can reopen/edit them later via the gear icon.

You can also prefill both values via URL hash:

```text
https://<your-app>.azurewebsites.net/#baseUrl=https%3A%2F%2F<your-app>.azurewebsites.net&key=<url-encoded-key>
```

On load, the page reads and stores these values, then removes the hash from the address bar.

## Using MCP Server

The function app also exposes an MCP server endpoint:

```text
https://<your-app>.azurewebsites.net/runtime/webhooks/mcp
```

By default, this endpoint requires the MCP extension system key in the `x-functions-key` header.

### Get MCP Extension Key

```bash
# Get the function app name from azd
FUNC_NAME=$(azd env get-value AZURE_FUNCTION_NAME)

# Get the resource group
RG=$(az functionapp list --query "[?name=='$FUNC_NAME'].resourceGroup" -o tsv)

# Get the MCP extension system key
MCP_KEY=$(az functionapp keys list --name "$FUNC_NAME" --resource-group "$RG" --query systemKeys.mcp_extension -o tsv)
echo "$MCP_KEY"
```

### Example VS Code `mcp.json` Configuration (Secure Key Prompt)

Use `inputs` with `password: true` so the MCP key isn't hardcoded in the file.

```json
{
  "inputs": [
    {
      "type": "promptString",
      "id": "functions-mcp-extension-system-key",
      "description": "Azure Functions MCP Extension System Key",
      "password": true
    },
    {
      "type": "promptString",
      "id": "functionapp-host",
      "description": "Function app host, e.g. func-api-xxxx.azurewebsites.net"
    }
  ],
  "servers": {
    "remote-mcp-function": {
      "type": "http",
      "url": "https://${input:functionapp-host}/runtime/webhooks/mcp",
      "headers": {
        "x-functions-key": "${input:functions-mcp-extension-system-key}"
      }
    }
  }
}
```

## Using the API

Once deployed, your agent is available as an HTTP API with two chat endpoints:

- `POST /agent/chat` for standard JSON responses
- `POST /agent/chatstream` for streaming Server-Sent Events (SSE)

### Basic Request

```bash
curl -X POST "https://<your-app>.azurewebsites.net/agent/chat?code=<function-key>" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is the price of a Standard_D4s_v5 VM in East US?"}'
```

### Response

```json
{
  "session_id": "abc123-def456-...",
  "response": "The agent's final response text",
  "response_intermediate": "Any intermediate responses",
  "tool_calls": ["list of tools invoked during the response"]
}
```

The response always includes a `session_id` (also returned in the `x-ms-session-id` response header). Use this ID to continue the conversation.

### Multi-Turn Conversations

To resume an existing session, pass the session ID in the `x-ms-session-id` request header:

```bash
# Follow-up — resumes the same session with full conversation history
curl -X POST "https://<your-app>.azurewebsites.net/agent/chat?code=<function-key>" \
  -H "Content-Type: application/json" \
  -H "x-ms-session-id: abc123-def456-..." \
  -d '{"prompt": "If I run that VM 24/7 for a month, what would it cost?"}'
```

If you omit `x-ms-session-id`, a new session is created automatically and its ID is returned in the response. See `test/test.cloud.http` for more examples.

### Streaming Endpoint (SSE)

Use `POST /agent/chatstream` to receive responses incrementally as SSE events.

```bash
curl -N -X POST "https://<your-app>.azurewebsites.net/agent/chatstream?code=<function-key>" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"prompt": "Give me a quick summary of Azure Functions pricing in 3 bullets."}'
```

To resume an existing session, pass `x-ms-session-id` the same way as `/agent/chat`.

Typical streamed event types include:

- `session` (contains `session_id`)
- `delta` (incremental text chunks)
- `intermediate` (intermediate reasoning/response snippets)
- `tool_start` / `tool_end` (tool execution lifecycle metadata)
- `message` (final full response)
- `done` (stream completion)

Example SSE payload sequence:

```text
data: {"type":"session","session_id":"..."}

data: {"type":"delta","content":"Hello"}

data: {"type":"tool_start","tool_name":"bash","tool_call_id":"..."}

data: {"type":"message","content":"Hello...final"}

data: {"type":"done"}
```

### Getting the URL and Chat Function Key

After deployment, get the function app hostname and the `chat` function key using the Azure CLI:

```bash
# Get the function app name from azd
FUNC_NAME=$(azd env get-value AZURE_FUNCTION_NAME)

# Get the resource group
RG=$(az functionapp list --query "[?name=='$FUNC_NAME'].resourceGroup" -o tsv)

# Get the base URL
HOST=$(az functionapp show --name "$FUNC_NAME" --resource-group "$RG" --query defaultHostName -o tsv)
echo "https://$HOST"

# Get the chat function key
az functionapp function keys list --name "$FUNC_NAME" --resource-group "$RG" --function-name chat --query default -o tsv
```

Store these values in a `.env` file at the workspace root for use with `test/test.cloud.http` and the terminal snippets below:

```bash
BASE_URL=https://<your-app>.azurewebsites.net
FUNCTION_KEY=<your-chat-function-key>
```

> `.env` is gitignored by default — never commit secrets.

### Formatted Terminal Output with glow

The agent's `response` field contains Markdown. You can render it directly in the terminal using [`glow`](https://github.com/charmbracelet/glow) and [`jq`](https://jqlang.org):

```bash
# Install dependencies (macOS)
brew install glow jq
```

```bash
# Source your .env and call the agent
source .env && curl -s -X POST "$BASE_URL/agent/chat?code=$FUNCTION_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is the price of a Standard D4s v5 VM in East US?"}' \
  | jq -r '.response' \
  | glow -
```

For multi-turn conversations, capture the `session_id` from the first response and pass it via `x-ms-session-id`:

```bash
source .env

# Start a session
SESSION_ID=$(curl -s -X POST "$BASE_URL/agent/chat?code=$FUNCTION_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is the price of a Standard D4s v5 VM in East US?"}' \
  | jq -r '.session_id')

# Follow up in the same session
curl -s -X POST "$BASE_URL/agent/chat?code=$FUNCTION_KEY" \
  -H "Content-Type: application/json" \
  -H "x-ms-session-id: $SESSION_ID" \
  -d '{"prompt": "If I run that VM 24/7 for a month, what would it cost?"}' \
  | jq -r '.response' \
  | glow -
```

## Known Limitations

- **Connector triggers and tools require Azure deployment** — they depend on Azure API Connections and managed identity.
- **Use `azd up`, not `azd provision` + `azd deploy` separately.** The pre-package hook scripts don't run in the correct sequence when provision and deploy are executed independently.
- **Windows is not supported.** The packaging hooks are shell scripts (`.sh`) and require macOS, Linux, or WSL.

## Try It

1. Clone this repo
2. Explore `src/main.agent.md` and the other `.agent.md` files to see how agents are defined
3. Run `func start` in `src/` to test locally, or `azd up` to deploy to Azure
4. Open the chat UI at the app root URL
5. Call `/agent/chat` (JSON) or `/agent/chatstream` (SSE) directly (see `test/test.cloud.http` for examples)
