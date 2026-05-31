import pytest

from app.services.lei_validation_service import lei_checksum_ok


@pytest.mark.parametrize(
    "lei", ["5493001KJTIIGC8Y1R12", "529900T8BM49AURSDO55", "54930084UKLVMY22DS16"]
)
def test_valid_checksums(lei):
    assert lei_checksum_ok(lei) is True


@pytest.mark.parametrize(
    "lei",
    [
        "984500F1F2E3D4C5B6A7",  # wrong check digits
        "5493001KJTIIGC8Y1R1",  # 19 chars
        "5493001KJTIIGC8Y1R123",  # 21 chars
        "5493001KJTIIGC8Y1R1!",  # non-alphanumeric
        "5493001KJTIIGC8Y1R1é",  # non-ASCII alphanumeric (é is alnum but not ascii)
        "",
    ],
)
def test_invalid_checksums(lei):
    assert lei_checksum_ok(lei) is False


def test_lowercase_is_accepted_via_upcasing():
    assert lei_checksum_ok("5493001kjtiigc8y1r12") is True
