"""Investigation state types and defaults."""
from __future__ import annotations

from typing import Literal

EvidenceID = Literal[
    "emf_5", "dots", "uv", "freezing", "orb", "writing", "spirit_box"
]

Difficulty = Literal[
    "amateur", "intermediate", "professional", "nightmare", "insanity"
]

InvestigationPhase = Literal["evidence", "behavioral"]

# Default soft facts — reset on every new investigation
DEFAULT_SOFT_FACTS: dict = {
    "model_gender": "unknown",
    "ghost_age": None,
    "favorite_room_changed": False,
    "banshee_scream": False,
    "fusebox_emf": False,
    "turned_on_breaker": False,
    "freezing_breath_during_hunt": False,
    "ghost_turned_on_light_switch": False,
    "dots_visible_naked_eye": False,
    "ghost_stepped_in_salt": False,
    "ghost_hunted_from_player_room": False,
    "airball_event": False,
}
