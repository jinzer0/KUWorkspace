"""
장비 예약 서비스
"""

from datetime import datetime, timedelta
from dataclasses import replace

from src.domain.models import (
    User,
    EquipmentAsset,
    EquipmentBooking,
    EquipmentBookingStatus,
    ResourceStatus,
    decode_future_status_changes,
    encode_future_status_changes,
    UserRole,
    generate_id,
    now_iso,
)
from src.domain.daily_booking_rules import (
    build_daily_booking_period,
    validate_daily_booking_dates,
)
from src.domain.restriction_rules import evaluate_user_restriction
from src.storage.repositories import (
    UserRepository,
    RoomBookingRepository,
    EquipmentAssetRepository,
    EquipmentBookingRepository,
    AuditLogRepository,
    UnitOfWork,
)
from src.storage.file_lock import global_lock
from src.runtime_clock import get_active_clock, get_runtime_clock
from src.config import (
    MAX_ACTIVE_EQUIPMENT_BOOKINGS,
    MAX_RESTRICTED_EQUIPMENT_BOOKINGS,
    LATE_CANCEL_THRESHOLD_MINUTES,
    FIXED_BOOKING_START_HOUR,
    FIXED_BOOKING_START_MINUTE,
    FIXED_BOOKING_END_HOUR,
    FIXED_BOOKING_END_MINUTE,
)
from src.domain.field_rules import (
    validate_reason_text,
    validate_reservation_memo_text,
    validate_equipment_asset_type,
    validate_equipment_description,
    validate_equipment_name,
)


MAX_EQUIPMENT_RESOURCES = 20
MIN_EQUIPMENT_RESOURCES = 12


class EquipmentBookingError(Exception):
    """장비 예약 관련 예외"""


class AdminRequiredError(Exception):
    """관리자 권한 필요 예외"""


def _require_admin(user):
    """관리자 권한 확인"""
    if user.role != UserRole.ADMIN:
        raise AdminRequiredError("관리자만 수행할 수 있는 작업입니다.")


class EquipmentService:
    """장비 예약 서비스"""

    def __init__(
        self,
        equipment_repo=None,
        booking_repo=None,
        room_booking_repo=None,
        user_repo=None,
        audit_repo=None,
        penalty_service=None,
        clock=None,
    ):
        from src.domain.penalty_service import PenaltyService

        self.clock = clock or get_runtime_clock()
        self.equipment_repo = equipment_repo or EquipmentAssetRepository()
        self.booking_repo = booking_repo or EquipmentBookingRepository()
        self.room_booking_repo = room_booking_repo or RoomBookingRepository()
        self.user_repo = user_repo or UserRepository()
        self.audit_repo = audit_repo or AuditLogRepository()
        self.penalty_service = penalty_service or PenaltyService(
            user_repo=self.user_repo,
            audit_repo=self.audit_repo,
            clock=self.clock,
        )

    def _get_existing_user(self, user):
        current_user = self.user_repo.get_by_id(user.id)
        if current_user is None:
            raise EquipmentBookingError("존재하지 않는 사용자입니다.")
        return current_user

    def _get_existing_user_by_id(self, user_id):
        current_user = self.user_repo.get_by_id(user_id)
        if current_user is None:
            raise EquipmentBookingError("존재하지 않는 사용자입니다.")
        return current_user

    def _get_existing_admin(self, admin):
        _require_admin(admin)
        current_admin = self.user_repo.get_by_id(admin.id)
        if current_admin is None or current_admin.role != UserRole.ADMIN:
            raise AdminRequiredError("관리자만 수행할 수 있는 작업입니다.")
        return current_admin

    def _ensure_user_can_create_booking(self, user):
        current_user = self._get_existing_user(user)
        status = evaluate_user_restriction(current_user, self.clock.now())

        if status["is_banned"]:
            raise EquipmentBookingError(
                f"이용이 금지된 상태입니다. 금지 해제일: {status['restriction_until']}"
            )

        cancel_restricted_until = current_user.equipment_cancel_restricted_until
        if cancel_restricted_until:
            restriction_end = datetime.fromisoformat(cancel_restricted_until)
            if restriction_end > self.clock.now():
                raise EquipmentBookingError(
                    f"빈번한 취소로 인해 예약이 제한된 상태입니다. 제한 해제일: {cancel_restricted_until}"
                )

        if status["is_restricted"]:
            equipment_active = len(self.booking_repo.get_quota_active_by_user(current_user.id))
            if equipment_active >= MAX_RESTRICTED_EQUIPMENT_BOOKINGS:
                raise EquipmentBookingError(
                    "패널티로 인해 추가 예약이 불가합니다."
                )

        return current_user

    def _run_policy_checks(self):
        from src.domain.policy_service import PolicyService

        PolicyService(
            user_repo=self.user_repo,
            room_booking_repo=self.room_booking_repo,
            equipment_booking_repo=self.booking_repo,
            equipment_repo=self.equipment_repo,
            penalty_repo=self.penalty_service.penalty_repo,
            audit_repo=self.audit_repo,
            penalty_service=self.penalty_service,
            clock=self.clock,
        ).run_all_checks()

    def _future_unavailable_overlaps(self, equipment, start_time, end_time):
        requested_start = datetime.fromisoformat(start_time) if isinstance(start_time, str) else start_time
        requested_end = datetime.fromisoformat(end_time) if isinstance(end_time, str) else end_time
        for item in decode_future_status_changes(equipment.future_status_changes):
            if item["state"] in {"completed", "cancelled"}:
                continue
            if item["status"] == ResourceStatus.AVAILABLE.value:
                continue
            item_start = datetime.fromisoformat(item["start_time"])
            item_end = datetime.fromisoformat(item["end_time"])
            if requested_end > item_start and requested_start < item_end:
                return item
        return None

    def _ensure_no_future_unavailable_overlap(self, equipment, start_time, end_time):
        item = self._future_unavailable_overlaps(equipment, start_time, end_time)
        if item:
            raise EquipmentBookingError(
                f"장비가 예정된 {item['status']} 상태 기간({item['start_time']} ~ {item['end_time']})과 겹칩니다."
            )

    def _get_group_members_for_booking(self, booking):
        if not booking.group_id:
            return [booking]
        members = self.booking_repo.get_by_group_id(booking.group_id)
        if not members:
            raise EquipmentBookingError("존재하지 않는 예약 그룹입니다.")
        return sorted(members, key=lambda item: (item.created_at, item.id))

    def _collapse_group_rows(self, bookings):
        collapsed = []
        seen_group_ids = set()
        for booking in bookings:
            if booking.group_id:
                if booking.group_id in seen_group_ids:
                    continue
                seen_group_ids.add(booking.group_id)
            collapsed.append(booking)
        return collapsed

    def _ensure_group_status(self, bookings, status, action_text):
        for booking in bookings:
            if booking.status != status:
                raise EquipmentBookingError(
                    f"'{booking.status.value}' 상태의 예약은 {action_text}할 수 없습니다."
                )

    def _eligible_group_rows(self, bookings, status, action_text):
        self._ensure_group_status(bookings, status, action_text)
        return bookings

    def _ensure_group_owner(self, bookings, user_id, action_text):
        for booking in bookings:
            if booking.user_id != user_id:
                raise EquipmentBookingError(f"본인의 예약만 {action_text}할 수 있습니다.")

    def _group_target_id(self, booking):
        return booking.group_id or booking.id

    def schedule_future_status_change(
        self,
        admin,
        equipment_id,
        start_time,
        end_time,
        status,
        restore_status=ResourceStatus.AVAILABLE,
    ):
        admin = self._get_existing_admin(admin)
        target_status = ResourceStatus(status)
        restore_status = ResourceStatus(restore_status)
        start_time, end_time = self._validate_booking_time(start_time, end_time)
        if start_time <= self.clock.now():
            raise EquipmentBookingError("미래 시점의 상태 변경만 예약할 수 있습니다.")

        with global_lock(), UnitOfWork():
            equipment = self.equipment_repo.get_by_id(equipment_id)
            if equipment is None:
                raise EquipmentBookingError("존재하지 않는 장비입니다.")

            items = decode_future_status_changes(equipment.future_status_changes)
            new_item = {
                "id": generate_id(),
                "start_time": start_time.isoformat(timespec="minutes"),
                "end_time": end_time.isoformat(timespec="minutes"),
                "status": target_status.value,
                "restore_status": restore_status.value,
                "state": "pending",
            }
            if target_status != ResourceStatus.AVAILABLE:
                for item in items:
                    if item["state"] in {"completed", "cancelled"}:
                        continue
                    item_start = datetime.fromisoformat(item["start_time"])
                    item_end = datetime.fromisoformat(item["end_time"])
                    if end_time > item_start and start_time < item_end:
                        raise EquipmentBookingError("이미 겹치는 장비 상태 예약이 있습니다.")
            items.append(new_item)
            updated = replace(
                equipment,
                future_status_changes=encode_future_status_changes(items),
                updated_at=now_iso(),
            )
            self.equipment_repo.update(updated)
            self.audit_repo.log_action(
                actor_id=admin.id,
                action="schedule_equipment_future_status_change",
                target_type="equipment",
                target_id=equipment_id,
                details=f"예약: {new_item['id']} {new_item['start_time']} ~ {new_item['end_time']} {target_status.value}",
            )
            return new_item

    def cancel_future_status_change(self, admin, equipment_id, schedule_id):
        admin = self._get_existing_admin(admin)
        with global_lock(), UnitOfWork():
            equipment = self.equipment_repo.get_by_id(equipment_id)
            if equipment is None:
                raise EquipmentBookingError("존재하지 않는 장비입니다.")
            items = decode_future_status_changes(equipment.future_status_changes)
            cancelled_item = None
            updated_items = []
            for item in items:
                if item["id"] == schedule_id and item["state"] in {"pending", "started"}:
                    cancelled_item = {
                        **item,
                        "state": "cancelled",
                        "cancelled_at": now_iso(),
                    }
                    continue
                updated_items.append(item)
            if cancelled_item is None:
                raise EquipmentBookingError("취소할 장비 상태 예약이 없습니다.")
            updated = replace(
                equipment,
                future_status_changes=encode_future_status_changes(updated_items),
                updated_at=now_iso(),
            )
            self.equipment_repo.update(updated)
            self.audit_repo.log_action(
                actor_id=admin.id,
                action="cancel_equipment_future_status_change",
                target_type="equipment",
                target_id=equipment_id,
                details=f"취소: {schedule_id}",
            )
            return cancelled_item

    def _require_current_boundary(self, boundary_time, action_name):
        current_time = self.clock.now()
        if boundary_time != current_time:
            raise EquipmentBookingError(
                f"{action_name}은 현재 운영 시점({current_time.strftime('%Y-%m-%d %H:%M')})과 일치하는 예약에서만 가능합니다."
            )

    def _require_start_request_window(self, booking):
        start_time = datetime.fromisoformat(booking.start_time)
        self._require_current_boundary(start_time, "픽업 요청")

    def _require_end_request_window(self, booking):
        end_time = datetime.fromisoformat(booking.end_time)
        current_time = self.clock.now()
        if current_time > end_time:
            raise EquipmentBookingError(
                f"반납 요청은 예약 종료 시점({end_time.strftime('%Y-%m-%d %H:%M')}) 이전 또는 해당 시점에서만 가능합니다."
            )

    def _is_late_cancel(self, booking, current_time=None):
        if current_time is None:
            current_time = self.clock.now()
        start_time = datetime.fromisoformat(booking.start_time)
        if current_time >= start_time:
            return True
        return (start_time - current_time).total_seconds() / 60 <= LATE_CANCEL_THRESHOLD_MINUTES

    def _get_cancellable_booking(self, user, booking_id):
        user = self._get_existing_user(user)
        booking = self.booking_repo.get_by_id(booking_id)
        if booking is None:
            raise EquipmentBookingError("존재하지 않는 예약입니다.")
        bookings = self._get_group_members_for_booking(booking)
        self._ensure_group_owner(bookings, user.id, "취소")
        self._eligible_group_rows(bookings, EquipmentBookingStatus.RESERVED, "취소")
        return user, booking

    def preview_cancel_booking_impact(self, user, booking_id):
        user, booking = self._get_cancellable_booking(user, booking_id)
        return self.penalty_service.preview_cancel_impact(
            user=user,
            booking_type="equipment_booking",
            booking_id=booking.id,
            booking_start_time=booking.start_time,
            domain_bookings=self.booking_repo.get_by_user(user.id),
        )

    def will_apply_late_cancel_penalty(self, user, booking_id):
        return self.preview_cancel_booking_impact(user, booking_id).is_late_cancel

    def get_all_equipment(self):
        """모든 장비 조회"""
        return self.equipment_repo.get_all()

    def get_available_equipment(self):
        """예약 가능한 장비 조회"""
        return self.equipment_repo.get_available()

    def get_equipment(self, equipment_id):
        """장비 조회"""
        return self.equipment_repo.get_by_id(equipment_id)

    def get_equipment_by_type(self, asset_type):
        """종류별 장비 조회"""
        return self.equipment_repo.get_by_type(asset_type)

    def get_available_equipment_by_type(self, asset_type, start_time, end_time):
        equipment_list = [
            item
            for item in self.equipment_repo.get_by_type(asset_type)
            if item.status == ResourceStatus.AVAILABLE
        ]
        available = []
        for item in equipment_list:
            if self._future_unavailable_overlaps(item, start_time, end_time):
                continue
            conflicts = self.booking_repo.get_confirmed_conflicting(
                item.id, start_time.isoformat(), end_time.isoformat()
            )
            if not conflicts:
                available.append(item)
        return available

    def get_available_equipment_for_period(self, start_time, end_time):
        available = []
        for item in self.equipment_repo.get_available():
            if self._future_unavailable_overlaps(item, start_time, end_time):
                continue
            conflicts = self.booking_repo.get_confirmed_conflicting(
                item.id, start_time.isoformat(), end_time.isoformat()
            )
            if not conflicts:
                available.append(item)
        return available

    def _is_eighteen_next_day_request(self, start_time):
        current_time = self.clock.now()
        return (
            current_time.hour == FIXED_BOOKING_END_HOUR
            and current_time.minute == FIXED_BOOKING_END_MINUTE
            and start_time.date() == (current_time + timedelta(days=1)).date()
        )

    def _reject_eighteen_next_day_conflict(self, start_time, conflicts):
        if conflicts and self._is_eighteen_next_day_request(start_time):
            raise EquipmentBookingError(
                "이미 예약된 장비입니다. 18:00 다음날 예약은 선착순 예외 정책에 따라 이후 동일 자원/기간 요청이 거부됩니다."
            )

    def _same_operating_moment_conflict(self, conflict, start_time, end_time):
        if get_active_clock() is None:
            return False
        if datetime.fromisoformat(conflict.start_time) != start_time:
            return False
        if datetime.fromisoformat(conflict.end_time) != end_time:
            return False
        created_at = datetime.fromisoformat(conflict.created_at)
        current_slot = self.clock.now().replace(second=0, microsecond=0)
        return created_at.replace(second=0, microsecond=0) == current_slot

    def _pending_status_for_conflicts(self, start_time, end_time, conflicts):
        if not conflicts:
            return EquipmentBookingStatus.RESERVED
        self._reject_eighteen_next_day_conflict(start_time, conflicts)
        if all(self._same_operating_moment_conflict(conflict, start_time, end_time) for conflict in conflicts):
            return EquipmentBookingStatus.PENDING
        raise EquipmentBookingError(
            "해당 기간에 이미 예약이 있습니다. 다른 날짜 또는 장비를 선택해주세요."
        )

    def create_daily_booking(
        self, user, equipment_id, start_date, end_date, max_active=MAX_ACTIVE_EQUIPMENT_BOOKINGS, memo=""
    ):
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                user = self._ensure_user_can_create_booking(user)
                equipment = self.equipment_repo.get_by_id(equipment_id)
                if equipment is None:
                    raise EquipmentBookingError("존재하지 않는 장비입니다.")

                if equipment.status != ResourceStatus.AVAILABLE:
                    raise EquipmentBookingError(
                        f"장비가 현재 {equipment.status.value} 상태입니다."
                    )

                valid, error, _ = validate_daily_booking_dates(
                    start_date, end_date, self.clock.now()
                )
                if not valid:
                    raise EquipmentBookingError(error)

                start_time, end_time = build_daily_booking_period(start_date, end_date)
                self._ensure_no_future_unavailable_overlap(equipment, start_time, end_time)

                active_bookings = self._collapse_group_rows(
                    self.booking_repo.get_quota_active_by_user(user.id)
                )
                if len(active_bookings) >= max_active:
                    raise EquipmentBookingError(
                        f"활성 장비 예약 한도({max_active}건)를 초과했습니다. 현재 활성 예약: {len(active_bookings)}건"
                    )

                conflicts = self.booking_repo.get_confirmed_conflicting(
                    equipment_id, start_time.isoformat(), end_time.isoformat()
                )
                booking_status = self._pending_status_for_conflicts(
                    start_time, end_time, conflicts
                )

                validate_reservation_memo_text(memo)

                booking = EquipmentBooking(
                    id=generate_id(),
                    user_id=user.id,
                    equipment_id=equipment_id,
                    start_time=start_time.isoformat(),
                    end_time=end_time.isoformat(),
                    status=booking_status,
                    memo=memo,
                )

                self.booking_repo.add(booking)
                self.audit_repo.log_action(
                    actor_id=user.id,
                    action="create_equipment_booking_daily",
                    target_type="equipment_booking",
                    target_id=booking.id,
                    details=f"장비: {equipment.name}, 기간: {start_time} ~ {end_time}",
                )
                return booking

    def modify_daily_booking(self, user, booking_id, start_date, end_date, memo=""):
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                user = self._get_existing_user(user)
                booking = self.booking_repo.get_by_id(booking_id)
                if booking is None:
                    raise EquipmentBookingError("존재하지 않는 예약입니다.")
                bookings = self._get_group_members_for_booking(booking)
                self._ensure_group_owner(bookings, user.id, "변경")
                bookings = self._eligible_group_rows(bookings, EquipmentBookingStatus.RESERVED, "변경")

                valid, error, _ = validate_daily_booking_dates(
                    start_date, end_date, self.clock.now()
                )
                if not valid:
                    raise EquipmentBookingError(error)

                start_time, end_time = build_daily_booking_period(start_date, end_date)
                booking_ids = {item.id for item in bookings}
                for item in bookings:
                    equipment = self.equipment_repo.get_by_id(item.equipment_id)
                    if equipment is None:
                        raise EquipmentBookingError("존재하지 않는 장비입니다.")
                    self._ensure_no_future_unavailable_overlap(equipment, start_time, end_time)
                    conflicts = self.booking_repo.get_confirmed_conflicting(
                        item.equipment_id,
                        start_time.isoformat(),
                        end_time.isoformat(),
                        exclude_ids=booking_ids,
                    )
                    if conflicts:
                        raise EquipmentBookingError(
                            "해당 기간에 이미 예약이 있습니다. 다른 날짜를 선택해주세요."
                        )

                validate_reservation_memo_text(memo)

                updated_bookings = []
                for item in bookings:
                    updated = replace(
                        item,
                        start_time=start_time.isoformat(),
                        end_time=end_time.isoformat(),
                        memo=memo,
                        updated_at=now_iso(),
                    )
                    self.booking_repo.update(updated)
                    updated_bookings.append(updated)
                self.audit_repo.log_action(
                    actor_id=user.id,
                    action="modify_equipment_booking_daily",
                    target_type="equipment_booking",
                    target_id=self._group_target_id(booking),
                    details=f"변경: {start_time} ~ {end_time}",
                )
                return updated_bookings if booking.group_id else updated_bookings[0]

    def admin_modify_daily_booking(self, admin, booking_id, start_date, end_date):
        admin = self._get_existing_admin(admin)
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                booking = self.booking_repo.get_by_id(booking_id)
                if booking is None:
                    raise EquipmentBookingError("존재하지 않는 예약입니다.")

                bookings = self._get_group_members_for_booking(booking)
                bookings = self._eligible_group_rows(bookings, EquipmentBookingStatus.RESERVED, "변경")

                booking_user = self.user_repo.get_by_id(booking.user_id)
                if booking_user is None:
                    raise EquipmentBookingError("존재하지 않는 사용자입니다.")

                valid, error, _ = validate_daily_booking_dates(
                    start_date, end_date, self.clock.now()
                )
                if not valid:
                    raise EquipmentBookingError(error)

                start_time, end_time = build_daily_booking_period(start_date, end_date)
                booking_ids = {item.id for item in bookings}
                for item in bookings:
                    equipment = self.equipment_repo.get_by_id(item.equipment_id)
                    if equipment is None:
                        raise EquipmentBookingError("존재하지 않는 장비입니다.")
                    self._ensure_no_future_unavailable_overlap(equipment, start_time, end_time)
                    conflicts = self.booking_repo.get_confirmed_conflicting(
                        item.equipment_id,
                        start_time.isoformat(),
                        end_time.isoformat(),
                        exclude_ids=booking_ids,
                    )
                    if conflicts:
                        raise EquipmentBookingError("해당 기간에 이미 예약이 있습니다.")

                updated_bookings = []
                for item in bookings:
                    updated = replace(
                        item,
                        start_time=start_time.isoformat(),
                        end_time=end_time.isoformat(),
                        updated_at=now_iso(),
                    )
                    self.booking_repo.update(updated)
                    updated_bookings.append(updated)
                self.audit_repo.log_action(
                    actor_id=admin.id,
                    action="admin_modify_equipment_booking_daily",
                    target_type=(
                        "equipment_booking_group" if booking.group_id else "equipment_booking"
                    ),
                    target_id=self._group_target_id(booking),
                    details=f"변경: {start_time} ~ {end_time}",
                )
                return updated_bookings if booking.group_id else updated_bookings[0]

    def create_booking(
        self,
        user,
        equipment_id,
        start_time,
        end_time,
        max_active=MAX_ACTIVE_EQUIPMENT_BOOKINGS,
        memo="",
    ):
        """
        장비 예약 생성

        Args:
            user: 예약자
            equipment_id: 장비 ID
            start_time: 시작 시간
            end_time: 종료 시간
            max_active: 최대 활성 예약 수 (제한 상태에 따라 다름)

        Returns:
            생성된 예약

        Raises:
            EquipmentBookingError: 예약 불가 시
        """
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                user = self._ensure_user_can_create_booking(user)
                effective_max_active = min(max_active, MAX_ACTIVE_EQUIPMENT_BOOKINGS)

                equipment = self.equipment_repo.get_by_id(equipment_id)
                if equipment is None:
                    raise EquipmentBookingError("존재하지 않는 장비입니다.")

                if equipment.status != ResourceStatus.AVAILABLE:
                    raise EquipmentBookingError(
                        f"장비가 현재 {equipment.status.value} 상태입니다."
                    )

                start_time, end_time = self._validate_booking_time(start_time, end_time)
                self._ensure_no_future_unavailable_overlap(equipment, start_time, end_time)

                active_bookings = self._collapse_group_rows(
                    self.booking_repo.get_quota_active_by_user(user.id)
                )
                if len(active_bookings) >= effective_max_active:
                    raise EquipmentBookingError(
                        f"활성 예약 한도({effective_max_active}건)를 초과했습니다. "
                        f"현재 활성 예약: {len(active_bookings)}건"
                    )

                conflicts = self.booking_repo.get_confirmed_conflicting(
                    equipment_id, start_time.isoformat(), end_time.isoformat()
                )
                booking_status = self._pending_status_for_conflicts(
                    start_time, end_time, conflicts
                )

                validate_reservation_memo_text(memo)

                booking = EquipmentBooking(
                    id=generate_id(),
                    user_id=user.id,
                    equipment_id=equipment_id,
                    start_time=start_time.isoformat(),
                    end_time=end_time.isoformat(),
                    status=booking_status,
                    memo=memo,
                )

                self.booking_repo.add(booking)

                self.audit_repo.log_action(
                    actor_id=user.id,
                    action="create_equipment_booking",
                    target_type="equipment_booking",
                    target_id=booking.id,
                    details=f"장비: {equipment.name}, 시간: {start_time} ~ {end_time}",
                )

                return booking

    def create_group_booking(
        self,
        user,
        equipment_ids,
        start_time,
        end_time,
        max_active=MAX_ACTIVE_EQUIPMENT_BOOKINGS,
        memo="",
    ):
        """여러 장비를 하나의 원자적 예약 그룹으로 생성합니다."""
        equipment_ids = list(equipment_ids)
        if not equipment_ids:
            raise EquipmentBookingError("예약할 장비를 선택해주세요.")
        if len(set(equipment_ids)) != len(equipment_ids):
            raise EquipmentBookingError("같은 장비를 중복 선택할 수 없습니다.")

        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                user = self._ensure_user_can_create_booking(user)
                effective_max_active = min(max_active, MAX_ACTIVE_EQUIPMENT_BOOKINGS)

                active_bookings = self._collapse_group_rows(
                    self.booking_repo.get_quota_active_by_user(user.id)
                )
                if len(active_bookings) >= effective_max_active:
                    raise EquipmentBookingError(
                        f"활성 예약 한도({effective_max_active}건)를 초과했습니다. "
                        f"현재 활성 예약: {len(active_bookings)}건"
                    )

                start_time, end_time = self._validate_booking_time(start_time, end_time)
                validate_reservation_memo_text(memo)

                equipment_by_id = {}
                status_by_id = {}
                for equipment_id in equipment_ids:
                    equipment = self.equipment_repo.get_by_id(equipment_id)
                    if equipment is None:
                        raise EquipmentBookingError("존재하지 않는 장비입니다.")
                    if equipment.status != ResourceStatus.AVAILABLE:
                        raise EquipmentBookingError(
                            f"장비가 현재 {equipment.status.value} 상태입니다."
                        )
                    self._ensure_no_future_unavailable_overlap(
                        equipment, start_time, end_time
                    )
                    conflicts = self.booking_repo.get_confirmed_conflicting(
                        equipment_id, start_time.isoformat(), end_time.isoformat()
                    )
                    status_by_id[equipment_id] = self._pending_status_for_conflicts(
                        start_time, end_time, conflicts
                    )
                    equipment_by_id[equipment_id] = equipment

                asset_types = [equipment_by_id[equipment_id].asset_type for equipment_id in equipment_ids]
                if len(set(asset_types)) != len(asset_types):
                    raise EquipmentBookingError("같은 종류의 장비는 예약하실 수 없습니다.")

                group_id = generate_id()
                bookings = []
                for equipment_id in equipment_ids:
                    booking = EquipmentBooking(
                        id=generate_id(),
                        user_id=user.id,
                        equipment_id=equipment_id,
                        start_time=start_time.isoformat(),
                        end_time=end_time.isoformat(),
                        status=status_by_id[equipment_id],
                        group_id=group_id,
                        memo=memo,
                    )
                    self.booking_repo.add(booking)
                    bookings.append(booking)

                equipment_names = ", ".join(
                    equipment_by_id[equipment_id].name for equipment_id in equipment_ids
                )
                self.audit_repo.log_action(
                    actor_id=user.id,
                    action="create_equipment_group_booking",
                    target_type="equipment_booking_group",
                    target_id=group_id,
                    details=f"장비: {equipment_names}, 시간: {start_time} ~ {end_time}",
                )

                return bookings

    def _validate_booking_time(self, start_time, end_time):
        now = self.clock.now()
        if start_time < now:
            raise EquipmentBookingError("과거 시간은 선택할 수 없습니다.")
        if end_time <= start_time:
            raise EquipmentBookingError("종료 시간은 시작 시간보다 늦어야 합니다.")
        if start_time.minute % 30 != 0 or end_time.minute % 30 != 0:
            raise EquipmentBookingError("시간은 30분 단위로만 입력 가능합니다.")

        normalized_start = datetime.combine(
            start_time.date(),
            datetime.min.time().replace(
                hour=FIXED_BOOKING_START_HOUR,
                minute=FIXED_BOOKING_START_MINUTE,
            ),
        )
        normalized_end = datetime.combine(
            end_time.date(),
            datetime.min.time().replace(
                hour=FIXED_BOOKING_END_HOUR,
                minute=FIXED_BOOKING_END_MINUTE,
            ),
        )

        today = now.date()
        if normalized_start.date() < today:
            raise EquipmentBookingError("과거 시간은 선택할 수 없습니다.")
        if normalized_start.date() > today + timedelta(days=180):
            raise EquipmentBookingError("예약 시작일은 오늘로부터 180일 이내여야 합니다.")
        duration_days = (normalized_end.date() - normalized_start.date()).days + 1
        if duration_days > 14:
            raise EquipmentBookingError("예약 기간은 최대 14일까지 가능합니다.")
        return normalized_start, normalized_end

    def modify_booking(self, user, booking_id, new_start_time, new_end_time, memo=""):
        """
        예약 변경 (사용자: reserved 상태만)
        """
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                user = self._get_existing_user(user)
                booking = self.booking_repo.get_by_id(booking_id)
                if booking is None:
                    raise EquipmentBookingError("존재하지 않는 예약입니다.")
                bookings = self._get_group_members_for_booking(booking)

                self._ensure_group_owner(bookings, user.id, "변경")
                bookings = self._eligible_group_rows(bookings, EquipmentBookingStatus.RESERVED, "변경")

                new_start_time, new_end_time = self._validate_booking_time(
                    new_start_time, new_end_time
                )
                booking_ids = {item.id for item in bookings}
                for item in bookings:
                    equipment = self.equipment_repo.get_by_id(item.equipment_id)
                    if equipment is None:
                        raise EquipmentBookingError("존재하지 않는 장비입니다.")
                    self._ensure_no_future_unavailable_overlap(
                        equipment, new_start_time, new_end_time
                    )

                    conflicts = self.booking_repo.get_confirmed_conflicting(
                        item.equipment_id,
                        new_start_time.isoformat(),
                        new_end_time.isoformat(),
                        exclude_ids=booking_ids,
                    )
                    if conflicts:
                        raise EquipmentBookingError(
                            "해당 시간대에 이미 예약이 있습니다. 다른 시간을 선택해주세요."
                        )

                validate_reservation_memo_text(memo)

                updated_bookings = []
                for item in bookings:
                    updated = replace(
                        item,
                        start_time=new_start_time.isoformat(),
                        end_time=new_end_time.isoformat(),
                        memo=memo,
                        updated_at=now_iso(),
                    )
                    self.booking_repo.update(updated)
                    updated_bookings.append(updated)

                self.audit_repo.log_action(
                    actor_id=user.id,
                    action="modify_equipment_booking",
                    target_type="equipment_booking",
                    target_id=self._group_target_id(booking),
                    details=f"변경: {new_start_time} ~ {new_end_time}",
                )

                return updated_bookings if booking.group_id else updated_bookings[0]


    def _promote_waitlist_for_cancelled_booking(self, booking, actor_id):
        from src.domain.policy_service import PolicyService

        return PolicyService(
            user_repo=self.user_repo,
            room_booking_repo=self.room_booking_repo,
            equipment_booking_repo=self.booking_repo,
            equipment_repo=self.equipment_repo,
            penalty_repo=self.penalty_service.penalty_repo,
            audit_repo=self.audit_repo,
            penalty_service=self.penalty_service,
            clock=self.clock,
        ).promote_equipment_waitlist_for_booking(booking, actor_id=actor_id)

    def cancel_booking(self, user, booking_id):
        """
        예약 취소 (사용자)

        Returns:
            (취소된 예약, 직전 취소 여부)
        """
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                user, booking = self._get_cancellable_booking(user, booking_id)
                bookings = self._get_group_members_for_booking(booking)
                self._ensure_group_owner(bookings, user.id, "취소")
                bookings = self._eligible_group_rows(bookings, EquipmentBookingStatus.RESERVED, "취소")
                updated_bookings = []
                impacts = []
                for item in bookings:
                    impact, _ = self.penalty_service.apply_cancel_impact(
                        user=user,
                        booking_type="equipment_booking",
                        booking_id=item.id,
                        booking_start_time=item.start_time,
                        domain_bookings=self.booking_repo.get_by_user(user.id),
                        actor_id=user.id,
                    )
                    impacts.append(impact)
                    updated = replace(
                        item,
                        status=EquipmentBookingStatus.CANCELLED,
                        cancelled_at=now_iso(),
                        updated_at=now_iso(),
                    )
                    self.booking_repo.update(updated)
                    updated_bookings.append(updated)

                self.audit_repo.log_action(
                    actor_id=user.id,
                    action="cancel_equipment_booking",
                    target_type=(
                        "equipment_booking_group" if booking.group_id else "equipment_booking"
                    ),
                    target_id=self._group_target_id(booking),
                    details="사용자 취소",
                )
                for item in bookings:
                    self._promote_waitlist_for_cancelled_booking(item, actor_id=user.id)

                result = updated_bookings if booking.group_id else updated_bookings[0]
                return result, any(impact.is_late_cancel for impact in impacts)

    def admin_cancel_booking(self, admin, booking_id, reason=""):
        """관리자에 의한 예약 취소"""
        admin = self._get_existing_admin(admin)
        try:
            validate_reason_text(reason)
        except ValueError as error:
            raise EquipmentBookingError(str(error)) from error
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                booking = self.booking_repo.get_by_id(booking_id)
                if booking is None:
                    raise EquipmentBookingError("존재하지 않는 예약입니다.")
                bookings = self._get_group_members_for_booking(booking)

                bookings = self._eligible_group_rows(bookings, EquipmentBookingStatus.RESERVED, "취소")

                booking_user = self.user_repo.get_by_id(booking.user_id)
                if booking_user is None:
                    raise EquipmentBookingError("존재하지 않는 사용자입니다.")

                updated_bookings = []
                for item in bookings:
                    updated = replace(
                        item,
                        status=EquipmentBookingStatus.ADMIN_CANCELLED,
                        cancelled_at=now_iso(),
                        updated_at=now_iso(),
                    )
                    self.booking_repo.update(updated)
                    updated_bookings.append(updated)

                self.audit_repo.log_action(
                    actor_id=admin.id,
                    action="admin_cancel_equipment_booking",
                    target_type=(
                        "equipment_booking_group" if booking.group_id else "equipment_booking"
                    ),
                    target_id=self._group_target_id(booking),
                    details=f"사유: {reason}",
                )
                for item in bookings:
                    self._promote_waitlist_for_cancelled_booking(item, actor_id=admin.id)

                return updated_bookings if booking.group_id else updated_bookings[0]

    def admin_modify_booking(self, admin, booking_id, new_start_time, new_end_time):
        """관리자에 의한 예약 변경 (미래의 reserved 상태만)"""
        admin = self._get_existing_admin(admin)
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                booking = self.booking_repo.get_by_id(booking_id)
                if booking is None:
                    raise EquipmentBookingError("존재하지 않는 예약입니다.")
                bookings = self._get_group_members_for_booking(booking)

                bookings = self._eligible_group_rows(bookings, EquipmentBookingStatus.RESERVED, "변경")

                booking_user = self.user_repo.get_by_id(booking.user_id)
                if booking_user is None:
                    raise EquipmentBookingError("존재하지 않는 사용자입니다.")

                now = self.clock.now()
                start = datetime.fromisoformat(booking.start_time)
                if start <= now:
                    raise EquipmentBookingError(
                        "이미 시작된 예약은 변경할 수 없습니다."
                    )

                new_start_time, new_end_time = self._validate_booking_time(
                    new_start_time, new_end_time
                )
                booking_ids = {item.id for item in bookings}
                for item in bookings:
                    equipment = self.equipment_repo.get_by_id(item.equipment_id)
                    if equipment is None:
                        raise EquipmentBookingError("존재하지 않는 장비입니다.")
                    self._ensure_no_future_unavailable_overlap(
                        equipment, new_start_time, new_end_time
                    )

                    conflicts = self.booking_repo.get_confirmed_conflicting(
                        item.equipment_id,
                        new_start_time.isoformat(),
                        new_end_time.isoformat(),
                        exclude_ids=booking_ids,
                    )
                    if conflicts:
                        raise EquipmentBookingError("해당 시간대에 이미 예약이 있습니다.")

                updated_bookings = []
                for item in bookings:
                    updated = replace(
                        item,
                        start_time=new_start_time.isoformat(),
                        end_time=new_end_time.isoformat(),
                        updated_at=now_iso(),
                    )
                    self.booking_repo.update(updated)
                    updated_bookings.append(updated)

                self.audit_repo.log_action(
                    actor_id=admin.id,
                    action="admin_modify_equipment_booking",
                    target_type=(
                        "equipment_booking_group" if booking.group_id else "equipment_booking"
                    ),
                    target_id=self._group_target_id(booking),
                    details=f"변경: {new_start_time} ~ {new_end_time}",
                )

                return updated_bookings if booking.group_id else updated_bookings[0]

    def checkout(self, admin, booking_id):
        """대여 시작 처리 (체크아웃)"""
        admin = self._get_existing_admin(admin)
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                booking = self.booking_repo.get_by_id(booking_id)
                if booking is None:
                    raise EquipmentBookingError("존재하지 않는 예약입니다.")
                bookings = self._get_group_members_for_booking(booking)

                bookings = self._eligible_group_rows(
                    bookings, EquipmentBookingStatus.PICKUP_REQUESTED, "대여 시작"
                )

                booking_user = self.user_repo.get_by_id(booking.user_id)
                if booking_user is None:
                    raise EquipmentBookingError("존재하지 않는 사용자입니다.")
                self._require_current_boundary(
                    datetime.fromisoformat(booking.start_time), "대여 시작"
                )

                updated_bookings = []
                for item in bookings:
                    updated = replace(
                        item,
                        status=EquipmentBookingStatus.CHECKED_OUT,
                        checked_out_at=now_iso(),
                        updated_at=now_iso(),
                    )
                    self.booking_repo.update(updated)
                    updated_bookings.append(updated)

                self.audit_repo.log_action(
                    actor_id=admin.id,
                    action="equipment_checkout",
                    target_type=(
                        "equipment_booking_group" if booking.group_id else "equipment_booking"
                    ),
                    target_id=self._group_target_id(booking),
                    details="",
                )

                return updated_bookings if booking.group_id else updated_bookings[0]

    def request_pickup(self, user, booking_id):
        with global_lock(), UnitOfWork():
            user = self._get_existing_user(user)
            booking = self.booking_repo.get_by_id(booking_id)
            if booking is None:
                raise EquipmentBookingError("존재하지 않는 예약입니다.")
            bookings = self._get_group_members_for_booking(booking)

            self._ensure_group_owner(bookings, user.id, "픽업 요청")
            bookings = self._eligible_group_rows(bookings, EquipmentBookingStatus.RESERVED, "픽업 요청")

            self._require_start_request_window(booking)

            updated_bookings = []
            for item in bookings:
                updated = replace(
                    item,
                    status=EquipmentBookingStatus.PICKUP_REQUESTED,
                    requested_pickup_at=now_iso(),
                    updated_at=now_iso(),
                )
                self.booking_repo.update(updated)
                updated_bookings.append(updated)
            self.audit_repo.log_action(
                actor_id=user.id,
                action="request_equipment_pickup",
                target_type=(
                    "equipment_booking_group" if booking.group_id else "equipment_booking"
                ),
                target_id=self._group_target_id(booking),
                details="",
            )
            return updated_bookings if booking.group_id else updated_bookings[0]

    def return_equipment(self, admin, booking_id):
        """
        반납 처리

        Returns:
            (완료된 예약, 지연 시간(분))
        """
        admin = self._get_existing_admin(admin)
        with global_lock(), UnitOfWork():
            booking = self.booking_repo.get_by_id(booking_id)
            if booking is None:
                raise EquipmentBookingError("존재하지 않는 예약입니다.")
            bookings = self._get_group_members_for_booking(booking)

            bookings = self._eligible_group_rows(bookings, EquipmentBookingStatus.CHECKED_OUT, "반납")

            end_time = datetime.fromisoformat(booking.end_time)
            self._require_current_boundary(end_time, "반납 처리")
            delay_minutes = 0

            updated_bookings = []
            for item in bookings:
                updated = replace(
                    item,
                    status=EquipmentBookingStatus.RETURNED,
                    returned_at=now_iso(),
                    updated_at=now_iso(),
                )
                self.booking_repo.update(updated)
                updated_bookings.append(updated)

            self.audit_repo.log_action(
                actor_id=admin.id,
                action="equipment_return",
                target_type=(
                    "equipment_booking_group" if booking.group_id else "equipment_booking"
                ),
                target_id=self._group_target_id(booking),
                details=f"지연: {delay_minutes}분",
            )

            booking_user = self.user_repo.get_by_id(booking.user_id)
            if booking_user is None:
                raise EquipmentBookingError("존재하지 않는 사용자입니다.")
            self.penalty_service.record_normal_use(booking_user)

            result = updated_bookings if booking.group_id else updated_bookings[0]
            return result, delay_minutes

    def force_complete_return(self, admin, booking_id):
        admin = self._get_existing_admin(admin)
        with global_lock(), UnitOfWork():
            booking = self.booking_repo.get_by_id(booking_id)
            if booking is None:
                raise EquipmentBookingError("존재하지 않는 예약입니다.")
            bookings = self._get_group_members_for_booking(booking)

            bookings = self._eligible_group_rows(
                bookings, EquipmentBookingStatus.CHECKED_OUT, "지연 반납 처리"
            )

            end_time = datetime.fromisoformat(booking.end_time)
            self._require_current_boundary(end_time, "지연 반납 처리")
            delay_minutes = int((self.clock.now() - end_time).total_seconds() / 60)
            if delay_minutes <= 0:
                delay_minutes = 60

            updated_bookings = []
            for item in bookings:
                updated = replace(
                    item,
                    status=EquipmentBookingStatus.RETURNED,
                    returned_at=now_iso(),
                    updated_at=now_iso(),
                )
                self.booking_repo.update(updated)
                updated_bookings.append(updated)

            booking_user = self.user_repo.get_by_id(booking.user_id)
            if booking_user is None:
                raise EquipmentBookingError("존재하지 않는 사용자입니다.")
            self.penalty_service.apply_late_return(
                user=booking_user,
                booking_type="equipment_booking",
                booking_id=self._group_target_id(booking),
                delay_minutes=delay_minutes,
                actor_id=admin.id,
            )

            self.audit_repo.log_action(
                actor_id=admin.id,
                action="force_complete_equipment_return",
                target_type=(
                    "equipment_booking_group" if booking.group_id else "equipment_booking"
                ),
                target_id=self._group_target_id(booking),
                details=f"지연: {delay_minutes}분",
            )

            result = updated_bookings if booking.group_id else updated_bookings[0]
            return result, delay_minutes

    def request_return(self, user, booking_id):
        with global_lock(), UnitOfWork():
            user = self._get_existing_user(user)
            booking = self.booking_repo.get_by_id(booking_id)
            if booking is None:
                raise EquipmentBookingError("존재하지 않는 예약입니다.")
            bookings = self._get_group_members_for_booking(booking)

            self._ensure_group_owner(bookings, user.id, "반납 신청")
            bookings = self._eligible_group_rows(bookings, EquipmentBookingStatus.CHECKED_OUT, "반납 신청")
            self._require_end_request_window(booking)

            updated_bookings = []
            for item in bookings:
                updated = replace(
                    item,
                    status=EquipmentBookingStatus.RETURN_REQUESTED,
                    requested_return_at=now_iso(),
                    updated_at=now_iso(),
                )
                self.booking_repo.update(updated)
                updated_bookings.append(updated)
            self.audit_repo.log_action(
                actor_id=user.id,
                action="request_equipment_return",
                target_type=(
                    "equipment_booking_group" if booking.group_id else "equipment_booking"
                ),
                target_id=self._group_target_id(booking),
                details="",
            )
            return updated_bookings if booking.group_id else updated_bookings[0]

    def approve_return_request(self, admin, booking_id):
        admin = self._get_existing_admin(admin)
        with global_lock(), UnitOfWork():
            booking = self.booking_repo.get_by_id(booking_id)
            if booking is None:
                raise EquipmentBookingError("존재하지 않는 예약입니다.")
            bookings = self._get_group_members_for_booking(booking)

            bookings = self._eligible_group_rows(
                bookings, EquipmentBookingStatus.RETURN_REQUESTED, "반납 승인 처리"
            )

            end_time = datetime.fromisoformat(booking.end_time)
            self._require_current_boundary(end_time, "반납 승인")
            delay_minutes = 0

            updated_bookings = []
            for item in bookings:
                updated = replace(
                    item,
                    status=EquipmentBookingStatus.RETURNED,
                    returned_at=now_iso(),
                    updated_at=now_iso(),
                )
                self.booking_repo.update(updated)
                updated_bookings.append(updated)
            self.audit_repo.log_action(
                actor_id=admin.id,
                action="approve_equipment_return_request",
                target_type=(
                    "equipment_booking_group" if booking.group_id else "equipment_booking"
                ),
                target_id=self._group_target_id(booking),
                details=f"지연: {delay_minutes}분",
            )

            booking_user = self.user_repo.get_by_id(booking.user_id)
            if booking_user is None:
                raise EquipmentBookingError("존재하지 않는 사용자입니다.")

            self.penalty_service.record_normal_use(booking_user)

            result = updated_bookings if booking.group_id else updated_bookings[0]
            return result, delay_minutes

    def get_user_bookings(self, user_id):
        """사용자의 모든 예약 조회"""
        self._get_existing_user_by_id(user_id)
        return self._collapse_group_rows(self.booking_repo.get_by_user(user_id))

    def get_user_active_bookings(self, user_id):
        """사용자의 활성 예약 조회"""
        self._get_existing_user_by_id(user_id)
        return self._collapse_group_rows(self.booking_repo.get_quota_active_by_user(user_id))

    def get_all_bookings(self, admin):
        """모든 예약 조회 (관리자용)"""
        self._get_existing_admin(admin)
        return self._collapse_group_rows(self.booking_repo.get_all())

    def get_equipment_bookings(self, equipment_id):
        """장비별 예약 조회"""
        return self.booking_repo.get_by_equipment(equipment_id)

    def _has_checked_out_equipment_booking(self, equipment_id):
        return any(
            booking.status == EquipmentBookingStatus.CHECKED_OUT
            for booking in self.booking_repo.get_by_equipment(equipment_id)
        )

    def _has_reserved_or_checked_out_equipment_booking(self, equipment_id):
        blocking_statuses = {
            EquipmentBookingStatus.RESERVED,
            EquipmentBookingStatus.PICKUP_REQUESTED,
            EquipmentBookingStatus.CHECKED_OUT,
            EquipmentBookingStatus.RETURN_REQUESTED,
        }
        return any(
            booking.status in blocking_statuses
            for booking in self.booking_repo.get_by_equipment(equipment_id)
        )

    def _next_serial_number(self, asset_type, abbr=None):
        equipment_list = self.equipment_repo.get_all()
        if abbr is not None:
            # 직접입력 시 관리자가 입력한 약자 사용
            prefix = abbr.upper()
        else:
            # 기존 종류 선택 시 해당 종류의 기존 prefix 사용
            matching_prefixes = [
                item.serial_number.split("-", 1)[0]
                for item in equipment_list
                if item.asset_type == asset_type and "-" in item.serial_number
            ]
            if matching_prefixes:
                prefix = sorted(matching_prefixes)[0]
            else:
                ascii_letters = "".join(
                    char.upper() for char in asset_type if char.isascii() and char.isalpha()
                )
                prefix = (ascii_letters + "EQ")[:2]
        used_numbers = []
        for item in equipment_list:
            if not item.serial_number.startswith(f"{prefix}-"):
                continue
            suffix = item.serial_number.split("-", 1)[1]
            if suffix.isdigit():
                used_numbers.append(int(suffix))
        next_number = max(used_numbers, default=0) + 1
        if next_number > 999:
            raise EquipmentBookingError("장비 시리얼 번호를 더 이상 자동 생성할 수 없습니다.")
        return f"{prefix}-{next_number:03d}"

    def add_equipment_resource(self, admin, name, asset_type, description="", abbr=None):
        admin = self._get_existing_admin(admin)
        try:
            validate_equipment_name(name)
            validate_equipment_asset_type(asset_type)
            validate_equipment_description(description or "")
        except ValueError as error:
            raise EquipmentBookingError(str(error)) from error

        with global_lock(), UnitOfWork():
            equipment_list = self.equipment_repo.get_all()
            if len(equipment_list) >= MAX_EQUIPMENT_RESOURCES:
                raise EquipmentBookingError("장비는 최대 20개까지 등록할 수 있습니다.")
            serial_number = self._next_serial_number(asset_type, abbr=abbr)
            equipment = EquipmentAsset(
                id=serial_number,
                name=name,
                asset_type=asset_type,
                serial_number=serial_number,
                status=ResourceStatus.AVAILABLE,
                description=description or "",
            )
            self.equipment_repo.add(equipment)
            self.audit_repo.log_action(
                actor_id=admin.id,
                action="add_equipment_resource",
                target_type="equipment",
                target_id=equipment.id,
                details=f"장비 추가: {equipment.name} ({equipment.asset_type})",
            )
            return equipment

    def edit_equipment_resource_name(self, admin, equipment_id, name):
        admin = self._get_existing_admin(admin)
        try:
            validate_equipment_name(name)
        except ValueError as error:
            raise EquipmentBookingError(str(error)) from error

        with global_lock(), UnitOfWork():
            equipment = self.equipment_repo.get_by_id(equipment_id)
            if equipment is None:
                raise EquipmentBookingError("존재하지 않는 장비입니다.")
            if self._has_checked_out_equipment_booking(equipment_id):
                raise EquipmentBookingError("대여 중인 장비 이름은 수정할 수 없습니다.")
            updated_equipment = replace(equipment, name=name, updated_at=now_iso())
            self.equipment_repo.update(updated_equipment)
            self.audit_repo.log_action(
                actor_id=admin.id,
                action="edit_equipment_resource_name",
                target_type="equipment",
                target_id=equipment.id,
                details=f"이름 수정: {name}",
            )
            return updated_equipment

    def delete_equipment_resource(self, admin, equipment_id):
        admin = self._get_existing_admin(admin)
        with global_lock(), UnitOfWork():
            equipment_list = self.equipment_repo.get_all()
            equipment = self.equipment_repo.get_by_id(equipment_id)
            if equipment is None:
                raise EquipmentBookingError("존재하지 않는 장비입니다.")
            if len(equipment_list) <= MIN_EQUIPMENT_RESOURCES:
                raise EquipmentBookingError("장비는 최소 12개 이상 유지해야 합니다.")
            if self._has_reserved_or_checked_out_equipment_booking(equipment_id):
                raise EquipmentBookingError("예약 또는 대여 중인 장비는 삭제할 수 없습니다.")
            self.equipment_repo.delete(equipment_id)
            self.audit_repo.log_action(
                actor_id=admin.id,
                action="delete_equipment_resource",
                target_type="equipment",
                target_id=equipment.id,
                details=f"장비 삭제: {equipment.name}",
            )
            return equipment

    def update_equipment_status(self, admin, equipment_id, new_status):
        """
        장비 상태 변경

        maintenance/disabled로 변경 시 미래 예약 자동 취소

        Returns:
            (변경된 장비, 취소된 예약 목록)
        """
        admin = self._get_existing_admin(admin)
        with global_lock(), UnitOfWork():
            equipment = self.equipment_repo.get_by_id(equipment_id)
            if equipment is None:
                raise EquipmentBookingError("존재하지 않는 장비입니다.")

            cancelled_bookings = []

            # maintenance 또는 disabled로 변경 시 미래 예약 취소
            if new_status in {ResourceStatus.MAINTENANCE, ResourceStatus.DISABLED}:
                now = self.clock.now()
                for booking in self.booking_repo.get_by_equipment(equipment_id):
                    if booking.status == EquipmentBookingStatus.RESERVED:
                        start = datetime.fromisoformat(booking.start_time)
                        if start > now:
                            booking_user = self.user_repo.get_by_id(booking.user_id)
                            if booking_user is None:
                                raise EquipmentBookingError(
                                    "존재하지 않는 사용자입니다."
                                )
                            updated_booking = replace(
                                booking,
                                status=EquipmentBookingStatus.ADMIN_CANCELLED,
                                cancelled_at=now_iso(),
                                updated_at=now_iso(),
                            )
                            self.booking_repo.update(updated_booking)
                            cancelled_bookings.append(updated_booking)

            updated_equipment = replace(
                equipment, status=new_status, updated_at=now_iso()
            )

            self.equipment_repo.update(updated_equipment)

            self.audit_repo.log_action(
                actor_id=admin.id,
                action="update_equipment_status",
                target_type="equipment",
                target_id=equipment_id,
                details=f"상태 변경: {new_status.value}, 취소된 예약: {len(cancelled_bookings)}건",
            )

            return updated_equipment, cancelled_bookings
