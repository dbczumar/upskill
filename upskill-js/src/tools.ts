/**
 * Tool Manager — Unified tool interface for MCP and local tools.
 */

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { SSEClientTransport } from "@modelcontextprotocol/sdk/client/sse.js";
import type { MCPServerConfig, ToolInfo, ToolSchema } from "./types.js";
import { z, ZodType, ZodObject, ZodRawShape } from "zod";

// Environment variable configuration
const TOOL_TIMEOUT_MS = parseInt(process.env.UPSKILL_TOOL_TIMEOUT_MS || "30000");
const TOOL_MAX_RETRIES = parseInt(process.env.UPSKILL_TOOL_MAX_RETRIES || "3");
const TOOL_RETRY_BACKOFF_MS = parseInt(process.env.UPSKILL_TOOL_RETRY_BACKOFF_MS || "1000");

/**
 * Resolve config and environment variables in a string.
 * Supports ${config.x.y} and ${ENV_VAR} syntax.
 */
function resolveConfigVars(value: string, config: Record<string, unknown>): string {
  // Replace ${config.x.y} patterns
  let result = value.replace(/\$\{config\.([^}]+)\}/g, (_, path: string) => {
    const parts = path.split(".");
    let current: unknown = config;
    for (const part of parts) {
      if (current && typeof current === "object" && part in current) {
        current = (current as Record<string, unknown>)[part];
      } else {
        return `\${config.${path}}`; // Keep original if not found
      }
    }
    return String(current);
  });

  // Replace ${ENV_VAR} patterns with environment variables
  result = result.replace(/\$\{([^}]+)\}/g, (_, varName: string) => {
    return process.env[varName] || `\${${varName}}`;
  });

  return result;
}

// Type for local tool functions
type LocalToolFn = (args: Record<string, unknown>) => unknown | Promise<unknown>;

interface LocalTool {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  fn: LocalToolFn;
}

export class ToolManager {
  private mcpConfigs: MCPServerConfig[];
  private localToolPaths: string[];
  private config: Record<string, unknown>;

  private mcpClients: Map<string, Client> = new Map();
  private mcpTools: Map<string, { serverName: string; schema: Record<string, unknown> }> = new Map();
  private localTools: Map<string, LocalTool> = new Map();
  private toolInfos: ToolInfo[] = [];
  private initialized = false;

  constructor(
    mcpConfigs: MCPServerConfig[],
    localToolPaths: string[],
    config: Record<string, unknown> = {}
  ) {
    this.mcpConfigs = mcpConfigs;
    this.localToolPaths = localToolPaths;
    this.config = config;
  }

  /**
   * Initialize all MCP connections and load local tools.
   */
  async initialize(): Promise<void> {
    if (this.initialized) return;

    // Connect to MCP servers
    for (const config of this.mcpConfigs) {
      await this.connectMCPServer(config);
    }

    // Load local tools
    for (const toolPath of this.localToolPaths) {
      await this.loadLocalTools(toolPath);
    }

    this.initialized = true;
  }

  private async connectMCPServer(config: MCPServerConfig): Promise<void> {
    try {
      if (config.transport === "stdio") {
        await this.connectStdioServer(config);
      } else if (config.transport === "streamable_http" || config.transport === "http") {
        await this.connectHTTPServer(config);
      } else {
        console.warn(`Unknown transport: ${config.transport}`);
      }
    } catch (e) {
      console.warn(`Warning: Failed to connect to MCP server '${config.name}': ${e}`);
    }
  }

  private async connectStdioServer(config: MCPServerConfig): Promise<void> {
    if (!config.command) {
      throw new Error(`stdio transport requires 'command': ${config.name}`);
    }

    // Resolve config vars in args
    const args = (config.args || []).map((arg) => resolveConfigVars(arg, this.config));

    // Resolve config vars in env
    const env: Record<string, string> = { ...process.env } as Record<string, string>;
    for (const [key, value] of Object.entries(config.env || {})) {
      env[key] = resolveConfigVars(value, this.config);
    }

    const transport = new StdioClientTransport({
      command: config.command,
      args,
      env,
    });

    const client = new Client(
      { name: "upskill", version: "0.1.0" },
      { capabilities: {} }
    );

    await client.connect(transport);
    this.mcpClients.set(config.name, client);
    await this.discoverMCPTools(config.name, client);
  }

  private async connectHTTPServer(config: MCPServerConfig): Promise<void> {
    if (!config.url) {
      throw new Error(`HTTP transport requires 'url': ${config.name}`);
    }

    // Resolve config vars in URL and headers
    const url = resolveConfigVars(config.url, this.config);
    const headers: Record<string, string> = {};
    for (const [key, value] of Object.entries(config.headers || {})) {
      headers[key] = resolveConfigVars(value, this.config);
    }

    const transport = new SSEClientTransport(new URL(url), {
      requestInit: {
        headers,
      },
    });

    const client = new Client(
      { name: "upskill", version: "0.1.0" },
      { capabilities: {} }
    );

    await client.connect(transport);
    this.mcpClients.set(config.name, client);
    await this.discoverMCPTools(config.name, client);
  }

  private async discoverMCPTools(serverName: string, client: Client): Promise<void> {
    const result = await client.listTools();

    for (const tool of result.tools) {
      const toolName = tool.name;
      this.mcpTools.set(toolName, {
        serverName,
        schema: tool.inputSchema as Record<string, unknown>,
      });

      this.toolInfos.push({
        name: toolName,
        description: tool.description || "",
        parameters: (tool.inputSchema as Record<string, unknown>) || { type: "object", properties: {} },
        source: `mcp:${serverName}`,
      });
    }
  }

  private async loadLocalTools(toolPath: string): Promise<void> {
    try {
      // Dynamic import of the tool module
      const module = await import(toolPath);

      // Find all exported functions with _tool metadata
      for (const [name, value] of Object.entries(module)) {
        if (typeof value === "function" && (value as unknown as { _isTool?: boolean })._isTool) {
          const toolFn = value as LocalToolFn & {
            _toolName: string;
            _toolDescription: string;
            _toolSchema: Record<string, unknown>;
          };

          const toolName = toolFn._toolName || name;
          const description = toolFn._toolDescription || "";
          const parameters = toolFn._toolSchema || { type: "object", properties: {} };

          this.localTools.set(toolName, {
            name: toolName,
            description,
            parameters,
            fn: toolFn,
          });

          this.toolInfos.push({
            name: toolName,
            description,
            parameters,
            source: "local",
          });
        }
      }
    } catch (e) {
      console.warn(`Warning: Failed to load local tools from '${toolPath}': ${e}`);
    }
  }

  /**
   * Get tool schemas in OpenAI format.
   */
  getToolSchemas(): ToolSchema[] {
    return this.toolInfos.map((info) => ({
      type: "function",
      function: {
        name: info.name,
        description: info.description,
        parameters: info.parameters,
      },
    }));
  }

  /**
   * Get list of available tool names.
   */
  getToolNames(): string[] {
    return this.toolInfos.map((info) => info.name);
  }

  /**
   * Get a map of tool names to descriptions.
   */
  getToolDescriptions(): Map<string, string> {
    const descriptions = new Map<string, string>();
    for (const info of this.toolInfos) {
      descriptions.set(info.name, info.description);
    }
    return descriptions;
  }

  /**
   * Call a tool by name with retry logic.
   */
  async callTool(name: string, args: Record<string, unknown>): Promise<string> {
    let lastError: Error | null = null;

    for (let attempt = 0; attempt < TOOL_MAX_RETRIES; attempt++) {
      try {
        const result = await this.withTimeout(
          this.callToolImpl(name, args),
          TOOL_TIMEOUT_MS
        );
        return result;
      } catch (e) {
        lastError = e instanceof Error ? e : new Error(String(e));
        console.warn(`Tool '${name}' failed (attempt ${attempt + 1}/${TOOL_MAX_RETRIES}): ${lastError.message}`);

        if (attempt < TOOL_MAX_RETRIES - 1) {
          const backoff = TOOL_RETRY_BACKOFF_MS * Math.pow(2, attempt);
          await this.sleep(backoff);
        }
      }
    }

    return `Error: Tool '${name}' failed after ${TOOL_MAX_RETRIES} attempts: ${lastError?.message}`;
  }

  private async callToolImpl(name: string, args: Record<string, unknown>): Promise<string> {
    // Check MCP tools
    const mcpTool = this.mcpTools.get(name);
    if (mcpTool) {
      const client = this.mcpClients.get(mcpTool.serverName);
      if (!client) {
        throw new Error(`MCP server '${mcpTool.serverName}' not connected`);
      }

      const result = await client.callTool({ name, arguments: args });

      // Convert result to string
      if (result.content && Array.isArray(result.content)) {
        const parts: string[] = [];
        for (const item of result.content) {
          if (typeof item === "object" && item !== null && "text" in item) {
            parts.push(String(item.text));
          } else {
            parts.push(String(item));
          }
        }
        return parts.join("\n");
      }
      return String(result);
    }

    // Check local tools
    const localTool = this.localTools.get(name);
    if (localTool) {
      const result = await localTool.fn(args);
      if (result === null || result === undefined) {
        return "";
      }
      if (typeof result === "string") {
        return result;
      }
      return JSON.stringify(result);
    }

    throw new Error(`Unknown tool '${name}'`);
  }

  private withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error(`Timeout after ${ms}ms`));
      }, ms);

      promise
        .then((value) => {
          clearTimeout(timer);
          resolve(value);
        })
        .catch((err) => {
          clearTimeout(timer);
          reject(err);
        });
    });
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  /**
   * Close all MCP connections.
   */
  async close(): Promise<void> {
    for (const client of this.mcpClients.values()) {
      await client.close();
    }
    this.mcpClients.clear();
    this.mcpTools.clear();
    this.localTools.clear();
    this.toolInfos = [];
    this.initialized = false;
  }
}

/**
 * Tool metadata attached to decorated functions.
 */
export interface ToolMetadata {
  _isTool: true;
  _toolName: string;
  _toolDescription: string;
  _toolSchema: Record<string, unknown>;
}

/**
 * Options for the tool decorator.
 */
export interface ToolOptions<T extends ZodRawShape = ZodRawShape> {
  /** Tool name (defaults to function name) */
  name?: string;
  /** Tool description */
  description: string;
  /** Zod schema for parameters */
  parameters?: ZodObject<T>;
}

/**
 * Convert a Zod schema to JSON Schema format.
 */
function zodToJsonSchema(schema: ZodType): Record<string, unknown> {
  // Use zod's built-in JSON schema generation if available,
  // otherwise do a basic conversion
  if (schema instanceof z.ZodObject) {
    const shape = schema.shape;
    const properties: Record<string, unknown> = {};
    const required: string[] = [];

    for (const [key, value] of Object.entries(shape)) {
      const zodValue = value as ZodType;
      properties[key] = zodTypeToJsonSchema(zodValue);

      // Check if required (not optional/nullable)
      if (!zodValue.isOptional() && !zodValue.isNullable()) {
        required.push(key);
      }
    }

    return {
      type: "object",
      properties,
      ...(required.length > 0 ? { required } : {}),
    };
  }

  return { type: "object", properties: {} };
}

/**
 * Convert a single Zod type to JSON Schema.
 */
function zodTypeToJsonSchema(zodType: ZodType): Record<string, unknown> {
  const description = zodType.description;
  let schema: Record<string, unknown> = {};

  if (zodType instanceof z.ZodString) {
    schema = { type: "string" };
  } else if (zodType instanceof z.ZodNumber) {
    schema = { type: "number" };
  } else if (zodType instanceof z.ZodBoolean) {
    schema = { type: "boolean" };
  } else if (zodType instanceof z.ZodArray) {
    schema = {
      type: "array",
      items: zodTypeToJsonSchema(zodType.element),
    };
  } else if (zodType instanceof z.ZodEnum) {
    schema = {
      type: "string",
      enum: zodType.options,
    };
  } else if (zodType instanceof z.ZodOptional) {
    schema = zodTypeToJsonSchema(zodType.unwrap());
  } else if (zodType instanceof z.ZodNullable) {
    schema = zodTypeToJsonSchema(zodType.unwrap());
  } else if (zodType instanceof z.ZodDefault) {
    schema = zodTypeToJsonSchema(zodType._def.innerType);
  } else if (zodType instanceof z.ZodObject) {
    schema = zodToJsonSchema(zodType);
  } else {
    schema = { type: "string" }; // Default fallback
  }

  if (description) {
    schema.description = description;
  }

  return schema;
}

/**
 * Create a tool from a function with Zod schema validation.
 *
 * @example
 * ```typescript
 * const myTool = tool({
 *   name: "get_weather",
 *   description: "Get the current weather for a location",
 *   parameters: z.object({
 *     location: z.string().describe("The city name"),
 *     units: z.enum(["celsius", "fahrenheit"]).optional().describe("Temperature units"),
 *   }),
 * }, async (args) => {
 *   return `Weather in ${args.location}: 72°F`;
 * });
 * ```
 */
export function tool<T extends ZodRawShape, R>(
  options: ToolOptions<T>,
  fn: (args: z.infer<ZodObject<T>>) => R | Promise<R>
): ((args: z.infer<ZodObject<T>>) => R | Promise<R>) & ToolMetadata {
  const decorated = fn as ((args: z.infer<ZodObject<T>>) => R | Promise<R>) & ToolMetadata;

  decorated._isTool = true;
  decorated._toolName = options.name || fn.name || "unnamed_tool";
  decorated._toolDescription = options.description;
  decorated._toolSchema = options.parameters
    ? zodToJsonSchema(options.parameters)
    : { type: "object", properties: {} };

  return decorated;
}

/**
 * Simple tool decorator for functions without Zod schemas.
 * Uses the function name and an empty schema.
 *
 * @example
 * ```typescript
 * const myTool = simpleTool(
 *   "Get the current time",
 *   () => new Date().toISOString()
 * );
 * ```
 */
export function simpleTool<R>(
  description: string,
  fn: (args: Record<string, unknown>) => R | Promise<R>
): ((args: Record<string, unknown>) => R | Promise<R>) & ToolMetadata {
  const decorated = fn as ((args: Record<string, unknown>) => R | Promise<R>) & ToolMetadata;

  decorated._isTool = true;
  decorated._toolName = fn.name || "unnamed_tool";
  decorated._toolDescription = description;
  decorated._toolSchema = { type: "object", properties: {} };

  return decorated;
}
