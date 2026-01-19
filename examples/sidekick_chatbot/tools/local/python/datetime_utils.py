"""Datetime and timezone utilities."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from upskill import tool


class TimezoneConversion(BaseModel):
    """Parameters for converting time between timezones."""

    time_str: str = Field(description="Time in format 'YYYY-MM-DD HH:MM' or 'HH:MM' (assumes today)")
    from_tz: str = Field(description="Source IANA timezone (e.g., 'America/New_York')")
    to_tz: str = Field(description="Target IANA timezone (e.g., 'Europe/London')")


@tool
def current_time(timezone: str = "UTC") -> str:
    """Get the current time in a specific timezone.

    Args:
        timezone: IANA timezone name (e.g., "America/New_York", "Europe/London", "Asia/Tokyo").
    """
    try:
        tz = ZoneInfo(timezone)
        now = datetime.now(tz)
        return now.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception as e:
        return f"Error: Invalid timezone '{timezone}'. Use IANA format like 'America/New_York'."


@tool
def convert_timezone(params: TimezoneConversion) -> str:
    """Convert a time from one timezone to another.

    Args:
        params: The timezone conversion parameters.
    """
    try:
        from_zone = ZoneInfo(params.from_tz)
        to_zone = ZoneInfo(params.to_tz)

        # Parse time string
        if len(params.time_str) <= 5:  # HH:MM format
            today = datetime.now(from_zone).date()
            dt = datetime.strptime(params.time_str, "%H:%M").replace(
                year=today.year, month=today.month, day=today.day, tzinfo=from_zone
            )
        else:
            dt = datetime.strptime(params.time_str, "%Y-%m-%d %H:%M").replace(tzinfo=from_zone)

        converted = dt.astimezone(to_zone)
        return converted.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception as e:
        return f"Error: {e}"


@tool
def time_until(target: str, timezone: str = "UTC") -> str:
    """Calculate time remaining until a target date/time.

    Args:
        target: Target datetime in format "YYYY-MM-DD" or "YYYY-MM-DD HH:MM".
        timezone: IANA timezone for the target time.
    """
    try:
        tz = ZoneInfo(timezone)
        now = datetime.now(tz)

        if len(target) == 10:  # Date only
            target_dt = datetime.strptime(target, "%Y-%m-%d").replace(tzinfo=tz)
        else:
            target_dt = datetime.strptime(target, "%Y-%m-%d %H:%M").replace(tzinfo=tz)

        diff = target_dt - now

        if diff.total_seconds() < 0:
            return f"That time has already passed ({abs(diff.days)} days ago)."

        days = diff.days
        hours, remainder = divmod(diff.seconds, 3600)
        minutes = remainder // 60

        parts = []
        if days:
            parts.append(f"{days} day{'s' if days != 1 else ''}")
        if hours:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")

        return ", ".join(parts) if parts else "Less than a minute"
    except Exception as e:
        return f"Error: {e}"
