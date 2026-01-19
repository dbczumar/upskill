"""
ChatAgent and Agent — Main user-facing interfaces for Upskill.

ChatAgent: Loads an agent repository and provides a simple run() method
for executing conversations.

Agent: Typed agent with input/output schemas for structured I/O.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import threading
import warnings
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Generic, TypeVar, get_args, get_origin
from weakref import WeakSet

from pydantic import BaseModel

# TODO: Fix our async usage of litellm - we're likely not properly awaiting their
# cleanup. This suppresses the symptom but we should fix the root cause.
warnings.filterwarnings(
    "ignore",
    message="coroutine.*was never awaited",
    module="litellm.*"
)

from upskill.loader import AgentConfig, load_agent
from upskill.loop import run_agentic_loop, run_agentic_loop_stream, run_agentic_loop_structured
from upskill.skills import SkillManager
from upskill.tools import ToolManager

# Type variables for Agent input/output
InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")

logger = logging.getLogger(__name__)

# Track all agents for automatic cleanup on exit
_active_agents: WeakSet[_BaseAgent] = WeakSet()


def _cleanup_agents():
    """Clean up all active agents on program exit."""
    for agent in list(_active_agents):
        try:
            agent._shutdown()
        except Exception:
            pass  # Best effort cleanup


atexit.register(_cleanup_agents)


class _BaseAgent:
    """
    Base class with shared functionality for ChatAgent and Agent.

    Handles event loop management, tool initialization, and lifecycle.
    """

    _config: AgentConfig
    _skill_manager: SkillManager
    _loop: asyncio.AbstractEventLoop | None
    _loop_thread: threading.Thread | None
    _tool_manager: ToolManager | None
    _closed: bool

    def _init_base(self, path: str | Path | None) -> None:
        """Initialize base agent state. Called by subclass __init__."""
        self._config = load_agent(path)

        # Persistent event loop and tool manager for connection reuse
        self._loop = None
        self._loop_thread = None
        self._tool_manager = None
        self._closed = False

        # Initialize MCP connections at startup (must happen before SkillManager)
        self._initialize_tools()

        # Create skill manager with tool descriptions for better skill selection
        tool_descriptions = self._tool_manager.get_tool_descriptions()
        self._skill_manager = SkillManager.from_skills(self._config.skills, tool_descriptions)

        # Validate that skills reference existing tools
        self._validate_skill_tools()

        # Register for automatic cleanup
        _active_agents.add(self)

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """Ensure we have a running event loop in a background thread."""
        if self._loop is None or not self._loop.is_running():
            self._loop = asyncio.new_event_loop()

            def run_loop():
                asyncio.set_event_loop(self._loop)
                self._loop.run_forever()

            self._loop_thread = threading.Thread(target=run_loop, daemon=True)
            self._loop_thread.start()
            logger.debug("Started background event loop")

        return self._loop

    def _initialize_tools(self) -> None:
        """Initialize all MCP connections at startup."""
        loop = self._ensure_loop()
        self._tool_manager = ToolManager(
            mcp_configs=self._config.mcp_servers,
            local_tool_paths=self._config.local_tool_paths,
            config=self._config.config,
        )
        future = asyncio.run_coroutine_threadsafe(
            self._tool_manager.initialize(), loop
        )
        future.result()  # Wait for initialization
        logger.debug("Initialized ToolManager with %d tools", len(self._tool_manager.get_tool_names()))

    def _validate_skill_tools(self) -> None:
        """Warn if skills reference tools that don't exist."""
        available_tools = set(self._tool_manager.get_tool_names())
        for skill in self._config.skills:
            for tool_name in skill.tools:
                if tool_name not in available_tools:
                    warnings.warn(
                        f"Skill '{skill.name}' requires tool '{tool_name}' which is not available. "
                        f"Available tools: {sorted(available_tools)}",
                        stacklevel=4,
                    )

    @property
    def skills(self) -> list[dict[str, str]]:
        """List of skill metadata (name and description)."""
        return [
            {"name": s.name, "description": s.description}
            for s in self._config.skills
        ]

    @property
    def instructions(self) -> str:
        """The agent's instructions from AGENTS.md."""
        return self._config.instructions

    def _build_system_prompt(self) -> str:
        """Build the full system prompt from AGENTS.md and skill summary."""
        parts = []

        # Add AGENTS.md instructions
        if self._config.instructions:
            parts.append(self._config.instructions)

        # Add skill summary for progressive disclosure
        skill_summary = self._skill_manager.get_skill_summary()
        if skill_summary:
            parts.append(skill_summary)

        # Add guidance on skill usage
        parts.append(
            "## How to Use Skills\n\n"
            "When handling a request:\n"
            "1. **Plan**: Think about what information you need to gather and what actions you need to take\n"
            "2. **Review**: Look at available skills and their tools - refine your plan based on what's possible\n"
            "3. **Check loaded skills**: See if already-loaded skills can handle part or all of the request\n"
            "4. **Load if needed**: Load additional skill(s) if your loaded skills aren't sufficient\n"
            "5. **Execute**: Use the tools to gather information and perform actions\n"
            "6. **Iterate**: If results aren't sufficient, revisit your plan and consider other skills/tools"
        )

        return "\n\n".join(parts)

    def _shutdown(self) -> None:
        """Internal shutdown - stops the event loop (subprocesses die automatically)."""
        if self._closed:
            return
        self._closed = True

        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._loop_thread:
                self._loop_thread.join(timeout=2)
            self._loop = None
            self._loop_thread = None
            logger.debug("Stopped background event loop")

    def close(self) -> None:
        """Close the agent and clean up resources. Optional - cleanup happens automatically on exit."""
        self._shutdown()

    def __del__(self) -> None:
        self._shutdown()


class ChatAgent(_BaseAgent):
    """
    A chat agent loaded from an Upskill repository.

    Example:
        agent = ChatAgent()  # Load from current directory
        response = agent.run(messages=[{"role": "user", "content": "Hello!"}])
        agent.close()  # Clean up when done
    """

    def __init__(self, path: str | Path | None = None) -> None:
        """
        Load an agent from the specified path.

        Args:
            path: Path to agent repository. Defaults to current directory.
        """
        self._init_base(path)

    def run(self, messages: list[dict[str, Any]]) -> str:
        """
        Run the agent with the given message history.

        Args:
            messages: List of messages in OpenAI format:
                [{"role": "user", "content": "..."}, ...]

        Returns:
            The assistant's response as a string.
        """
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(self.arun(messages), loop)
        return future.result()

    async def arun(self, messages: list[dict[str, Any]]) -> str:
        """
        Run the agent asynchronously with the given message history.

        Args:
            messages: List of messages in OpenAI format:
                [{"role": "user", "content": "..."}, ...]

        Returns:
            The assistant's response as a string.
        """
        system_prompt = self._build_system_prompt()

        return await run_agentic_loop(
            messages=messages,
            system_prompt=system_prompt,
            llm_config=self._config.llm,
            skill_manager=self._skill_manager,
            tool_manager=self._tool_manager,
        )

    def stream(self, messages: list[dict[str, Any]]) -> Iterator[str]:
        """
        Run the agent with streaming, yielding tokens as they arrive.

        Args:
            messages: List of messages in OpenAI format:
                [{"role": "user", "content": "..."}, ...]

        Yields:
            Text tokens as they are generated.
        """
        loop = self._ensure_loop()
        queue: Queue[str | None] = Queue()

        async def stream_to_queue():
            try:
                async for token in self.astream(messages):
                    queue.put(token)
            finally:
                queue.put(None)  # Signal completion

        future = asyncio.run_coroutine_threadsafe(stream_to_queue(), loop)

        while True:
            try:
                token = queue.get(timeout=0.1)
                if token is None:
                    break
                yield token
            except Empty:
                # Check if the coroutine has failed
                if future.done() and future.exception():
                    raise future.exception()

    async def astream(self, messages: list[dict[str, Any]]) -> AsyncIterator[str]:
        """
        Run the agent asynchronously with streaming, yielding tokens as they arrive.

        Args:
            messages: List of messages in OpenAI format:
                [{"role": "user", "content": "..."}, ...]

        Yields:
            Text tokens as they are generated.
        """
        system_prompt = self._build_system_prompt()

        async for token in run_agentic_loop_stream(
            messages=messages,
            system_prompt=system_prompt,
            llm_config=self._config.llm,
            skill_manager=self._skill_manager,
            tool_manager=self._tool_manager,
        ):
            yield token

    def __enter__(self) -> ChatAgent:
        return self

    def __exit__(self, *args) -> None:
        self._shutdown()


def _type_to_json_schema(t: type) -> dict[str, Any]:
    """Convert a Python type to a JSON schema."""
    # Handle Pydantic models
    if isinstance(t, type) and issubclass(t, BaseModel):
        return t.model_json_schema()

    # Handle basic types
    origin = get_origin(t)
    args = get_args(t)

    if t is str:
        return {"type": "string"}
    elif t is int:
        return {"type": "integer"}
    elif t is float:
        return {"type": "number"}
    elif t is bool:
        return {"type": "boolean"}
    elif t is None or t is type(None):
        return {"type": "null"}
    elif origin is list:
        if args:
            return {"type": "array", "items": _type_to_json_schema(args[0])}
        return {"type": "array"}
    elif origin is dict:
        if args and len(args) == 2:
            return {
                "type": "object",
                "additionalProperties": _type_to_json_schema(args[1]),
            }
        return {"type": "object"}
    elif t is dict:
        return {"type": "object"}
    elif t is list:
        return {"type": "array"}
    else:
        # Default to object for unknown types
        return {"type": "object"}


def _parse_output(value: str, output_type: type[OutputT]) -> OutputT:
    """Parse a string output into the specified type."""
    # Handle Pydantic models
    if isinstance(output_type, type) and issubclass(output_type, BaseModel):
        return output_type.model_validate_json(value)

    # Try to parse as JSON first
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = value

    # Handle basic types
    if output_type is str:
        return value if isinstance(value, str) else str(parsed)
    elif output_type is int:
        return int(parsed)
    elif output_type is float:
        return float(parsed)
    elif output_type is bool:
        return bool(parsed)
    elif output_type is dict or get_origin(output_type) is dict:
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    elif output_type is list or get_origin(output_type) is list:
        return parsed if isinstance(parsed, list) else [parsed]
    else:
        return parsed


def _format_input(value: InputT, input_type: type[InputT]) -> str:
    """Format an input value as a string for the LLM."""
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    elif isinstance(value, (dict, list)):
        return json.dumps(value)
    else:
        return str(value)


class Agent(_BaseAgent, Generic[InputT, OutputT]):
    """
    A typed agent with structured input/output schemas.

    Example with Pydantic models:
        class Query(BaseModel):
            question: str
            context: str | None = None

        class Answer(BaseModel):
            response: str
            confidence: float

        agent = Agent[Query, Answer](
            input_schema=Query,
            output_schema=Answer,
        )
        result = agent.run(Query(question="What is ML?"))
        print(result.response, result.confidence)

    Example with basic types:
        agent = Agent[str, dict](
            input_schema=str,
            output_schema=dict,
        )
        result = agent.run("Summarize this text")
        print(result)
    """

    def __init__(
        self,
        input_schema: type[InputT],
        output_schema: type[OutputT],
        path: str | Path | None = None,
    ) -> None:
        """
        Create a typed agent with structured I/O.

        Args:
            input_schema: The type for input (Pydantic model or Python type).
            output_schema: The type for output (Pydantic model or Python type).
            path: Path to agent repository. Defaults to current directory.
        """
        self._input_schema = input_schema
        self._output_schema = output_schema
        self._output_json_schema = _type_to_json_schema(output_schema)
        self._init_base(path)

    def _build_system_prompt(self) -> str:
        """Build the full system prompt with output format instructions."""
        # Get base system prompt
        base_prompt = super()._build_system_prompt()
        parts = [base_prompt] if base_prompt else []

        # Add output format instructions for Pydantic models
        if isinstance(self._output_schema, type) and issubclass(self._output_schema, BaseModel):
            schema_desc = json.dumps(self._output_json_schema, indent=2)
            parts.append(
                f"## Output Format\n\n"
                f"You must respond with valid JSON matching this schema:\n"
                f"```json\n{schema_desc}\n```"
            )

        return "\n\n".join(parts)

    def run(self, input_value: InputT) -> OutputT:
        """
        Run the agent with typed input and get typed output.

        Args:
            input_value: The input matching input_schema.

        Returns:
            The output matching output_schema.
        """
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(self.arun(input_value), loop)
        return future.result()

    async def arun(self, input_value: InputT) -> OutputT:
        """
        Run the agent asynchronously with typed input and get typed output.

        Args:
            input_value: The input matching input_schema.

        Returns:
            The output matching output_schema.
        """
        system_prompt = self._build_system_prompt()

        # Format input as user message
        input_str = _format_input(input_value, self._input_schema)
        messages = [{"role": "user", "content": input_str}]

        # Run with structured output
        result_str = await run_agentic_loop_structured(
            messages=messages,
            system_prompt=system_prompt,
            llm_config=self._config.llm,
            skill_manager=self._skill_manager,
            tool_manager=self._tool_manager,
            output_schema=self._output_schema,
        )

        return _parse_output(result_str, self._output_schema)

    def __enter__(self) -> Agent[InputT, OutputT]:
        return self

    def __exit__(self, *args) -> None:
        self._shutdown()
