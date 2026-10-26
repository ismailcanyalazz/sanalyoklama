"""Yoklama iş kuralları: kayıt üretimi, QR ile işaretleme, güvenlik kontrolleri."""
from datetime import date, datetime, timedelta

import pytest

from app.extensions import db
from app.models import (
    PRESENT_LIKE,
    STATUS_ABSENT,
    STATUS_EXCUSED,
    STATUS_PRESENT,
    AttendanceRecord,
    AuditLog,
    Leave,
)
from app.services import (
    AttendanceError,
    autoclose_expired_sessions,
    close_session,
    create_session,
    mark_attendance_by_code,
    mark_attendance_with_identity,
    resolve_student_identity,
    update_record_manually,
)
from app.utils.security import totp
from app.utils.text import names_match, normalize_student_no


def test_session_creates_record_for_every_student(open_session, students):
    assert len(open_session.records) == len(students)
    assert all(record.status == STATUS_ABSENT for record in open_session.records)


def test_second_open_session_is_blocked(app, staff_user, open_session):
    with pytest.raises(AttendanceError):
        create_session(
            creator=staff_user,
            title="İkinci Oturum",
            session_date=date.today(),
            start_time=open_session.start_time,
            end_time=open_session.end_time,
        )


def test_valid_code_marks_student_present(open_session, students):
    code = totp(open_session.secret, step=open_session.refresh_seconds)
    record = mark_attendance_by_code(
        student=students[0], session_id=open_session.id, code=code,
        device_id="cihaz-1",
    )
    assert record.status == STATUS_PRESENT
    assert record.method == "qr"
    assert record.status in PRESENT_LIKE


def test_invalid_code_is_rejected_and_logged(open_session, students):
    with pytest.raises(AttendanceError) as error:
        mark_attendance_by_code(
            student=students[0], session_id=open_session.id, code="000000",
            device_id="cihaz-1",
        )
    assert error.value.code == "invalid_code"
    assert AuditLog.query.filter_by(action="scan_rejected").count() == 1


def test_same_student_cannot_scan_twice(open_session, students):
    code = totp(open_session.secret, step=open_session.refresh_seconds)
    mark_attendance_by_code(
        student=students[0], session_id=open_session.id, code=code,
        device_id="cihaz-1",
    )
    with pytest.raises(AttendanceError) as error:
        mark_attendance_by_code(
            student=students[0], session_id=open_session.id, code=code,
            device_id="cihaz-1",
        )
    assert error.value.code == "duplicate"


def test_same_device_cannot_mark_two_students(open_session, students):
    code = totp(open_session.secret, step=open_session.refresh_seconds)
    mark_attendance_by_code(
        student=students[0], session_id=open_session.id, code=code,
        device_id="ortak-cihaz",
    )
    with pytest.raises(AttendanceError) as error:
        mark_attendance_by_code(
            student=students[1], session_id=open_session.id, code=code,
            device_id="ortak-cihaz",
        )
    assert error.value.code == "device_conflict"


def test_closed_session_rejects_scan(open_session, students, staff_user):
    close_session(open_session, actor=staff_user)
    code = totp(open_session.secret, step=open_session.refresh_seconds)
    with pytest.raises(AttendanceError) as error:
        mark_attendance_by_code(
            student=students[0], session_id=open_session.id, code=code,
            device_id="cihaz-2",
        )
    assert error.value.code == "closed"


def test_expired_session_is_closed_automatically(open_session):
    open_session.closes_at = datetime.now() - timedelta(minutes=1)
    db.session.commit()
    assert autoclose_expired_sessions() == 1
    assert not open_session.is_open
    assert AuditLog.query.filter_by(action="session_autoclose").count() == 1


def test_manual_update_records_note_and_actor(open_session, students, staff_user):
    record = AttendanceRecord.query.filter_by(
        session_id=open_session.id, student_id=students[2].id
    ).first()
    update_record_manually(
        record=record, status=STATUS_EXCUSED, note="Ailesinin yanına gitti.",
        actor=staff_user,
    )
    assert record.status == STATUS_EXCUSED
    assert record.method == "manual"
    assert record.updated_by_id == staff_user.id
    assert AuditLog.query.filter_by(action="record_manual_update").count() == 1


# --------------------------------------------------------------------------- #
# Kimlik doğrulama (okul numarası + ad soyad)
# --------------------------------------------------------------------------- #
def test_identity_resolves_student(app, students):
    student = students[0]
    assert resolve_student_identity(student.student_no, student.full_name) is student


def test_identity_ignores_case_and_turkish_letters(app, students):
    student = students[0]  # "Ayşe Yılmaz"
    assert resolve_student_identity(student.student_no, "ayse yilmaz") is student
    assert resolve_student_identity(student.student_no, "AYŞE YILMAZ") is student
    # Ad-soyad sırası ve fazladan boşluk da tolere edilir
    assert resolve_student_identity(student.student_no, " yılmaz   ayşe ") is student


def test_identity_rejects_wrong_name(app, students):
    with pytest.raises(AttendanceError) as error:
        resolve_student_identity(students[0].student_no, "Başka Kişi")
    assert error.value.code == "identity_mismatch"
    assert AuditLog.query.filter_by(action="scan_rejected").count() == 1


def test_identity_rejects_unknown_number(app):
    with pytest.raises(AttendanceError) as error:
        resolve_student_identity("000000000", "Ayşe Yılmaz")
    assert error.value.code == "identity_mismatch"


def test_identity_requires_both_fields(app, students):
    with pytest.raises(AttendanceError) as error:
        resolve_student_identity(students[0].student_no, "   ")
    assert error.value.code == "missing_identity"


def test_identity_rejects_inactive_student(app, students):
    students[0].is_active_account = False
    db.session.commit()
    with pytest.raises(AttendanceError) as error:
        resolve_student_identity(students[0].student_no, students[0].full_name)
    assert error.value.code == "inactive"


def test_identity_scan_marks_student_present(open_session, students):
    code = totp(open_session.secret, step=open_session.refresh_seconds)
    record = mark_attendance_with_identity(
        student_no=students[0].student_no,
        full_name=students[0].full_name,
        session_id=open_session.id,
        code=code,
        device_id="telefon-1",
    )
    assert record.status == STATUS_PRESENT
    assert record.student_id == students[0].id


def test_identity_scan_needs_valid_code_before_identity(open_session, students):
    """Geçersiz kodla gelen istek, kimlik doğru olsa da reddedilir."""
    with pytest.raises(AttendanceError) as error:
        mark_attendance_with_identity(
            student_no=students[0].student_no,
            full_name=students[0].full_name,
            session_id=open_session.id,
            code="000000",
            device_id="telefon-1",
        )
    assert error.value.code == "invalid_code"


def test_name_normalization_helpers():
    assert names_match("Ayşe Yılmaz", "ayse yilmaz")
    assert names_match("İrem Öztürk", "irem ozturk")
    assert names_match("Ayşe Yılmaz", "Yılmaz Ayşe")
    assert not names_match("Ayşe Yılmaz", "Ayşe Kaya")
    assert not names_match("Ayşe Yılmaz", "")
    assert normalize_student_no(" 2023-001 01 ") == "202300101"


def test_leave_marks_student_excused_on_new_session(app, staff_user, students):
    db.session.add(
        Leave(
            student_id=students[0].id,
            leave_type="izin",
            start_date=date.today(),
            end_date=date.today(),
            created_by_id=staff_user.id,
        )
    )
    db.session.commit()

    start = datetime.now()
    session_obj = create_session(
        creator=staff_user,
        title="İzinli Testi",
        session_date=date.today(),
        start_time=start.time().replace(microsecond=0),
        end_time=(start + timedelta(minutes=20)).time().replace(microsecond=0),
    )
    record = AttendanceRecord.query.filter_by(
        session_id=session_obj.id, student_id=students[0].id
    ).first()
    assert record.status == STATUS_EXCUSED
