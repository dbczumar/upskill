"""
Skill Manager — Progressive disclosure of skills.

- Loads skill metadata (name, description) at startup
- Injects metadata into system prompt
- Provides load_skill(name) tool for on-demand full content loading
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from upskill.loader import SkillMetadata

logger = logging.getLogger(__name__)


@dataclass
class SkillLoadResult:
    """Result of loading a skill."""

    content: str  # The skill's markdown content (or error message)
    tools: list[str]  # Required tool names (empty if not found or no tools specified)
    success: bool  # Whether the skill was found


@dataclass
class ReferenceLoadResult:
    """Result of loading a skill reference."""

    content: str  # The reference's markdown content (or error message)
    success: bool  # Whether the reference was found


@dataclass
class ScriptLoadResult:
    """Result of loading a skill script."""

    content: str  # The script's source code (or error message)
    language: str  # The script language (python, bash, javascript)
    success: bool  # Whether the script was found


@dataclass
class SkillManager:
    """
    Manages skills with progressive disclosure.

    Skills are loaded lazily: only metadata (name, description) is included
    in the initial system prompt. Full skill content is loaded on-demand
    via the load_skill() tool.
    """

    skills: dict[str, SkillMetadata]
    loaded_skills: set[str]  # Names of skills whose full content has been loaded

    @classmethod
    def from_skills(cls, skills: list[SkillMetadata]) -> SkillManager:
        """Create a SkillManager from a list of skill metadata."""
        return cls(
            skills={s.name: s for s in skills},
            loaded_skills=set(),
        )

    def get_skill_summary(self) -> str:
        """
        Generate a summary of available skills for the system prompt.

        Returns a markdown-formatted list of skills with their descriptions.
        """
        if not self.skills:
            return ""

        lines = ["## Available Skills", ""]
        lines.append(
            "You have access to the following skills. "
            "Use `load_skill(name)` to load a skill's full instructions when needed."
        )
        lines.append("")

        for skill in self.skills.values():
            lines.append(f"- **{skill.name}**: {skill.description}")

        return "\n".join(lines)

    def load_skill(self, name: str) -> SkillLoadResult:
        """
        Load a skill's full content and return its required tools.

        Args:
            name: The name of the skill to load.

        Returns:
            SkillLoadResult with content, required tools, and success flag.
        """
        skill = self.skills.get(name)
        if not skill:
            available = ", ".join(sorted(self.skills.keys()))
            logger.debug("Skill '%s' not found. Available: %s", name, available)
            return SkillLoadResult(
                content=f"Error: Skill '{name}' not found. Available skills: {available}",
                tools=[],
                success=False,
            )

        self.loaded_skills.add(name)
        logger.debug("Loaded skill '%s' with %d required tools: %s", name, len(skill.tools), skill.tools)

        # Build content with reference and script info if available
        content = f"# Skill: {skill.name}\n\n{skill.content}"
        if skill.references:
            ref_names = sorted(skill.references.keys())
            content += f"\n\n## Available References\n\nThis skill has additional reference documents. Use `load_reference(skill_name, reference_name)` to load them:\n"
            for ref_name in ref_names:
                content += f"\n- `{ref_name}`"
            logger.debug("Skill '%s' has %d references: %s", name, len(ref_names), ref_names)

        if skill.scripts:
            script_names = sorted(skill.scripts.keys())
            content += f"\n\n## Available Scripts\n\nThis skill has executable scripts. Use `load_script(skill_name, script_name)` to load them, then use code_interpreter to run:\n"
            for script_name in script_names:
                ext = skill.scripts[script_name].suffix
                content += f"\n- `{script_name}` ({ext})"
            logger.debug("Skill '%s' has %d scripts: %s", name, len(script_names), script_names)

        return SkillLoadResult(
            content=content,
            tools=skill.tools,
            success=True,
        )

    def get_required_tools(self) -> set[str]:
        """Get all tool names required by currently loaded skills."""
        tools: set[str] = set()
        for name in self.loaded_skills:
            skill = self.skills.get(name)
            if skill:
                tools.update(skill.tools)
        return tools

    def load_reference(self, skill_name: str, reference_name: str) -> ReferenceLoadResult:
        """
        Load a reference document from a skill's references/ subdirectory.

        Args:
            skill_name: The name of the skill containing the reference.
            reference_name: The name of the reference to load (without .md extension).

        Returns:
            ReferenceLoadResult with content and success flag.
        """
        skill = self.skills.get(skill_name)
        if not skill:
            available = ", ".join(sorted(self.skills.keys()))
            logger.debug("Skill '%s' not found for reference lookup. Available: %s", skill_name, available)
            return ReferenceLoadResult(
                content=f"Error: Skill '{skill_name}' not found. Available skills: {available}",
                success=False,
            )

        if not skill.references:
            logger.debug("Skill '%s' has no references", skill_name)
            return ReferenceLoadResult(
                content=f"Error: Skill '{skill_name}' has no references.",
                success=False,
            )

        ref_path = skill.references.get(reference_name)
        if not ref_path:
            available_refs = ", ".join(sorted(skill.references.keys()))
            logger.debug("Reference '%s' not found in skill '%s'. Available: %s", reference_name, skill_name, available_refs)
            return ReferenceLoadResult(
                content=f"Error: Reference '{reference_name}' not found in skill '{skill_name}'. Available references: {available_refs}",
                success=False,
            )

        try:
            content = ref_path.read_text()
            logger.debug("Loaded reference '%s' from skill '%s' (%d chars)", reference_name, skill_name, len(content))
            return ReferenceLoadResult(
                content=f"# Reference: {reference_name}\n\n{content}",
                success=True,
            )
        except OSError as e:
            logger.error("Failed to read reference file %s: %s", ref_path, e)
            return ReferenceLoadResult(
                content=f"Error: Failed to read reference '{reference_name}': {e}",
                success=False,
            )

    def has_references(self) -> bool:
        """Check if any loaded skill has references."""
        for name in self.loaded_skills:
            skill = self.skills.get(name)
            if skill and skill.references:
                return True
        return False

    def get_available_references(self) -> dict[str, list[str]]:
        """Get all available references from loaded skills."""
        refs: dict[str, list[str]] = {}
        for name in self.loaded_skills:
            skill = self.skills.get(name)
            if skill and skill.references:
                refs[name] = sorted(skill.references.keys())
        return refs

    def load_script(self, skill_name: str, script_name: str) -> ScriptLoadResult:
        """
        Load a script from a skill's scripts/ subdirectory.

        Args:
            skill_name: The name of the skill containing the script.
            script_name: The name of the script to load (without extension).

        Returns:
            ScriptLoadResult with content, language, and success flag.
        """
        skill = self.skills.get(skill_name)
        if not skill:
            available = ", ".join(sorted(self.skills.keys()))
            logger.debug("Skill '%s' not found for script lookup. Available: %s", skill_name, available)
            return ScriptLoadResult(
                content=f"Error: Skill '{skill_name}' not found. Available skills: {available}",
                language="",
                success=False,
            )

        if not skill.scripts:
            logger.debug("Skill '%s' has no scripts", skill_name)
            return ScriptLoadResult(
                content=f"Error: Skill '{skill_name}' has no scripts.",
                language="",
                success=False,
            )

        script_path = skill.scripts.get(script_name)
        if not script_path:
            available_scripts = ", ".join(sorted(skill.scripts.keys()))
            logger.debug("Script '%s' not found in skill '%s'. Available: %s", script_name, skill_name, available_scripts)
            return ScriptLoadResult(
                content=f"Error: Script '{script_name}' not found in skill '{skill_name}'. Available scripts: {available_scripts}",
                language="",
                success=False,
            )

        # Determine language from extension
        ext_to_lang = {".py": "python", ".sh": "bash", ".js": "javascript"}
        language = ext_to_lang.get(script_path.suffix, "unknown")

        try:
            content = script_path.read_text()
            logger.debug("Loaded script '%s' from skill '%s' (%d chars, %s)", script_name, skill_name, len(content), language)
            return ScriptLoadResult(
                content=content,
                language=language,
                success=True,
            )
        except OSError as e:
            logger.error("Failed to read script file %s: %s", script_path, e)
            return ScriptLoadResult(
                content=f"Error: Failed to read script '{script_name}': {e}",
                language="",
                success=False,
            )

    def has_scripts(self) -> bool:
        """Check if any loaded skill has scripts."""
        for name in self.loaded_skills:
            skill = self.skills.get(name)
            if skill and skill.scripts:
                return True
        return False

    def get_available_scripts(self) -> dict[str, list[str]]:
        """Get all available scripts from loaded skills."""
        scripts: dict[str, list[str]] = {}
        for name in self.loaded_skills:
            skill = self.skills.get(name)
            if skill and skill.scripts:
                scripts[name] = sorted(skill.scripts.keys())
        return scripts

    def get_load_skill_tool_schema(self) -> dict:
        """
        Get the JSON schema for the load_skill tool.

        Returns a tool definition in OpenAI/LiteLLM format.
        """
        skill_names = list(self.skills.keys())

        return {
            "type": "function",
            "function": {
                "name": "load_skill",
                "description": (
                    "Load a skill's full instructions. Use this when you need "
                    "detailed guidance for handling a specific type of request. "
                    "The skill content will be added to the conversation."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "The name of the skill to load",
                            "enum": skill_names if skill_names else None,
                        },
                    },
                    "required": ["name"],
                },
            },
        }

    def get_load_reference_tool_schema(self) -> dict | None:
        """
        Get the JSON schema for the load_reference tool.

        Returns a tool definition in OpenAI/LiteLLM format, or None if no loaded
        skill has references.
        """
        available_refs = self.get_available_references()
        if not available_refs:
            return None

        # Build description with available references
        ref_list = []
        for skill_name, ref_names in available_refs.items():
            ref_list.append(f"- {skill_name}: {', '.join(ref_names)}")
        refs_desc = "\n".join(ref_list)

        return {
            "type": "function",
            "function": {
                "name": "load_reference",
                "description": (
                    "Load a reference document from a skill. References provide "
                    "additional context, examples, or detailed information. "
                    f"Available references:\n{refs_desc}"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_name": {
                            "type": "string",
                            "description": "The name of the skill containing the reference",
                            "enum": list(available_refs.keys()),
                        },
                        "reference_name": {
                            "type": "string",
                            "description": "The name of the reference to load",
                        },
                    },
                    "required": ["skill_name", "reference_name"],
                },
            },
        }

    def get_load_script_tool_schema(self) -> dict | None:
        """
        Get the JSON schema for the load_script tool.

        Returns a tool definition in OpenAI/LiteLLM format, or None if no loaded
        skill has scripts.
        """
        available_scripts = self.get_available_scripts()
        if not available_scripts:
            return None

        # Build description with available scripts
        script_list = []
        for skill_name, script_names in available_scripts.items():
            script_list.append(f"- {skill_name}: {', '.join(script_names)}")
        scripts_desc = "\n".join(script_list)

        return {
            "type": "function",
            "function": {
                "name": "load_script",
                "description": (
                    "Load an executable script from a skill. Scripts contain code "
                    "that can be run using the code interpreter. "
                    f"Available scripts:\n{scripts_desc}"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_name": {
                            "type": "string",
                            "description": "The name of the skill containing the script",
                            "enum": list(available_scripts.keys()),
                        },
                        "script_name": {
                            "type": "string",
                            "description": "The name of the script to load",
                        },
                    },
                    "required": ["skill_name", "script_name"],
                },
            },
        }
