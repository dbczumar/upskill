"""
Agentic Loop — Tool calling loop built on LiteLLM.

- Handle tool calls → execute → return results
- Use structured outputs internally for clean chat responses
- Handle context window exceeded errors with pruning
- Support streaming responses
- Support extended thinking/reasoning
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

import litellm
from litellm import acompletion, token_counter


@dataclass
class StreamEvent:
    """A typed streaming event from the agentic loop."""
    type: Literal["reasoning", "content", "tool_call", "tool_result"]
    content: str


@dataclass
class AgentResponse:
    """Response from the agent with optional reasoning."""
    content: str
    reasoning: str | None = None

from upskill.environment_variables import (
    UPSKILL_CONTEXT_PRUNE_THRESHOLD,
    UPSKILL_LLM_MAX_RETRIES,
    UPSKILL_LLM_TIMEOUT_SECONDS,
    UPSKILL_MAX_AGENT_ITERATIONS,
)
from upskill.skills import SkillManager
from upskill.tools import ToolManager

logger = logging.getLogger(__name__)


async def run_agentic_loop(
    messages: list[dict[str, Any]],
    system_prompt: str,
    llm_config: dict[str, Any],
    skill_manager: SkillManager,
    tool_manager: ToolManager,
    thinking: dict[str, Any] | None = None,
) -> AgentResponse:
    """
    Run the agentic loop until a final response is produced.

    Args:
        messages: The conversation history (user/assistant messages).
        system_prompt: The system prompt including AGENTS.md and skill summary.
        llm_config: LiteLLM configuration (model, temperature, etc.).
        skill_manager: The skill manager for progressive disclosure.
        tool_manager: The tool manager for MCP and local tools.
        thinking: Optional thinking config for extended reasoning.
            Example: {"type": "enabled", "budget_tokens": 10000}

    Returns:
        AgentResponse with content and optional reasoning.
    """
    # Build the full message list with system prompt
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    # Get all tool schemas upfront (tools are pre-initialized)
    all_tool_schemas = tool_manager.get_tool_schemas()

    def get_available_tools() -> list[dict]:
        """Get tools based on loaded skills (progressive disclosure)."""
        tools = []

        # Always include load_skill if there are skills
        if skill_manager.skills:
            tools.append(skill_manager.get_load_skill_tool_schema())

        # Add MCP tools required by loaded skills
        if skill_manager.loaded_skills:
            required_tools = skill_manager.get_required_tools()
            if required_tools:
                # Only include tools required by loaded skills
                for schema in all_tool_schemas:
                    if schema["function"]["name"] in required_tools:
                        tools.append(schema)
            else:
                # Skill loaded but didn't specify tools - include all
                tools.extend(all_tool_schemas)

            # Add load_reference tool if any loaded skill has references
            ref_schema = skill_manager.get_load_reference_tool_schema()
            if ref_schema:
                tools.append(ref_schema)

            # Add load_script tool if any loaded skill has scripts
            script_schema = skill_manager.get_load_script_tool_schema()
            if script_schema:
                tools.append(script_schema)

        return tools

    # Build LiteLLM kwargs from config
    llm_kwargs = dict(llm_config)
    llm_kwargs["num_retries"] = UPSKILL_LLM_MAX_RETRIES.get()

    # Add thinking config if provided
    if thinking:
        llm_kwargs["thinking"] = thinking

    # Track accumulated reasoning across iterations
    accumulated_reasoning: list[str] = []

    max_iterations = UPSKILL_MAX_AGENT_ITERATIONS.get()
    iteration = 0
    while iteration < max_iterations:
        iteration += 1

        # Check and prune context if needed
        full_messages = _prune_context_if_needed(full_messages, llm_kwargs["model"])

        # Get currently available tools (progressive disclosure)
        tools = get_available_tools()

        # Call the LLM
        try:
            response = await acompletion(
                messages=full_messages,
                tools=tools if tools else None,
                timeout=UPSKILL_LLM_TIMEOUT_SECONDS.get(),
                **llm_kwargs,
            )
        except litellm.ContextWindowExceededError:
            # Aggressive pruning on context exceeded
            full_messages = _prune_context_aggressive(full_messages)
            continue

        choice = response.choices[0]
        message = choice.message

        # Capture reasoning if present
        if hasattr(message, "reasoning_content") and message.reasoning_content:
            accumulated_reasoning.append(message.reasoning_content)

        # Check if we have a final response (no tool calls)
        if not message.tool_calls:
            return AgentResponse(
                content=message.content or "",
                reasoning="\n\n".join(accumulated_reasoning) if accumulated_reasoning else None,
            )

        # Add assistant message with tool calls to history
        full_messages.append(message.model_dump())

        # Execute each tool call
        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            try:
                arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                arguments = {}

            # Handle skill-related tools specially
            if tool_name == "load_skill":
                load_result = skill_manager.load_skills(arguments.get("names", []))
                result = load_result.content
            elif tool_name == "load_reference":
                ref_result = skill_manager.load_reference(
                    arguments.get("skill_name", ""),
                    arguments.get("reference_name", ""),
                )
                result = ref_result.content
            elif tool_name == "load_script":
                script_result = skill_manager.load_script(
                    arguments.get("skill_name", ""),
                    arguments.get("script_name", ""),
                )
                # Include language hint for code interpreter
                if script_result.success:
                    result = f"```{script_result.language}\n{script_result.content}\n```"
                else:
                    result = script_result.content
            else:
                result = await tool_manager.call_tool(tool_name, arguments)
                logger.debug("Tool '%s' returned: %s", tool_name, result[:200] if len(result) > 200 else result)

            # Add tool result to history
            full_messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

    # If we hit max turns, return empty response
    return AgentResponse(
        content="",
        reasoning="\n\n".join(accumulated_reasoning) if accumulated_reasoning else None,
    )


async def run_agentic_loop_stream(
    messages: list[dict[str, Any]],
    system_prompt: str,
    llm_config: dict[str, Any],
    skill_manager: SkillManager,
    tool_manager: ToolManager,
    thinking: dict[str, Any] | None = None,
) -> AsyncIterator[StreamEvent]:
    """
    Run the agentic loop with streaming, yielding events as they arrive.

    Args:
        messages: The conversation history (user/assistant messages).
        system_prompt: The system prompt including AGENTS.md and skill summary.
        llm_config: LiteLLM configuration (model, temperature, etc.).
        skill_manager: The skill manager for progressive disclosure.
        tool_manager: The tool manager for MCP and local tools.
        thinking: Optional thinking config for extended reasoning.
            Example: {"type": "enabled", "budget_tokens": 10000}

    Yields:
        StreamEvent objects with type (reasoning, content) and content.
    """
    # Build the full message list with system prompt
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    # Get all tool schemas upfront (tools are pre-initialized)
    all_tool_schemas = tool_manager.get_tool_schemas()

    def get_available_tools() -> list[dict]:
        """Get tools based on loaded skills (progressive disclosure)."""
        tools = []

        # Always include load_skill if there are skills
        if skill_manager.skills:
            tools.append(skill_manager.get_load_skill_tool_schema())

        # Add MCP tools required by loaded skills
        if skill_manager.loaded_skills:
            required_tools = skill_manager.get_required_tools()
            if required_tools:
                for schema in all_tool_schemas:
                    if schema["function"]["name"] in required_tools:
                        tools.append(schema)
            else:
                tools.extend(all_tool_schemas)

            ref_schema = skill_manager.get_load_reference_tool_schema()
            if ref_schema:
                tools.append(ref_schema)

            script_schema = skill_manager.get_load_script_tool_schema()
            if script_schema:
                tools.append(script_schema)

        return tools

    # Build LiteLLM kwargs from config
    llm_kwargs = dict(llm_config)
    llm_kwargs["num_retries"] = UPSKILL_LLM_MAX_RETRIES.get()

    # Add thinking config if provided
    if thinking:
        llm_kwargs["thinking"] = thinking

    max_iterations = UPSKILL_MAX_AGENT_ITERATIONS.get()
    iteration = 0

    while iteration < max_iterations:
        iteration += 1

        # Check and prune context if needed
        full_messages = _prune_context_if_needed(full_messages, llm_kwargs["model"])

        # Get currently available tools (progressive disclosure)
        tools = get_available_tools()

        # Call the LLM with streaming
        try:
            response = await acompletion(
                messages=full_messages,
                tools=tools if tools else None,
                timeout=UPSKILL_LLM_TIMEOUT_SECONDS.get(),
                stream=True,
                **llm_kwargs,
            )
        except litellm.ContextWindowExceededError:
            full_messages = _prune_context_aggressive(full_messages)
            continue

        # Accumulate the response
        content_buffer = ""
        reasoning_buffer = ""
        tool_calls_buffer: dict[int, dict] = {}  # index -> {id, name, arguments}

        async for chunk in response:
            delta = chunk.choices[0].delta

            # Handle reasoning/thinking tokens (when extended thinking is enabled)
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                reasoning_buffer += delta.reasoning_content
                yield StreamEvent(type="reasoning", content=delta.reasoning_content)

            # Handle content tokens
            if delta.content:
                content_buffer += delta.content
                yield StreamEvent(type="content", content=delta.content)

            # Handle tool calls (accumulated across chunks)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_buffer:
                        tool_calls_buffer[idx] = {
                            "id": tc.id or "",
                            "name": tc.function.name if tc.function and tc.function.name else "",
                            "arguments": "",
                        }
                    if tc.id:
                        tool_calls_buffer[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_buffer[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_buffer[idx]["arguments"] += tc.function.arguments

        # Check if we have a final response (no tool calls)
        if not tool_calls_buffer:
            return

        # Build tool calls list for the assistant message
        tool_calls_list = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                },
            }
            for tc in tool_calls_buffer.values()
        ]

        # Add assistant message with tool calls to history
        full_messages.append({
            "role": "assistant",
            "content": content_buffer or None,
            "tool_calls": tool_calls_list,
        })

        # Execute each tool call
        for tc in tool_calls_buffer.values():
            tool_name = tc["name"]
            try:
                arguments = json.loads(tc["arguments"])
            except json.JSONDecodeError:
                arguments = {}

            # Handle skill-related tools specially
            if tool_name == "load_skill":
                load_result = skill_manager.load_skills(arguments.get("names", []))
                result = load_result.content
            elif tool_name == "load_reference":
                ref_result = skill_manager.load_reference(
                    arguments.get("skill_name", ""),
                    arguments.get("reference_name", ""),
                )
                result = ref_result.content
            elif tool_name == "load_script":
                script_result = skill_manager.load_script(
                    arguments.get("skill_name", ""),
                    arguments.get("script_name", ""),
                )
                if script_result.success:
                    result = f"```{script_result.language}\n{script_result.content}\n```"
                else:
                    result = script_result.content
            else:
                result = await tool_manager.call_tool(tool_name, arguments)
                logger.debug("Tool '%s' returned: %s", tool_name, result[:200] if len(result) > 200 else result)

            # Add tool result to history
            full_messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })


def _prune_context_if_needed(
    messages: list[dict[str, Any]], model: str
) -> list[dict[str, Any]]:
    """
    Check token count and prune if approaching context limit.

    Strategy: Keep system prompt, first user message, and last N messages.
    Drop middle messages, prioritizing tool call/result messages (most verbose).
    """
    try:
        count = token_counter(model=model, messages=messages)
    except Exception:
        # If token counting fails, don't prune
        return messages

    # Get model context window (default to 128k if unknown)
    try:
        max_tokens = litellm.get_model_info(model).get("max_input_tokens", 128000)
    except Exception:
        max_tokens = 128000

    # Start pruning at threshold capacity
    threshold = int(max_tokens * UPSKILL_CONTEXT_PRUNE_THRESHOLD.get())

    if count < threshold:
        return messages

    return _prune_context_aggressive(messages)


async def run_agentic_loop_structured(
    messages: list[dict[str, Any]],
    system_prompt: str,
    llm_config: dict[str, Any],
    skill_manager: SkillManager,
    tool_manager: ToolManager,
    output_schema: type,
) -> str:
    """
    Run the agentic loop with structured output enforcement.

    Similar to run_agentic_loop but uses response_format for the final response.

    Args:
        messages: The conversation history (user/assistant messages).
        system_prompt: The system prompt including AGENTS.md and skill summary.
        llm_config: LiteLLM configuration (model, temperature, etc.).
        skill_manager: The skill manager for progressive disclosure.
        tool_manager: The tool manager for MCP and local tools.
        output_schema: The Pydantic model or type for structured output.

    Returns:
        The assistant's final response as a JSON string.
    """
    from pydantic import BaseModel

    # Build the full message list with system prompt
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    # Get all tool schemas upfront (tools are pre-initialized)
    all_tool_schemas = tool_manager.get_tool_schemas()

    def get_available_tools() -> list[dict]:
        """Get tools based on loaded skills (progressive disclosure)."""
        tools = []

        # Always include load_skill if there are skills
        if skill_manager.skills:
            tools.append(skill_manager.get_load_skill_tool_schema())

        # Add MCP tools required by loaded skills
        if skill_manager.loaded_skills:
            required_tools = skill_manager.get_required_tools()
            if required_tools:
                for schema in all_tool_schemas:
                    if schema["function"]["name"] in required_tools:
                        tools.append(schema)
            else:
                tools.extend(all_tool_schemas)

            ref_schema = skill_manager.get_load_reference_tool_schema()
            if ref_schema:
                tools.append(ref_schema)

            script_schema = skill_manager.get_load_script_tool_schema()
            if script_schema:
                tools.append(script_schema)

        return tools

    # Build LiteLLM kwargs from config
    llm_kwargs = dict(llm_config)
    llm_kwargs["num_retries"] = UPSKILL_LLM_MAX_RETRIES.get()

    # Prepare response_format for structured output
    is_pydantic = isinstance(output_schema, type) and issubclass(output_schema, BaseModel)
    response_format_kwargs = {}
    if is_pydantic:
        response_format_kwargs["response_format"] = output_schema

    max_iterations = UPSKILL_MAX_AGENT_ITERATIONS.get()
    iteration = 0
    while iteration < max_iterations:
        iteration += 1

        # Check and prune context if needed
        full_messages = _prune_context_if_needed(full_messages, llm_kwargs["model"])

        # Get currently available tools (progressive disclosure)
        tools = get_available_tools()

        # Call the LLM
        try:
            # For structured output, we only apply response_format on the final call (no tools)
            # During tool-calling iterations, we don't want to constrain the format
            if tools:
                response = await acompletion(
                    messages=full_messages,
                    tools=tools,
                    timeout=UPSKILL_LLM_TIMEOUT_SECONDS.get(),
                    **llm_kwargs,
                )
            else:
                # Final call with structured output
                response = await acompletion(
                    messages=full_messages,
                    timeout=UPSKILL_LLM_TIMEOUT_SECONDS.get(),
                    **llm_kwargs,
                    **response_format_kwargs,
                )
        except litellm.ContextWindowExceededError:
            full_messages = _prune_context_aggressive(full_messages)
            continue

        choice = response.choices[0]
        message = choice.message

        # Check if we have a final response (no tool calls)
        if not message.tool_calls:
            content = message.content or ""
            # If structured output, it should already be JSON
            return content

        # Add assistant message with tool calls to history
        full_messages.append(message.model_dump())

        # Execute each tool call
        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            try:
                arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                arguments = {}

            if tool_name == "load_skill":
                load_result = skill_manager.load_skills(arguments.get("names", []))
                result = load_result.content
            elif tool_name == "load_reference":
                ref_result = skill_manager.load_reference(
                    arguments.get("skill_name", ""),
                    arguments.get("reference_name", ""),
                )
                result = ref_result.content
            elif tool_name == "load_script":
                script_result = skill_manager.load_script(
                    arguments.get("skill_name", ""),
                    arguments.get("script_name", ""),
                )
                if script_result.success:
                    result = f"```{script_result.language}\n{script_result.content}\n```"
                else:
                    result = script_result.content
            else:
                result = await tool_manager.call_tool(tool_name, arguments)
                logger.debug("Tool '%s' returned: %s", tool_name, result[:200] if len(result) > 200 else result)

            full_messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

    return ""


def _prune_context_aggressive(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Aggressively prune context by removing middle messages.

    Keeps:
    - System prompt (first message)
    - First user message (the task)
    - Last 10 messages

    Prioritizes removing tool call/result messages in the middle.
    """
    if len(messages) <= 12:
        return messages

    # Keep system prompt
    system_msg = messages[0] if messages[0].get("role") == "system" else None

    # Find first user message
    first_user_idx = None
    for i, msg in enumerate(messages):
        if msg.get("role") == "user":
            first_user_idx = i
            break

    # Build pruned list
    pruned = []

    if system_msg:
        pruned.append(system_msg)

    if first_user_idx is not None and first_user_idx != 0:
        pruned.append(messages[first_user_idx])

    # Add last 10 messages (excluding any we already added)
    last_messages = messages[-10:]
    for msg in last_messages:
        if msg not in pruned:
            pruned.append(msg)

    return pruned
