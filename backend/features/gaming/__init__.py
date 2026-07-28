"""Gaming-specific automated editing features (Dota 2)."""

from backend.features.gaming.death_detect import (
    DotaHudLayout,
    detect_death_intervals,
    extract_slot_previews,
    identify_player_slot,
)

__all__ = [
    "DotaHudLayout",
    "detect_death_intervals",
    "extract_slot_previews",
    "identify_player_slot",
]
