"""
메시지 서비스 단위 테스트

테스트 범위:
- 유형 검증: inquiry, report만 허용
- 내용 검증: 길이 1-100, 줄바꿈 거부, 공백 거부, 빈 문자열 거부
- 영속성: 유효한 내용은 저장, 무효한 내용은 거부
"""

import pytest

from src.domain.message_service import MessageService, MessageError
from src.storage.repositories import UnitOfWork


class TestMessageTypeValidation:
    """메시지 유형 검증 테스트"""

    def test_create_message_with_inquiry_type(self, message_service, create_test_user):
        """inquiry 타입 메시지 생성 성공"""
        user = create_test_user()
        message = message_service.create_message(
            user_id=user.id, message_type="inquiry", content="테스트 문의"
        )

        assert message.type.value == "inquiry"
        assert message.content == "테스트 문의"
        assert message.user_id == user.id

    def test_create_message_with_report_type(self, message_service, create_test_user):
        """report 타입 메시지 생성 성공"""
        user = create_test_user()
        message = message_service.create_message(
            user_id=user.id, message_type="report", content="테스트 신고"
        )

        assert message.type.value == "report"
        assert message.content == "테스트 신고"
        assert message.user_id == user.id

    def test_reject_invalid_message_type_uppercase(self, message_service, create_test_user):
        """INQUIRY 타입은 거부"""
        user = create_test_user()
        with pytest.raises(MessageError) as exc_info:
            message_service.create_message(
                user_id=user.id, message_type="INQUIRY", content="테스트"
            )
        assert "유효한 메시지 유형" in str(exc_info.value)

    def test_reject_invalid_message_type_korean_inquiry(self, message_service, create_test_user):
        """한글 타입은 거부"""
        user = create_test_user()
        with pytest.raises(MessageError) as exc_info:
            message_service.create_message(
                user_id=user.id, message_type="문의", content="테스트"
            )
        assert "유효한 메시지 유형" in str(exc_info.value)

    def test_reject_invalid_message_type_empty_string(self, message_service, create_test_user):
        """빈 타입 문자열은 거부"""
        user = create_test_user()
        with pytest.raises(MessageError) as exc_info:
            message_service.create_message(
                user_id=user.id, message_type="", content="테스트"
            )
        assert "유효한 메시지 유형" in str(exc_info.value)

    def test_reject_invalid_message_type_random_string(self, message_service, create_test_user):
        """정의되지 않은 타입은 거부"""
        user = create_test_user()
        with pytest.raises(MessageError) as exc_info:
            message_service.create_message(
                user_id=user.id, message_type="random_type", content="테스트"
            )
        assert "유효한 메시지 유형" in str(exc_info.value)


class TestMessageContentValidation:
    """메시지 내용 검증 테스트"""

    def test_accept_content_length_1(self, message_service, create_test_user):
        """1글자 내용은 허용"""
        user = create_test_user()
        message = message_service.create_message(
            user_id=user.id, message_type="inquiry", content="a"
        )
        assert message.content == "a"

    def test_accept_content_length_100(self, message_service, create_test_user):
        """100글자 내용은 허용"""
        user = create_test_user()
        content = "a" * 100
        message = message_service.create_message(
            user_id=user.id, message_type="inquiry", content=content
        )
        assert message.content == content
        assert len(message.content) == 100

    def test_reject_empty_content(self, message_service, create_test_user):
        """빈 내용은 거부"""
        user = create_test_user()
        with pytest.raises(MessageError) as exc_info:
            message_service.create_message(
                user_id=user.id, message_type="inquiry", content=""
            )
        assert "비어있습니다" in str(exc_info.value)

    def test_reject_content_length_101(self, message_service, create_test_user):
        """101글자 이상은 거부"""
        user = create_test_user()
        content = "a" * 101
        with pytest.raises(MessageError) as exc_info:
            message_service.create_message(
                user_id=user.id, message_type="inquiry", content=content
            )
        assert "100글자 이하" in str(exc_info.value)

    def test_reject_content_length_200(self, message_service, create_test_user):
        """200글자 이상은 거부"""
        user = create_test_user()
        content = "테스트 내용" * 20  # 50글자 이상
        with pytest.raises(MessageError) as exc_info:
            message_service.create_message(
                user_id=user.id, message_type="inquiry", content=content
            )
        assert "100글자 이하" in str(exc_info.value)

    def test_reject_whitespace_only_content_space(self, message_service, create_test_user):
        """공백만 있는 내용은 거부"""
        user = create_test_user()
        with pytest.raises(MessageError) as exc_info:
            message_service.create_message(
                user_id=user.id, message_type="inquiry", content="   "
            )
        assert "공백만으로" in str(exc_info.value)

    def test_reject_whitespace_only_content_tab(self, message_service, create_test_user):
        """탭만 있는 내용은 거부"""
        user = create_test_user()
        with pytest.raises(MessageError) as exc_info:
            message_service.create_message(
                user_id=user.id, message_type="inquiry", content="\t\t"
            )
        assert "공백만으로" in str(exc_info.value)

    def test_reject_whitespace_only_content_mixed(self, message_service, create_test_user):
        """공백 혼합만 있는 내용은 거부"""
        user = create_test_user()
        with pytest.raises(MessageError) as exc_info:
            message_service.create_message(
                user_id=user.id, message_type="inquiry", content="  \t  "
            )
        assert "공백만으로" in str(exc_info.value)

    def test_reject_newline_lf_content(self, message_service, create_test_user):
        """LF 줄바꿈을 포함한 내용은 거부"""
        user = create_test_user()
        with pytest.raises(MessageError) as exc_info:
            message_service.create_message(
                user_id=user.id,
                message_type="inquiry",
                content="first line\nsecond line",
            )
        assert "줄바꿈을 포함할 수 없습니다" in str(exc_info.value)

    def test_reject_newline_cr_content(self, message_service, create_test_user):
        """CR 줄바꿈을 포함한 내용은 거부"""
        user = create_test_user()
        with pytest.raises(MessageError) as exc_info:
            message_service.create_message(
                user_id=user.id,
                message_type="inquiry",
                content="first line\rsecond line",
            )
        assert "줄바꿈을 포함할 수 없습니다" in str(exc_info.value)

    def test_reject_newline_crlf_content(self, message_service, create_test_user):
        """CRLF 줄바꿈을 포함한 내용은 거부"""
        user = create_test_user()
        with pytest.raises(MessageError) as exc_info:
            message_service.create_message(
                user_id=user.id,
                message_type="inquiry",
                content="first line\r\nsecond line",
            )
        assert "줄바꿈을 포함할 수 없습니다" in str(exc_info.value)

    def test_reject_newline_only_lf(self, message_service, create_test_user):
        """LF만 있는 내용은 거부"""
        user = create_test_user()
        with pytest.raises(MessageError) as exc_info:
            message_service.create_message(
                user_id=user.id, message_type="inquiry", content="\n"
            )
        assert "줄바꿈을 포함할 수 없습니다" in str(exc_info.value)


class TestMessagePersistence:
    """메시지 영속성 테스트"""

    def test_valid_message_persists_to_repository(
        self, message_service, message_repo, create_test_user
    ):
        """유효한 메시지는 저장소에 저장됨"""
        user = create_test_user()
        message = message_service.create_message(
            user_id=user.id, message_type="inquiry", content="test content"
        )

        # 저장소에서 검증
        saved_messages = message_repo.get_by_user(user.id)
        assert len(saved_messages) == 1
        assert saved_messages[0].id == message.id
        assert saved_messages[0].content == "test content"

    def test_invalid_message_type_does_not_persist(
        self, message_service, message_repo, create_test_user
    ):
        """유효하지 않은 타입의 메시지는 저장되지 않음"""
        user = create_test_user()
        with pytest.raises(MessageError):
            message_service.create_message(
                user_id=user.id, message_type="invalid", content="test"
            )

        saved_messages = message_repo.get_by_user(user.id)
        assert len(saved_messages) == 0

    def test_invalid_content_does_not_persist(
        self, message_service, message_repo, create_test_user
    ):
        """유효하지 않은 내용의 메시지는 저장되지 않음"""
        user = create_test_user()
        with pytest.raises(MessageError):
            message_service.create_message(
                user_id=user.id, message_type="inquiry", content=""
            )

        saved_messages = message_repo.get_by_user(user.id)
        assert len(saved_messages) == 0

    def test_original_content_preserved_without_trim(
        self, message_service, message_repo, create_test_user
    ):
        """원본 내용이 정확히 보존됨 (공백 포함)"""
        user = create_test_user()
        original_content = "  leading and trailing spaces  "
        message = message_service.create_message(
            user_id=user.id, message_type="inquiry", content=original_content
        )

        saved_messages = message_repo.get_by_user(user.id)
        assert saved_messages[0].content == original_content
        assert saved_messages[0].content == message.content

    def test_korean_content_persisted_correctly(
        self, message_service, message_repo, create_test_user
    ):
        """한글 내용이 정확히 보존됨"""
        user = create_test_user()
        korean_content = "한글 테스트 내용입니다"
        message = message_service.create_message(
            user_id=user.id, message_type="inquiry", content=korean_content
        )

        saved_messages = message_repo.get_by_user(user.id)
        assert saved_messages[0].content == korean_content

    def test_special_characters_preserved(
        self, message_service, message_repo, create_test_user
    ):
        """특수 문자가 정확히 보존됨"""
        user = create_test_user()
        content_with_special = "!@#$%^&*()_+-=[]{}|;:',.<>?/"
        message = message_service.create_message(
            user_id=user.id, message_type="inquiry", content=content_with_special
        )

        saved_messages = message_repo.get_by_user(user.id)
        assert saved_messages[0].content == content_with_special

    def test_multiple_messages_all_persist(
        self, message_service, message_repo, create_test_user
    ):
        """여러 메시지가 모두 저장됨"""
        user = create_test_user()
        msg1 = message_service.create_message(
            user_id=user.id, message_type="inquiry", content="first"
        )
        msg2 = message_service.create_message(
            user_id=user.id, message_type="report", content="second"
        )

        saved_messages = message_repo.get_by_user(user.id)
        assert len(saved_messages) == 2
        ids = {m.id for m in saved_messages}
        assert msg1.id in ids
        assert msg2.id in ids


class TestMessageContentPreservation:
    """메시지 내용 보존 테스트"""

    def test_preserve_content_with_numbers(
        self, message_service, message_repo, create_test_user
    ):
        """숫자가 포함된 내용 보존"""
        user = create_test_user()
        content = "123456789 test 123"
        message = message_service.create_message(
            user_id=user.id, message_type="inquiry", content=content
        )

        saved = message_repo.get_by_user(user.id)[0]
        assert saved.content == content

    def test_preserve_content_with_emoji(
        self, message_service, message_repo, create_test_user
    ):
        """이모지가 포함된 내용 보존"""
        user = create_test_user()
        content = "테스트 😊 이모지"
        message = message_service.create_message(
            user_id=user.id, message_type="inquiry", content=content
        )

        saved = message_repo.get_by_user(user.id)[0]
        assert saved.content == content

    def test_preserve_content_with_leading_trailing_space(
        self, message_service, message_repo, create_test_user
    ):
        """앞뒤 공백이 있는 내용 보존 (trim 안함)"""
        user = create_test_user()
        content = "  content with spaces  "
        message = message_service.create_message(
            user_id=user.id, message_type="inquiry", content=content
        )

        saved = message_repo.get_by_user(user.id)[0]
        assert saved.content == content
        assert saved.content.startswith(" ")
        assert saved.content.endswith(" ")

    def test_preserve_content_with_internal_spaces(
        self, message_service, message_repo, create_test_user
    ):
        """내부 공백이 있는 내용 보존"""
        user = create_test_user()
        content = "test   with   multiple   spaces"
        message = message_service.create_message(
            user_id=user.id, message_type="inquiry", content=content
        )

        saved = message_repo.get_by_user(user.id)[0]
        assert saved.content == content


class TestMessageReadAPI:
    """메시지 읽기 전용 API 테스트"""

    def test_list_messages_empty(self, message_service):
        """메시지가 없을 때 빈 리스트 반환"""
        messages = message_service.list_messages()
        assert messages == []
        assert isinstance(messages, list)

    def test_list_messages_returns_all_messages(
        self, message_service, message_repo, create_test_user
    ):
        """모든 저장된 메시지 반환"""
        user = create_test_user()
        msg1 = message_service.create_message(
            user_id=user.id, message_type="inquiry", content="first message"
        )
        msg2 = message_service.create_message(
            user_id=user.id, message_type="report", content="second message"
        )

        listed_messages = message_service.list_messages()

        assert len(listed_messages) == 2
        ids = {m.id for m in listed_messages}
        assert msg1.id in ids
        assert msg2.id in ids

    def test_list_messages_returns_exact_field_values(
        self, message_service, create_test_user
    ):
        """리스트된 메시지가 정확한 필드 값을 반환"""
        user = create_test_user()
        original_content = "exact content test"
        message = message_service.create_message(
            user_id=user.id, message_type="inquiry", content=original_content
        )

        listed_messages = message_service.list_messages()
        listed = listed_messages[0]

        assert listed.id == message.id
        assert listed.user_id == user.id
        assert listed.content == original_content
        assert listed.type.value == "inquiry"
        assert listed.created_at == message.created_at

    def test_list_messages_preserves_message_objects(
        self, message_service, create_test_user
    ):
        """리스트된 메시지가 Message 객체 타입 유지"""
        user = create_test_user()
        message_service.create_message(
            user_id=user.id, message_type="inquiry", content="test"
        )

        listed_messages = message_service.list_messages()

        assert len(listed_messages) == 1
        from src.domain.models import Message
        assert isinstance(listed_messages[0], Message)

    def test_list_messages_no_sorting_applied(
        self, message_service, message_repo, create_test_user
    ):
        """리스트 메서드는 정렬을 적용하지 않음"""
        user = create_test_user()
        # 3개 메시지 생성
        msg1 = message_service.create_message(
            user_id=user.id, message_type="inquiry", content="msg1"
        )
        msg2 = message_service.create_message(
            user_id=user.id, message_type="inquiry", content="msg2"
        )
        msg3 = message_service.create_message(
            user_id=user.id, message_type="inquiry", content="msg3"
        )

        listed_messages = message_service.list_messages()

        # 리스트 메서드는 정렬을 적용하지 않으므로 저장 순서 유지
        assert listed_messages[0].id == msg1.id
        assert listed_messages[1].id == msg2.id
        assert listed_messages[2].id == msg3.id

    def test_list_messages_is_read_only_no_mutation(
        self, message_service, create_test_user
    ):
        """리스트 메서드는 메시지를 변경하지 않음"""
        user = create_test_user()
        original_message = message_service.create_message(
            user_id=user.id, message_type="inquiry", content="original"
        )

        # 리스트를 가져온 후, 반환된 리스트 자체를 수정 시도
        listed_messages = message_service.list_messages()
        
        # 반환된 리스트 수정 (이것은 서비스 내부 상태에 영향을 주지 않아야 함)
        listed_messages.append("modified")

        # 다시 리스트를 가져와서 원본이 변경되지 않았는지 확인
        fresh_messages = message_service.list_messages()
        assert len(fresh_messages) == 1
        assert fresh_messages[0].id == original_message.id

    def test_list_messages_preserves_all_message_fields_order(
        self, message_service, message_repo, create_test_user
    ):
        """리스트된 메시지가 모든 필드를 정확히 보존"""
        user = create_test_user()
        content = "special content with chars: !@#$%"
        message = message_service.create_message(
            user_id=user.id, message_type="report", content=content
        )

        listed = message_service.list_messages()[0]

        # 정확한 필드 값 확인
        assert listed.id == message.id
        assert listed.user_id == message.user_id
        assert listed.created_at == message.created_at
        assert listed.type == message.type
        assert listed.content == message.content

    def test_list_messages_multiple_users(
        self, message_service, create_test_user
    ):
        """여러 사용자의 모든 메시지 반환"""
        user1 = create_test_user()
        user2 = create_test_user()
        
        msg1 = message_service.create_message(
            user_id=user1.id, message_type="inquiry", content="user1 msg"
        )
        msg2 = message_service.create_message(
            user_id=user2.id, message_type="report", content="user2 msg"
        )

        listed = message_service.list_messages()

        assert len(listed) == 2
        ids = {m.id for m in listed}
        assert msg1.id in ids
        assert msg2.id in ids
