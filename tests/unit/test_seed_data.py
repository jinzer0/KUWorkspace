from src.storage.integrity import DataIntegrityError
import scripts.seed_data as seed_data


def test_get_seed_timestamp_returns_sentinel(monkeypatch):
    monkeypatch.setattr(seed_data, "read_clock_marker", lambda: seed_data.CLOCK_SENTINEL)

    assert seed_data.get_seed_timestamp() == seed_data.CLOCK_SENTINEL


def test_get_seed_timestamp_returns_normalized_clock_value(monkeypatch):
    monkeypatch.setattr(seed_data, "read_clock_marker", lambda: "2030-01-02T18:00:59")

    assert seed_data.get_seed_timestamp() == "2030-01-02T18:00"


def test_get_seed_timestamp_rejects_non_timestamp_value(monkeypatch):
    monkeypatch.setattr(seed_data, "read_clock_marker", lambda: "not-a-timestamp")
    monkeypatch.setattr(seed_data, "CLOCK_FILE", "/tmp/fake_clock.txt")

    try:
        seed_data.get_seed_timestamp()
        assert False, "expected DataIntegrityError"
    except DataIntegrityError as error:
        assert "시드 타임스탬프 형식이 올바르지 않습니다" in str(error)
