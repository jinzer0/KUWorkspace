"""
메시지 서비스
사용자 문의/신고 메시지의 유형 검증, 내용 검증, 영속성 처리
"""

from src.domain.models import Message, MessageType
from src.storage.repositories import MessageRepository, UnitOfWork
from src.storage.file_lock import global_lock


class MessageError(Exception):
    """메시지 서비스 예외"""

    pass


class MessageService:
    """메시지 생성 및 검증 서비스"""

    def __init__(self, message_repo=None):
        self.message_repo = message_repo or MessageRepository()

    def create_message(self, user_id, message_type, content):
        """
        메시지 생성 및 영속성 처리

        Args:
            user_id: 사용자 ID
            message_type: 메시지 유형 ("inquiry" 또는 "report")
            content: 메시지 내용

        Returns:
            생성된 메시지 객체

        Raises:
            MessageError: 유효하지 않은 입력 시
        """
        # 유형 검증
        self._validate_type(message_type)

        # 내용 검증
        self._validate_content(content)

        # 메시지 생성
        message = Message(
            user_id=user_id, type=MessageType(message_type), content=content
        )

        # 영속성 처리
        with global_lock():
            with UnitOfWork():
                self.message_repo.add(message)

        return message

    def _validate_type(self, message_type):
        """메시지 유형 검증"""
        valid_types = {"inquiry", "report"}
        if message_type not in valid_types:
            raise MessageError(
                f"유효한 메시지 유형이 아닙니다. 허용값: {valid_types}"
            )

    def list_messages(self):
        """
        모든 메시지 조회 (읽기 전용)

        Returns:
            저장된 모든 Message 객체 리스트 (정렬 없음, 변경 없음)
        """
        return self.message_repo.get_all()

    def _validate_content(self, content):
        """메시지 내용 검증"""
        # 비어있는 경우 거부
        if not content:
            raise MessageError("메시지 내용이 비어있습니다.")

        # 줄바꿈 포함 거부 (공백 체크 전에 수행)
        if "\n" in content or "\r" in content:
            raise MessageError("메시지 내용에 줄바꿈을 포함할 수 없습니다.")

        # 공백만 있는 경우 거부
        if content.strip() == "":
            raise MessageError("메시지 내용이 공백만으로 이루어져 있습니다.")

        # 길이 검증: 1~100 문자
        if len(content) < 1:
            raise MessageError("메시지 내용은 1글자 이상이어야 합니다.")

        if len(content) > 100:
            raise MessageError("메시지 내용은 100글자 이하여야 합니다.")

