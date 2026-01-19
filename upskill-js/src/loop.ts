/**
 * Agentic Loop — Tool calling loop built on Vercel AI SDK.
 */

import { generateText, streamText, tool as aiTool, jsonSchema, type CoreMessage, type LanguageModel } from "ai";
import { openai } from "@ai-sdk/openai";
import { anthropic } from "@ai-sdk/anthropic";
import { z } from "zod";
import type { LLMConfig, Message, ToolSchema } from "./types.js";
import { SkillManager } from "./skills.js";
import { ToolManager } from "./tools.js";

// Environment variable configuration
const MAX_AGENT_ITERATIONS = parseInt(process.env.UPSKILL_MAX_AGENT_ITERATIONS || "50");
const DEBUG = process.env.UPSKILL_DEBUG === "true";

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
  toolManager: ToolManager
): Promise<string> {
  const { model, provider } = getModel(llmConfig.model);
  const allToolSchemas = toolManager.getToolSchemas();

  // Convert messages to AI SDK format
  const coreMessages: CoreMessage[] = messages.map(convertMessage);

  for (let iteration = 0; iteration < MAX_AGENT_ITERATIONS; iteration++) {
    const tools = buildAISDKTools(skillManager, toolManager, allToolSchemas, provider);

    const result = await generateText({
      model,
      system: systemPrompt,
      messages: coreMessages,
      tools: Object.keys(tools).length > 0 ? tools : undefined,
      temperature: llmConfig.temperature,
      maxTokens: llmConfig.max_tokens,
      maxSteps: 1, // We handle the loop ourselves
    });

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
      return result.text || "";
    }
  }

  // Max iterations reached
  return "";
}

/**
 * Run the agentic loop with streaming, yielding tokens as they arrive.
 */
export async function* runAgenticLoopStream(
  messages: Message[],
  systemPrompt: string,
  llmConfig: LLMConfig,
  skillManager: SkillManager,
  toolManager: ToolManager
): AsyncGenerator<string, void, unknown> {
  const { model, provider } = getModel(llmConfig.model);
  const allToolSchemas = toolManager.getToolSchemas();

  // Convert messages to AI SDK format
  const coreMessages: CoreMessage[] = messages.map(convertMessage);

  for (let iteration = 0; iteration < MAX_AGENT_ITERATIONS; iteration++) {
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
        yield part.textDelta;
        text += part.textDelta;
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
