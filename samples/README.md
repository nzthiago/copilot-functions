# Samples

Each subdirectory is a standalone Azure Functions app deployable with [`azd up`](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd).

| Sample | Trigger | Custom Tools | Connectors | MCP Servers | Skills | Sandbox | Chat UI |
|---|---|---|---|---|---|---|---|
| [basic-chat](basic-chat/) | HTTP | | | | | ✅ | ✅ |
| [daily-tech-news-email](daily-tech-news-email/) | Timer | | ✅ Office 365 | | | ✅ | |
| [daily-azure-report](daily-azure-report/) | Timer + HTTP | ✅ azure_rest | ✅ Office 365 | ✅ MS Learn | ✅ azure-resources | | ✅ |

See each sample's README for prerequisites and deployment instructions.
