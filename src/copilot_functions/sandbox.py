"""
ACA Dynamic Sessions sandbox — execute_python tool.

Provides an ``execute_python`` Copilot SDK tool backed by Azure Container Apps
dynamic sessions (code-interpreter pools).  Configured via the
``execution_sandbox`` block in AGENTS.md frontmatter.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.parse
from typing import Any, Dict, Optional
from uuid import uuid4

import aiohttp
from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider
from copilot import define_tool
from copilot.tools import Tool, ToolInvocation, ToolResult
from pydantic import BaseModel, Field

from .config import resolve_env_var

_API_VERSION = "2025-10-02-preview"

# ---------------------------------------------------------------------------
# Playwright helper that is pre-loaded into every sandbox session
# ---------------------------------------------------------------------------

_ACA_SESSION_SETUP = """
async def launch_browser(width=1280, height=800):
    from playwright.async_api import async_playwright
    p = await async_playwright().start()
    browser = await p.chromium.launch(
        headless=True,
        args=[
            f'--window-size={width},{height}',
            '--disable-blink-features=AutomationControlled',
            '--disable-extensions',
        ],
    )
    context = await browser.new_context(
        user_agent=(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/131.0.0.0 Safari/537.36'
        ),
        viewport={'width': width, 'height': height},
    )
    page = await context.new_page()
    return page
"""

# ---------------------------------------------------------------------------
# Tool description (ported from reference main.py)
# ---------------------------------------------------------------------------

_EXECUTE_PYTHON_DESCRIPTION = (
    "Execute Python code in a persistent sandboxed REPL backed by a"
    " Jupyter kernel. Returns JSON with result, stdout, and stderr.\n"
    "\n"
    "IMPORTANT: Only use this tool when you need to actually run code —"
    " computation, data processing, web browsing, file operations, etc."
    " Do NOT call this tool just to print text, format output, or display"
    " results you already have. Respond directly with text instead.\n"
    "\n"
    "Key behaviors:\n"
    "- State persists across calls: variables, imports, and files"
    " (/mnt/data/) are retained between invocations.\n"
    "- The last expression value is returned in 'result' (like a"
    " Jupyter cell). Use print() for explicit output to 'stdout'.\n"
    "- Top-level await is supported (Jupyter kernel).\n"
    "- Shell commands: use subprocess.run(), not '!' syntax.\n"
    "- Common packages are pre-installed: numpy, pandas, matplotlib,"
    " scikit-learn, playwright, etc.\n"
    "\n"
    "Returning binary data (images, screenshots):\n"
    "- Generate the data, base64-encode it, and print it to stdout.\n"
    "- Example for plots:\n"
    "  import matplotlib; matplotlib.use('Agg')\n"
    "  import matplotlib.pyplot as plt, base64, io\n"
    "  fig, ax = plt.subplots()\n"
    "  ax.plot([1,2,3],[4,5,6])\n"
    "  buf = io.BytesIO()\n"
    "  fig.savefig(buf, format='png'); buf.seek(0)\n"
    "  print(base64.b64encode(buf.read()).decode())\n"
    "  plt.close()\n"
    "\n"
    "Playwright (browser automation):\n"
    "- A helper is pre-loaded: page = await launch_browser()\n"
    "  Returns a Playwright Page with anti-detection settings.\n"
    "  Call it once, then reuse `page` across calls (state persists).\n"
    "- Use the async API with top-level await.\n"
    "- To see what's on a page, you can:\n"
    "  1. Take a screenshot (returns base64 you can analyze):\n"
    "     import base64\n"
    "     screenshot_bytes = await page.screenshot(full_page=False)\n"
    "     print(base64.b64encode(screenshot_bytes).decode())\n"
    "  2. Extract text from the DOM:\n"
    "     text = await page.inner_text('body')\n"
    "     elements = await page.query_selector_all('css selector')\n"
    "     for el in elements:\n"
    "         print(await el.text_content())\n"
    "  Prefer DOM extraction for structured data. Use screenshots\n"
    "  when you need to understand visual layout or image content.\n"
    "- Use CSS selectors and aria attributes to find and interact\n"
    "  with elements.\n"
    "- If a site blocks you with a CAPTCHA,\n"
    "  try to solve it first. If you're unable to,\n"
    "  try a different site rather than\n"
    "  retrying the same one.\n"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitize_input(code: str) -> str:
    """Strip backticks, whitespace, and 'python' prefix from LLM output."""
    code = re.sub(r"^(\s|`)*(?i:python)?\s*", "", code)
    code = re.sub(r"(\s|`)*$", "", code)
    return code


def _build_url(endpoint: str, session_id: str) -> str:
    base = endpoint.rstrip("/")
    encoded_id = urllib.parse.quote(session_id)
    return f"{base}/executions?api-version={_API_VERSION}&identifier={encoded_id}"


async def _execute_code(
    endpoint: str,
    code: str,
    session_id: str,
    token_provider,
    http_session: aiohttp.ClientSession,
) -> str:
    """Execute Python code in an ACA dynamic session."""
    code = _sanitize_input(code)
    token = await token_provider()
    url = _build_url(endpoint, session_id)

    async with http_session.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "codeInputType": "Inline",
            "executionType": "Synchronous",
            "code": code,
            "timeoutInSeconds": 60,
        },
        timeout=aiohttp.ClientTimeout(total=120),
    ) as response:
        if response.status >= 400:
            body = await response.text()
            raise RuntimeError(f"ACA sessions API error ({response.status}): {body[:500]}")
        data = await response.json()

    result = data.get("result", {})
    return json.dumps(
        {
            "result": result.get("executionResult"),
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# Sandbox cache (singleton, like _ConnectorToolCache)
# ---------------------------------------------------------------------------


class _SandboxCache:
    """Lazy-init singleton for the execute_python tool."""

    def __init__(self):
        self._tools: list | None = None
        self._endpoint: str = ""
        self._lock = asyncio.Lock()
        self._credential: Optional[DefaultAzureCredential] = None
        self._token_provider = None
        self._http_session: Optional[aiohttp.ClientSession] = None

    def configure(self, config: Dict[str, Any]) -> None:
        raw_endpoint = config.get("session_pool_management_endpoint", "")
        if not raw_endpoint:
            logging.warning("execution_sandbox: missing 'session_pool_management_endpoint', skipping")
            return
        self._endpoint = resolve_env_var(str(raw_endpoint))
        if not self._endpoint or self._endpoint.startswith("$") or self._endpoint.startswith("%"):
            logging.warning(
                f"execution_sandbox: could not resolve endpoint '{raw_endpoint}', skipping"
            )
            self._endpoint = ""
            return
        logging.info(f"execution_sandbox: configured with endpoint {self._endpoint}")

    async def get_tools(self) -> list:
        if self._tools is not None:
            return self._tools

        async with self._lock:
            if self._tools is not None:
                return self._tools

            if not self._endpoint:
                self._tools = []
                return self._tools

            # Lazily create the credential, token provider, and shared HTTP session
            self._credential = DefaultAzureCredential()
            self._token_provider = get_bearer_token_provider(
                self._credential, "https://dynamicsessions.io/.default"
            )
            self._http_session = aiohttp.ClientSession()
            logging.info("execution_sandbox: credential, token provider, and HTTP session initialized")

            endpoint = self._endpoint
            token_provider = self._token_provider
            http_session = self._http_session

            async def _handle_execute_python(invocation: ToolInvocation) -> ToolResult:
                args = invocation.arguments or {}
                code = args.get("code", "")
                if not code.strip():
                    return ToolResult(
                        text_result_for_llm='{"error": "No code provided"}',
                        result_type="failure",
                    )

                # Fresh session per invocation
                aca_session_id = str(uuid4())
                logging.info(
                    f"execution_sandbox: executing code in ACA session {aca_session_id} "
                    f"(copilot_session={invocation.session_id}, tool_call={invocation.tool_call_id})"
                )

                try:
                    # Pre-load Playwright helper
                    await _execute_code(endpoint, _ACA_SESSION_SETUP, aca_session_id, token_provider, http_session)

                    # Execute the user's code
                    result = await _execute_code(endpoint, code, aca_session_id, token_provider, http_session)
                    logging.info(
                        f"execution_sandbox: ACA session {aca_session_id} completed successfully"
                    )
                    return ToolResult(text_result_for_llm=result, result_type="success")
                except Exception as exc:
                    error_msg = f"{type(exc).__name__}: {exc}"
                    logging.error(f"execution_sandbox: ACA session {aca_session_id} failed: {error_msg}")
                    return ToolResult(
                        text_result_for_llm=json.dumps({"error": error_msg}),
                        result_type="failure",
                    )

            tool = Tool(
                name="execute_python",
                description=_EXECUTE_PYTHON_DESCRIPTION,
                parameters={
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Python code to execute",
                        },
                    },
                    "required": ["code"],
                },
                handler=_handle_execute_python,
            )

            self._tools = [tool]
            logging.info("execution_sandbox: execute_python tool registered")
            return self._tools


_cache = _SandboxCache()


def configure_sandbox(config: Dict[str, Any]) -> None:
    """Configure the sandbox from AGENTS.md ``execution_sandbox`` frontmatter."""
    _cache.configure(config)


async def get_sandbox_tools() -> list:
    """Return the sandbox tools (lazy-init on first call)."""
    return await _cache.get_tools()
