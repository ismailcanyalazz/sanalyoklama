"""İş kuralları: oturum açma/kapama, QR ile yoklama alma, manuel düzenleme,
istatistik hesaplama.

Görünüm (view) katmanı olabildiğince ince tutulmuş; doğrulama ve veri
bütünlüğü kuralları bu modülde toplanmıştır.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from flask import current_app
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import (
    ABSENT_LIKE,
    METHOD_AUTO,
    METHOD_MANUAL,
    METHOD_QR,
    PRESENT_LIKE,
    ROLE_STUDENT,
    SESSION_CLOSED,
    STATUS_ABSENT,
    STATUS_LABELS,
    STATUS_PRESENT,
    AttendanceRecord,
    AttendanceSession,
    Leave,
    User,
    now,
)
from .utils.audit import client_ip, log_action, user_agent
from .utils.security import generate_secret, verify_totp
from .utils.text import names_match, normalize_student_no


class AttendanceError(Exception):
    """Kullanıcıya gösterilebilir iş kuralı hatası."""

    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.message = message
        self.code = code


# Numara/ad eşleşmediğinde gösterilen tek tip mesaj. Hangi alanın hatalı
# olduğunun söylenmemesi, deneme yanılma ile öğrenci listesinin çıkarılmasını
# zorlaştırır.
IDENTITY_MISMATCH_MESSAGE = (
    "Okul numarası ile ad soyad kayıtlarla eşleşmiyor. "
    "Bilgilerinizi kontrol edin; sorun sürerse yurt görevlisine başvurun."
)


# --------------------------------------------------------------------------- #
# Öğrenci listesi
# --------------------------------------------------------------------------- #
def active_students() -> list[User]:
    return (
        User.query.filter_by(role=ROLE_STUDENT, is_active_account=True)
        .order_by(User.full_name)
        .all()
    )


def find_student_by_no(student_no: str) -> User | None:
    """Okul numarasından öğrenciyi bulur (boşluk/ayraç farklarını tolere eder)."""
    cleaned = normalize_student_no(student_no)
    if not cleaned:
        return None

    student = User.query.filter_by(student_no=cleaned, role=ROLE_STUDENT).first()
    if student is not None:
        return student

    # Numara veritabanında boşluklu/ayraçlı kaydedilmiş olabilir
    for candidate in User.query.filter_by(role=ROLE_STUDENT).all():
        if normalize_student_no(candidate.student_no) == cleaned:
            return candidate
    return None


def resolve_student_identity(student_no: str, full_name: str) -> User:
    """Okul numarası + ad soyad ikilisini doğrulayıp öğrenciyi döndürür.

    Öğrenciler sisteme giriş yapmadığı için kimlik, yoklama anında girilen bu
    iki bilgi ile doğrulanır. Numara bulunamazsa ya da ad soyad kayıtla
    uyuşmazsa okutma reddedilir.
    """
    cleaned_no = normalize_student_no(student_no)
    given_name = (full_name or "").strip()

    if not cleaned_no or not given_name:
        raise AttendanceError(
            "Okul numarası ve ad soyad alanlarının ikisi de doldurulmalıdır.",
            "missing_identity",
        )

    student = find_student_by_no(cleaned_no)

    if student is None or not names_match(student.full_name, given_name):
        log_action(
            "scan_rejected",
            detail=(
                "Kimlik doğrulanamadı "
                f"(girilen numara: {cleaned_no}, girilen ad: {given_name})."
            ),
            commit=True,
        )
        raise AttendanceError(IDENTITY_MISMATCH_MESSAGE, "identity_mismatch")

    if not student.is_active_account:
        log_action(
            "scan_rejected",
            target_type="user",
            target_id=student.id,
            detail=f"Pasif öğrenci kaydı ile okutma denemesi ({cleaned_no}).",
            commit=True,
        )
        raise AttendanceError(
            "Kaydınız pasif durumda. Yurt yönetimine başvurun.", "inactive"
        )

    return student


# --------------------------------------------------------------------------- #
# Oturum yaşam döngüsü
# --------------------------------------------------------------------------- #
def create_session(
    *,
    creator: User,
    title: str,
    session_date: date,
    start_time: time,
    end_time: time,
    refresh_seconds: int | None = None,
    note: str | None = None,
) -> AttendanceSession:
    """Yeni yoklama oturumu açar ve tüm aktif öğrenciler için boş kayıt üretir."""
    if end_time <= start_time:
        raise AttendanceError("Bitiş saati, başlangıç saatinden sonra olmalıdır.")

    open_same_day = AttendanceSession.query.filter_by(
        session_date=session_date
    ).all()
    for existing in open_same_day:
        if existing.is_open:
            raise AttendanceError(
                "Bu tarihte hâlihazırda açık bir yoklama oturumu var. "
                "Yeni oturum açmadan önce mevcut oturumu kapatın."
            )

    refresh = int(refresh_seconds or current_app.config["QR_REFRESH_SECONDS"])
    refresh = max(5, min(refresh, 120))

    session_obj = AttendanceSession(
        title=title.strip() or "Akşam Yoklaması",
        session_date=session_date,
        start_time=start_time,
        end_time=end_time,
        opened_at=now(),
        closes_at=datetime.combine(session_date, end_time),
        secret=generate_secret(),
        refresh_seconds=refresh,
        note=(note or "").strip() or None,
        created_by_id=creator.id,
    )
    db.session.add(session_obj)
    db.session.flush()  # id gerekli

    ensure_records(session_obj)
    log_action(
        "session_open",
        target_type="session",
        target_id=session_obj.id,
        detail=(
            f"{session_obj.session_date} {session_obj.start_time:%H:%M}-"
            f"{session_obj.end_time:%H:%M} oturumu açıldı "
            f"(QR yenileme: {refresh} sn)"
        ),
    )
    db.session.commit()
    return session_obj


def ensure_records(session_obj: AttendanceSession) -> int:
    """Oturumda kaydı olmayan öğrenciler için 'Yok' kaydı oluşturur.

    Öğrencinin o güne ait izin/rapor kaydı varsa durum otomatik olarak
    'İzinli'/'Raporlu' işaretlenir.
    """
    existing_ids = {
        row[0]
        for row in db.session.query(AttendanceRecord.student_id).filter_by(
            session_id=session_obj.id
        )
    }
    created = 0
    for student in active_students():
        if student.id in existing_ids:
            continue
        leave = Leave.active_for(student.id, session_obj.session_date)
        record = AttendanceRecord(
            session_id=session_obj.id,
            student_id=student.id,
            status=leave.mapped_status if leave else STATUS_ABSENT,
            method=METHOD_AUTO,
            marked_at=now(),
            note=(
                f"{leave.type_label} kaydı nedeniyle otomatik işaretlendi."
                if leave
                else None
            ),
        )
        db.session.add(record)
        created += 1
    db.session.flush()
    return created


def close_session(session_obj: AttendanceSession, *, actor: User | None = None,
                  reason: str = "manuel") -> AttendanceSession:
    """Oturumu kapatır, eksik kayıtları tamamlar."""
    if session_obj.status == SESSION_CLOSED:
        return session_obj
    ensure_records(session_obj)
    session_obj.close()
    summary = session_obj.summary()
    log_action(
        "session_close",
        target_type="session",
        target_id=session_obj.id,
        detail=(
            f"Oturum kapatıldı ({reason}). Mevcut: {summary['present']}, "
            f"Yok: {summary['absent']}, İzinli: {summary['excused']}, "
            f"Raporlu: {summary['reported']}, Geç: {summary['late']}"
        ),
        user=actor,
    )
    db.session.commit()
    return session_obj


def autoclose_expired_sessions() -> int:
    """Süresi dolan açık oturumları otomatik kapatır.

    Her istek öncesinde (before_request) çağrılır; böylece oturumun belirli bir
    süre sonunda kendiliğinden kapanması garanti edilir.
    """
    expired = [
        s
        for s in AttendanceSession.query.filter_by(status="open").all()
        if s.is_expired
    ]
    for session_obj in expired:
        ensure_records(session_obj)
        session_obj.close()
        log_action(
            "session_autoclose",
            target_type="session",
            target_id=session_obj.id,
            detail="Süre dolduğu için oturum otomatik kapatıldı.",
        )
    if expired:
        db.session.commit()
    return len(expired)


def get_open_session(day: date | None = None) -> AttendanceSession | None:
    """Belirtilen gün için açık oturumu döndürür."""
    query = AttendanceSession.query.filter_by(status="open")
    if day is not None:
        query = query.filter_by(session_date=day)
    for session_obj in query.order_by(AttendanceSession.opened_at.desc()).all():
        if session_obj.is_open:
            return session_obj
    return None


# --------------------------------------------------------------------------- #
# QR ile yoklama alma
# --------------------------------------------------------------------------- #
def require_open_session(session_id: int) -> AttendanceSession:
    """Oturumu bulur ve açık olduğunu doğrular; süresi dolmuşsa kapatır."""
    session_obj = db.session.get(AttendanceSession, session_id)
    if session_obj is None:
        raise AttendanceError("Yoklama oturumu bulunamadı.", "not_found")

    if not session_obj.is_open:
        if session_obj.status != SESSION_CLOSED:
            close_session(session_obj, reason="süre doldu")
        raise AttendanceError(
            "Bu yoklama oturumu kapanmış. Lütfen yurt görevlisine başvurun.",
            "closed",
        )
    return session_obj


def verify_session_code(
    session_id: int, code: str, *, student: User | None = None
) -> AttendanceSession:
    """Oturumu bulup açık olduğunu ve kodun geçerliliğini doğrular.

    Kimlik (numara + ad soyad) sorgulanmadan önce çağrılır: geçerli bir QR
    kodu olmayan birinin formu deneme yanılma ile öğrenci listesi çıkarmak
    için kullanmasını engeller.
    """
    session_obj = require_open_session(session_id)

    if not verify_totp(
        session_obj.secret,
        code,
        step=session_obj.refresh_seconds,
        window=current_app.config["TOTP_VALID_WINDOW"],
    ):
        log_action(
            "scan_rejected",
            target_type="session",
            target_id=session_obj.id,
            detail=f"Geçersiz/süresi geçmiş kod denemesi (kod: {code}).",
            user=student,
            commit=True,
        )
        raise AttendanceError(
            "Kod geçersiz veya süresi dolmuş. Ekrandaki yeni QR kodu okutun.",
            "invalid_code",
        )

    return session_obj


def mark_attendance_by_code(
    *,
    student: User,
    session_id: int,
    code: str | None,
    device_id: str,
    code_already_verified: bool = False,
) -> AttendanceRecord:
    """QR koddan gelen tek kullanımlık kodu doğrular ve öğrenciyi mevcut işaretler.

    Doğrulama adımları
    ------------------
    1. Oturum var mı, açık mı (süresi dolmuşsa otomatik kapatılır)?
    2. Kod, oturumun gizli anahtarı ile üretilmiş geçerli bir TOTP mi?
    3. Öğrenci bu oturumda daha önce kaydedilmiş mi?
    4. Aynı cihaz bu oturumda başka bir öğrenci için kullanılmış mı?
    """
    if not student.is_student:
        raise AttendanceError(
            "Yalnızca öğrenci hesapları QR kod ile yoklama verebilir.", "role"
        )

    if code_already_verified:
        # Kod, okutma bileti verilirken doğrulanmıştı (bkz. blueprints/scan.py)
        session_obj = require_open_session(session_id)
    else:
        session_obj = verify_session_code(session_id, code, student=student)

    record = AttendanceRecord.query.filter_by(
        session_id=session_obj.id, student_id=student.id
    ).first()

    if record is not None and record.status in PRESENT_LIKE:
        raise AttendanceError(
            f"Bu oturumda zaten yoklama verdiniz "
            f"({record.marked_at:%H:%M}).",
            "duplicate",
        )

    # Aynı cihazdan başka bir öğrenci okutmuş mu?
    if device_id and current_app.config["ENFORCE_DEVICE_UNIQUENESS"]:
        other = (
            AttendanceRecord.query.filter(
                AttendanceRecord.session_id == session_obj.id,
                AttendanceRecord.device_id == device_id,
                AttendanceRecord.student_id != student.id,
            ).first()
        )
        if other is not None:
            log_action(
                "scan_rejected",
                target_type="session",
                target_id=session_obj.id,
                detail=(
                    "Aynı cihazdan ikinci kayıt denemesi "
                    f"(cihazı kullanan: {other.student.full_name})."
                ),
                user=student,
                commit=True,
            )
            raise AttendanceError(
                "Bu cihaz bu oturumda başka bir öğrenci için kullanılmış. "
                "Her öğrenci kendi telefonundan okutmalıdır.",
                "device_conflict",
            )

    if record is None:
        record = AttendanceRecord(
            session_id=session_obj.id, student_id=student.id
        )
        db.session.add(record)

    record.status = STATUS_PRESENT
    record.method = METHOD_QR
    record.marked_at = now()
    record.device_id = device_id or None
    record.ip_address = client_ip()
    record.user_agent = user_agent()
    record.note = None
    record.updated_by_id = None
    record.updated_at = None

    log_action(
        "scan_accepted",
        target_type="record",
        target_id=session_obj.id,
        detail=(
            f"{student.full_name} ({student.student_no or student.username}) "
            f"QR ile 'Mevcut' işaretlendi."
        ),
        user=student,
    )
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise AttendanceError(
            "Kayıt zaten alınmış görünüyor. Sayfayı yenileyip kontrol edin.",
            "duplicate",
        )
    return record


def mark_attendance_with_identity(
    *,
    student_no: str,
    full_name: str,
    session_id: int,
    code: str,
    device_id: str,
) -> AttendanceRecord:
    """Öğrencinin girdiği numara + ad soyad ile yoklama alır.

    Öğrenci sisteme giriş yapmaz: ekrandaki QR kodu okutur, açılan formda
    okul numarasını ve ad soyadını yazar. Bu iki bilgi kayıtla eşleşirse
    yoklama 'Mevcut' olarak işlenir, eşleşmezse okutma reddedilir.
    """
    # Önce kod: geçerli bir QR olmadan kimlik sorgulanmaz.
    verify_session_code(session_id, code)
    student = resolve_student_identity(student_no, full_name)
    return mark_attendance_by_code(
        student=student,
        session_id=session_id,
        code=code,
        device_id=device_id,
    )


# --------------------------------------------------------------------------- #
# Manuel düzenleme
# --------------------------------------------------------------------------- #
def update_record_manually(
    *, record: AttendanceRecord, status: str, note: str | None, actor: User
) -> AttendanceRecord:
    """Yurt görevlisi/yönetici tarafından manuel durum ve açıklama güncellemesi."""
    if status not in STATUS_LABELS:
        raise AttendanceError("Geçersiz yoklama durumu.")

    previous = record.status
    record.status = status
    record.method = METHOD_MANUAL
    record.note = (note or "").strip() or None
    record.updated_by_id = actor.id
    record.updated_at = now()
    if previous != status:
        record.marked_at = now()

    log_action(
        "record_manual_update",
        target_type="record",
        target_id=record.id,
        detail=(
            f"{record.student.full_name}: "
            f"{STATUS_LABELS.get(previous, previous)} -> {STATUS_LABELS[status]}"
            + (f" | Açıklama: {record.note}" if record.note else "")
        ),
        user=actor,
    )
    db.session.commit()
    return record


# --------------------------------------------------------------------------- #
# İstatistikler
# --------------------------------------------------------------------------- #
def session_date_bounds(days: int = 30) -> tuple[date, date]:
    end = date.today()
    start = end - timedelta(days=days - 1)
    return start, end


def status_distribution(start: date, end: date) -> dict[str, int]:
    rows = (
        db.session.query(AttendanceRecord.status, func.count(AttendanceRecord.id))
        .join(AttendanceSession)
        .filter(AttendanceSession.session_date.between(start, end))
        .group_by(AttendanceRecord.status)
        .all()
    )
    data = {key: 0 for key in STATUS_LABELS}
    for status, count in rows:
        data[status] = count
    return data


def daily_attendance_rates(start: date, end: date) -> list[dict]:
    """Gün bazında devam oranları (grafik için)."""
    sessions = (
        AttendanceSession.query.filter(
            AttendanceSession.session_date.between(start, end)
        )
        .order_by(AttendanceSession.session_date)
        .all()
    )
    result = []
    for session_obj in sessions:
        summary = session_obj.summary()
        result.append(
            {
                "date": session_obj.session_date.strftime("%d.%m.%Y"),
                "iso_date": session_obj.session_date.isoformat(),
                "session_id": session_obj.id,
                "title": session_obj.title,
                "total": summary["total"],
                "present": summary["present"],
                "late": summary["late"],
                "absent": summary["absent"],
                "excused": summary["excused"],
                "reported": summary["reported"],
                "rate": summary["rate"],
            }
        )
    return result


def student_statistics(start: date, end: date) -> list[dict]:
    """Öğrenci bazında devam/devamsızlık özeti."""
    rows = (
        db.session.query(
            User.id,
            User.full_name,
            User.student_no,
            User.room_no,
            AttendanceRecord.status,
            func.count(AttendanceRecord.id),
        )
        .join(AttendanceRecord, AttendanceRecord.student_id == User.id)
        .join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id)
        .filter(AttendanceSession.session_date.between(start, end))
        .group_by(User.id, AttendanceRecord.status)
        .all()
    )

    bucket: dict[int, dict] = {}
    for user_id, full_name, student_no, room_no, status, count in rows:
        entry = bucket.setdefault(
            user_id,
            {
                "student_id": user_id,
                "full_name": full_name,
                "student_no": student_no or "-",
                "room_no": room_no or "-",
                "total": 0,
                "present": 0,
                "late": 0,
                "absent": 0,
                "excused": 0,
                "reported": 0,
            },
        )
        entry[status] = entry.get(status, 0) + count
        entry["total"] += count

    results = []
    for entry in bucket.values():
        total = entry["total"]
        present_like = sum(entry.get(s, 0) for s in PRESENT_LIKE)
        absent_like = sum(entry.get(s, 0) for s in ABSENT_LIKE)
        entry["attendance_rate"] = round(present_like / total * 100, 1) if total else 0.0
        entry["absence_rate"] = round(absent_like / total * 100, 1) if total else 0.0
        results.append(entry)

    results.sort(key=lambda e: (-e["absence_rate"], e["full_name"]))
    return results


def dashboard_data(days: int = 30) -> dict:
    start, end = session_date_bounds(days)
    daily = daily_attendance_rates(start, end)
    distribution = status_distribution(start, end)
    students = student_statistics(start, end)
    threshold = current_app.config["ABSENCE_WARNING_THRESHOLD"]

    total_records = sum(distribution.values())
    present_like = sum(distribution[s] for s in PRESENT_LIKE)

    return {
        "start": start,
        "end": end,
        "daily": daily,
        "distribution": distribution,
        "students": students,
        "risky_students": [s for s in students if s["absence_rate"] >= threshold],
        "threshold": threshold,
        "session_count": len(daily),
        "student_count": User.query.filter_by(
            role=ROLE_STUDENT, is_active_account=True
        ).count(),
        "overall_rate": round(present_like / total_records * 100, 1)
        if total_records
        else 0.0,
    }
