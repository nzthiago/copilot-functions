# Markdown-Based Agents on Azure Functions (Experimental)

> **⚠️ This is an experimental feature.** The agent runtime, deployment model, and APIs described here are under active development and subject to change.

Today, you can build custom agents with GitHub Copilot. You define your agent's personality and behavior in a markdown file (`AGENTS.md`), add skills as knowledge files, and configure MCP servers for live data and actions. All of that just works in VS Code or Copilot CLI — locally, on your machine.

This repo demonstrates an experimental new runtime that lets you deploy the same markdown-based agent project to Azure Functions with zero code changes. The agent runs in the cloud, behind an HTTP API, and can be called from anywhere.

**Key features**

- Deploy markdown-based agents as an Azure Functions app
- Choose from GitHub models or Microsoft Foundry models to power your agent
- Built-in HTTP APIs for chatting with your agent (`POST /agent/chat`, `POST /agent/chatstream`)
- Built-in MCP server endpoint for remote MCP clients (`/runtime/webhooks/mcp`)
- Built-in single-page chat UI
- Automatic session persistence with Azure Files
- Run prompts on a schedule using timer triggers
- Trigger agents from external events like Teams channel messages using Azure connector triggers
- Dynamically generate tools from Azure API Connections (connectors)
- Give your agent custom tools written in plain Python

**Hosting your agent in Azure Functions**

Azure Functions is a serverless compute platform that already supports runtimes like JavaScript, Python, and .NET. An agent project with `AGENTS.md`, skills, and MCP servers is just another workload. This experiment adds a new runtime to Azure Functions that natively understands and runs markdown-based agent projects.

Development workflow:

1. Define and test your agent in VS Code as a standard Copilot project
2. Deploy the same project to Azure Functions with `azd up`
3. Your agent is now a cloud-hosted HTTP API — no rewrites needed

This repo includes a sample **Teams chat agent** that responds to messages in a Microsoft Teams channel and can create articles on demand.

## Project Structure

```
src/                           # Self-contained Azure Functions app
├── function_app.py            # Thin entry point (imports copilot_functions)
├── AGENTS.md                  # Agent instructions and behavior (+ optional frontmatter)
├── host.json                  # Azure Functions host configuration
├── requirements.txt           # Python dependencies
├── .funcignore                # Files to exclude from deployment
├── public/
│   └── index.html             # Built-in chat UI
├── tools/                     # Custom tools written in plain Python
│   ├── start_article_creation.py
│   └── get_article_creation_status.py
└── copilot_functions/         # Library: Azure Functions + Copilot SDK integration
    ├── app.py                 # create_function_app() factory
    ├── runner.py              # Agent execution and session management
    ├── tools.py               # Dynamic tool discovery from tools/
    ├── connector_tools.py     # Azure connector → Copilot tool generation
    ├── connectors.py          # ARM connector Swagger parsing
    ├── connector_tool_cache.py
    ├── client_manager.py      # CopilotClient singleton
    ├── sandbox.py             # ACA dynamic sessions (execute_python tool)
    ├── arm.py                 # ARM API client
    ├── config.py              # Session state config
    ├── mcp.py                 # MCP server config loading
    └── skills.py              # Skill directory discovery
```

The `src` folder is a complete Azure Functions Python app. `function_app.py` is a thin wrapper that calls `create_function_app()` from the `copilot_functions` library. Your agent definition lives in `AGENTS.md` and `tools/` — the library handles all the Copilot SDK integration, HTTP routes, MCP endpoints, and dynamic trigger registration.

`AGENTS.md` supports optional YAML frontmatter. The frontmatter can be used to take your agent beyond HTTP or a chat interface by integrating with Azure Functions' event-driven programming model. For example, you can define timer-triggered functions that run on a [schedule](#timer-triggers-from-agentsmd-frontmatter) without needing to write any Azure Functions code.

## Running Locally in VS Code

1. Open the `src` folder in VS Code
2. Enable the experimental setting: `chat.useAgentSkills`
3. Enable built-in tools in Copilot Chat
4. Start chatting with your agent in Copilot Chat

Your agent's instructions from `AGENTS.md`, skills from `.github/skills/`, and MCP servers from `.vscode/mcp.json` are all automatically loaded.

## Deploying to Azure Functions

### Prerequisites: Create a GitHub Personal Access Token

The Azure Functions deployment requires a GitHub token with Copilot permissions. GitHub Copilot SDK (which is used by Functions to run your agent) currently requires authentication to persist and resume sessions (even though sessions are stored locally). If you choose a GitHub model to power your agent (see [Model Selection](#model-selection)), the token is also used to access the model.

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

## Triggers from `AGENTS.md` Frontmatter

You can define event-driven agent runs directly in `src/AGENTS.md` frontmatter using a `functions` array. The agent supports multiple trigger types:

### Timer Triggers

Run your agent on a schedule:

```yaml
---
functions:
  - name: timerAgent
    trigger: timer
    schedule: "0 */2 * * * *"
    prompt: "What's the price of a Standard_D4s_v5 VM in East US?"
    logger: true
---
```

- `schedule` and `prompt` are required for timer entries.
- `name` is optional (a safe unique name is generated if omitted).
- `logger` is optional and defaults to `true`.

### Connector Triggers (Teams Channel Messages)

Trigger your agent when a new message appears in a Microsoft Teams channel:

```yaml
---
functions:
  - name: teams_chat_agent
    trigger: teams_new_channel_message
    connection_id: /subscriptions/.../providers/Microsoft.Web/connections/teams
    team_id: <team-guid>
    channel_id: <channel-id>
    min_interval: 30    # optional: seconds between polls when active (default: 60)
    max_interval: 120   # optional: max seconds between polls when idle (default: 300)
    logger: true
---
```

- `connection_id` is the ARM resource ID of an authenticated Azure API Connection for the Teams connector.
- `team_id` and `channel_id` identify the Teams channel to monitor.
- `min_interval` (optional, default: 60) — polling interval in seconds after items are found (fastest rate).
- `max_interval` (optional, default: 300) — maximum polling interval in seconds when idle (backoff cap).
- `connection_id`, `team_id`, and `channel_id` support [environment variable substitution](#environment-variable-substitution).
- When the trigger fires, the full Teams message JSON payload is passed as the prompt to the agent.

The connector trigger uses the [azure-functions-connectors](https://github.com/anthonychu/azure-functions-connectors-python) package, which polls the connector for new items and dispatches them via Azure Storage Queues.

**Prerequisites for connector triggers:**

1. An Azure API Connection resource (e.g., Teams) — created and authenticated via Azure Portal or CLI
2. The function app's managed identity must have `Microsoft.Web/connections/dynamicInvoke/action` and `Microsoft.Web/connections/read` permissions on the connection (Contributor or a custom role)
3. `AZURE_CLIENT_ID` app setting must be set to the managed identity's client ID (automatically configured by the included Bicep templates)
4. Azure Storage Queue and Table endpoints must be enabled (automatically configured by the included Bicep templates)

### Common Behavior

- `functions` section is optional.
- `name` is optional for all trigger types (a safe unique name is generated if omitted).
- `logger` defaults to `true`. When enabled, the agent's full output is logged including `session_id`, `response`, `response_intermediate`, and `tool_calls`.
- All trigger functions are registered at startup from frontmatter and run in the same runtime as `/agent/chat`.

### Environment Variable Substitution

Certain frontmatter fields support `%ENV_VAR%` or `$ENV_VAR` syntax to reference environment variables (app settings). Substitution is **full-string only** — the entire value must be a single variable reference (partial substitution like `prefix$VAR` is not supported).

**Fields that support substitution** (resource identifiers and endpoints):

| Section | Field |
|---------|-------|
| `functions[]` | `connection_id`, `team_id`, `channel_id` |
| `tools_from_connections[]` | `connection_id` |
| `execution_sandbox` | `session_pool_management_endpoint` |

Fields like `name`, `trigger`, `schedule`, `prompt`, `min_interval`, `max_interval`, and `logger` do **not** support substitution.

If an environment variable is not set, the original string is returned unchanged and a warning is logged.

## Dynamic Tools from Azure Connectors

You can give your agent tools that are dynamically discovered from Azure API Connections (managed connectors). Add a `tools_from_connections` section to your `AGENTS.md` frontmatter:

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

You can give your agent the ability to execute Python code in a sandboxed environment by adding an `execution_sandbox` section to your `AGENTS.md` frontmatter:

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

- **Python tools in `src/tools/` do not work locally** since they're not natively supported by Copilot. They are fully functional after deploying with `azd up`.
- **Use `azd up`, not `azd provision` + `azd deploy` separately.** The pre-package hook scripts don't run in the correct sequence when provision and deploy are executed independently.
- **Windows is not supported.** The packaging hooks are shell scripts (`.sh`) and require macOS, Linux, or WSL.

## Try It

1. Clone this repo
2. Open `src` in VS Code and chat with the agent locally (MCP and skills work; Python tools require cloud deployment)
3. Explore the `src` folder to see the agent definition
4. Run `azd up` to deploy to Azure Functions
5. Open your cloud-hosted chat UI at `/`
6. Optionally call `/agent/chat` (JSON) or `/agent/chatstream` (SSE) directly (see `test/test.cloud.http` for examples)
