"""Veritabanı modelleri.

Tablolar
--------
users               : öğrenci / yurt görevlisi / yönetici hesapları
attendance_sessions : yurt görevlisinin açtığı yoklama oturumları
attendance_records  : her öğrenci için oturum bazlı yoklama kaydı
leaves              : izin / rapor kayıtları (otomatik "izinli" işaretlemesi)
audit_logs          : tüm kritik işlemlerin zaman damgalı günlüğü
"""
from datetime import date, datetime, time, timedelta

from flask_login import UserMixin
from sqlalchemy import UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager

# --------------------------------------------------------------------------- #
# Sabitler
# --------------------------------------------------------------------------- #
ROLE_STUDENT = "student"
ROLE_STAFF = "staff"
ROLE_ADMIN = "admin"

ROLE_LABELS = {
    ROLE_STUDENT: "Öğrenci",
    ROLE_STAFF: "Yurt Görevlisi",
    ROLE_ADMIN: "Yönetici",
}

STATUS_PRESENT = "present"
STATUS_LATE = "late"
STATUS_EXCUSED = "excused"
STATUS_REPORTED = "reported"
STATUS_ABSENT = "absent"

STATUS_LABELS = {
    STATUS_PRESENT: "Mevcut",
    STATUS_LATE: "Geç Geldi",
    STATUS_EXCUSED: "İzinli",
    STATUS_REPORTED: "Raporlu",
    STATUS_ABSENT: "Yok",
}

STATUS_BADGES = {
    STATUS_PRESENT: "success",
    STATUS_LATE: "warning",
    STATUS_EXCUSED: "info",
    STATUS_REPORTED: "secondary",
    STATUS_ABSENT: "danger",
}

# Devamsızlık sayılan durumlar
ABSENT_LIKE = {STATUS_ABSENT}
# "Katılmış" sayılan durumlar (devam oranı hesabında)
PRESENT_LIKE = {STATUS_PRESENT, STATUS_LATE}

METHOD_QR = "qr"
METHOD_MANUAL = "manual"
METHOD_AUTO = "auto"
METHOD_LABELS = {
    METHOD_QR: "QR Kod",
    METHOD_MANUAL: "Manuel",
    METHOD_AUTO: "Otomatik",
}

SESSION_OPEN = "open"
SESSION_CLOSED = "closed"

LEAVE_TYPES = {
    "izin": "İzinli",
    "rapor": "Raporlu",
    "gorevli": "Görevli/Etkinlik",
}

LEAVE_STATUS_MAP = {
    "izin": STATUS_EXCUSED,
    "rapor": STATUS_REPORTED,
    "gorevli": STATUS_EXCUSED,
}


def now() -> datetime:
    """Saniye hassasiyetinde yerel zaman."""
    return datetime.now().replace(microsecond=0)


# --------------------------------------------------------------------------- #
# Kullanıcı
# --------------------------------------------------------------------------- #
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False)
    # Öğrenci hesapları parolasızdır (boş metin): giriş yapmaz, yalnızca
    # yoklamada numara + ad soyad ile doğrulanırlar.
    password_hash = db.Column(db.String(255), nullable=False, default="")
    role = db.Column(db.String(16), nullable=False, default=ROLE_STUDENT, index=True)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(32))

    # Öğrenciye özel alanlar
    student_no = db.Column(db.String(32), unique=True)
    department = db.Column(db.String(120))
    class_year = db.Column(db.String(16))
    room_no = db.Column(db.String(16), index=True)

    is_active_account = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    last_login_at = db.Column(db.DateTime)

    records = db.relationship(
        "AttendanceRecord",
        back_populates="student",
        foreign_keys="AttendanceRecord.student_id",
        cascade="all, delete-orphan",
    )
    leaves = db.relationship(
        "Leave",
        back_populates="student",
        foreign_keys="Leave.student_id",
        cascade="all, delete-orphan",
    )

    # --- parola ---
    def set_password(self, raw_password: str | None) -> None:
        """Parola belirler. None/boş verilirse hesap parolasız olur.

        Öğrenciler sisteme giriş yapmadığı için parolasız kaydedilir; bu
        hesaplarla giriş denemesi her zaman başarısız olur (bkz. can_login).
        """
        self.password_hash = generate_password_hash(raw_password) if raw_password else ""

    def check_password(self, raw_password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, raw_password)

    @property
    def has_password(self) -> bool:
        return bool(self.password_hash)

    @property
    def can_login(self) -> bool:
        """Yalnızca görevli ve yönetici hesapları sisteme giriş yapabilir."""
        return self.role in (ROLE_STAFF, ROLE_ADMIN) and self.has_password

    # --- roller ---
    @property
    def is_student(self) -> bool:
        return self.role == ROLE_STUDENT

    @property
    def is_staff(self) -> bool:
        return self.role == ROLE_STAFF

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def can_manage_attendance(self) -> bool:
        """Yurt görevlisi ve yönetici yoklama yönetebilir."""
        return self.role in (ROLE_STAFF, ROLE_ADMIN)

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)

    # Flask-Login: pasif hesaplar giriş yapamaz
    @property
    def is_active(self) -> bool:  # noqa: D401
        return bool(self.is_active_account)

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role})>"


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))


# --------------------------------------------------------------------------- #
# Yoklama oturumu
# --------------------------------------------------------------------------- #
class AttendanceSession(db.Model):
    __tablename__ = "attendance_sessions"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False, default="Akşam Yoklaması")
    session_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)

    opened_at = db.Column(db.DateTime, nullable=False, default=now)
    closes_at = db.Column(db.DateTime, nullable=False)
    closed_at = db.Column(db.DateTime)

    # TOTP üretimi için oturuma özel gizli anahtar (base32)
    secret = db.Column(db.String(64), nullable=False)
    refresh_seconds = db.Column(db.Integer, nullable=False, default=15)

    status = db.Column(db.String(16), nullable=False, default=SESSION_OPEN, index=True)
    note = db.Column(db.Text)

    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_by = db.relationship("User", foreign_keys=[created_by_id])

    records = db.relationship(
        "AttendanceRecord",
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # --- durum ---
    @property
    def is_expired(self) -> bool:
        return now() >= self.closes_at

    @property
    def is_open(self) -> bool:
        return self.status == SESSION_OPEN and not self.is_expired

    @property
    def seconds_left(self) -> int:
        return max(0, int((self.closes_at - now()).total_seconds()))

    @property
    def status_label(self) -> str:
        if self.is_open:
            return "Açık"
        return "Kapalı"

    def close(self, closed_at: datetime | None = None) -> None:
        if self.status != SESSION_CLOSED:
            self.status = SESSION_CLOSED
            self.closed_at = closed_at or now()

    # --- özet ---
    def summary(self) -> dict:
        counts = {key: 0 for key in STATUS_LABELS}
        for record in self.records:
            counts[record.status] = counts.get(record.status, 0) + 1
        total = sum(counts.values())
        present = sum(counts[s] for s in PRESENT_LIKE)
        counts["total"] = total
        counts["present_like"] = present
        counts["rate"] = round(present / total * 100, 1) if total else 0.0
        return counts

    def __repr__(self) -> str:
        return f"<AttendanceSession {self.session_date} {self.title}>"


# --------------------------------------------------------------------------- #
# Yoklama kaydı
# --------------------------------------------------------------------------- #
class AttendanceRecord(db.Model):
    __tablename__ = "attendance_records"
    __table_args__ = (
        # Bir öğrenci bir oturumda yalnızca bir kez kaydedilebilir
        UniqueConstraint("session_id", "student_id", name="uq_record_session_student"),
        # Aynı cihaz (tarayıcı) bir oturumda yalnızca bir kez okutabilir
        UniqueConstraint("session_id", "device_id", name="uq_record_session_device"),
    )

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer, db.ForeignKey("attendance_sessions.id"), nullable=False, index=True
    )
    student_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )

    status = db.Column(db.String(16), nullable=False, default=STATUS_ABSENT, index=True)
    method = db.Column(db.String(16), nullable=False, default=METHOD_QR)
    marked_at = db.Column(db.DateTime, nullable=False, default=now)

    device_id = db.Column(db.String(64))
    ip_address = db.Column(db.String(64))
    user_agent = db.Column(db.String(255))
    note = db.Column(db.Text)

    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at = db.Column(db.DateTime)

    session = db.relationship("AttendanceSession", back_populates="records")
    student = db.relationship(
        "User", back_populates="records", foreign_keys=[student_id]
    )
    updated_by = db.relationship("User", foreign_keys=[updated_by_id])

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def status_badge(self) -> str:
        return STATUS_BADGES.get(self.status, "secondary")

    @property
    def method_label(self) -> str:
        return METHOD_LABELS.get(self.method, self.method)

    def __repr__(self) -> str:
        return f"<AttendanceRecord s={self.session_id} u={self.student_id} {self.status}>"


# --------------------------------------------------------------------------- #
# İzin / rapor
# --------------------------------------------------------------------------- #
class Leave(db.Model):
    __tablename__ = "leaves"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    leave_type = db.Column(db.String(16), nullable=False, default="izin")
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    note = db.Column(db.Text)

    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now)

    student = db.relationship("User", back_populates="leaves", foreign_keys=[student_id])
    created_by = db.relationship("User", foreign_keys=[created_by_id])

    @property
    def type_label(self) -> str:
        return LEAVE_TYPES.get(self.leave_type, self.leave_type)

    @property
    def mapped_status(self) -> str:
        return LEAVE_STATUS_MAP.get(self.leave_type, STATUS_EXCUSED)

    def covers(self, day: date) -> bool:
        return self.start_date <= day <= self.end_date

    @staticmethod
    def active_for(student_id: int, day: date):
        return (
            Leave.query.filter(
                Leave.student_id == student_id,
                Leave.start_date <= day,
                Leave.end_date >= day,
            )
            .order_by(Leave.created_at.desc())
            .first()
        )

    def __repr__(self) -> str:
        return f"<Leave {self.student_id} {self.start_date}..{self.end_date}>"


# --------------------------------------------------------------------------- #
# Günlük (log)
# --------------------------------------------------------------------------- #
class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    actor_name = db.Column(db.String(120))
    actor_role = db.Column(db.String(16))
    action = db.Column(db.String(64), nullable=False, index=True)
    target_type = db.Column(db.String(32))
    target_id = db.Column(db.Integer)
    detail = db.Column(db.Text)
    ip_address = db.Column(db.String(64))
    user_agent = db.Column(db.String(255))

    user = db.relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return f"<AuditLog {self.created_at} {self.action}>"


# --------------------------------------------------------------------------- #
# Yardımcılar
# --------------------------------------------------------------------------- #
def default_session_window(minutes: int) -> tuple[time, time]:
    """Şimdiden başlayan, 'minutes' dakika süren bir saat aralığı üretir."""
    begin = now()
    end = begin + timedelta(minutes=minutes)
    return begin.time().replace(microsecond=0), end.time().replace(microsecond=0)
