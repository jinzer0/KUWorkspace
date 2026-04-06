# Existing Code Patterns & API Reference

**Source:** Background agent scan of src/cli/, src/domain/, tests/  
**Purpose:** Actionable reference for calling validators, services, handlers, and understanding error handling patterns  
**Generated:** 2026-04-06

---

## 1. VALIDATOR FUNCTIONS (`src/cli/validators.py`)

### Input Validation Functions
All return `(bool, value_or_none, error_message_str)` tuple

```python
# Date parsing (3 formats accepted: YYYY-MM-DD, YYYY.MM.DD, YYYY MM DD)
validate_date_input(date_str: str) 
  → (bool, datetime.date | None, str)
  
  Error cases:
    - "날짜 형식이 올바르지 않습니다. (예: 2024-01-15)"
    - "유효하지 않은 날짜입니다."
    - "과거 날짜는 선택할 수 없습니다."
    - "{MAX_BOOKING_DAYS}일 이내의 날짜만 선택 가능합니다."

# Time parsing (HH:MM or HHMM format; only 09:00, 18:00, and 30-min slots allowed)
validate_time_input(time_str: str)
  → (bool, datetime.time | None, str)
  
  Error cases:
    - "시간 형식이 올바르지 않습니다. (예: 09:00, 14:30)"
    - "유효하지 않은 시간입니다."
    - "시간은 {TIME_SLOT_MINUTES}분 단위로만 입력 가능합니다. (예: 09:00, 09:30)"

# Combined datetime with bounds checking
validate_datetime_input(date_str: str, time_str: str)
  → (bool, datetime.datetime | None, str)
  
  Performs: validate_date_input + validate_time_input + combines + checks past

# Integer range validation
validate_positive_int(value_str: str, min_val: int = 1, max_val: int = 100)
  → (bool, int | None, str)
  
  Error cases:
    - "숫자를 입력해주세요."
    - f"{min_val} 이상의 값을 입력해주세요."
    - f"{max_val} 이하의 값을 입력해주세요."

# Menu choice validation (enforces 0-max_option range)
validate_menu_choice(choice: str, max_option: int, allow_zero: bool = True)
  → (bool, int | None, str)
  
  Error cases:
    - "숫자를 입력해주세요."
    - f"0~{max_option} 사이의 번호를 입력해주세요." (or 1~N if allow_zero=False)

# Delegates to auth_rules module
validate_username(username: str)
  → (bool, str)  # Returns (is_valid, error_message_or_empty)
  
  Rules (from plan 4.1.1):
    - 3-20 characters
    - Alphanumeric + underscore only
    - Case-sensitive uniqueness check (by domain layer)
    - Error: "이미 존재하는 사용자명입니다: {username}"

validate_password(password: str)
  → (bool, str)
  
  Rules (from plan 4.1.2):
    - 4-50 characters
    - No spaces (other chars OK)
    - Case-sensitive comparison
    - Error: generic auth error string from domain layer
```

### Interactive Input Functions
Return the parsed value or None on cancel; loop until valid input or user quits

```python
# Interactive date prompt; user can input 'q'/'quit'/'취소' to cancel
get_date_input(prompt: str = "날짜 (YYYY-MM-DD)")
  → datetime.date | None
  
  Behavior:
    - Repeats prompt until valid date or cancel
    - Prints validation errors with "  ✗ {error}" prefix

get_time_input(prompt: str = "시간 (HH:MM)")
  → datetime.time | None
  
  Behavior:
    - Repeats prompt until valid time or cancel

# Combines date + time into single datetime
get_datetime_input(date_prompt: str = "날짜", time_prompt: str = "시간")
  → datetime.datetime | None
  
  Behavior:
    - Calls get_date_input then get_time_input
    - Returns None if either cancelled

# Date range (start/end) for booking
get_daily_date_range_input(start_prompt: str = "시작 날짜", end_prompt: str = "종료 날짜")
  → (datetime.date | None, datetime.date | None)
  
  Behavior:
    - Gets start date, then end date
    - Returns (None, None) if either cancelled

get_positive_int_input(prompt: str, min_val: int = 1, max_val: int = 100)
  → int | None
```

---

## 2. SERVICE CLASS METHODS

### AuthService (`src/domain/auth_service.py`)

```python
class AuthService:
  def signup(username: str, password: str, role: UserRole = UserRole.USER) -> User
    Raises: AuthError("이미 존재하는 사용자명입니다: {username}")
            AuthError("사용자명을 입력해주세요.")
            AuthError("비밀번호를 입력해주세요.")
    
  def login(username: str, password: str) -> User
    Raises: AuthError("존재하지 않는 사용자입니다.")
            AuthError("비밀번호가 일치하지 않습니다.")
    
  def get_user(user_id: str) -> User
    Raises: AuthError("사용자를 찾을 수 없습니다: {user.id}")
    
  def get_user_by_username(username: str) -> User
    Raises: AuthError("존재하지 않는 사용자입니다.")
    
  def update_user(user: User) -> User
    Raises: AuthError if update fails
    
  def get_all_users(admin: User) -> list[User]
    Raises: AuthError("관리자 권한이 필요합니다.") if caller not admin
    
  def is_admin(user: User) -> bool
    Returns True if user.role == UserRole.ADMIN
```

**Usage Pattern:**
```python
try:
  user = auth_service.login(username, password)
except AuthError as e:
  print_error(str(e))  # Display error to user
```

---

### RoomService (`src/domain/room_service.py`)

**Common Raises:**
- `RoomBookingError(message)` - business logic validation failure
- `AdminRequiredError(message)` - admin-only operation
- All raise with specific Korean error message strings (plan-compliant)

**Key Methods:**

```python
class RoomService:
  # Queries
  def get_all_rooms() -> list[Room]
  def get_available_rooms() -> list[Room]
    # Filters by status == AVAILABLE
    
  def get_room(room_id: str) -> Room | None
  
  def get_available_rooms_for_attendees(attendee_count: int, start_time: datetime, end_time: datetime) -> list[Room]
    # Returns rooms: available status, capacity >= attendee_count, no conflicts in [start, end]
    # Sorted by capacity ASC (for greedy selection)
    
  def get_user_bookings(user_id: str) -> list[RoomBooking]
  def get_user_active_bookings(user_id: str) -> list[RoomBooking]
    # Filters for status in [RESERVED, CHECKIN_REQUESTED, CHECKED_IN, CHECKOUT_REQUESTED]
    
  def get_all_bookings(admin: User) -> list[RoomBooking]
    Raises: AdminRequiredError if not admin
    
  # Create/Modify
  def create_daily_booking(user: User, room_id: str, start_date: date, end_date: date, attendee_count: int, max_active: int = 1) -> RoomBooking
    # Validates: user state (banned/restricted), occupancy 1-8, date ranges, no conflicts
    # Records: created_at, updated_at, status=RESERVED
    Raises: RoomBookingError (multiple validation cases from plan 6.5.1.2)
    
  def create_booking(user: User, room_id: str, start_time: datetime, end_time: datetime, max_active: int = ...) -> RoomBooking
    # Lower-level API (time-based); called by create_daily_booking
    
  def modify_daily_booking(user: User, booking_id: str, start_date: date, end_date: date) -> RoomBooking
    # User can only modify reserved bookings, same date validation as create
    Raises: RoomBookingError if not reserved, already started, conflicts, etc.
    
  def admin_modify_daily_booking(admin: User, booking_id: str, start_date: date, end_date: date) -> RoomBooking
    # Admin version: fewer restrictions, 180-day window from original start_date
    
  # Cancellations
  def cancel_booking(user: User, booking_id: str) -> (RoomBooking, bool)
    # Returns: (updated_booking, is_late_cancel)
    # is_late_cancel = True if same-day 09:00 cancel (triggers +2 penalty)
    # Records: cancelled_at, status=CANCELLED
    Raises: RoomBookingError
    
  def admin_cancel_booking(admin: User, booking_id: str, reason: str = "") -> RoomBooking
    # Sets status=ADMIN_CANCELLED, optionally records reason in audit log
    
  # Check-in/Out Flow
  def request_check_in(user: User, booking_id: str) -> RoomBooking
    # User initiates: status reserved → checkin_requested
    # Records: requested_checkin_at
    # Must call at start_time (09:00)
    Raises: RoomBookingError if timing wrong, status wrong, etc.
    
  def check_in(admin: User, booking_id: str) -> RoomBooking
    # Admin approves: status checkin_requested → checked_in
    # Records: checked_in_at (actual time admin approved)
    # Called on time advance if missed, or explicitly by admin
    
  def request_checkout(user: User, booking_id: str) -> RoomBooking
    # User initiates: status checked_in → checkout_requested
    # Records: requested_checkout_at
    
  def check_out(admin: User, booking_id: str) -> (RoomBooking, int)
    # Admin approves: status checkout_requested → completed
    # Returns: (updated_booking, delay_minutes)
    # delay_minutes = max(0, (now - booking.end_time).total_seconds() / 60)
    # If delay > 0, penalty service will apply late-checkout penalty
    
  def approve_checkout_request(admin: User, booking_id: str) -> (RoomBooking, int)
    # Alias for check_out
    
  # State Management
  def mark_no_show(booking_id: str, admin: User | None = None, actor_id: str = "system") -> RoomBooking
    # Sets status=NO_SHOW; called automatically on time advance if no checkin/checkout
    # Penalty service applies +3 points
    
  def update_room_status(admin: User, room_id: str, new_status: ResourceStatus) -> (Room, list[RoomBooking])
    # Changes room status (available/maintenance/disabled)
    # Returns: (updated_room, list_of_cancelled_future_bookings)
    # If new_status is maintenance/disabled: auto-cancel all future reserved bookings
    Raises: AdminRequiredError if not admin
```

**Common Error Messages (from plan 6.5.1):**
```
"이용이 금지된 상태입니다. 해제일: YYYY-MM-DD"  # User is banned
"패널티로 인해 추가 예약이 불가합니다."  # User restricted + active booking exists
"이미 활성 회의실 예약이 있습니다."  # Max active exceeded
"숫자를 입력해주세요."  # Invalid occupancy input
"1 이상의 인원을 입력해주세요."  # Occupancy <= 0
"수용 가능한 최대 인원은 8명입니다."  # Occupancy > 8
"날짜 형식이 올바르지 않습니다. (예: 2099-01-01)"  # Date parse failed
"당일 예약은 불가합니다. 내일부터 예약 가능합니다."  # start_date == today
"과거 날짜는 예약할 수 없습니다."  # start_date < today
"예약 시작일은 오늘로부터 180일 이내여야 합니다."  # start_date > today + 180 days
"종료일은 시작일보다 빠를 수 없습니다."  # end_date < start_date
"예약 기간은 최대 14일까지 가능합니다."  # (end_date - start_date).days > 14
"해당 인원과 기간에 예약 가능한 회의실이 없습니다."  # No match after filtering
"더 작은 회의실이 예약 가능합니다. 해당 회의실을 먼저 이용해주세요."  # Greedy check failed
"선택한 회의실을 예약할 수 없습니다. 다시 시도해주세요."  # Status changed after room list displayed
"이미 시작된 예약은 변경할 수 없습니다."  # Modify with start_time <= now
"직전 취소로 인해 패널티 2점이 부과됩니다. 그래도 취소하시겠습니까?"  # Same-day cancel confirmation
"체크인 요청은 예약 당일 09:00 시점에서만 가능합니다."  # Checkin timing wrong
"체크인 요청이 접수되었습니다. 관리자 승인 대기 상태입니다."  # Success message
```

---

### EquipmentService (`src/domain/equipment_service.py`)

**Parallel to RoomService** with these differences:

```python
class EquipmentService:
  # Queries
  def get_all_equipment() -> list[EquipmentAsset]
  def get_available_equipment() -> list[EquipmentAsset]
  def get_equipment_by_type(asset_type: str) -> list[EquipmentAsset]
    # Returns equipment sorted by serial_number ASC
    
  def get_available_equipment_by_type(asset_type: str, start_time: datetime, end_time: datetime) -> list[EquipmentAsset]
    # Filters: available status, no conflicts in [start, end]
    # Returns sorted by serial ASC
    
  def get_user_bookings(user_id: str) -> list[EquipmentBooking]
  def get_user_active_bookings(user_id: str) -> list[EquipmentBooking]
  def get_all_bookings(admin: User) -> list[EquipmentBooking]
    Raises: AdminRequiredError
    
  # Create/Modify
  def create_daily_booking(user: User, equipment_id: str, start_date: date, end_date: date, max_active: int = 1) -> EquipmentBooking
    # No attendee_count (equipment is 1-to-1)
    # Same date/state validation as RoomService
    Raises: EquipmentBookingError
    
  def modify_daily_booking(user: User, booking_id: str, start_date: date, end_date: date) -> EquipmentBooking
  def admin_modify_daily_booking(admin: User, booking_id: str, start_date: date, end_date: date) -> EquipmentBooking
  
  # Cancellations
  def cancel_booking(user: User, booking_id: str) -> (EquipmentBooking, bool)
    # Returns: (updated_booking, is_late_cancel)
    
  def admin_cancel_booking(admin: User, booking_id: str, reason: str = "") -> EquipmentBooking
  
  # Pickup/Return Flow (analogous to check-in/out)
  def request_pickup(user: User, booking_id: str) -> EquipmentBooking
    # Status: reserved → pickup_requested
    # Records: requested_pickup_at
    # Must call at start_time (09:00)
    
  def checkout(admin: User, booking_id: str) -> EquipmentBooking
    # Status: pickup_requested → checked_out
    # Records: checked_out_at
    
  def request_return(user: User, booking_id: str) -> EquipmentBooking
    # Status: checked_out → return_requested
    # Records: requested_return_at
    
  def return_equipment(admin: User, booking_id: str) -> (EquipmentBooking, int)
    # Status: return_requested → returned
    # Returns: (updated_booking, delay_minutes)
    # Records: returned_at
    
  def approve_return_request(admin: User, booking_id: str) -> (EquipmentBooking, int)
    # Alias for return_equipment
    
  def mark_no_show(booking_id: str, admin: User | None = None, actor_id: str = "system") -> EquipmentBooking
    # Status: → NO_SHOW
    
  def update_equipment_status(admin: User, equipment_id: str, new_status: ResourceStatus) -> (EquipmentAsset, list[EquipmentBooking])
    Raises: AdminRequiredError
```

---

### PolicyService (`src/domain/policy_service.py`)

**Purpose:** Business rule checks and time-advance orchestration

```python
class PolicyService:
  def check_user_can_book(user: User) -> (bool, int, str)
    # Returns: (can_book, max_active_total, message)
    # Checks: user not banned, not restricted+already_has_active
    # Message: empty if OK, else "이용이 금지된 상태입니다. 해제일: ..." or "패널티로 인해 ..."
    
  def get_max_bookings_for_user(user: User) -> (int, int)
    # Returns: (max_room_bookings, max_equipment_bookings)
    # If RESTRICTED: both are 1
    # If NORMAL: both are unlimited (or very high)
    # If BANNED: both are 0
    
  def prepare_advance(current_time: datetime | None = None) -> dict
    # Preview what will happen on time advance
    # Returns dict with start/end events, blockers, etc.
    
  def advance_time(actor_id: str = "system") -> dict
    # Main orchestration method called when advancing time slot
    # Performs (in order):
    #   1. Auto-approve missed check-ins/pickups (at 09:00)
    #   2. Auto-approve missed check-outs/returns (at 18:00)
    #   3. Mark no-shows (bookings that expired without checkin/checkout)
    #   4. Apply late-penalty calculations
    #   5. Process normal-use rewards (record_normal_use)
    #   6. Lift restrictions if expired (check_90_day_reset)
    #   7. Auto-cancel banned user future bookings
    #   8. Auto-reset room/equipment status (maintenance → available after last booking)
    # Returns: dict with events, maintenance results, affected users
    
  def run_all_checks(current_time: datetime | None = None) -> dict
    # Lightweight maintenance checks (penalties, expiry, etc.)
    # Called on menu entry
    
  def _check_penalty_resets(current_time: datetime) -> list[User]
    # Check 90-day reset window for each user
    
  def _check_restriction_expiry(current_time: datetime) -> list[User]
    # Check if restriction_until has passed
    
  def _cancel_banned_user_bookings(current_time: datetime) -> list[str]
    # For each banned user: auto-cancel all future reserved/pickup_requested bookings
    # Returns: list of cancelled booking IDs
```

**Return Dict Example:**
```python
{
  "current_time": datetime(2026, 4, 6, 18, 0),
  "next_time": datetime(2026, 4, 7, 9, 0),
  "start_blockers": [...],  # e.g., ["회의실 2 체크인 요청 1건", "장비 PJ-001 픽업 요청 1건"]
  "end_blockers": [...],
  "user_events": {  # For non-admin users: only own events
    "room_bookings_starting": [...],
    "room_bookings_ending": [...],
    "equipment_bookings_starting": [...],
    "equipment_bookings_ending": [...]
  },
  "system_events": {  # For admin users: system-wide
    "room_bookings_starting_count": 5,
    "room_bookings_ending_count": 3,
    ...
  },
  "maintenance": {
    "penalties_applied": {...},
    "rewards_applied": [...],
    "restrictions_lifted": [...],
    "banned_bookings_cancelled": [...],
    "status_resets": [...]
  }
}
```

---

### PenaltyService (`src/domain/penalty_service.py`)

```python
class PenaltyService:
  # Apply penalties (triggered automatically during time advance or by admin)
  def apply_no_show(user: User, booking_type: str, booking_id: str, actor_id: str = "system") -> Penalty
    # Adds +3 penalty points
    # Called on time advance if booking expired without checkin/checkout
    
  def apply_late_cancel(user: User, booking_type: str, booking_id: str, actor_id: str = "system") -> Penalty
    # Adds +2 penalty points
    # Called if user cancels same-day (09:00)
    
  def apply_late_return(user: User, booking_type: str, booking_id: str, delay_minutes: int, actor_id: str = "system") -> Penalty | None
    # Adds +ceil(delay_minutes / 10) penalty points
    # Returns None if delay_minutes <= 0
    # Called on time advance when checkout/return approval is late
    
  def apply_damage(admin: User, user: User, booking_type: str, booking_id: str, points: int, memo: str) -> Penalty
    # Admin-issued penalty for damage/contamination
    # Admin specifies points (1-5 range, typically)
    Raises: AdminRequiredError, PenaltyError("파손/오염 패널티는 1~{MAX}점 사이...")
    
  def record_normal_use(user: User) -> bool
    # Called when booking transitions to COMPLETED
    # Increments user.normal_use_streak
    # If streak reaches 10: apply -1 penalty point (min 0), reset streak to 0
    # Returns: True if points reduced, False otherwise
    
  def check_90_day_reset(user: User, current_time: datetime | None = None) -> bool
    # If last penalty was > 90 days ago: reset points to 0, streak to 0
    # Returns: True if reset applied
    
  def get_user_status(user: User) -> dict
    # Returns: {
    #   "points": int,
    #   "is_banned": bool,  # points >= 6
    #   "is_restricted": bool,  # points >= 3 and < 6
    #   "restriction_until": datetime | None,
    #   "max_active_bookings": int,  # 0 if banned, 1 if restricted, unlimited if normal
    #   "warning_message": str,  # "이용이 금지..." or "패널티로 인해..." or ""
    #   "normal_use_streak": int,
    # }
    
  def get_user_penalties(user_id: str) -> list[Penalty]
    # All penalty records for user (append-only log)
    
  def _update_user_penalty_points(user: User, delta: int) -> None
    # Internal: adds delta to user.penalty_points
    # Updates restriction_until based on new point total:
    #   - 0-2: restriction_until = None, streak can accumulate
    #   - 3-5: restriction_until = None, max active = 1
    #   - 6+: restriction_until = now + 30 days, max active = 0
```

**Penalty Scoring Rules (from plan 6.6.3, 6.5.1.5):**
- no_show: +3 points (automatic on time advance if booking expired without checkin/checkout)
- late_cancel: +2 points (same-day 09:00 cancel with user confirmation)
- late_checkout (room): +ceil(delay_min/10) points
- late_return (equipment): +ceil(delay_min/10) points
- damage: admin-specified (typically 3-5)
- contamination: admin-specified (typically 3-5)
- normal_use_reward: -1 point after 10-streak (min 0)
- 90_day_reset: admin command → reset to 0 (admin only, plan 6.6.3.3.3)

**Restriction Tiers:**
```
0-2 pts: NORMAL (unrestricted bookings, streak eligible)
3-5 pts: RESTRICTED (max 1 active room, max 1 active equipment)
6+ pts: BANNED (no bookings, restriction_until = now + 30 days)
```

---

## 3. MENU HANDLER METHODS

### UserMenu (`src/cli/user_menu.py`)

All handler methods return `None` (they manage flow internally: print, pause, loop)

```python
class UserMenu:
  def __init__(self, user, auth_service=None, room_service=None, equipment_service=None, penalty_service=None, policy_service=None, message_service=None) -> None

  def run(self) -> bool  # Returns: logout_flag (True = user wants to logout)
  
  # Room Submenu
  def _show_rooms(self) -> None
    # Lists all rooms with status ([사용가능]/[점검중]/[사용불가])
    
  def _create_room_booking(self) -> None
    # Interactive flow: occupancy → date range → room select → create
    # Calls: validate_positive_int, get_daily_date_range_input, room_service.create_daily_booking
    
  def _show_my_room_bookings(self) -> None
    # Lists user's room bookings (max 20, sorted by start_time DESC)
    
  def _modify_room_booking(self) -> None
    # Select booking → date range input → confirm → modify
    
  def _request_room_checkin(self) -> None
    # Select booking → time check (must be current_time) → confirm → request_check_in
    
  def _request_room_checkout(self) -> None
    # Select booking (only checked_in status) → confirm → request_checkout
    
  def _cancel_room_booking(self) -> None
    # Select booking → check for same-day penalty → confirm (with special dialog if penalty) → cancel
    
  # Equipment Submenu
  def _show_equipment(self) -> None
    # Lists all equipment grouped by type, sorted by serial ASC
    
  def _create_equipment_booking(self) -> None
    # Type select → date range → equipment select → create
    
  def _show_my_equipment_bookings(self) -> None
    # Lists user's equipment bookings
    
  def _modify_equipment_booking(self) -> None
  def _request_equipment_pickup(self) -> None
  def _request_equipment_return(self) -> None
  def _cancel_equipment_booking(self) -> None
  
  # Info Submenu
  def _show_my_status(self) -> None
    # Displays: username, role, penalty points, restriction status, booking summary
    
  def _submit_message(self) -> None
    # Optional: submit message/inquiry (if message_service active)
```

**Error Handling Pattern:**
```python
def _some_operation(self) -> None:
  try:
    # ... gather inputs ...
    result = self.room_service.some_method(...)
    print_success("✓ 작업이 완료되었습니다.")
  except RoomBookingError as e:
    print_error(str(e))
  except Exception as e:
    print_error(f"예상치 못한 오류: {str(e)}")
  finally:
    pause()  # Wait for user to press Enter
```

---

### AdminMenu (`src/cli/admin_menu.py`)

Similar structure to UserMenu; all handlers return `None`

```python
class AdminMenu:
  def run(self) -> bool  # Returns: logout_flag
  
  # Room Management
  def _show_rooms(self) -> None
  def _change_room_status(self) -> None
    # Select room → select new status (available/maintenance) → confirm → update
    
  def _show_all_room_bookings(self) -> None
    # Displays all room bookings with status (사용중/예약있음/예약없음)
    
  def _room_checkin(self) -> None
    # Lists rooms with checkin_requested status → approve with confirm
    
  def _room_checkout(self) -> None
    # Lists rooms with checkout_requested status → approve with confirm
    
  def _admin_cancel_room_booking(self) -> None
    # Select booking → enter memo (0-20 chars) → confirm → cancel
    
  def _admin_modify_room_booking_time(self) -> None
    # Select booking → date range input → confirm → modify
    
  # Equipment Management
  def _show_equipment(self) -> None
  def _change_equipment_status(self) -> None
  def _show_all_equipment_bookings(self) -> None
  def _equipment_checkout(self) -> None  # Approve pickup
  def _equipment_return(self) -> None  # Approve return
  def _admin_cancel_equipment_booking(self) -> None
  def _admin_modify_equipment_booking_time(self) -> None
  
  # User Management
  def _show_users(self) -> None
    # List all users with penalty status
    
  def _show_user_detail(self) -> None
    # Select user → display full profile + penalty history
    
  def _apply_damage_penalty(self) -> None
    # Select user → select booking → enter points (1-5) → enter memo → confirm → apply
    # Calls: validate_positive_int(points, 1, 5), penalty_service.apply_damage
```

---

## 4. ERROR MESSAGE PATTERNS

### Validator Error Messages
All printed with prefix `  ✗ {error_text}`

```
날짜 형식이 올바르지 않습니다. (예: 2024-01-15)
유효하지 않은 날짜입니다.
과거 날짜는 선택할 수 없습니다.
{MAX_BOOKING_DAYS}일 이내의 날짜만 선택 가능합니다.
시간 형식이 올바르지 않습니다. (예: 09:00, 14:30)
유효하지 않은 시간입니다.
시간은 {TIME_SLOT_MINUTES}분 단위로만 입력 가능합니다. (예: 09:00, 09:30)
숫자를 입력해주세요.
{min_val} 이상의 값을 입력해주세요.
{max_val} 이하의 값을 입력해주세요.
0~{max_option} 사이의 번호를 입력해주세요.
```

### Service Exception Messages
All raised as domain-specific exceptions:
- `AuthError(message)`
- `RoomBookingError(message)`
- `EquipmentBookingError(message)`
- `PenaltyError(message)`
- `AdminRequiredError(message)`

Common messages (Korean, plan-compliant):
```
이미 존재하는 사용자명입니다: {username}
사용자명을 입력해주세요.
비밀번호를 입력해주세요.
존재하지 않는 사용자입니다.
비밀번호가 일치하지 않습니다.
관리자 권한이 필요합니다.
존재하지 않는 예약입니다.
존재하지 않는 회의실입니다.
존재하지 않는 장비입니다.
본인의 예약만 변경/취소/요청할 수 있습니다.
'{status}' 상태의 예약은 ... 할 수 없습니다.
해당 기간에 이미 예약이 있습니다.
활성 예약 한도({max}건)를 초과했습니다.
과거 시간은 예약할 수 없습니다.
종료 시간은 시작 시간 이후여야 합니다.
예약은 {TIME_SLOT_MINUTES}분 단위로만 가능합니다.
현재 사용 중인 회의실과 동일합니다.
동일한 장비로는 교체할 수 없습니다. 다른 장비를 선택해주세요.
파손/오염 패널티는 1~{MAX}점 사이여야 합니다.
```

### Menu Display Patterns
Success messages (printed via `print_success()`):
```
✓ 예약이 완료되었습니다.
✓ 예약이 변경되었습니다.
✓ 예약이 취소되었습니다.
✓ 체크인 요청이 접수되었습니다. 관리자 승인 대기 상태입니다.
✓ 퇴실 요청이 접수되었습니다. 관리자 승인 대기 상태입니다.
✓ 픽업 요청이 접수되었습니다. 관리자 승인 대기 상태입니다.
✓ 반납 요청이 접수되었습니다. 관리자 승인 대기 상태입니다.
✓ 체크인 처리됐습니다.
✓ 퇴실 승인이 완료됐습니다.
✓ 대여 승인이 완료됐습니다.
✓ 반납 승인이 완료됐습니다.
✓ 상태가 변경되었습니다.
```

Confirmation prompts:
```
정말 취소하시겠습니까? (y/n)
정말로 취소하시겠습니까? (y/n)
정말로 픽업 요청하시겠습니까? (y/n)
정말로 반납하시겠습니까? (y/n)
정말 변경하시겠습니까? (y/n)
정말로 수정하시겠습니까? (y/n)
정말로 승인하시겠습니까? (y/n)
직전 취소로 인해 패널티 2점이 부과됩니다. 그래도 취소하시겠습니까?
```

Confirmation answers:
- Accept: `y`, `yes`, `예`, `ㅇ` (case-insensitive for English)
- Reject: `n`, `no`, `아니오`, `ㄴ`
- Invalid: "y 또는 n을 입력해주세요."

---

## 5. TEST COVERAGE SUMMARY

**By Area:**

| Area | Test Files | Key Fixtures |
|---|---|---|
| **Auth** | `test_auth_service.py`, `test_guest_menu_clock.py` | AuthService instance, mock UserRepository |
| **Rooms** | `test_room_service.py`, `test_daily_booking_flow.py`, E2E | RoomService, mock Room/RoomBooking repos, clock fixture |
| **Equipment** | `test_equipment_service.py`, E2E | EquipmentService, mock Equipment/Booking repos |
| **Penalties** | `test_penalty_service.py`, `test_policy_service.py` | PenaltyService, User fixtures with points, mock repos |
| **Policy/Clock** | `test_policy_service.py`, `test_policy_service.py` (integration) | PolicyService, clock mocking, time advance scenarios |
| **Menus** | `test_user_menu.py`, `test_admin_menu.py`, `test_menu_dispatch.py` | UserMenu/AdminMenu instances, mock services, input mocking |
| **Storage** | `test_jsonl_handler.py`, `test_repositories.py` | JSONL read/write, lock enforcement, UnitOfWork |
| **Config** | `test_config.py` | Constants (MAX_BOOKING_DAYS, TIME_SLOT_MINUTES, etc.) |

**Test Execution:**
```bash
pytest tests/unit/ -v                    # All unit tests
pytest tests/integration/ -v             # All integration tests
pytest tests/e2e/ -v                     # All E2E tests
pytest tests/ -v                         # All tests
pytest tests/unit/test_room_service.py -v  # Single file
```

---

## 6. USAGE EXAMPLES

### Example 1: Creating a Room Booking (Service Layer)
```python
# User calls this after input validation
try:
    booking = room_service.create_daily_booking(
        user=logged_in_user,
        room_id="room_123",
        start_date=date(2026, 4, 10),
        end_date=date(2026, 4, 12),
        attendee_count=4,
        max_active=1  # Policy check
    )
    print_success(f"✓ 예약이 완료되었습니다. 시간: {booking.start_time} ~ {booking.end_time}")
except RoomBookingError as e:
    print_error(str(e))  # e.g., "이용이 금지된 상태입니다. 해제일: 2026-05-06"
```

### Example 2: Advancing Time (Orchestration)
```python
# Admin or system triggers time advance
try:
    result = policy_service.advance_time(actor_id="admin_user_123")
    
    # result is a dict with:
    # - current_time, next_time
    # - maintenance: penalties, rewards, restrictions_lifted, cancelled_bookings, status_resets
    # - user_events or system_events (depending on role)
    
    print(f"✓ 운영 시점을 {result['next_time']}로 이동했습니다.")
    
    # Display events to user
    for event in result.get('user_events', {}).get('room_bookings_ending', []):
        print(f"  [이벤트] {event}")
        
except Exception as e:
    print_error(f"시점 전환 오류: {str(e)}")
```

### Example 3: Applying Penalties
```python
# Admin applies damage penalty
try:
    penalty = penalty_service.apply_damage(
        admin=admin_user,
        user=target_user,
        booking_type="room_booking",
        booking_id="booking_uuid",
        points=3,
        memo="테이블 손상"
    )
    
    # Check new status
    status = penalty_service.get_user_status(target_user)
    if status['is_banned']:
        print_warning(f"⚠ {target_user.username}가 이용금지 상태입니다. ({status['restriction_until']}까지)")
    
except PenaltyError as e:
    print_error(str(e))
```

### Example 4: Testing a Service Method
```python
# In tests/unit/test_room_service.py
from unittest.mock import Mock, MagicMock
from src.domain.room_service import RoomService
from src.domain.models import User, UserRole, RoomBookingError

def test_create_booking_when_banned():
    # Setup mocks
    user_repo = Mock()
    banned_user = User(id="u1", username="test", password="p", role=UserRole.USER, penalty_points=6)
    user_repo.get_by_id.return_value = banned_user
    
    room_service = RoomService(user_repo=user_repo, ...)
    
    # Test
    with pytest.raises(RoomBookingError, match="이용이 금지"):
        room_service.create_daily_booking(
            user=banned_user,
            room_id="r1",
            start_date=date(2026, 4, 10),
            end_date=date(2026, 4, 12),
            attendee_count=2
        )
```

---

**END OF REFERENCE**

Use this guide alongside `/PLAN_ANALYSIS.md` for complete implementation coverage.
