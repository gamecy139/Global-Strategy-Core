"""
RELIGION SYSTEM
---------------
Defines the canonical set of religions recognised by the game, provides
validation helpers, and is the single source of truth for any religion-
related constants used by other systems (Diplomacy, Economy, Population).

Adding a new religion in the future is a one-line change: add it to
``Religion`` and everything else adapts automatically.

The ``ReligionSystem`` class handles DB persistence.  It is kept lightweight:
religion is a property of the ``country_state`` row, so all reads/writes
delegate to the shared ``Database`` instance.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game_backend.db import Database
    from game_backend.diplomacy_system import DiplomacySystem


# ---------------------------------------------------------------------------
# Canonical religion enum
# ---------------------------------------------------------------------------

class Religion(str, Enum):
    """
    All valid religion values in the game.

    Inherits from ``str`` so instances compare equal to plain strings,
    which makes SQLite round-trips transparent:

        Religion("Islam") == "Islam"  →  True
    """
    ISLAM       = "Islam"
    CHRISTIANITY = "Christianity"
    JUDAISM     = "Judaism"
    HINDUISM    = "Hinduism"
    ATHEISM     = "Atheism"

    @classmethod
    def values(cls) -> list[str]:
        """Return all valid religion name strings."""
        return [r.value for r in cls]

    @classmethod
    def is_valid(cls, name: str) -> bool:
        """True if ``name`` is a recognised religion (case-sensitive)."""
        return name in cls.values()

    @classmethod
    def parse(cls, name: str) -> "Religion":
        """
        Convert a string to a Religion, raising ValueError for unknown values.

        Example
        -------
            Religion.parse("Islam")      →  Religion.ISLAM
            Religion.parse("Paganism")   →  ValueError
        """
        try:
            return cls(name)
        except ValueError:
            valid = ", ".join(cls.values())
            raise ValueError(
                f"'{name}' is not a recognised religion. Valid options: {valid}"
            )


# ---------------------------------------------------------------------------
# Diplomacy modifier constants
# (Imported by DiplomacySystem — kept here for a single point of control)
# ---------------------------------------------------------------------------

#: Relation penalty applied when two countries follow different religions.
#: This modifier is dynamic (computed at query time) and does NOT alter base relations.
DIFFERENT_RELIGION_MODIFIER: int = -2


# ---------------------------------------------------------------------------
# ReligionSystem — DB-backed read/write for a country's religion field
# ---------------------------------------------------------------------------

class ReligionSystem:
    """
    Handles reading and writing the ``religion`` column of ``country_state``.

    The class is intentionally thin — religion is one field in the shared
    row rather than a separate table.  All validation uses the ``Religion``
    enum above.

    Syncing with DiplomacySystem
    ----------------------------
    After calling ``set_religion()``, pass the optional ``diplomacy`` parameter
    (a ``DiplomacySystem`` instance) so that the in-memory Country object is
    updated immediately and dynamic relation modifiers stay accurate:

        rel_sys.set_religion("guild_1", "Evoria", "Islam", diplomacy=ds)

    Parameters
    ----------
    db : Database
        Shared database instance (must have been initialised via ``db.init()``).
    """

    def __init__(self, db: "Database") -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_religion(self, server_id: str, country_id: str) -> str:
        """Return the current religion for a country (string, e.g. 'Islam')."""
        row = self._db.get_or_create_country(server_id, country_id)
        return str(row["religion"])

    def get_snapshot(self, server_id: str, country_id: str) -> dict:
        """
        Return a religion snapshot dict.

        Keys: server_id, country_id, religion
        """
        return {
            "server_id":  server_id,
            "country_id": country_id,
            "religion":   self.get_religion(server_id, country_id),
        }

    def list_by_religion(self, server_id: str, religion: str) -> list[str]:
        """
        Return all country IDs on a server that follow ``religion``.
        Useful for applying persecution events and for future event triggers.
        """
        Religion.parse(religion)   # Validates the value
        rows = self._db.get_all_countries(server_id)
        return [r["country_id"] for r in rows if r["religion"] == religion]

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def set_religion(
        self,
        server_id:   str,
        country_id:  str,
        religion:    str,
        diplomacy:   "DiplomacySystem | None" = None,
    ) -> None:
        """
        Persist a new religion for a country.

        Parameters
        ----------
        religion  : Must be one of the ``Religion`` enum values.
        diplomacy : Optional DiplomacySystem instance.  If provided, the
                    in-memory Country object is updated so that dynamic
                    relation modifiers reflect the change immediately.

        Raises ValueError for unrecognised religion names.
        """
        Religion.parse(religion)   # Validate — raises ValueError if invalid
        self._db.get_or_create_country(server_id, country_id)
        self._db.update_fields(server_id, country_id, religion=religion)

        # Sync in-memory DiplomacySystem if provided
        if diplomacy is not None:
            try:
                diplomacy.update_country_religion(country_id, religion)
            except KeyError:
                pass  # Country not yet registered in DiplomacySystem — that's fine

    def ensure_valid(self, religion: str) -> Religion:
        """Validate and return the Religion enum member for the given string."""
        return Religion.parse(religion)
