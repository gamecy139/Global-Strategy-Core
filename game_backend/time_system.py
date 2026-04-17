"""
TIME SYSTEM
-----------
Manages the in-game calendar and time progression.

- In-game date: year / month / day
- Each month has exactly 30 days
- Time advances via real-time ticks (every 60 seconds)
- Five speed multipliers control how many in-game days pass per tick
- Time can be paused at any moment
"""

from enum import IntEnum
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Speed settings — how many in-game days advance per 60-second tick
# ---------------------------------------------------------------------------

class TimeSpeed(IntEnum):
    PAUSE = 0   # No time progression
    X1    = 1   # 1 minute  =  3 in-game days
    X2    = 2   # 1 minute  = 12 in-game days
    X3    = 3   # 1 minute  = 24 in-game days
    X4    = 4   # 1 minute  = 48 in-game days
    X5    = 5   # 1 minute  = 60 in-game days


# Maps each speed level to the number of in-game days advanced per tick
DAYS_PER_TICK: dict[TimeSpeed, int] = {
    TimeSpeed.PAUSE: 0,
    TimeSpeed.X1:    3,
    TimeSpeed.X2:   12,
    TimeSpeed.X3:   24,
    TimeSpeed.X4:   48,
    TimeSpeed.X5:   60,
}

# Fixed month length
DAYS_PER_MONTH: int = 30


# ---------------------------------------------------------------------------
# TimeState — persistent snapshot of the current in-game time
# ---------------------------------------------------------------------------

@dataclass
class TimeState:
    year:   int       = 1       # In-game year (starts at 1)
    month:  int       = 1       # 1–12
    day:    int       = 1       # 1–30
    speed:  TimeSpeed = TimeSpeed.X1
    paused: bool      = False

    def to_dict(self) -> dict:
        """Serialise to a plain dictionary (for storage / Discord embeds)."""
        return {
            "year":   self.year,
            "month":  self.month,
            "day":    self.day,
            "speed":  self.speed.value,
            "paused": self.paused,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TimeState":
        """Deserialise from a plain dictionary."""
        return cls(
            year   = data["year"],
            month  = data["month"],
            day    = data["day"],
            speed  = TimeSpeed(data["speed"]),
            paused = data["paused"],
        )


# ---------------------------------------------------------------------------
# TimeSystem — the main engine
# ---------------------------------------------------------------------------

class TimeSystem:
    """
    Global in-game time engine.

    Call ``tick()`` once every real-world 60 seconds to advance the calendar.
    """

    MONTHS_PER_YEAR: int = 12

    def __init__(self, initial_state: TimeState | None = None) -> None:
        self.state: TimeState = initial_state or TimeState()

    # ------------------------------------------------------------------
    # Core tick — advance time by one real-world minute worth of in-game days
    # ------------------------------------------------------------------

    def tick(self) -> int:
        """
        Advance the in-game date by the number of days that correspond to the
        current speed setting.

        Returns the number of in-game days that actually passed (0 when paused).
        """
        if self.state.paused:
            return 0

        days_to_advance = DAYS_PER_TICK[self.state.speed]
        self._advance_days(days_to_advance)
        return days_to_advance

    # ------------------------------------------------------------------
    # Speed & pause controls
    # ------------------------------------------------------------------

    def set_speed(self, speed: TimeSpeed) -> None:
        """Change the time advancement speed."""
        self.state.speed = speed
        # Setting a non-pause speed implicitly un-pauses
        if speed != TimeSpeed.PAUSE:
            self.state.paused = False

    def pause(self) -> None:
        """Halt all time progression."""
        self.state.paused = True

    def unpause(self) -> None:
        """Resume time progression at the current speed."""
        self.state.paused = False

    # ------------------------------------------------------------------
    # Direct date manipulation
    # ------------------------------------------------------------------

    def advance_days(self, days: int) -> None:
        """
        Manually advance the calendar by an arbitrary number of days.
        Useful for admin commands or scripted events.
        """
        if days < 0:
            raise ValueError("Cannot advance time by a negative number of days.")
        self._advance_days(days)

    def set_date(self, year: int, month: int, day: int) -> None:
        """Directly set the in-game date (admin / testing use)."""
        if not (1 <= month <= self.MONTHS_PER_YEAR):
            raise ValueError(f"Month must be between 1 and {self.MONTHS_PER_YEAR}.")
        if not (1 <= day <= DAYS_PER_MONTH):
            raise ValueError(f"Day must be between 1 and {DAYS_PER_MONTH}.")
        if year < 1:
            raise ValueError("Year must be at least 1.")
        self.state.year  = year
        self.state.month = month
        self.state.day   = day

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def total_days_elapsed(self) -> int:
        """
        Return the total number of in-game days since Year 1, Month 1, Day 1.
        Useful for comparing dates (e.g. checking ceasefire expiry).
        """
        return (
            (self.state.year  - 1) * self.MONTHS_PER_YEAR * DAYS_PER_MONTH
            + (self.state.month - 1) * DAYS_PER_MONTH
            + (self.state.day   - 1)
        )

    def days_until(self, year: int, month: int, day: int) -> int:
        """
        Return how many in-game days remain until a future date.
        Returns a negative value if the target date is in the past.
        """
        target_total = (
            (year  - 1) * self.MONTHS_PER_YEAR * DAYS_PER_MONTH
            + (month - 1) * DAYS_PER_MONTH
            + (day   - 1)
        )
        return target_total - self.total_days_elapsed()

    def date_string(self) -> str:
        """Human-readable date: e.g. 'Year 3, Month 7, Day 14'."""
        s = self.state
        return f"Year {s.year}, Month {s.month}, Day {s.day}"

    def get_state(self) -> TimeState:
        """Return a reference to the current TimeState."""
        return self.state

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _advance_days(self, days: int) -> None:
        """
        Add ``days`` to the current date, handling overflow from
        days → months → years correctly.
        """
        total_day_index = (
            (self.state.year  - 1) * self.MONTHS_PER_YEAR * DAYS_PER_MONTH
            + (self.state.month - 1) * DAYS_PER_MONTH
            + (self.state.day   - 1)
            + days
        )

        # Decompose the flat day index back into year / month / day
        days_per_year = self.MONTHS_PER_YEAR * DAYS_PER_MONTH  # 360

        self.state.year  = total_day_index // days_per_year + 1
        remainder        = total_day_index % days_per_year
        self.state.month = remainder // DAYS_PER_MONTH + 1
        self.state.day   = remainder % DAYS_PER_MONTH + 1
