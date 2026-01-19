"""
This module defines environment variables used in Upskill.

Upskill's environment variables adhere to the following naming conventions:
- Public variables: environment variable names begin with `UPSKILL_`
- Internal-use variables: For variables used only internally, names start with `_UPSKILL_`
"""

import os


class _EnvironmentVariable:
    """
    Represents an environment variable.
    """

    def __init__(self, name: str, type_: type, default):
        self.name = name
        self.type = type_
        self.default = default

    @property
    def defined(self) -> bool:
        return self.name in os.environ

    def get_raw(self) -> str | None:
        return os.getenv(self.name)

    def set(self, value) -> None:
        os.environ[self.name] = str(value)

    def unset(self) -> None:
        os.environ.pop(self.name, None)

    def get(self):
        """
        Reads the value of the environment variable if it exists and converts it to the desired
        type. Otherwise, returns the default value.
        """
        if (val := self.get_raw()) is not None:
            try:
                return self.type(val)
            except Exception as e:
                raise ValueError(f"Failed to convert {val!r} for {self.name}: {e}")
        return self.default

    def __str__(self) -> str:
        return f"{self.name} (default: {self.default})"

    def __repr__(self) -> str:
        return repr(self.name)


class _BooleanEnvironmentVariable(_EnvironmentVariable):
    """
    Represents a boolean environment variable.
    """

    def __init__(self, name: str, default: bool | None):
        if not (default is True or default is False or default is None):
            raise ValueError(f"{name} default value must be one of [True, False, None]")
        super().__init__(name, bool, default)

    def get(self) -> bool | None:
        if not self.defined:
            return self.default

        val = os.getenv(self.name)
        lowercased = val.lower()
        if lowercased not in ["true", "false", "1", "0"]:
            raise ValueError(
                f"{self.name} value must be one of ['true', 'false', '1', '0'] (case-insensitive), "
                f"but got {val}"
            )
        return lowercased in ["true", "1"]


# =============================================================================
# Logging Configuration
# =============================================================================

#: Specifies the logging level for Upskill. Valid values: DEBUG, INFO, WARNING, ERROR, CRITICAL.
#: (default: ``INFO``)
UPSKILL_LOG_LEVEL = _EnvironmentVariable("UPSKILL_LOG_LEVEL", str, "INFO")


# =============================================================================
# Tool Configuration
# =============================================================================

#: Specifies the timeout in seconds for tool calls.
#: (default: ``30``)
UPSKILL_TOOL_TIMEOUT_SECONDS = _EnvironmentVariable("UPSKILL_TOOL_TIMEOUT_SECONDS", int, 30)

#: Specifies the maximum number of retries for tool calls.
#: (default: ``3``)
UPSKILL_TOOL_MAX_RETRIES = _EnvironmentVariable("UPSKILL_TOOL_MAX_RETRIES", int, 3)

#: Specifies the base backoff in seconds between tool call retries (doubles each retry).
#: (default: ``1.0``)
UPSKILL_TOOL_RETRY_BACKOFF = _EnvironmentVariable("UPSKILL_TOOL_RETRY_BACKOFF", float, 1.0)


# =============================================================================
# LLM Configuration
# =============================================================================

#: Specifies the maximum number of retries for LLM calls.
#: (default: ``7``)
UPSKILL_LLM_MAX_RETRIES = _EnvironmentVariable("UPSKILL_LLM_MAX_RETRIES", int, 7)

#: Specifies the timeout in seconds for LLM calls.
#: (default: ``120``)
UPSKILL_LLM_TIMEOUT_SECONDS = _EnvironmentVariable("UPSKILL_LLM_TIMEOUT_SECONDS", int, 120)

#: Specifies the maximum number of LLM call iterations within a single run() call.
#: Each iteration is one LLM round-trip (call → tool execution → repeat).
#: This prevents infinite tool-calling loops.
#: (default: ``50``)
UPSKILL_MAX_AGENT_ITERATIONS = _EnvironmentVariable("UPSKILL_MAX_AGENT_ITERATIONS", int, 50)

#: Specifies the context window threshold percentage at which pruning starts.
#: (default: ``0.8`` = 80%)
UPSKILL_CONTEXT_PRUNE_THRESHOLD = _EnvironmentVariable("UPSKILL_CONTEXT_PRUNE_THRESHOLD", float, 0.8)
