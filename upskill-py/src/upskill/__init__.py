"""
Upskill - Turn skills and tools into a running agent.
"""

import logging

from upskill.environment_variables import UPSKILL_LOG_LEVEL

# Configure logging for upskill
_logger = logging.getLogger("upskill")

if not _logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    _logger.addHandler(_handler)

_log_level = getattr(logging, UPSKILL_LOG_LEVEL.get().upper(), logging.INFO)
_logger.setLevel(_log_level)

from upskill.agent import Agent, ChatAgent
from upskill.loop import AgentResponse, StreamEvent
from upskill.tools import get_config, tool

__all__ = ["Agent", "AgentResponse", "ChatAgent", "StreamEvent", "get_config", "tool"]
__version__ = "0.1.0"
