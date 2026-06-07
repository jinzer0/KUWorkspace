from src.cli.menu import pause
from src.cli.formatters import (
    print_header,
    print_error,
    print_info,
    print_success,
    print_warning,
    format_datetime,
)


class ClockMenu:
    """공용 운영 시계 메뉴"""

    def __init__(self, policy_service, actor_id="system", allow_advance=True):
        self.policy_service = policy_service
        self.actor_id = actor_id
        self.allow_advance = allow_advance

    def run(self):
        while True:
            preview = self.policy_service.prepare_advance(actor_id=self.actor_id)

            print_header("운영 시계")
            print(f"  현재 운영 시점: {format_datetime(preview['current_time'].isoformat())}")
            print(f"  다음 시점: {format_datetime(preview['next_time'].isoformat())}")
            print()
            print("  1. 현재 시점 보기")
            if self.allow_advance:
                print("  2. 다음 시점으로 이동")
                print("  3. 미해결 사건 보기")
            else:
                print("  2. 미해결 사건 보기")
            print("  0. 돌아가기")
            print("-" * 50)

            choice = input("선택: ").strip()

            if choice == "1":
                self._show_preview(preview)
            elif self.allow_advance and choice == "2":
                self._advance()
            elif choice == "2":
                if not self.allow_advance:
                    self._show_blockers(preview)
                else:
                    print_error("잘못된 선택입니다.")
            elif choice == "3" and self.allow_advance:
                self._show_blockers(preview)
            elif choice == "0":
                return
            else:
                print_error("잘못된 선택입니다.")
                pause()

    def _show_preview(self, preview):
        print_header("운영 시점 정보")
        print(f"  현재 운영 시점: {format_datetime(preview['current_time'].isoformat())}")
        print(f"  다음 시점: {format_datetime(preview['next_time'].isoformat())}")
        if preview["events"]:
            print()
            print("  [예상 이벤트]")
            for event in preview["events"]:
                print(f"  - {event}")
        pause()

    def _show_blockers(self, preview):
        print_header("미해결 사건")
        if not preview["blockers"]:
            print_success("현재 시점에서는 다음 단계로 이동할 수 있습니다.")
            pause()
            return

        print_warning("다음 시점으로 이동하기 전에 아래 작업을 완료해야 합니다.")
        for blocker in preview["blockers"]:
            print(f"  - {blocker}")
        pause()

    def _print_maintenance_summary(self, maintenance):
        if not maintenance:
            return
        summary_items = [
            ("만료된 회의실 점검", maintenance.get("room_maintenance_expired", [])),
            ("장비 미래 상태 적용", maintenance.get("equipment_future_status_changes", [])),
            ("회의실 대기 확정", maintenance.get("room_pending_promoted", [])),
            ("회의실 대기 취소", maintenance.get("room_pending_cancelled", [])),
            ("장비 대기 확정", maintenance.get("equipment_pending_promoted", [])),
            ("장비 대기 취소", maintenance.get("equipment_pending_cancelled", [])),
            ("패널티 초기화", maintenance.get("penalty_reset_users", [])),
            ("예약 제한 만료", maintenance.get("restriction_expired_users", [])),
            ("이용 금지 예약 자동 취소", maintenance.get("banned_user_cancelled_bookings", [])),
        ]
        visible_items = [(label, values) for label, values in summary_items if values]
        if not visible_items:
            print_info("정책 점검 추가 처리 내역이 없습니다.")
            return
        print()
        print("  [정책 점검 요약]")
        for label, values in visible_items:
            print(f"  - {label}: {len(values)}건")

    def _advance(self):
        preview = self.policy_service.prepare_advance(actor_id=self.actor_id)
        force = False

        if preview["blockers"]:
            print_header("시점 이동 경고")
            print_warning("다음 시점으로 이동하기 전에 아래 작업이 남아 있습니다.")
            for blocker in preview["blockers"]:
                print(f"  - {blocker}")
            if preview.get("force_notice"):
                print()
                print_warning(preview["force_notice"])
            if not input("강행하려면 'FORCE'를 입력하세요: ").strip().upper() == "FORCE":
                pause()
                return
            force = True

        result = self.policy_service.advance_time(actor_id=self.actor_id, force=force)
        print_header("시점 이동 결과")

        if not result["can_advance"]:
            print_error("시점 이동이 차단되었습니다.")
            for blocker in result["blockers"]:
                print(f"  - {blocker}")
            pause()
            return

        print_success(
            f"운영 시점을 {format_datetime(result['next_time'].isoformat())}로 이동했습니다."
        )
        if result["events"]:
            print()
            print("  [이벤트]")
            for event in result["events"]:
                print(f"  - {event}")
        else:
            print_info("발생한 추가 이벤트가 없습니다.")
        self._print_maintenance_summary(result.get("maintenance"))
        pause()
