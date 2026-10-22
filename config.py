"""Uygulama yapılandırması.

Tüm ortam değişkenleri .env dosyasından (varsa) okunur. Örnek dosya:
.env.example
"""
import os
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"


def _writable_dir(path: Path) -> bool:
    """Dizin oluşturulabiliyor ve içine yazılabiliyor mu?"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".yazilabilir"
        probe.touch()
        probe.unlink()
        return True
    except OSError:
        return False


# Vercel/AWS Lambda gibi ortamlarda proje dizini salt okunurdur; bu durumda
# geçici dizine düşülür (kalıcı veri için DATABASE_URL tanımlanmalıdır).
DATA_DIR = INSTANCE_DIR if _writable_dir(INSTANCE_DIR) else Path(
    tempfile.gettempdir()
) / "sanalyoklama"
if DATA_DIR is not INSTANCE_DIR:
    _writable_dir(DATA_DIR)

IS_SERVERLESS = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


def _normalize_db_url(url: str) -> str:
    """Heroku/Render/Neon tarzı adresleri SQLAlchemy biçimine çevirir."""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def _as_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "evet"}


class Config:
    # --- Genel ---
    SECRET_KEY = os.environ.get("SECRET_KEY", "gelistirme-ortami-icin-gizli-anahtar")
    APP_NAME = os.environ.get("APP_NAME", "Sanal Yoklama Sistemi")
    DORM_NAME = os.environ.get(
        "DORM_NAME", "Nallıhan MYO Kız Öğrenci Yurdu"
    )

    # --- Veritabanı ---
    SQLALCHEMY_DATABASE_URI = _normalize_db_url(
        os.environ.get("DATABASE_URL") or f"sqlite:///{DATA_DIR / 'yoklama.db'}"
    )
    # Sunucusuz (serverless) dağıtımda tablolar ilk istekte oluşturulur.
    AUTO_INIT_DB = _as_bool(os.environ.get("AUTO_INIT_DB"), IS_SERVERLESS)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # --- Oturum / çerez güvenliği ---
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _as_bool(os.environ.get("SESSION_COOKIE_SECURE"), False)
    REMEMBER_COOKIE_HTTPONLY = True
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8  # 8 saat
    WTF_CSRF_TIME_LIMIT = None

    # --- Yoklama / QR ayarları ---
    # Ekranda görünen QR kodun yenilenme ve TOTP adım süresi (saniye)
    QR_REFRESH_SECONDS = int(os.environ.get("QR_REFRESH_SECONDS", 15))
    # Doğrulamada kabul edilen komşu zaman penceresi sayısı (saat kaymaları için)
    TOTP_VALID_WINDOW = int(os.environ.get("TOTP_VALID_WINDOW", 1))
    # Yeni oturumun varsayılan açık kalma süresi (dakika)
    DEFAULT_SESSION_MINUTES = int(os.environ.get("DEFAULT_SESSION_MINUTES", 30))
    # Aynı cihazdan bir oturumda yalnızca tek kayıt alınsın mı?
    ENFORCE_DEVICE_UNIQUENESS = _as_bool(
        os.environ.get("ENFORCE_DEVICE_UNIQUENESS"), True
    )
    # Okutma denemesi hız sınırı: aynı IP için 1 dakikada en fazla N istek
    SCAN_RATE_LIMIT = int(os.environ.get("SCAN_RATE_LIMIT", 30))
    # Devamsızlık uyarı eşiği (%)
    ABSENCE_WARNING_THRESHOLD = float(
        os.environ.get("ABSENCE_WARNING_THRESHOLD", 20)
    )

    # --- İlk yönetici hesabı (flask init-db ile oluşturulur) ---
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin1234!")
    ADMIN_FULL_NAME = os.environ.get("ADMIN_FULL_NAME", "Sistem Yöneticisi")


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = _as_bool(os.environ.get("SESSION_COOKIE_SECURE"), True)


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    QR_REFRESH_SECONDS = 15
    SCAN_RATE_LIMIT = 1000


CONFIGS = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}


def get_config(name: str | None = None):
    name = name or os.environ.get("FLASK_CONFIG", "default")
    return CONFIGS.get(name, DevelopmentConfig)
