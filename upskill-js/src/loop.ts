/**
 * Agentic Loop — Tool calling loop built on Vercel AI SDK.
 */

import { generateText, streamText, tool as aiTool, jsonSchema, type CoreMessage, type LanguageModel } from "ai";
import { openai } from "@ai-sdk/openai";
import { anthropic } from "@ai-sdk/anthropic";
import { z } from "zod";
import type { LLMConfig, Message, ToolSchema, StreamEvent, AgentResponse, ThinkingConfig } from "./types.js";
import { SkillManager } from "./skills.js";
import { ToolManager } from "./tools.js";

// Environment variable configuration
const MAX_AGENT_ITERATIONS = parseInt(process.env.UPSKILL_MAX_AGENT_ITERATIONS || "50");
const DEBUG = process.env.UPSKILL_DEBUG === "true";
// Rough character limit before proactive pruning (conservative estimate: 100k tokens * 4 chars)
const CONTEXT_CHAR_LIMIT = parseInt(process.env.UPSKILL_CONTEXT_CHAR_LIMIT || "400000");

/**
 * Estimate total character count in messages (rough proxy for context size).
 */
function estimateContextSize(messages: CoreMessage[]): number {
  let total = 0;
  for (const msg of messages) {
    if (typeof msg.content === "string") {
      total += msg.content.length;
    } else if (Array.isArray(msg.content)) {
      for (const part of msg.content) {
        if (part.type === "text") {
          total += part.text.length;
        } else if (part.type === "tool-call") {
          total += part.toolName.length + JSON.stringify(part.args).length;
        } else if (part.type === "tool-result") {
          total += String(part.result).length;
        }
      }
    }
  }
  return total;
}

/**
 * Prune context by removing middle messages.
 * Keeps first user message and last 10 messages.
 */
function pruneContext(messages: CoreMessage[]): CoreMessage[] {
  if (messages.length <= 12) {
    return messages;
  }

  // Find first user message
  let firstUserIdx = -1;
  for (let i = 0; i < messages.length; i++) {
    if (messages[i].role === "user") {
      firstUserIdx = i;
      break;
    }
  }

  const pruned: CoreMessage[] = [];

  // Add first user message
  if (firstUserIdx >= 0) {
    pruned.push(messages[firstUserIdx]);
  }

  // Add last 10 messages (excluding any we already added)
  const lastMessages = messages.slice(-10);
  for (const msg of lastMessages) {
    if (!pruned.includes(msg)) {
      pruned.push(msg);
    }
  }

  if (DEBUG) console.log(`[DEBUG] Pruned context from ${messages.length} to ${pruned.length} messages`);
  return pruned;
}

/**
 * Check if context is too large and prune if needed.
 * Uses simple character count heuristic.
 */
function pruneContextIfNeeded(messages: CoreMessage[]): CoreMessage[] {
  const charCount = estimateContextSize(messages);

  if (DEBUG) console.log(`[DEBUG] Context size: ${charCount} chars (limit: ${CONTEXT_CHAR_LIMIT})`);

  if (charCount < CONTEXT_CHAR_LIMIT) {
    return messages;
  }

  if (DEBUG) console.log(`[DEBUG] Context pruning triggered`);
  return pruneContext(messages);
}

/**
 * Check if an error is a context overflow error.
 */
function isContextOverflowError(error: unknown): boolean {
  const msg = String(error).toLowerCase();
  return msg.includes("context") || msg.includes("token") || msg.includes("too long") || msg.includes("maximum");
}

/**
 * Parse model string and return the appropriate AI SDK model instance.
 * Supports "provider/model" format (e.g., "openai/gpt-4o", "anthropic/claude-3-5-sonnet").
 */
function getModel(modelString: string): { model: LanguageModel; provider: string } {
  const parts = modelString.split("/");
  if (parts.length === 1) {
    // Default to OpenAI if no provider specified
    return { model: openai(modelString), provider: "openai" };
  }

  const provider = parts[0];
  const modelName = parts.slice(1).join("/");

  switch (provider) {
    case "openai":
      return { model: openai(modelName), provider: "openai" };
    case "anthropic":
      return { model: anthropic(modelName), provider: "anthropic" };
    default:
      // Try openai as fallback with full string
      return { model: openai(modelString), provider: "openai" };
  }
}

/**
 * Fix JSON Schema based on provider requirements.
 * Different providers have different schema validation rules.
 */
function fixJsonSchema(params: Record<string, unknown>, provider: string): Record<string, unknown> {
  const properties = (params.properties || {}) as Record<string, Record<string, unknown>>;
  const originalRequired = (params.required || []) as string[];
  const fixedProperties: Record<string, Record<string, unknown>> = {};

  // Formats that OpenAI doesn't support
  const openaiUnsupportedFormats = new Set(["uri", "uri-reference", "iri", "iri-reference"]);

  // Fix each property
  for (const [key, prop] of Object.entries(properties)) {
    const fixedProp: Record<string, unknown> = { ...prop };

    // All providers need a type
    if (!fixedProp.type) {
      fixedProp.type = "string";
    }

    // OpenAI-specific: remove unsupported formats
    if (provider === "openai") {
      if (fixedProp.format && openaiUnsupportedFormats.has(fixedProp.format as string)) {
        delete fixedProp.format;
      }
    }

    fixedProperties[key] = fixedProp;
  }

  // OpenAI strict mode: ALL properties must be in required
  // Other providers: preserve original required array
  const required = provider === "openai"
    ? Object.keys(fixedProperties)
    : originalRequired;

  const result: Record<string, unknown> = {
    type: "object",
    properties: fixedProperties,
  };

  if (required.length > 0) {
    result.required = required;
  }

  // OpenAI strict mode requires additionalProperties: false
  if (provider === "openai") {
    result.additionalProperties = false;
  }

  return result;
}

/**
 * Convert our ToolSchema to AI SDK tool format.
 */
function convertToolToAISDK(
  schema: ToolSchema,
  toolManager: ToolManager,
  provider: string
) {
  const params = schema.function.parameters as Record<string, unknown>;
  const fixedParams = fixJsonSchema(params, provider);

  return aiTool({
    description: schema.function.description || "",
    parameters: jsonSchema(fixedParams),
    execute: async (args) => {
      if (DEBUG) console.log(`[DEBUG] Executing tool: ${schema.function.name}`, args);
      const result = await toolManager.callTool(schema.function.name, args as Record<string, unknown>);
      if (DEBUG) console.log(`[DEBUG] Tool result: ${schema.function.name}`, result.slice(0, 200));
      return result;
    },
  });
}

/**
 * Build AI SDK tools from skill manager and tool manager.
 */
function buildAISDKTools(
  skillManager: SkillManager,
  toolManager: ToolManager,
  allToolSchemas: ToolSchema[],
  provider: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
): Record<string, any> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const tools: Record<string, any> = {};

  // Always include load_skill if there are skills
  if (skillManager.size > 0) {
    const loadSkillSchema = skillManager.getLoadSkillToolSchema();
    const toolDescriptions = toolManager.getToolDescriptions();
    tools["load_skill"] = aiTool({
      description: loadSkillSchema.function.description || "Load one or more skills",
      parameters: z.object({
        names: z.array(z.string()).describe("The names of the skills to load"),
      }),
      execute: async ({ names }) => {
        if (DEBUG) console.log(`[DEBUG] Loading skills: ${names.join(", ")}`);
        const result = skillManager.loadSkills(names, toolDescriptions);
        if (DEBUG) console.log(`[DEBUG] Skills loaded: ${names.join(", ")}`);
        return result.content;
      },
    });
  }

  // Add tools required by loaded skills
  if (skillManager.loadedCount > 0) {
    const requiredTools = skillManager.getRequiredTools();

    const schemasToAdd =
      requiredTools.size > 0
        ? allToolSchemas.filter((s) => requiredTools.has(s.function.name))
        : allToolSchemas;

    for (const schema of schemasToAdd) {
      tools[schema.function.name] = convertToolToAISDK(schema, toolManager, provider);
    }

    // Add load_reference if available
    const refSchema = skillManager.getLoadReferenceToolSchema();
    if (refSchema) {
      tools["load_reference"] = aiTool({
        description: refSchema.function.description || "Load a reference",
        parameters: z.object({
          skill_name: z.string().describe("The name of the skill"),
          reference_name: z.string().describe("The name of the reference to load"),
        }),
        execute: async ({ skill_name, reference_name }) => {
          const result = skillManager.loadReference(skill_name, reference_name);
          return result.content;
        },
      });
    }

    // Add load_script if available
    const scriptSchema = skillManager.getLoadScriptToolSchema();
    if (scriptSchema) {
      tools["load_script"] = aiTool({
        description: scriptSchema.function.description || "Load a script",
        parameters: z.object({
          skill_name: z.string().describe("The name of the skill"),
          script_name: z.string().describe("The name of the script to load"),
        }),
        execute: async ({ skill_name, script_name }) => {
          const result = skillManager.loadScript(skill_name, script_name);
          if (result.success) {
            return `\`\`\`${result.language}\n${result.content}\n\`\`\``;
          }
          return result.content;
        },
      });
    }
  }

  return tools;
}

/**
 * Convert our Message type to AI SDK CoreMessage format.
 */
function convertMessage(msg: Message): CoreMessage {
  if (msg.role === "tool") {
    return {
      role: "tool",
      content: [
        {
          type: "tool-result",
          toolCallId: msg.tool_call_id || "",
          toolName: "",
          result: msg.content || "",
        },
      ],
    };
  }

  if (msg.role === "assistant" && msg.tool_calls) {
    return {
      role: "assistant",
      content: [
        ...(msg.content ? [{ type: "text" as const, text: msg.content }] : []),
        ...msg.tool_calls.map((tc) => ({
          type: "tool-call" as const,
          toolCallId: tc.id,
          toolName: tc.function.name,
          args: JSON.parse(tc.function.arguments),
        })),
      ],
    };
  }

  return {
    role: msg.role as "system" | "user" | "assistant",
    content: msg.content || "",
  };
}

/**
 * Run the agentic loop until a final response is produced.
 */
export async function runAgenticLoop(
  messages: Message[],
  systemPrompt: string,
  llmConfig: LLMConfig,
  skillManager: SkillManager,
  toolManager: ToolManager,
  thinking?: ThinkingConfig
): Promise<AgentResponse> {
  const { model, provider } = getModel(llmConfig.model);
  const allToolSchemas = toolManager.getToolSchemas();

  // Convert messages to AI SDK format
  let coreMessages: CoreMessage[] = messages.map(convertMessage);

  // Track accumulated reasoning across iterations
  const accumulatedReasoning: string[] = [];

  for (let iteration = 0; iteration < MAX_AGENT_ITERATIONS; iteration++) {
    // Proactive pruning based on character count heuristic
    coreMessages = pruneContextIfNeeded(coreMessages);

    const tools = buildAISDKTools(skillManager, toolManager, allToolSchemas, provider);

    let result;
    try {
      result = await generateText({
        model,
        system: systemPrompt,
        messages: coreMessages,
        tools: Object.keys(tools).length > 0 ? tools : undefined,
        temperature: llmConfig.temperature,
        maxTokens: llmConfig.max_tokens,
        maxSteps: 1, // We handle the loop ourselves
        // Add thinking config if provided (Anthropic provider option)
        ...(thinking && provider === "anthropic" ? { experimental_thinking: { enabled: true, budgetTokens: thinking.budget_tokens } } : {}),
      });
    } catch (error) {
      // Reactive pruning on context overflow errors
      if (isContextOverflowError(error)) {
        if (DEBUG) console.log(`[DEBUG] Context overflow detected, pruning and retrying`);
        coreMessages = pruneContext(coreMessages);
        continue;
      }
      throw error;
    }

    // Capture reasoning if present (Vercel AI SDK returns it in result.reasoning)
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const reasoning = (result as any).reasoning;
    if (reasoning) {
      accumulatedReasoning.push(reasoning);
    }

    // Check if we have tool calls
    if (result.toolCalls && result.toolCalls.length > 0) {
      // Add assistant message with tool calls
      coreMessages.push({
        role: "assistant",
        content: [
          ...(result.text ? [{ type: "text" as const, text: result.text }] : []),
          ...result.toolCalls.map((tc) => ({
            type: "tool-call" as const,
            toolCallId: tc.toolCallId,
            toolName: tc.toolName,
            args: tc.args,
          })),
        ],
      });

      // Add tool results
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const toolResults = result.toolResults as any[];
      coreMessages.push({
        role: "tool",
        content: toolResults.map((tr) => ({
          type: "tool-result" as const,
          toolCallId: tr.toolCallId,
          toolName: tr.toolName,
          result: tr.result as string,
        })),
      });
    } else {
      // No tool calls - return final response
      return {
        content: result.text || "",
        reasoning: accumulatedReasoning.length > 0 ? accumulatedReasoning.join("\n\n") : null,
      };
    }
  }

  // Max iterations reached
  return {
    content: "",
    reasoning: accumulatedReasoning.length > 0 ? accumulatedReasoning.join("\n\n") : null,
  };
}

/**
 * Run the agentic loop with streaming, yielding events as they arrive.
 */
export async function* runAgenticLoopStream(
  messages: Message[],
  systemPrompt: string,
  llmConfig: LLMConfig,
  skillManager: SkillManager,
  toolManager: ToolManager,
  thinking?: ThinkingConfig
): AsyncGenerator<StreamEvent, void, unknown> {
  const { model, provider } = getModel(llmConfig.model);
  const allToolSchemas = toolManager.getToolSchemas();

  // Convert messages to AI SDK format
  let coreMessages: CoreMessage[] = messages.map(convertMessage);

  for (let iteration = 0; iteration < MAX_AGENT_ITERATIONS; iteration++) {
    // Proactive pruning based on character count heuristic
    coreMessages = pruneContextIfNeeded(coreMessages);

    if (DEBUG) console.log(`[DEBUG] Stream iteration ${iteration + 1}`);
    if (DEBUG) console.log(`[DEBUG] Messages count:`, coreMessages.length);
    if (DEBUG && coreMessages.length > 0) {
      const lastMsg = coreMessages[coreMessages.length - 1];
      console.log(`[DEBUG] Last message role:`, lastMsg.role);
      if (typeof lastMsg.content === 'string') {
        console.log(`[DEBUG] Last message content:`, lastMsg.content.slice(0, 100));
      } else if (Array.isArray(lastMsg.content)) {
        console.log(`[DEBUG] Last message content types:`, lastMsg.content.map((c: {type: string}) => c.type));
      }
    }
    const tools = buildAISDKTools(skillManager, toolManager, allToolSchemas, provider);
    if (DEBUG) console.log(`[DEBUG] Available tools:`, Object.keys(tools));

    const streamResult = streamText({
      model,
      system: systemPrompt,
      messages: coreMessages,
      tools: Object.keys(tools).length > 0 ? tools : undefined,
      temperature: llmConfig.temperature,
      maxTokens: llmConfig.max_tokens,
      maxSteps: 1, // We handle the loop ourselves
      // Add thinking config if provided (Anthropic provider option)
      ...(thinking && provider === "anthropic" ? { experimental_thinking: { enabled: true, budgetTokens: thinking.budget_tokens } } : {}),
    });

    // Consume the full stream to get both text and tool calls
    if (DEBUG) console.log(`[DEBUG] Starting full stream`);
    let text = "";
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const toolCallsAccum: any[] = [];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const toolResultsAccum: any[] = [];

    for await (const part of streamResult.fullStream) {
      if (part.type === "text-delta") {
        yield { type: "content", content: part.textDelta };
        text += part.textDelta;
      } else if (part.type === "reasoning") {
        // Vercel AI SDK emits reasoning events for extended thinking
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        yield { type: "reasoning", content: (part as any).textDelta || "" };
      } else if (part.type === "tool-call") {
        if (DEBUG) console.log(`[DEBUG] Tool call:`, part.toolName);
        toolCallsAccum.push(part);
      } else if (part.type === "tool-result") {
        if (DEBUG) console.log(`[DEBUG] Tool result for:`, part.toolName);
        toolResultsAccum.push(part);
      } else if (part.type === "finish") {
        if (DEBUG) console.log(`[DEBUG] Finish reason:`, part.finishReason);
      } else if (part.type === "error") {
        if (DEBUG) console.log(`[DEBUG] Error:`, part.error);
      }
    }
    if (DEBUG) console.log(`[DEBUG] Full stream complete, text length:`, text.length);

    const toolCalls = toolCallsAccum;
    const toolResults = toolResultsAccum;

    if (toolCalls && toolCalls.length > 0) {
      // Add assistant message with tool calls
      coreMessages.push({
        role: "assistant",
        content: [
          ...(text ? [{ type: "text" as const, text }] : []),
          ...toolCalls.map((tc) => ({
            type: "tool-call" as const,
            toolCallId: tc.toolCallId,
            toolName: tc.toolName,
            args: tc.args,
          })),
        ],
      });

      // Add tool results
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const typedToolResults = toolResults as any[];
      coreMessages.push({
        role: "tool",
        content: typedToolResults.map((tr) => ({
          type: "tool-result" as const,
          toolCallId: tr.toolCallId,
          toolName: tr.toolName,
          result: tr.result as string,
        })),
      });
    } else {
      // No tool calls - we're done
      if (DEBUG) console.log(`[DEBUG] No tool calls, returning. Text length:`, text.length);
      // Text was already yielded during streaming
      return;
    }
  }
}
