"""사용자 제한 상태 계산 규칙을 제공합니다."""

from datetime import datetime

from src.config import PENALTY_RESTRICTION_THRESHOLD, PENALTY_BAN_THRESHOLD


def evaluate_user_restriction(user, current_time=None):
    """사용자의 현재 제한 상태를 계산합니다."""
    if current_time is None:
        current_time = datetime.now()

    points = user.penalty_points
    restriction_until = user.restriction_until
    is_banned = False
    is_restricted = False
    max_active_bookings = 6

    if restriction_until and points >= PENALTY_RESTRICTION_THRESHOLD:
        restriction_end = datetime.fromisoformat(restriction_until)
        if restriction_end > current_time:
            if points >= PENALTY_BAN_THRESHOLD:
                is_banned = True
                max_active_bookings = 0
            else:
                is_restricted = True
                max_active_bookings = 1
        else:
            restriction_until = None

    return {
        "points": points,
        "is_banned": is_banned,
        "is_restricted": is_restricted,
        "restriction_until": restriction_until,
        "max_active_bookings": max_active_bookings,
    }
