/**
 * Datetime and timezone utilities for Sidekick chatbot.
 *
 * These are local tools that provide time-related functionality.
 */

import { z, ZodObject, ZodRawShape, ZodType } from "zod";

// Tool metadata interface
interface ToolMetadata {
  _isTool: true;
  _toolName: string;
  _toolDescription: string;
  _toolSchema: Record<string, unknown>;
}

// Convert Zod schema to JSON Schema
function zodToJsonSchema(schema: ZodType): Record<string, unknown> {
  if (schema instanceof z.ZodObject) {
    const shape = schema.shape;
    const properties: Record<string, unknown> = {};
    const required: string[] = [];

    for (const [key, value] of Object.entries(shape)) {
      const zodValue = value as ZodType;
      properties[key] = zodTypeToJsonSchema(zodValue);
      if (!zodValue.isOptional()) {
        required.push(key);
      }
    }

    return { type: "object", properties, ...(required.length > 0 ? { required } : {}) };
  }
  return { type: "object", properties: {} };
}

function zodTypeToJsonSchema(zodType: ZodType): Record<string, unknown> {
  const description = zodType.description;
  let schema: Record<string, unknown> = {};

  if (zodType instanceof z.ZodString) {
    schema = { type: "string" };
  } else if (zodType instanceof z.ZodNumber) {
    schema = { type: "number" };
  } else if (zodType instanceof z.ZodBoolean) {
    schema = { type: "boolean" };
  } else if (zodType instanceof z.ZodOptional) {
    schema = zodTypeToJsonSchema(zodType.unwrap());
  } else if (zodType instanceof z.ZodDefault) {
    schema = zodTypeToJsonSchema(zodType._def.innerType);
  } else {
    schema = { type: "string" };
  }

  if (description) schema.description = description;
  return schema;
}

// Simple tool decorator
function tool<T extends ZodRawShape, R>(
  options: { name?: string; description: string; parameters?: ZodObject<T> },
  fn: (args: z.infer<ZodObject<T>>) => R
): ((args: z.infer<ZodObject<T>>) => R) & ToolMetadata {
  const decorated = fn as ((args: z.infer<ZodObject<T>>) => R) & ToolMetadata;
  decorated._isTool = true;
  decorated._toolName = options.name || fn.name || "unnamed_tool";
  decorated._toolDescription = options.description;
  decorated._toolSchema = options.parameters
    ? zodToJsonSchema(options.parameters)
    : { type: "object", properties: {} };
  return decorated;
}

// ============================================
// TOOLS
// ============================================

/**
 * Get the current time in a specific timezone.
 */
export const current_time = tool(
  {
    name: "current_time",
    description: "Get the current time in a specific timezone.",
    parameters: z.object({
      timezone: z
        .string()
        .default("UTC")
        .describe("IANA timezone name (e.g., 'America/New_York', 'Europe/London')"),
    }),
  },
  ({ timezone = "UTC" }) => {
    try {
      const now = new Date();
      const formatter = new Intl.DateTimeFormat("en-US", {
        timeZone: timezone,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
        timeZoneName: "short",
      });
      return formatter.format(now);
    } catch {
      return `Error: Invalid timezone '${timezone}'. Use IANA format like 'America/New_York'.`;
    }
  }
);

/**
 * Convert a time from one timezone to another.
 */
export const convert_timezone = tool(
  {
    name: "convert_timezone",
    description: "Convert a time from one timezone to another.",
    parameters: z.object({
      time_str: z
        .string()
        .describe("Time in format 'YYYY-MM-DD HH:MM' or 'HH:MM' (assumes today)"),
      from_tz: z.string().describe("Source IANA timezone (e.g., 'America/New_York')"),
      to_tz: z.string().describe("Target IANA timezone (e.g., 'Europe/London')"),
    }),
  },
  ({ time_str, from_tz, to_tz }) => {
    try {
      let date: Date;

      if (time_str.length <= 5) {
        // HH:MM format - use today's date
        const today = new Date();
        const [hours, minutes] = time_str.split(":").map(Number);
        today.setHours(hours, minutes, 0, 0);
        date = today;
      } else {
        // YYYY-MM-DD HH:MM format
        const [datePart, timePart] = time_str.split(" ");
        date = new Date(`${datePart}T${timePart}:00`);
      }

      const formatter = new Intl.DateTimeFormat("en-US", {
        timeZone: to_tz,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
        timeZoneName: "short",
      });

      return formatter.format(date);
    } catch (e) {
      return `Error: ${e}`;
    }
  }
);

/**
 * Calculate time remaining until a target date/time.
 */
export const time_until = tool(
  {
    name: "time_until",
    description: "Calculate time remaining until a target date/time.",
    parameters: z.object({
      target: z.string().describe("Target datetime in format 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'"),
      timezone: z.string().default("UTC").describe("IANA timezone for the target time"),
    }),
  },
  ({ target, timezone = "UTC" }) => {
    try {
      const now = new Date();

      let targetDate: Date;
      if (target.length === 10) {
        targetDate = new Date(`${target}T00:00:00`);
      } else {
        const [datePart, timePart] = target.split(" ");
        targetDate = new Date(`${datePart}T${timePart}:00`);
      }

      const diffMs = targetDate.getTime() - now.getTime();

      if (diffMs < 0) {
        const daysAgo = Math.floor(Math.abs(diffMs) / (1000 * 60 * 60 * 24));
        return `That time has already passed (${daysAgo} days ago).`;
      }

      const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
      const hours = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
      const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));

      const parts: string[] = [];
      if (days) parts.push(`${days} day${days !== 1 ? "s" : ""}`);
      if (hours) parts.push(`${hours} hour${hours !== 1 ? "s" : ""}`);
      if (minutes) parts.push(`${minutes} minute${minutes !== 1 ? "s" : ""}`);

      return parts.length ? parts.join(", ") : "Less than a minute";
    } catch (e) {
      return `Error: ${e}`;
    }
  }
);
