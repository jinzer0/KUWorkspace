"""정책 서비스 - 가상 시점 전환과 상태 점검을 담당합니다."""

from datetime import datetime, timedelta
from dataclasses import replace
from typing import cast

from src.domain.models import (
    RoomBookingStatus,
    EquipmentBookingStatus,
    ResourceStatus,
    now_iso,
)
from src.domain.restriction_rules import evaluate_user_restriction
from src.storage.repositories import (
    UserRepository,
    RoomRepository,
    RoomBookingRepository,
    EquipmentAssetRepository,
    EquipmentBookingRepository,
    PenaltyRepository,
    AuditLogRepository,
    UnitOfWork,
)
from src.storage.file_lock import global_lock
from src.storage.integrity import validate_all_data_files
from src.domain.penalty_service import PenaltyService
from src.config import (
    MAX_ACTIVE_ROOM_BOOKINGS,
    MAX_ACTIVE_EQUIPMENT_BOOKINGS,
)
from src.runtime_clock import get_runtime_clock
from src.runtime_clock import compute_next_slot


class PolicyService:
    """정책 자동 처리 서비스"""

    def __init__(
        self,
        user_repo=None,
        room_repo=None,
        room_booking_repo=None,
        equipment_booking_repo=None,
        penalty_repo=None,
        audit_repo=None,
        penalty_service=None,
        equipment_repo=None,
        clock=None,
    ):
        self.clock = clock or get_runtime_clock()
        self.user_repo = user_repo or UserRepository()
        self.room_repo = room_repo or RoomRepository(
            file_path=self.user_repo.file_path.parent / 'rooms.txt'
        )
        self.room_booking_repo = room_booking_repo or RoomBookingRepository()
        self.equipment_booking_repo = (
            equipment_booking_repo or EquipmentBookingRepository()
        )
        self.penalty_repo = penalty_repo or PenaltyRepository()
        self.audit_repo = audit_repo or AuditLogRepository()
        self.equipment_repo = equipment_repo or EquipmentAssetRepository(
            file_path=self.equipment_booking_repo.file_path.parent / 'equipments.txt'
        )
        self.penalty_service = penalty_service or PenaltyService(
            user_repo=self.user_repo,
            penalty_repo=self.penalty_repo,
            audit_repo=self.audit_repo,
            clock=self.clock,
        )

    def run_all_checks(self, current_time=None):
        if current_time is None:
            current_time = self.clock.now()

        with global_lock():
            validate_all_data_files(
                repositories=self._integrity_repositories(),
                clock_file=self._clock_file_path(),
            )
            with UnitOfWork():
                return self._run_checks_locked(current_time)

    def _run_checks_locked(self, current_time):
        results = {
            "restored_room_resources": [],
            "restored_equipment_resources": [],
            "penalty_reset_users": [],
            "restriction_expired_users": [],
            "banned_user_cancelled_bookings": [],
        }

        restored = self._restore_overnight_resources(current_time)
        results["restored_room_resources"] = restored["rooms"]
        results["restored_equipment_resources"] = restored["equipment"]

        reset_users = self._check_penalty_resets(current_time)
        results["penalty_reset_users"] = [u.id for u in reset_users]

        expired_users = self._check_restriction_expiry(current_time)
        results["restriction_expired_users"] = [u.id for u in expired_users]

        cancelled = self._cancel_banned_user_bookings(current_time)
        results["banned_user_cancelled_bookings"] = cancelled
        return results

    def prepare_advance(self, current_time=None, actor_id="system", actor_role="user"):
        if current_time is None:
            current_time = self.clock.now()
        return self._build_advance_state(
            current_time,
            actor_id=actor_id,
            actor_role=actor_role,
        )

    def advance_time(self, actor_id="system", actor_role="user", force=False):
        with global_lock(), UnitOfWork():
            validate_all_data_files(
                repositories=self._integrity_repositories(),
                clock_file=self._clock_file_path(),
            )
            current_time = self.clock.now()
            state = self._build_advance_state(
                current_time,
                actor_id=actor_id,
                actor_role=actor_role,
            )
            if not state["can_advance"] and not force:
                self.audit_repo.log_action(
                    actor_id=actor_id,
                    action="clock_advance_blocked",
                    target_type="system_clock",
                    target_id=current_time.isoformat(),
                    details=" | ".join(cast(list[str], state["blockers"])),
                )
                return state

            auto_events = []

            # 18:00 슬롯 자동화는 18:00에 "도착"했을 때가 아니라
            # 18:00을 "떠날" 때 실행해야 사용자/관리자에게 퇴실 처리 기회를 줄 수 있다.
            if current_time.hour == 18:
                auto_events.extend(
                    self._handle_boundary_automation(
                        current_time,
                        actor_id=actor_id,
                    )
                )

            next_time = self.clock.advance()

            # 09:00 슬롯 자동화는 09:00에 도착한 직후 실행한다.
            if next_time.hour == 9:
                auto_events.extend(
                    self._handle_boundary_automation(
                        next_time,
                        actor_id=actor_id,
                    )
                )
            maintenance = self._run_checks_locked(next_time)
            events = list(cast(list[str], state["events"]))
            events.extend(auto_events)
            events.extend(self._build_post_advance_events(next_time, maintenance))

            self.audit_repo.log_action(
                actor_id=actor_id,
                action="clock_advance",
                target_type="system_clock",
                target_id=next_time.isoformat(),
                details=" | ".join(events) if events else "운영 시점 이동",
            )

            state["next_time"] = next_time
            state["events"] = self._build_display_result_events(
                previous_time=current_time,
                current_time=next_time,
                actor_id=actor_id,
                actor_role=actor_role,
            )
            state["maintenance"] = maintenance
            state["forced"] = force
            state["can_advance"] = True
            return state

    def _clock_file_path(self):
        return self.user_repo.file_path.parent / 'clock.txt'

    def _integrity_repositories(self):
        return [
            self.user_repo,
            self.room_repo,
            self.equipment_repo,
            self.room_booking_repo,
            self.equipment_booking_repo,
            self.penalty_repo,
            self.audit_repo,
        ]

    def _get_penalty_user(self, booking_user_id):
        return self.user_repo.get_by_id(booking_user_id)

    def _handle_boundary_automation(self, current_time, actor_id="system"):
        if current_time.hour == 9:
            return self._auto_handle_start_slot(
                current_time,
                actor_id=actor_id,
            )
        if current_time.hour == 18:
            return self._auto_handle_end_slot(
                current_time,
                actor_id=actor_id,
            )
        return []

    def _auto_handle_start_slot(self, current_time, actor_id="system"):
        events = []
        now = now_iso()

        # 09:00 시점: 픽업/체크인 요청이 들어온 건만 자동 승인 처리
        # RESERVED 상태(미요청 노쇼)는 이 시점에서 패널티를 부여하지 않음.
        # 유저가 09:00~18:00 사이에 요청할 수 있으므로,
        # 18:00 시점(_auto_handle_end_slot)에서 노쇼 여부를 최종 판단함.

        for booking in self.room_booking_repo.get_all():
            if datetime.fromisoformat(booking.start_time) != current_time:
                continue
            if booking.status == RoomBookingStatus.CHECKIN_REQUESTED:
                self.room_booking_repo.update(
                    replace(
                        booking,
                        status=RoomBookingStatus.CHECKED_IN,
                        checked_in_at=now,
                        updated_at=now,
                    )
                )
                events.append(f"회의실 예약 {booking.id[:8]} 자동 체크인 승인")
            # RESERVED 상태는 18:00에 처리 — 여기서는 아무것도 하지 않음

        for booking in self.equipment_booking_repo.get_all():
            if datetime.fromisoformat(booking.start_time) != current_time:
                continue
            if booking.status == EquipmentBookingStatus.PICKUP_REQUESTED:
                self.equipment_booking_repo.update(
                    replace(
                        booking,
                        status=EquipmentBookingStatus.CHECKED_OUT,
                        checked_out_at=now,
                        updated_at=now,
                    )
                )
                events.append(f"장비 예약 {booking.id[:8]} 자동 픽업 승인")
            # RESERVED 상태는 18:00에 처리 — 여기서는 아무것도 하지 않음

        # 09:00 시점: 전날 18:00에 신청된 퇴실/반납 요청 자동 승인 처리
        # (CHECKOUT_REQUESTED / RETURN_REQUESTED → 정상 완료 처리)
        end_time_yesterday = current_time.replace(hour=18, minute=0, second=0, microsecond=0)
        from datetime import timedelta
        end_time_yesterday = end_time_yesterday - timedelta(days=1)

        for booking in self.room_booking_repo.get_all():
            if datetime.fromisoformat(booking.end_time) != end_time_yesterday:
                continue
            if booking.status == RoomBookingStatus.CHECKOUT_REQUESTED:
                self.room_booking_repo.update(
                    replace(
                        booking,
                        status=RoomBookingStatus.COMPLETED,
                        completed_at=now,
                        updated_at=now,
                    )
                )
                user = self.user_repo.get_by_id(booking.user_id)
                if user:
                    self.penalty_service.record_normal_use(user)
                events.append(f"회의실 예약 {booking.id[:8]} 자동 퇴실 승인")

        for booking in self.equipment_booking_repo.get_all():
            if datetime.fromisoformat(booking.end_time) != end_time_yesterday:
                continue
            if booking.status == EquipmentBookingStatus.RETURN_REQUESTED:
                # 반납 신청 완료 → 정상 자동 승인
                self.equipment_booking_repo.update(
                    replace(
                        booking,
                        status=EquipmentBookingStatus.RETURNED,
                        returned_at=now,
                        updated_at=now,
                    )
                )
                user = self.user_repo.get_by_id(booking.user_id)
                if user:
                    self.penalty_service.record_normal_use(user)
                events.append(f"장비 예약 {booking.id[:8]} 자동 반납 승인")
            elif booking.status == EquipmentBookingStatus.CHECKED_OUT:
                # 반납 신청 안 함 → 지연 반납 패널티 + 자동 반납 처리
                self.equipment_booking_repo.update(
                    replace(
                        booking,
                        status=EquipmentBookingStatus.RETURNED,
                        returned_at=now,
                        updated_at=now,
                    )
                )
                user = self._get_penalty_user(booking.user_id)
                if user:
                    self.penalty_service.apply_late_return(
                        user=user,
                        booking_type="equipment_booking",
                        booking_id=booking.id,
                        delay_minutes=60,
                        actor_id=actor_id,
                    )
                events.append(f"장비 예약 {booking.id[:8]} 지연 반납 자동 패널티")

        return events

    def _restore_overnight_resources(self, current_time):
        if current_time.hour != 9:
            return {"rooms": [], "equipment": []}

        restored_rooms = []
        restored_equipment = []

        for room in self.room_repo.get_all():
            if room.status not in {ResourceStatus.MAINTENANCE, ResourceStatus.DISABLED}:
                continue
            if self._room_has_active_usage_at(room.id, current_time):
                continue

            latest_usage = self._get_latest_room_usage_booking(room.id)
            if latest_usage is None:
                continue

            latest_end = datetime.fromisoformat(latest_usage.end_time)
            restore_at = (latest_end + timedelta(days=1)).replace(
                hour=9,
                minute=0,
                second=0,
                microsecond=0,
            )
            if restore_at != current_time:
                continue

            self.room_repo.update(
                replace(
                    room,
                    status=ResourceStatus.AVAILABLE,
                    updated_at=now_iso(),
                )
            )
            restored_rooms.append(room.id)
            self.audit_repo.log_action(
                actor_id="system",
                action="auto_restore_room_status",
                target_type="room",
                target_id=room.id,
                details="익일 09:00 자동 복원",
            )

        for equipment in self.equipment_repo.get_all():
            if equipment.status not in {ResourceStatus.MAINTENANCE, ResourceStatus.DISABLED}:
                continue
            if datetime.fromisoformat(equipment.updated_at) >= current_time:
                continue
            if self._equipment_has_active_usage_at(equipment.id, current_time):
                continue

            self.equipment_repo.update(
                replace(
                    equipment,
                    status=ResourceStatus.AVAILABLE,
                    updated_at=now_iso(),
                )
            )
            restored_equipment.append(equipment.id)
            self.audit_repo.log_action(
                actor_id="system",
                action="auto_restore_equipment_status",
                target_type="equipment",
                target_id=equipment.id,
                details="익일 09:00 자동 복원",
            )

        return {"rooms": restored_rooms, "equipment": restored_equipment}

    def _get_latest_room_usage_booking(self, room_id):
        candidates = []

        for booking in self.room_booking_repo.get_by_room(room_id):
            if not booking.checked_in_at:
                continue
            if booking.status in {
                RoomBookingStatus.CANCELLED,
                RoomBookingStatus.ADMIN_CANCELLED,
            }:
                continue
            candidates.append(booking)

        if not candidates:
            return None

        return max(
            candidates,
            key=lambda booking: (
                datetime.fromisoformat(booking.checked_in_at),
                datetime.fromisoformat(booking.end_time),
                booking.id,
            ),
        )

    def _room_has_active_usage_at(self, room_id, current_time):
        active_statuses = {
            RoomBookingStatus.RESERVED,
            RoomBookingStatus.CHECKIN_REQUESTED,
            RoomBookingStatus.CHECKED_IN,
            RoomBookingStatus.CHECKOUT_REQUESTED,
        }
        for booking in self.room_booking_repo.get_by_room(room_id):
            if booking.status not in active_statuses:
                continue
            start_time = datetime.fromisoformat(booking.start_time)
            end_time = datetime.fromisoformat(booking.end_time)
            if start_time <= current_time < end_time:
                return True
        return False

    def _equipment_has_active_usage_at(self, equipment_id, current_time):
        active_statuses = {
            EquipmentBookingStatus.RESERVED,
            EquipmentBookingStatus.PICKUP_REQUESTED,
            EquipmentBookingStatus.CHECKED_OUT,
            EquipmentBookingStatus.RETURN_REQUESTED,
        }
        for booking in self.equipment_booking_repo.get_by_equipment(equipment_id):
            if booking.status not in active_statuses:
                continue
            start_time = datetime.fromisoformat(booking.start_time)
            end_time = datetime.fromisoformat(booking.end_time)
            if start_time <= current_time < end_time:
                return True
        return False

    def _auto_handle_end_slot(self, current_time, actor_id="system"):
        events = []
        now = now_iso()

        # 18:00 시점: 당일(start_time == 오늘 09:00) 예약 중 RESERVED 상태 → 노쇼 패널티
        # 기존 09:00 처리 로직과 동일, 시점만 18:00으로 이동
        start_time_today = current_time.replace(hour=9, minute=0, second=0, microsecond=0)

        for booking in self.room_booking_repo.get_all():
            if datetime.fromisoformat(booking.start_time) != start_time_today:
                continue
            if booking.status == RoomBookingStatus.RESERVED:
                self.room_booking_repo.update(
                    replace(
                        booking,
                        status=RoomBookingStatus.ADMIN_CANCELLED,
                        cancelled_at=now,
                        updated_at=now,
                    )
                )
                user = self._get_penalty_user(booking.user_id)
                if user:
                    self.penalty_service.apply_late_cancel(
                        user=user,
                        booking_type="room_booking",
                        booking_id=booking.id,
                        actor_id=actor_id,
                    )
                events.append(f"회의실 예약 {booking.id[:8]} 시작 미처리 자동 취소")

        for booking in self.equipment_booking_repo.get_all():
            if datetime.fromisoformat(booking.start_time) != start_time_today:
                continue
            if booking.status == EquipmentBookingStatus.RESERVED:
                self.equipment_booking_repo.update(
                    replace(
                        booking,
                        status=EquipmentBookingStatus.ADMIN_CANCELLED,
                        cancelled_at=now,
                        updated_at=now,
                    )
                )
                user = self._get_penalty_user(booking.user_id)
                if user:
                    self.penalty_service.apply_late_cancel(
                        user=user,
                        booking_type="equipment_booking",
                        booking_id=booking.id,
                        actor_id=actor_id,
                    )
                events.append(f"장비 예약 {booking.id[:8]} 시작 미처리 자동 취소")

        # 18:00 시점: 정상 퇴실/반납 처리 및 지연 패널티
        # 18:00 시점: CHECKED_IN(지연 퇴실 패널티), CHECKED_OUT(지연 반납 패널티)만 처리
        # CHECKOUT_REQUESTED / RETURN_REQUESTED는 다음날 09:00(_auto_handle_start_slot)에서 자동 승인 처리

        for booking in self.room_booking_repo.get_all():
            if datetime.fromisoformat(booking.end_time) != current_time:
                continue
            if booking.status == RoomBookingStatus.CHECKED_IN:
                self.room_booking_repo.update(
                    replace(
                        booking,
                        status=RoomBookingStatus.COMPLETED,
                        completed_at=now,
                        updated_at=now,
                    )
                )
                user = self._get_penalty_user(booking.user_id)
                if user:
                    self.penalty_service.apply_late_return(
                        user=user,
                        booking_type="room_booking",
                        booking_id=booking.id,
                        delay_minutes=60,
                        actor_id=actor_id,
                    )
                events.append(f"회의실 예약 {booking.id[:8]} 지연 퇴실 자동 패널티")

        for booking in self.equipment_booking_repo.get_all():
            if datetime.fromisoformat(booking.end_time) != current_time:
                continue
            # CHECKED_OUT 상태는 18:00에 blocker로만 처리
            # 유저가 반납 신청을 안 한 경우 → 다음날 09:00에 지연 패널티 + 자동 반납 처리
            # (아무것도 하지 않음)

        return events

    def _build_force_notice(self, actor_id, blockers):
        if not blockers:
            return ""
        return "미해결 사건이 있어도 강행할 수 있습니다. 자동 패널티는 각 예약의 책임 사용자 기준으로 처리됩니다."

    def _build_advance_state(self, current_time, actor_id="system", actor_role="user"):
        next_time = self.clock.next_slot()
        blockers = []

        if current_time.hour == 9:
            blockers.extend(self._collect_start_blockers(current_time))
        else:
            blockers.extend(self._collect_end_blockers(current_time))

        return {
            "can_advance": len(blockers) == 0,
            "current_time": current_time,
            "next_time": next_time,
            "blockers": blockers,
            "events": self._build_display_events(
                current_time=current_time,
                actor_id=actor_id,
                actor_role=actor_role,
            ),
            "force_notice": self._build_force_notice(actor_id, blockers),
        }

    def _build_display_events(self, current_time, actor_id="system", actor_role="user"):
        next_time = compute_next_slot(current_time)
        events = [f"{next_time.strftime('%Y-%m-%d %H:%M')}로 이동 준비"]

        if actor_role == "admin":
            if current_time.hour == 9:
                events.append(
                    f"회의실 예약 종료 예정 {self._count_room_endings(next_time)}건, 장비 반납 예정 {self._count_equipment_endings(next_time)}건"
                )
            else:
                events.append(
                    f"회의실 예약 시작 예정 {self._count_room_starts(next_time)}건, 장비 픽업 예정 {self._count_equipment_starts(next_time)}건"
                )
            return events

        if current_time.hour == 9:
            events.append(
                f"당일 종료 예정 회의실 {self._count_room_endings(next_time, actor_id)}건, 장비 {self._count_equipment_endings(next_time, actor_id)}건"
            )
        else:
            events.append(
                f"다음 시점 시작 예정 회의실 {self._count_room_starts(next_time, actor_id)}건, 장비 {self._count_equipment_starts(next_time, actor_id)}건"
            )
        return events

    def _build_display_result_events(self, previous_time, current_time, actor_id="system", actor_role="user"):
        events = []

        room_completed = [
            booking
            for booking in self.room_booking_repo.get_all()
            if booking.completed_at == current_time.isoformat()
            and (actor_role == "admin" or booking.user_id == actor_id)
        ]
        equipment_returned = [
            booking
            for booking in self.equipment_booking_repo.get_all()
            if booking.returned_at == current_time.isoformat()
            and (actor_role == "admin" or booking.user_id == actor_id)
        ]
        room_started = [
            booking
            for booking in self.room_booking_repo.get_all()
            if booking.checked_in_at == current_time.isoformat()
            and (actor_role == "admin" or booking.user_id == actor_id)
        ]
        equipment_started = [
            booking
            for booking in self.equipment_booking_repo.get_all()
            if booking.checked_out_at == current_time.isoformat()
            and (actor_role == "admin" or booking.user_id == actor_id)
        ]

        if actor_role == "admin":
            if current_time.hour == 18:
                if room_completed:
                    events.append(f"회의실 예약 종료 처리 {len(room_completed)}건")
                if equipment_returned:
                    events.append(f"장비 반납 처리 {len(equipment_returned)}건")
            else:
                if room_started:
                    events.append(f"회의실 예약 시작 처리 {len(room_started)}건")
                if equipment_started:
                    events.append(f"장비 픽업 처리 {len(equipment_started)}건")
            return events

        if current_time.hour == 18:
            if room_completed:
                events.append("본인의 회의실 예약이 종료되었습니다.")
            if equipment_returned:
                events.append("본인의 장비 반납이 완료되었습니다.")
        else:
            if room_started:
                events.append("본인의 회의실 예약이 시작되었습니다.")
            if equipment_started:
                events.append("본인의 장비 픽업이 완료되었습니다.")
        return events

    def _user_label(self, user_id):
        user = self.user_repo.get_by_id(user_id)
        if user is None:
            return user_id
        return user.username

    def _collect_start_blockers(self, current_time):
        blockers = []

        for booking in self.room_booking_repo.get_all():
            if booking.status not in {
                RoomBookingStatus.RESERVED,
                RoomBookingStatus.CHECKIN_REQUESTED,
            }:
                continue
            if datetime.fromisoformat(booking.start_time) != current_time:
                continue
            if booking.status == RoomBookingStatus.CHECKIN_REQUESTED:
                blockers.append(
                    f"회의실 예약 {booking.id[:8]} ({self._user_label(booking.user_id)})은 체크인 승인 대기 상태입니다."
                )
            else:
                blockers.append(
                    f"회의실 예약 {booking.id[:8]} ({self._user_label(booking.user_id)})은 체크인 요청 또는 자동 취소 처리가 필요합니다."
                )

        for booking in self.equipment_booking_repo.get_all():
            if booking.status not in {
                EquipmentBookingStatus.RESERVED,
                EquipmentBookingStatus.PICKUP_REQUESTED,
            }:
                continue
            if datetime.fromisoformat(booking.start_time) != current_time:
                continue
            if booking.status == EquipmentBookingStatus.PICKUP_REQUESTED:
                blockers.append(
                    f"장비 예약 {booking.id[:8]} ({self._user_label(booking.user_id)})은 픽업 승인 대기 상태입니다."
                )
            else:
                blockers.append(
                    f"장비 예약 {booking.id[:8]} ({self._user_label(booking.user_id)})은 픽업 요청 또는 자동 취소 처리가 필요합니다."
                )

        return blockers

    def _collect_end_blockers(self, current_time):
        blockers = []

        for booking in self.room_booking_repo.get_all():
            if datetime.fromisoformat(booking.end_time) != current_time:
                continue
            if booking.status == RoomBookingStatus.CHECKED_IN:
                blockers.append(
                    f"회의실 예약 {booking.id[:8]} ({self._user_label(booking.user_id)})은 사용자 퇴실 신청이 필요합니다."
                )
            elif booking.status == RoomBookingStatus.CHECKOUT_REQUESTED:
                blockers.append(
                    f"회의실 예약 {booking.id[:8]} ({self._user_label(booking.user_id)})은 관리자 퇴실 승인이 필요합니다."
                )

        for booking in self.equipment_booking_repo.get_all():
            if datetime.fromisoformat(booking.end_time) != current_time:
                continue
            if booking.status == EquipmentBookingStatus.CHECKED_OUT:
                blockers.append(
                    f"장비 예약 {booking.id[:8]} ({self._user_label(booking.user_id)})은 사용자 반납 신청이 필요합니다."
                )
            elif booking.status == EquipmentBookingStatus.RETURN_REQUESTED:
                blockers.append(
                    f"장비 예약 {booking.id[:8]} ({self._user_label(booking.user_id)})은 관리자 반납 승인이 필요합니다."
                )

        return blockers

    def _count_room_starts(self, target_time, user_id=None):
        return len(
            [
                booking
                for booking in self.room_booking_repo.get_all()
                if booking.status
                in {RoomBookingStatus.RESERVED, RoomBookingStatus.CHECKIN_REQUESTED}
                and (user_id is None or booking.user_id == user_id)
                and datetime.fromisoformat(booking.start_time) == target_time
            ]
        )

    def _count_equipment_starts(self, target_time, user_id=None):
        return len(
            [
                booking
                for booking in self.equipment_booking_repo.get_all()
                if booking.status
                in {EquipmentBookingStatus.RESERVED, EquipmentBookingStatus.PICKUP_REQUESTED}
                and (user_id is None or booking.user_id == user_id)
                and datetime.fromisoformat(booking.start_time) == target_time
            ]
        )

    def _count_room_endings(self, target_time, user_id=None):
        return len(
            [
                booking
                for booking in self.room_booking_repo.get_all()
                if booking.status
                in {RoomBookingStatus.CHECKED_IN, RoomBookingStatus.CHECKOUT_REQUESTED}
                and (user_id is None or booking.user_id == user_id)
                and datetime.fromisoformat(booking.end_time) == target_time
            ]
        )

    def _count_equipment_endings(self, target_time, user_id=None):
        return len(
            [
                booking
                for booking in self.equipment_booking_repo.get_all()
                if booking.status
                in {
                    EquipmentBookingStatus.CHECKED_OUT,
                    EquipmentBookingStatus.RETURN_REQUESTED,
                }
                and (user_id is None or booking.user_id == user_id)
                and datetime.fromisoformat(booking.end_time) == target_time
            ]
        )

    def _build_post_advance_events(self, current_time, maintenance):
        events = [f"운영 시점이 {current_time.strftime('%Y-%m-%d %H:%M')}로 이동했습니다."]

        reset_count = len(maintenance["penalty_reset_users"])
        expired_count = len(maintenance["restriction_expired_users"])
        cancelled_count = len(maintenance["banned_user_cancelled_bookings"])
        restored_room_count = len(maintenance["restored_room_resources"])
        restored_equipment_count = len(maintenance["restored_equipment_resources"])

        if reset_count:
            events.append(f"90일 경과 패널티 초기화 {reset_count}건")
        if expired_count:
            events.append(f"이용 제한 만료 처리 {expired_count}건")
        if cancelled_count:
            events.append(f"이용 금지 사용자 미래 예약 자동 취소 {cancelled_count}건")
        if restored_room_count:
            events.append(f"회의실 상태 익일 09:00 자동 복원 {restored_room_count}건")
        if restored_equipment_count:
            events.append(f"장비 상태 익일 09:00 자동 복원 {restored_equipment_count}건")

        return events

    def _check_penalty_resets(self, current_time):
        """90일 경과 패널티 초기화"""
        reset_users = []

        for user in self.user_repo.get_all():
            if user.penalty_points > 0:
                if self.penalty_service.check_90_day_reset(user, current_time):
                    reset_users.append(user)

        return reset_users

    def _check_restriction_expiry(self, current_time):
        """제한 기간 만료 반영"""
        expired_users = []

        for user in self.user_repo.get_all():
            if user.restriction_until:
                restriction_end = datetime.fromisoformat(user.restriction_until)
                if restriction_end <= current_time:
                    # 제한 기간 만료 - restriction_until 초기화
                    updated = replace(
                        user, restriction_until=None, updated_at=now_iso()
                    )
                    self.user_repo.update(updated)

                    self.audit_repo.log_action(
                        actor_id="system",
                        action="restriction_expired",
                        target_type="user",
                        target_id=user.id,
                        details="제한 기간 만료",
                    )

                    expired_users.append(updated)

        return expired_users

    def _cancel_banned_user_bookings(self, current_time):
        """6점 이상 사용자의 미래 예약 자동 취소"""
        cancelled_ids = []

        for user in self.user_repo.get_all():
            status = evaluate_user_restriction(user, current_time)
            if status["is_banned"]:
                # 회의실 미래 예약 취소
                for booking in self.room_booking_repo.get_by_user(user.id):
                    if booking.status == RoomBookingStatus.RESERVED:
                        start = datetime.fromisoformat(booking.start_time)
                        if start > current_time:
                            updated = replace(
                                booking,
                                status=RoomBookingStatus.ADMIN_CANCELLED,
                                cancelled_at=now_iso(),
                                updated_at=now_iso(),
                            )
                            self.room_booking_repo.update(updated)
                            cancelled_ids.append(booking.id)

                            self.audit_repo.log_action(
                                actor_id="system",
                                action="auto_cancel_banned_user",
                                target_type="room_booking",
                                target_id=booking.id,
                                details=f"사용자 {user.username} 이용 금지로 인한 자동 취소",
                            )

                # 장비 미래 예약 취소
                for booking in self.equipment_booking_repo.get_by_user(user.id):
                    if booking.status == EquipmentBookingStatus.RESERVED:
                        start = datetime.fromisoformat(booking.start_time)
                        if start > current_time:
                            updated = replace(
                                booking,
                                status=EquipmentBookingStatus.ADMIN_CANCELLED,
                                cancelled_at=now_iso(),
                                updated_at=now_iso(),
                            )
                            self.equipment_booking_repo.update(updated)
                            cancelled_ids.append(booking.id)

                            self.audit_repo.log_action(
                                actor_id="system",
                                action="auto_cancel_banned_user",
                                target_type="equipment_booking",
                                target_id=booking.id,
                                details=f"사용자 {user.username} 이용 금지로 인한 자동 취소",
                            )

        return cancelled_ids

    def check_user_can_book(self, user):
        """
        사용자가 예약 가능한지 확인

        Returns:
            (can_book: bool, max_active_total: int, message: str)
        """
        status = self.penalty_service.get_user_status(user)

        if status.get("is_banned"):
            return (
                False,
                0,
                f"이용이 금지된 상태입니다. 금지 해제일: {status.get('restriction_until', '알 수 없음')}",
            )

        if status.get("is_restricted"):
            room_active = len(self.room_booking_repo.get_active_by_user(user.id))
            equipment_active = len(
                self.equipment_booking_repo.get_active_by_user(user.id)
            )

            if room_active >= MAX_ACTIVE_ROOM_BOOKINGS and equipment_active >= MAX_ACTIVE_EQUIPMENT_BOOKINGS:
                return (
                    False,
                    MAX_ACTIVE_ROOM_BOOKINGS + MAX_ACTIVE_EQUIPMENT_BOOKINGS,
                    "패널티로 인해 추가 예약이 불가합니다.",
                )
            return (
                True,
                MAX_ACTIVE_ROOM_BOOKINGS + MAX_ACTIVE_EQUIPMENT_BOOKINGS,
                "패널티로 인해 각 예약 유형별 1건까지만 유지할 수 있습니다.",
            )

        return (
            True,
            MAX_ACTIVE_ROOM_BOOKINGS + MAX_ACTIVE_EQUIPMENT_BOOKINGS,
            "",
        )

    def get_max_bookings_for_user(self, user):
        """
        사용자의 최대 예약 가능 수 반환

        Returns:
            (max_room_bookings: int, max_equipment_bookings: int)
        """
        can_book, max_total, _ = self.check_user_can_book(user)

        if not can_book:
            return (0, 0)

        if max_total == MAX_ACTIVE_ROOM_BOOKINGS + MAX_ACTIVE_EQUIPMENT_BOOKINGS:
            room_active = len(self.room_booking_repo.get_active_by_user(user.id))
            equipment_active = len(
                self.equipment_booking_repo.get_active_by_user(user.id)
            )
            return (
                0 if room_active >= MAX_ACTIVE_ROOM_BOOKINGS else MAX_ACTIVE_ROOM_BOOKINGS,
                0 if equipment_active >= MAX_ACTIVE_EQUIPMENT_BOOKINGS else MAX_ACTIVE_EQUIPMENT_BOOKINGS,
            )

        return (MAX_ACTIVE_ROOM_BOOKINGS, MAX_ACTIVE_EQUIPMENT_BOOKINGS)

    def get_user_flow_limits(self, user):
        status = self.penalty_service.get_user_status(user)
        room_active = len(self.room_booking_repo.get_active_by_user(user.id))
        equipment_active = len(self.equipment_booking_repo.get_active_by_user(user.id))
        total_active = room_active + equipment_active

        if status.get("is_banned"):
            return {
                "can_book": False,
                "room_limit": 0,
                "equipment_limit": 0,
                "message": f"이용이 금지된 상태입니다. 금지 해제일: {status.get('restriction_until', '알 수 없음')}",
            }

        if status.get("is_restricted"):
            room_limit = 0 if room_active >= MAX_ACTIVE_ROOM_BOOKINGS else MAX_ACTIVE_ROOM_BOOKINGS
            equipment_limit = 0 if equipment_active >= MAX_ACTIVE_EQUIPMENT_BOOKINGS else MAX_ACTIVE_EQUIPMENT_BOOKINGS
            if room_limit == 0 and equipment_limit == 0:
                return {
                    "can_book": False,
                    "room_limit": room_limit,
                    "equipment_limit": equipment_limit,
                    "message": "패널티로 인해 추가 예약이 불가합니다.",
                }
            return {
                "can_book": True,
                "room_limit": room_limit,
                "equipment_limit": equipment_limit,
                "message": "패널티로 인해 각 예약 유형별 1건까지만 유지할 수 있습니다.",
            }

        return {
            "can_book": True,
            "room_limit": 0 if room_active >= 1 else 1,
            "equipment_limit": 0 if equipment_active >= 1 else 1,
            "message": "",
        }
