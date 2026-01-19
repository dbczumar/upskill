"""
Agentic Loop — Tool calling loop built on LiteLLM.

- Handle tool calls → execute → return results
- Use structured outputs internally for clean chat responses
- Handle context window exceeded errors with pruning
"""

from __future__ import annotations

import json
import logging
from typing import Any

import litellm
from litellm import completion, token_counter

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
) -> str:
    """
    Run the agentic loop until a final response is produced.

    Args:
        messages: The conversation history (user/assistant messages).
        system_prompt: The system prompt including AGENTS.md and skill summary.
        llm_config: LiteLLM configuration (model, temperature, etc.).
        skill_manager: The skill manager for progressive disclosure.
        tool_manager: The tool manager for MCP and local tools.

    Returns:
        The assistant's final text response.
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
            response = completion(
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

        # Check if we have a final response (no tool calls)
        if not message.tool_calls:
            return message.content or ""

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
                load_result = skill_manager.load_skill(arguments.get("name", ""))
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

    # If we hit max turns, return the last message content or empty string
    return ""


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
                response = completion(
                    messages=full_messages,
                    tools=tools,
                    timeout=UPSKILL_LLM_TIMEOUT_SECONDS.get(),
                    **llm_kwargs,
                )
            else:
                # Final call with structured output
                response = completion(
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
                load_result = skill_manager.load_skill(arguments.get("name", ""))
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
