"""Yoklama güvenliği: zaman bağımlı tek kullanımlık kod (TOTP) üretimi/doğrulaması,
cihaz kimliği ve basit hız sınırlama.

TOTP, RFC 6238'e uygun biçimde HMAC-SHA1 ile üretilir. Harici bir kütüphaneye
ihtiyaç duyulmaması için standart kütüphane (hmac/hashlib/base64) kullanılmıştır.
Her yoklama oturumunun kendine ait bir gizli anahtarı (secret) vardır; bu nedenle
bir oturuma ait kod başka bir oturumda geçersizdir.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from collections import defaultdict, deque
from threading import Lock

DIGITS = 6
_B32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


# --------------------------------------------------------------------------- #
# Gizli anahtar
# --------------------------------------------------------------------------- #
def generate_secret(length: int = 32) -> str:
    """Oturuma özel base32 gizli anahtar üretir."""
    return "".join(secrets.choice(_B32_ALPHABET) for _ in range(length))


def _decode_secret(secret: str) -> bytes:
    padded = secret.strip().upper()
    padded += "=" * (-len(padded) % 8)
    try:
        return base64.b32decode(padded, casefold=True)
    except Exception:  # base32 dışı bir anahtar verilmişse ham baytları kullan
        return secret.encode("utf-8")


# --------------------------------------------------------------------------- #
# TOTP
# --------------------------------------------------------------------------- #
def _hotp(key: bytes, counter: int, digits: int = DIGITS) -> str:
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code_int % (10**digits)).zfill(digits)


def current_counter(step: int, timestamp: float | None = None) -> int:
    ts = time.time() if timestamp is None else timestamp
    return int(ts // step)


def totp(secret: str, step: int = 15, timestamp: float | None = None,
         digits: int = DIGITS) -> str:
    """Verilen anın tek kullanımlık kodunu döndürür."""
    key = _decode_secret(secret)
    return _hotp(key, current_counter(step, timestamp), digits)


def verify_totp(secret: str, code: str, step: int = 15, window: int = 1,
                timestamp: float | None = None, digits: int = DIGITS) -> bool:
    """Kodu, komşu zaman pencerelerini de deneyerek doğrular.

    window=1 ise bir önceki ve bir sonraki adım da kabul edilir. Bu, öğrenci
    telefonu ile sunucu saati arasındaki küçük kaymaları tolere eder.
    """
    if not code:
        return False
    code = str(code).strip()
    if not code.isdigit() or len(code) != digits:
        return False
    key = _decode_secret(secret)
    counter = current_counter(step, timestamp)
    for drift in range(-window, window + 1):
        expected = _hotp(key, counter + drift, digits)
        if hmac.compare_digest(expected, code):
            return True
    return False


def seconds_until_refresh(step: int = 15, timestamp: float | None = None) -> int:
    """Ekrandaki QR kodun yenilenmesine kalan saniye."""
    ts = time.time() if timestamp is None else timestamp
    return int(step - (ts % step)) or step


# --------------------------------------------------------------------------- #
# QR içeriği
# --------------------------------------------------------------------------- #
def build_scan_payload(session_id: int, code: str) -> str:
    """QR kodun içine yazılan kısa yük (payload).

    Biçim: NMYO|<oturum_id>|<kod>
    Telefonun kendi kamerası ile okutulduğunda açılacak bağlantı ise
    /yoklama/<oturum_id>/<kod> adresidir (bkz. api.scan_link).
    """
    return f"NMYO|{session_id}|{code}"


def parse_scan_payload(payload: str) -> tuple[int | None, str | None]:
    """QR yükünü ayrıştırır. Hem 'NMYO|1|123456' hem de tam URL biçimini kabul eder."""
    if not payload:
        return None, None
    text = payload.strip()

    if text.startswith("NMYO|"):
        parts = text.split("|")
        if len(parts) == 3 and parts[1].isdigit():
            return int(parts[1]), parts[2].strip()
        return None, None

    # http(s)://.../yoklama/<id>/<code> biçimi
    if "/yoklama/" in text:
        tail = text.split("/yoklama/", 1)[1]
        tail = tail.split("?", 1)[0].strip("/")
        parts = tail.split("/")
        if len(parts) >= 2 and parts[0].isdigit():
            return int(parts[0]), parts[1].strip()
    return None, None


# --------------------------------------------------------------------------- #
# Cihaz kimliği
# --------------------------------------------------------------------------- #
DEVICE_COOKIE_NAME = "yoklama_device"


def new_device_id() -> str:
    return os.urandom(16).hex()


def fingerprint(device_id: str, user_agent: str = "") -> str:
    """Cihaz kimliğini kullanıcı aracısıyla birlikte özetler (gizlilik için hash)."""
    raw = f"{device_id}|{user_agent}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:48]


# --------------------------------------------------------------------------- #
# Basit hız sınırlama (tek süreçli dağıtımlar için)
# --------------------------------------------------------------------------- #
class RateLimiter:
    """IP başına, kayan 60 saniyelik pencerede istek sayısını sınırlar."""

    def __init__(self, limit: int = 30, period: int = 60):
        self.limit = limit
        self.period = period
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        if self.limit <= 0:
            return True
        now_ts = time.time()
        with self._lock:
            bucket = self._hits[key]
            while bucket and now_ts - bucket[0] > self.period:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now_ts)
            return True

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


scan_limiter = RateLimiter()
