"""사용자 제한 상태 계산 규칙을 제공합니다."""

from datetime import datetime

from src.config import (
    PENALTY_RESTRICTION_THRESHOLD,
    PENALTY_BAN_THRESHOLD,
    MAX_ACTIVE_ROOM_BOOKINGS,
    MAX_ACTIVE_EQUIPMENT_BOOKINGS,
)
from src.runtime_clock import get_current_time


def evaluate_user_restriction(user, current_time=None):
    """사용자의 현재 제한 상태를 계산합니다."""
    if current_time is None:
        current_time = get_current_time()

    points = user.penalty_points
    restriction_until = user.restriction_until
    is_banned = False
    is_restricted = False
    max_active_bookings = (
        MAX_ACTIVE_ROOM_BOOKINGS + MAX_ACTIVE_EQUIPMENT_BOOKINGS
    )

    if restriction_until:
        restriction_end = datetime.fromisoformat(restriction_until)
        if restriction_end <= current_time:
            restriction_until = None

    if points >= PENALTY_BAN_THRESHOLD and restriction_until is not None:
        is_banned = True
    elif PENALTY_RESTRICTION_THRESHOLD <= points < PENALTY_BAN_THRESHOLD and restriction_until is not None:
        is_restricted = True

    if is_banned:
        max_active_bookings = 0
    elif is_restricted:
        max_active_bookings = 1

    return {
        "points": points,
        "is_banned": is_banned,
        "is_restricted": is_restricted,
        "restriction_until": restriction_until,
        "max_active_bookings": max_active_bookings,
    }
