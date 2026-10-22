"""TOTP üretimi/doğrulaması ve QR yükünün ayrıştırılması testleri."""
import time as time_module

from app.utils.security import (
    build_scan_payload,
    generate_secret,
    parse_scan_payload,
    seconds_until_refresh,
    totp,
    verify_totp,
)


def test_generated_code_is_six_digits():
    secret = generate_secret()
    code = totp(secret, step=15)
    assert code.isdigit() and len(code) == 6


def test_valid_code_is_accepted():
    secret = generate_secret()
    code = totp(secret, step=15)
    assert verify_totp(secret, code, step=15, window=1)


def test_wrong_code_is_rejected():
    secret = generate_secret()
    code = totp(secret, step=15)
    wrong = str((int(code) + 1) % 1000000).zfill(6)
    assert not verify_totp(secret, wrong, step=15, window=1)


def test_code_of_another_session_is_rejected():
    secret_a, secret_b = generate_secret(), generate_secret()
    code_a = totp(secret_a, step=15)
    assert not verify_totp(secret_b, code_a, step=15, window=1)


def test_expired_code_is_rejected():
    secret = generate_secret()
    reference = time_module.time()
    old_code = totp(secret, step=15, timestamp=reference - 600)
    assert not verify_totp(secret, old_code, step=15, window=1, timestamp=reference)


def test_window_tolerates_small_clock_drift():
    secret = generate_secret()
    reference = time_module.time()
    previous = totp(secret, step=15, timestamp=reference - 15)
    assert verify_totp(secret, previous, step=15, window=1, timestamp=reference)


def test_payload_round_trip():
    payload = build_scan_payload(7, "123456")
    assert parse_scan_payload(payload) == (7, "123456")


def test_payload_from_url():
    url = "https://yoklama.ornek.com/yoklama/12/654321"
    assert parse_scan_payload(url) == (12, "654321")


def test_invalid_payload_returns_none():
    assert parse_scan_payload("rastgele-metin") == (None, None)


def test_refresh_countdown_in_range():
    assert 1 <= seconds_until_refresh(15) <= 15
