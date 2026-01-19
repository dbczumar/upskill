/**
 * Skill Manager — Progressive disclosure of skills.
 */

import * as fs from "fs";
import * as path from "path";
import type {
  SkillMetadata,
  SkillLoadResult,
  ReferenceLoadResult,
  ScriptLoadResult,
  ToolSchema,
} from "./types.js";

export class SkillManager {
  private skills: Map<string, SkillMetadata>;
  private loadedSkills: Set<string>;

  constructor(skills: SkillMetadata[]) {
    this.skills = new Map(skills.map((s) => [s.name, s]));
    this.loadedSkills = new Set();
  }

  /**
   * Generate a summary of available skills for the system prompt.
   */
  getSkillSummary(): string {
    if (this.skills.size === 0) {
      return "";
    }

    const lines = [
      "## Available Skills",
      "",
      "You have access to the following skills. " +
        "Use `load_skill({ names: [...] })` to load skill(s) and their tools when needed.",
      "",
    ];

    for (const skill of this.skills.values()) {
      lines.push(`- **${skill.name}**: ${skill.description}`);
      if (skill.tools.length > 0) {
        lines.push(`  - Tools: ${skill.tools.join(", ")}`);
      }
    }

    return lines.join("\n");
  }

  /**
   * Load a skill's full content.
   */
  loadSkill(name: string): SkillLoadResult {
    return this.loadSkills([name]);
  }

  /**
   * Load multiple skills at once and return combined content with tools grouped by skill.
   */
  loadSkills(names: string[], toolDescriptions?: Map<string, string>): SkillLoadResult {
    const errors: string[] = [];
    const allTools: string[] = [];
    const contentParts: string[] = [];

    for (const name of names) {
      const skill = this.skills.get(name);
      if (!skill) {
        const available = Array.from(this.skills.keys()).sort().join(", ");
        errors.push(`Error: Skill '${name}' not found. Available skills: ${available}`);
        continue;
      }

      this.loadedSkills.add(name);

      let content = `# Skill: ${skill.name}\n\n${skill.content}`;

      // Add tools section with descriptions grouped by skill
      if (skill.tools.length > 0) {
        content += `\n\n## Tools for ${skill.name}\n`;
        for (const toolName of skill.tools) {
          const desc = toolDescriptions?.get(toolName) || "";
          content += `\n- **${toolName}**${desc ? `: ${desc}` : ""}`;
          allTools.push(toolName);
        }
      }

      // Add reference info
      if (skill.references.size > 0) {
        const refNames = Array.from(skill.references.keys()).sort();
        content += `\n\n## Available References\n\nThis skill has additional reference documents. Use \`load_reference(skill_name, reference_name)\` to load them:\n`;
        for (const refName of refNames) {
          content += `\n- \`${refName}\``;
        }
      }

      // Add script info
      if (skill.scripts.size > 0) {
        const scriptNames = Array.from(skill.scripts.keys()).sort();
        content += `\n\n## Available Scripts\n\nThis skill has executable scripts. Use \`load_script(skill_name, script_name)\` to load them:\n`;
        for (const scriptName of scriptNames) {
          const scriptPath = skill.scripts.get(scriptName)!;
          const ext = path.extname(scriptPath);
          content += `\n- \`${scriptName}\` (${ext})`;
        }
      }

      contentParts.push(content);
    }

    if (errors.length > 0 && contentParts.length === 0) {
      return {
        content: errors.join("\n"),
        tools: [],
        success: false,
      };
    }

    const finalContent = errors.length > 0
      ? [...errors, "", ...contentParts].join("\n")
      : contentParts.join("\n\n---\n\n");

    return {
      content: finalContent,
      tools: allTools,
      success: contentParts.length > 0,
    };
  }

  /**
   * Load a reference document from a skill.
   */
  loadReference(skillName: string, referenceName: string): ReferenceLoadResult {
    const skill = this.skills.get(skillName);
    if (!skill) {
      const available = Array.from(this.skills.keys()).sort().join(", ");
      return {
        content: `Error: Skill '${skillName}' not found. Available skills: ${available}`,
        success: false,
      };
    }

    if (skill.references.size === 0) {
      return {
        content: `Error: Skill '${skillName}' has no references.`,
        success: false,
      };
    }

    const refPath = skill.references.get(referenceName);
    if (!refPath) {
      const availableRefs = Array.from(skill.references.keys()).sort().join(", ");
      return {
        content: `Error: Reference '${referenceName}' not found in skill '${skillName}'. Available references: ${availableRefs}`,
        success: false,
      };
    }

    try {
      const content = fs.readFileSync(refPath, "utf-8");
      return {
        content: `# Reference: ${referenceName}\n\n${content}`,
        success: true,
      };
    } catch (e) {
      return {
        content: `Error: Failed to read reference '${referenceName}': ${e}`,
        success: false,
      };
    }
  }

  /**
   * Load a script from a skill.
   */
  loadScript(skillName: string, scriptName: string): ScriptLoadResult {
    const skill = this.skills.get(skillName);
    if (!skill) {
      const available = Array.from(this.skills.keys()).sort().join(", ");
      return {
        content: `Error: Skill '${skillName}' not found. Available skills: ${available}`,
        language: "",
        success: false,
      };
    }

    if (skill.scripts.size === 0) {
      return {
        content: `Error: Skill '${skillName}' has no scripts.`,
        language: "",
        success: false,
      };
    }

    const scriptPath = skill.scripts.get(scriptName);
    if (!scriptPath) {
      const availableScripts = Array.from(skill.scripts.keys()).sort().join(", ");
      return {
        content: `Error: Script '${scriptName}' not found in skill '${skillName}'. Available scripts: ${availableScripts}`,
        language: "",
        success: false,
      };
    }

    const extToLang: Record<string, string> = {
      ".py": "python",
      ".sh": "bash",
      ".js": "javascript",
      ".ts": "typescript",
    };
    const ext = path.extname(scriptPath);
    const language = extToLang[ext] || "unknown";

    try {
      const content = fs.readFileSync(scriptPath, "utf-8");
      return {
        content,
        language,
        success: true,
      };
    } catch (e) {
      return {
        content: `Error: Failed to read script '${scriptName}': ${e}`,
        language: "",
        success: false,
      };
    }
  }

  /**
   * Get all tool names required by currently loaded skills.
   */
  getRequiredTools(): Set<string> {
    const tools = new Set<string>();
    for (const name of this.loadedSkills) {
      const skill = this.skills.get(name);
      if (skill) {
        for (const tool of skill.tools) {
          tools.add(tool);
        }
      }
    }
    return tools;
  }

  /**
   * Check if any skill has references.
   */
  hasReferences(): boolean {
    for (const name of this.loadedSkills) {
      const skill = this.skills.get(name);
      if (skill && skill.references.size > 0) {
        return true;
      }
    }
    return false;
  }

  /**
   * Check if any skill has scripts.
   */
  hasScripts(): boolean {
    for (const name of this.loadedSkills) {
      const skill = this.skills.get(name);
      if (skill && skill.scripts.size > 0) {
        return true;
      }
    }
    return false;
  }

  /**
   * Get the load_skill tool schema.
   */
  getLoadSkillToolSchema(): ToolSchema {
    const skillNames = Array.from(this.skills.keys());
    return {
      type: "function",
      function: {
        name: "load_skill",
        description:
          "Load one or more skills' full instructions. Use this when you need " +
          "detailed guidance for handling a specific type of request. " +
          "You can load multiple skills at once by passing an array of names.",
        parameters: {
          type: "object",
          properties: {
            names: {
              type: "array",
              items: {
                type: "string",
                enum: skillNames.length > 0 ? skillNames : undefined,
              },
              description: "The names of the skills to load",
            },
          },
          required: ["names"],
        },
      },
    };
  }

  /**
   * Get the load_reference tool schema (if any loaded skill has references).
   */
  getLoadReferenceToolSchema(): ToolSchema | null {
    const availableRefs: Record<string, string[]> = {};
    for (const name of this.loadedSkills) {
      const skill = this.skills.get(name);
      if (skill && skill.references.size > 0) {
        availableRefs[name] = Array.from(skill.references.keys()).sort();
      }
    }

    if (Object.keys(availableRefs).length === 0) {
      return null;
    }

    const refList = Object.entries(availableRefs)
      .map(([skill, refs]) => `- ${skill}: ${refs.join(", ")}`)
      .join("\n");

    return {
      type: "function",
      function: {
        name: "load_reference",
        description:
          "Load a reference document from a skill. References provide " +
          `additional context, examples, or detailed information.\nAvailable references:\n${refList}`,
        parameters: {
          type: "object",
          properties: {
            skill_name: {
              type: "string",
              description: "The name of the skill containing the reference",
              enum: Object.keys(availableRefs),
            },
            reference_name: {
              type: "string",
              description: "The name of the reference to load",
            },
          },
          required: ["skill_name", "reference_name"],
        },
      },
    };
  }

  /**
   * Get the load_script tool schema (if any loaded skill has scripts).
   */
  getLoadScriptToolSchema(): ToolSchema | null {
    const availableScripts: Record<string, string[]> = {};
    for (const name of this.loadedSkills) {
      const skill = this.skills.get(name);
      if (skill && skill.scripts.size > 0) {
        availableScripts[name] = Array.from(skill.scripts.keys()).sort();
      }
    }

    if (Object.keys(availableScripts).length === 0) {
      return null;
    }

    const scriptList = Object.entries(availableScripts)
      .map(([skill, scripts]) => `- ${skill}: ${scripts.join(", ")}`)
      .join("\n");

    return {
      type: "function",
      function: {
        name: "load_script",
        description:
          "Load an executable script from a skill. Scripts contain code " +
          `that can be run using the code interpreter.\nAvailable scripts:\n${scriptList}`,
        parameters: {
          type: "object",
          properties: {
            skill_name: {
              type: "string",
              description: "The name of the skill containing the script",
              enum: Object.keys(availableScripts),
            },
            script_name: {
              type: "string",
              description: "The name of the script to load",
            },
          },
          required: ["skill_name", "script_name"],
        },
      },
    };
  }

  get size(): number {
    return this.skills.size;
  }

  get loadedCount(): number {
    return this.loadedSkills.size;
  }
}
