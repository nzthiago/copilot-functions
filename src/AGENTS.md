---
name: Anthony's chat agent
description: An agent that does awesome things
tools_from_connections:
  - connection_id: $SQL_CONNECTION_ID
  - connection_id: $TEAMS_CONNECTION_ID
execution_sandbox:
  session_pool_management_endpoint: $ACA_SESSION_POOL_ENDPOINT
---

You're a helpful assistant.