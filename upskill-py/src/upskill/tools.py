"""
Tool Manager — Unified tool interface for MCP and local tools.

- Connect to MCP servers (stdio and HTTP transports)
- Load local Python tools (@tool decorator)
- Expose all tools to the agentic loop
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import logging
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, get_type_hints

logger = logging.getLogger(__name__)

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client

from upskill.environment_variables import (
    UPSKILL_TOOL_MAX_RETRIES,
    UPSKILL_TOOL_RETRY_BACKOFF,
    UPSKILL_TOOL_TIMEOUT_SECONDS,
)
from upskill.loader import MCPServerConfig


def _sanitize_schema(schema: dict) -> dict:
    """
    Sanitize a JSON schema to be compatible with OpenAI's function calling.

    Fixes common issues like arrays missing 'items'.
    """
    if not isinstance(schema, dict):
        return schema

    result = {}
    for key, value in schema.items():
        if isinstance(value, dict):
            value = _sanitize_schema(value)
        elif isinstance(value, list):
            value = [_sanitize_schema(v) if isinstance(v, dict) else v for v in value]
        result[key] = value

    # Fix array types missing 'items'
    if result.get("type") == "array" and "items" not in result:
        result["items"] = {"type": "string"}

    return result


@dataclass
class ToolInfo:
    """Information about an available tool."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    source: str  # "mcp:<server_name>" or "local"


def _resolve_config_vars(value: str, config: dict[str, Any]) -> str:
    """
    Resolve config references like ${config.jira.url} in a string.

    Supports both ${config.x.y} syntax and ${ENV_VAR} syntax.
    Config references are resolved first, then environment variables.
    """
    import re

    def replace_config_ref(match: re.Match) -> str:
        path = match.group(1)  # e.g., "jira.url"
        parts = path.split(".")
        current = config
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                # Config path not found, return original (let env var expansion handle it)
                return match.group(0)
        return str(current)

    # Replace ${config.x.y} patterns
    result = re.sub(r"\$\{config\.([^}]+)\}", replace_config_ref, value)

    # Then expand any remaining ${ENV_VAR} patterns
    result = os.path.expandvars(result)

    return result


@dataclass
class ToolManager:
    """
    Manages MCP servers and local tools.

    Provides a unified interface for tool discovery and invocation.
    """

    mcp_configs: list[MCPServerConfig]
    local_tool_paths: list[Path]
    config: dict[str, Any] = field(default_factory=dict)

    # Runtime state
    _exit_stack: AsyncExitStack = field(default_factory=AsyncExitStack)
    _mcp_sessions: dict[str, ClientSession] = field(default_factory=dict)
    _mcp_tools: dict[str, tuple[str, dict]] = field(
        default_factory=dict
    )  # tool_name -> (server_name, tool_schema)
    _local_tools: dict[str, Callable] = field(default_factory=dict)
    _tool_infos: list[ToolInfo] = field(default_factory=list)
    _initialized: bool = False

    async def initialize(self) -> None:
        """Initialize all MCP connections and load local tools."""
        if self._initialized:
            return

        logger.debug("Initializing ToolManager with %d MCP servers", len(self.mcp_configs))

        # Connect to MCP servers sequentially (anyio cancel scopes require same task)
        for config in self.mcp_configs:
            await self._connect_mcp_server(config)

        # Load local Python tools
        for path in self.local_tool_paths:
            self._load_local_tools(path)

        logger.debug("ToolManager initialized with %d tools", len(self._tool_infos))
        self._initialized = True

    async def _connect_mcp_server(self, config: MCPServerConfig) -> None:
        """Connect to an MCP server and discover its tools."""
        try:
            if config.transport == "stdio":
                await self._connect_stdio_server(config)
            elif config.transport in ("streamable_http", "http"):
                await self._connect_http_server(config)
            else:
                raise ValueError(f"Unknown transport: {config.transport}")
        except Exception as e:
            # Log but don't fail - allow agent to work with available tools
            print(f"Warning: Failed to connect to MCP server '{config.name}': {e}")

    async def _connect_stdio_server(self, mcp_config: MCPServerConfig) -> None:
        """Connect to a stdio-based MCP server."""
        if not mcp_config.command:
            raise ValueError(f"stdio transport requires 'command': {mcp_config.name}")

        # Resolve config references and environment variables in args
        resolved_args = [
            _resolve_config_vars(arg, self.config) for arg in mcp_config.args
        ]

        # Resolve config references and environment variables in env dict
        env = dict(os.environ)
        for key, value in mcp_config.env.items():
            env[key] = _resolve_config_vars(value, self.config)

        params = StdioServerParameters(
            command=mcp_config.command,
            args=resolved_args,
            env=env,
        )

        # Pass through MCP server stderr only when debug logging is enabled
        if logger.isEnabledFor(logging.DEBUG):
            errlog = sys.stderr
        else:
            errlog = open(os.devnull, "w")
            self._exit_stack.callback(errlog.close)

        streams_ctx = stdio_client(params, errlog=errlog)
        read_stream, write_stream = await self._exit_stack.enter_async_context(streams_ctx)

        session = ClientSession(read_stream, write_stream)
        await self._exit_stack.enter_async_context(session)
        await session.initialize()

        self._mcp_sessions[mcp_config.name] = session
        await self._discover_mcp_tools(mcp_config.name, session)

    async def _connect_http_server(self, mcp_config: MCPServerConfig) -> None:
        """Connect to an HTTP-based MCP server."""
        if not mcp_config.url:
            raise ValueError(f"HTTP transport requires 'url': {mcp_config.name}")

        # Resolve config references and environment variables in headers
        headers = {
            k: _resolve_config_vars(v, self.config)
            for k, v in mcp_config.headers.items()
        }

        # Use exit stack to manage context managers
        streams_ctx = streamablehttp_client(mcp_config.url, headers=headers)
        read_stream, write_stream, _ = await self._exit_stack.enter_async_context(streams_ctx)

        session = ClientSession(read_stream, write_stream)
        await self._exit_stack.enter_async_context(session)
        await session.initialize()

        self._mcp_sessions[mcp_config.name] = session
        await self._discover_mcp_tools(mcp_config.name, session)

    async def _discover_mcp_tools(self, server_name: str, session: ClientSession) -> None:
        """Discover tools from an MCP server."""
        result = await session.list_tools()
        logger.debug("Discovered %d tools from MCP server '%s'", len(result.tools), server_name)

        for tool in result.tools:
            # Use the tool name as-is from the MCP server
            tool_name = tool.name
            self._mcp_tools[tool_name] = (server_name, tool.model_dump())

            # Sanitize and convert MCP tool schema to OpenAI format
            schema = tool.inputSchema if tool.inputSchema else {"type": "object", "properties": {}}
            schema = _sanitize_schema(schema)

            self._tool_infos.append(
                ToolInfo(
                    name=tool_name,
                    description=tool.description or "",
                    parameters=schema,
                    source=f"mcp:{server_name}",
                )
            )

    def _load_local_tools(self, path: Path) -> None:
        """Load local Python tools from a file."""
        if not path.exists():
            logger.warning("Local tool file not found: %s", path)
            return

        try:
            # Load the module dynamically
            spec = importlib.util.spec_from_file_location(path.stem, path)
            if spec is None or spec.loader is None:
                logger.warning("Could not load module from %s", path)
                return

            module = importlib.util.module_from_spec(spec)
            sys.modules[path.stem] = module
            spec.loader.exec_module(module)

            # Find all @tool decorated functions
            for name, obj in inspect.getmembers(module):
                if callable(obj) and getattr(obj, "_is_tool", False):
                    tool_name = getattr(obj, "_tool_name", name)
                    description = getattr(obj, "_tool_description", "")
                    schema = getattr(obj, "_tool_schema", {"type": "object", "properties": {}})

                    self._local_tools[tool_name] = obj
                    self._tool_infos.append(
                        ToolInfo(
                            name=tool_name,
                            description=description,
                            parameters=schema,
                            source="local",
                        )
                    )
                    logger.debug("Loaded local tool '%s' from %s", tool_name, path)

        except Exception as e:
            logger.error("Failed to load local tools from %s: %s", path, e)

    def get_tool_schemas(self) -> list[dict]:
        """
        Get tool schemas in OpenAI/LiteLLM format.

        Returns a list of tool definitions for the LLM.
        """
        tools = []
        for info in self._tool_infos:
            tools.append({
                "type": "function",
                "function": {
                    "name": info.name,
                    "description": info.description,
                    "parameters": info.parameters,
                },
            })
        return tools

    def get_tool_names(self) -> list[str]:
        """Get list of available tool names."""
        return [info.name for info in self._tool_infos]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """
        Call a tool by name with the given arguments.

        Includes retry logic with exponential backoff and timeouts.

        Args:
            name: The tool name (may include server prefix for MCP tools).
            arguments: The arguments to pass to the tool.

        Returns:
            The tool's result as a string.
        """
        logger.debug("Calling tool '%s' with arguments: %s", name, arguments)

        last_error: Exception | None = None
        timeout = UPSKILL_TOOL_TIMEOUT_SECONDS.get()
        max_retries = UPSKILL_TOOL_MAX_RETRIES.get()
        base_backoff = UPSKILL_TOOL_RETRY_BACKOFF.get()

        for attempt in range(max_retries):
            try:
                result = await asyncio.wait_for(
                    self._call_tool_impl(name, arguments),
                    timeout=timeout,
                )
                return result

            except asyncio.TimeoutError:
                last_error = asyncio.TimeoutError(f"Tool '{name}' timed out after {timeout}s")
                logger.warning("Tool '%s' timed out (attempt %d/%d)", name, attempt + 1, max_retries)

            except Exception as e:
                last_error = e
                logger.warning("Tool '%s' failed (attempt %d/%d): %s", name, attempt + 1, max_retries, e)

            # Exponential backoff before retry (skip on last attempt)
            if attempt < max_retries - 1:
                backoff = base_backoff * (2 ** attempt)
                logger.debug("Retrying tool '%s' in %.1fs", name, backoff)
                await asyncio.sleep(backoff)

        # All retries exhausted
        return f"Error: Tool '{name}' failed after {max_retries} attempts: {last_error}"

    async def _call_tool_impl(self, name: str, arguments: dict[str, Any]) -> str:
        """Internal implementation of tool calling without retries/timeout."""
        # Check MCP tools
        if name in self._mcp_tools:
            server_name, tool_schema = self._mcp_tools[name]
            session = self._mcp_sessions.get(server_name)
            if not session:
                raise ConnectionError(f"MCP server '{server_name}' not connected")

            result = await session.call_tool(name, arguments)
            # Convert result to string
            if hasattr(result, "content"):
                # MCP returns content as a list of content items
                parts = []
                for item in result.content:
                    if hasattr(item, "text"):
                        parts.append(item.text)
                    else:
                        parts.append(str(item))
                return "\n".join(parts)
            return str(result)

        # Check local tools
        if name in self._local_tools:
            func = self._local_tools[name]

            # Convert dict arguments to Pydantic models if needed
            converted_args = _convert_args_to_pydantic(func, arguments)

            # Handle both sync and async functions
            if asyncio.iscoroutinefunction(func):
                result = await func(**converted_args)
            else:
                result = func(**converted_args)

            # Convert result to string
            if result is None:
                return ""
            if isinstance(result, str):
                return result
            return json.dumps(result)

        raise ValueError(f"Unknown tool '{name}'")

    async def close(self) -> None:
        """Close all MCP connections and reset state."""
        await self._exit_stack.aclose()
        self._exit_stack = AsyncExitStack()
        self._mcp_sessions.clear()
        self._mcp_tools.clear()
        self._tool_infos.clear()
        self._initialized = False


def _convert_args_to_pydantic(func: Callable, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Convert dict arguments to Pydantic models where the function expects them.

    If a function parameter is type-hinted as a Pydantic BaseModel and the
    corresponding argument is a dict, instantiate the model from the dict.
    """
    try:
        from pydantic import BaseModel

        hints = get_type_hints(func)
    except Exception:
        return arguments

    converted = {}
    for key, value in arguments.items():
        param_type = hints.get(key)

        # Check if the type hint is a Pydantic model and value is a dict
        if (
            param_type is not None
            and isinstance(param_type, type)
            and issubclass(param_type, BaseModel)
            and isinstance(value, dict)
        ):
            converted[key] = param_type(**value)
        else:
            converted[key] = value

    return converted


def _generate_tool_schema(func: Callable) -> dict[str, Any]:
    """
    Generate a JSON schema for a function's parameters.

    Uses Pydantic TypeAdapter for schema generation and docstring-parser
    for extracting parameter descriptions.
    """
    from pydantic import TypeAdapter

    try:
        hints = get_type_hints(func)
    except Exception:
        hints = {}

    # Parse docstring for parameter descriptions
    param_descriptions: dict[str, str] = {}
    try:
        from docstring_parser import parse as parse_docstring

        if func.__doc__:
            parsed = parse_docstring(func.__doc__)
            param_descriptions = {p.arg_name: p.description for p in parsed.params if p.description}
    except ImportError:
        logger.debug("docstring-parser not installed, skipping parameter descriptions")
    except Exception as e:
        logger.debug("Failed to parse docstring: %s", e)

    sig = inspect.signature(func)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue

        param_type = hints.get(param_name, str)

        # Use Pydantic TypeAdapter for schema generation
        try:
            param_schema = TypeAdapter(param_type).json_schema()
            # Remove unnecessary fields that Pydantic adds
            param_schema.pop("title", None)
        except Exception:
            param_schema = {"type": "string"}

        # Add description from docstring if available
        if param_name in param_descriptions:
            param_schema["description"] = param_descriptions[param_name]

        # Check if parameter has a default
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

        properties[param_name] = param_schema

    schema = {
        "type": "object",
        "properties": properties,
    }

    if required:
        schema["required"] = required

    return schema


def tool(func: Callable) -> Callable:
    """
    Decorator to mark a function as a tool.

    The function's docstring is used as the tool description.
    Type hints are used to generate the JSON schema.

    Example:
        @tool
        def add(a: int, b: int) -> int:
            '''Add two numbers together.'''
            return a + b

        @tool
        async def fetch_data(url: str) -> str:
            '''Fetch data from a URL.'''
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    return await response.text()
    """
    func._is_tool = True
    func._tool_name = func.__name__
    func._tool_description = (func.__doc__ or "").strip()
    func._tool_schema = _generate_tool_schema(func)
    return func
