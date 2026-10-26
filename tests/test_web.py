"""Uç nokta (endpoint) ve yetkilendirme testleri + rapor üretimi."""
from app.models import STATUS_PRESENT, AttendanceRecord
from app.utils.reports import period_excel, period_pdf, session_excel, session_pdf
from app.utils.security import totp
from tests.conftest import login, open_scan_form, scan_with_identity


def test_login_page_is_reachable(client):
    response = client.get("/giris")
    assert response.status_code == 200
    assert "Sanal Yoklama".encode() in response.data


def test_student_cannot_login(client, students):
    """Öğrenci hesapları ile giriş yapılamaz."""
    response = client.post(
        "/giris",
        data={"username": students[0].student_no, "password": "Ogrenci1234!"},
    )
    assert response.status_code == 403
    assert "giriş yapmaz".encode("utf-8") in response.data


def test_wrong_password_is_rejected(client):
    response = client.post(
        "/giris", data={"username": "gorevli", "password": "yanlis"}
    )
    assert response.status_code == 401


def test_staff_pages_require_login(client):
    response = client.get("/gorevli/")
    assert response.status_code in (302, 401)


def test_staff_can_see_live_session(client, open_session):
    login(client, "gorevli", "Gorevli1234!")
    response = client.get(f"/gorevli/oturum/{open_session.id}/canli")
    assert response.status_code == 200


def test_qr_endpoint_returns_png(client, open_session):
    login(client, "gorevli", "Gorevli1234!")
    response = client.get(f"/api/oturum/{open_session.id}/qr.png")
    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.data[:4] == b"\x89PNG"


def test_code_endpoint_requires_login(client, open_session):
    response = client.get(f"/api/oturum/{open_session.id}/kod")
    assert response.status_code in (302, 401, 403)


def test_scan_link_asks_for_identity(client, open_session):
    """QR kodun açtığı sayfa, yoklamayı hemen almaz; numara + ad soyad ister."""
    response, ticket = open_scan_form(client, open_session)
    assert response.status_code == 200
    assert "Okul Numarası".encode("utf-8") in response.data
    assert "Ad Soyad".encode("utf-8") in response.data
    assert ticket


def test_identity_match_marks_attendance(client, open_session, students):
    student = students[0]
    response = scan_with_identity(
        client, open_session, student.student_no, student.full_name
    )
    assert response.status_code == 200
    assert "alındı".encode("utf-8") in response.data

    record = AttendanceRecord.query.filter_by(
        session_id=open_session.id, student_id=student.id
    ).first()
    assert record.status == STATUS_PRESENT
    assert record.method == "qr"


def test_identity_is_tolerant_to_typing_differences(client, open_session, students):
    """Büyük/küçük harf, Türkçe karakter ve ad-soyad sırası farkları kabul edilir."""
    student = students[1]  # "Elif Demir"
    response = scan_with_identity(
        client, open_session, f" {student.student_no} ", "demir  ELIF"
    )
    assert response.status_code == 200
    assert "alındı".encode("utf-8") in response.data


def test_wrong_name_is_rejected(client, open_session, students):
    response = scan_with_identity(
        client, open_session, students[0].student_no, "Başka Kişi"
    )
    assert response.status_code == 400
    assert "eşleşmiyor".encode("utf-8") in response.data

    record = AttendanceRecord.query.filter_by(
        session_id=open_session.id, student_id=students[0].id
    ).first()
    assert record.status != STATUS_PRESENT


def test_unknown_student_no_is_rejected(client, open_session):
    response = scan_with_identity(client, open_session, "999999999", "Hayali Kişi")
    assert response.status_code == 400
    assert "eşleşmiyor".encode("utf-8") in response.data


def test_scan_link_rejects_expired_code(client, open_session):
    response = client.get(f"/yoklama/{open_session.id}/000000")
    assert response.status_code == 200
    assert "alınamadı".encode("utf-8") in response.data


def test_ticket_cannot_be_used_from_another_device(app, open_session, students):
    """Bağlantı/bilet başka bir telefona iletilirse kabul edilmez."""
    first = app.test_client()
    _, ticket = open_scan_form(first, open_session)

    second = app.test_client()  # farklı cihaz = farklı çerez
    response = second.post(
        "/yoklama/kaydet",
        data={
            "ticket": ticket,
            "student_no": students[0].student_no,
            "full_name": students[0].full_name,
        },
    )
    assert response.status_code == 400
    assert "cihaz".encode("utf-8") in response.data


def test_manual_code_entry_marks_attendance(client, open_session, students):
    student = students[2]
    code = totp(open_session.secret, step=open_session.refresh_seconds)
    response = client.post(
        "/yoklama",
        data={
            "code": code,
            "student_no": student.student_no,
            "full_name": student.full_name,
        },
    )
    assert response.status_code == 200
    assert "alındı".encode("utf-8") in response.data

    record = AttendanceRecord.query.filter_by(
        session_id=open_session.id, student_id=student.id
    ).first()
    assert record.status == STATUS_PRESENT


def test_same_device_cannot_mark_second_student_over_web(
    client, open_session, students
):
    scan_with_identity(
        client, open_session, students[0].student_no, students[0].full_name
    )
    response = scan_with_identity(
        client, open_session, students[1].student_no, students[1].full_name
    )
    assert response.status_code == 400
    assert "cihaz".encode("utf-8") in response.data


def test_session_reports_are_generated(open_session):
    excel = session_excel(open_session, dorm_name="Test Yurdu")
    pdf = session_pdf(open_session, dorm_name="Test Yurdu")
    assert excel.getbuffer().nbytes > 1000
    assert pdf.getvalue()[:4] == b"%PDF"


def test_period_reports_are_generated(app, open_session, students):
    from datetime import date

    from app.services import student_statistics
    from app.utils.reports import build_matrix

    sessions = [open_session]
    records_by_student = [
        (
            student,
            {
                record.session_id: record.status
                for record in AttendanceRecord.query.filter_by(
                    student_id=student.id
                ).all()
            },
        )
        for student in students
    ]
    matrix = build_matrix(sessions, records_by_student)
    stats = student_statistics(date.today(), date.today())

    excel = period_excel(
        sessions=sessions, students_stats=stats, matrix=matrix,
        start=date.today(), end=date.today(), dorm_name="Test Yurdu",
    )
    pdf = period_pdf(
        sessions=sessions, students_stats=stats, matrix=matrix,
        start=date.today(), end=date.today(), dorm_name="Test Yurdu",
    )
    assert excel.getbuffer().nbytes > 1000
    assert pdf.getvalue()[:4] == b"%PDF"


def test_admin_dashboard_requires_login(client):
    assert client.get("/yonetim/").status_code in (302, 401, 403)


def test_admin_can_add_student_with_no_and_name(client):
    login(client, "admin", "Admin1234!")
    response = client.post(
        "/yonetim/ogrenci/yeni",
        data={
            "student_no": "202399999",
            "full_name": "Yeni Öğrenci Kaydı",
            "room_no": "404",
            "is_active_account": "y",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    from app.models import ROLE_STUDENT, User

    student = User.query.filter_by(student_no="202399999").first()
    assert student is not None
    assert student.role == ROLE_STUDENT
    assert student.full_name == "Yeni Öğrenci Kaydı"
    # Öğrenci parolasız kaydedilir ve giriş yapamaz
    assert not student.has_password
    assert not student.can_login


def test_admin_can_delete_student_with_records(client, open_session, students):
    """Öğrenci silinince yoklama kayıtları da gider."""
    from app.extensions import db
    from app.models import AttendanceRecord, User

    student_id = students[0].id
    assert AttendanceRecord.query.filter_by(student_id=student_id).count() == 1

    login(client, "admin", "Admin1234!")
    response = client.post(
        f"/yonetim/ogrenci/{student_id}/sil", follow_redirects=True
    )
    assert response.status_code == 200
    assert db.session.get(User, student_id) is None
    assert AttendanceRecord.query.filter_by(student_id=student_id).count() == 0


def test_admin_cannot_delete_own_account(client):
    from app.models import User

    login(client, "admin", "Admin1234!")
    admin = User.query.filter_by(username="admin").first()
    response = client.post(
        f"/yonetim/kullanici/{admin.id}/sil", follow_redirects=True
    )
    assert response.status_code == 200
    assert "silemezsiniz".encode("utf-8") in response.data
    assert User.query.filter_by(username="admin").first() is not None


def test_staff_with_sessions_cannot_be_deleted(client, open_session, staff_user):
    """Oturum açmış görevli silinemez; geçmiş kayıtların sahibi kaybolmasın."""
    from app.extensions import db
    from app.models import User

    staff_id = staff_user.id
    login(client, "admin", "Admin1234!")
    response = client.post(
        f"/yonetim/kullanici/{staff_id}/sil", follow_redirects=True
    )
    assert response.status_code == 200
    assert "silinemez".encode("utf-8") in response.data
    assert db.session.get(User, staff_id) is not None


def test_admin_can_delete_staff_without_records(client):
    from app.extensions import db
    from app.models import ROLE_STAFF, User

    extra = User(username="gorevli2", full_name="İkinci Görevli", role=ROLE_STAFF)
    extra.set_password("Gorevli1234!")
    db.session.add(extra)
    db.session.commit()
    extra_id = extra.id

    login(client, "admin", "Admin1234!")
    response = client.post(
        f"/yonetim/kullanici/{extra_id}/sil", follow_redirects=True
    )
    assert response.status_code == 200
    assert db.session.get(User, extra_id) is None


def test_admin_can_reset_staff_password(client, staff_user):
    """Yönetici, görevlinin parolasını sıfırlar; eski parola geçersiz olur."""
    from app.extensions import db
    from app.models import AuditLog, User

    staff_id = staff_user.id
    login(client, "admin", "Admin1234!")
    response = client.post(
        f"/yonetim/kullanici/{staff_id}/parola",
        data={"new_password": "YeniParola123!",
              "confirm_password": "YeniParola123!"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    updated = db.session.get(User, staff_id)
    assert updated.check_password("YeniParola123!")
    assert not updated.check_password("Gorevli1234!")
    assert AuditLog.query.filter_by(action="password_reset").count() == 1


def test_password_reset_requires_matching_confirmation(client, staff_user):
    from app.extensions import db
    from app.models import User

    staff_id = staff_user.id
    login(client, "admin", "Admin1234!")
    client.post(
        f"/yonetim/kullanici/{staff_id}/parola",
        data={"new_password": "YeniParola123!", "confirm_password": "baska"},
    )
    assert db.session.get(User, staff_id).check_password("Gorevli1234!")


def test_password_reset_page_rejects_student(client, students):
    login(client, "admin", "Admin1234!")
    response = client.get(
        f"/yonetim/kullanici/{students[0].id}/parola", follow_redirects=True
    )
    assert response.status_code == 200
    assert "giriş yapmaz".encode("utf-8") in response.data


def test_student_add_rejects_duplicate_number(client, students):
    login(client, "admin", "Admin1234!")
    response = client.post(
        "/yonetim/ogrenci/yeni",
        data={"student_no": students[0].student_no, "full_name": "Kopya Kayıt"},
    )
    assert response.status_code == 200
    assert "zaten kayıtlı".encode("utf-8") in response.data


def test_admin_dashboard_renders_for_admin(client, open_session):
    login(client, "admin", "Admin1234!")
    response = client.get("/yonetim/")
    assert response.status_code == 200
    assert "İstatistik".encode("utf-8") in response.data
