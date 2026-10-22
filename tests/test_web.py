"""Uç nokta (endpoint) ve yetkilendirme testleri + rapor üretimi."""
from app.models import STATUS_PRESENT, AttendanceRecord
from app.utils.reports import period_excel, period_pdf, session_excel, session_pdf
from app.utils.security import totp
from tests.conftest import login


def test_login_page_is_reachable(client):
    response = client.get("/giris")
    assert response.status_code == 200
    assert "Sanal Yoklama".encode() in response.data


def test_student_can_login_with_student_number(client, students):
    response = login(client, students[0].student_no, "Ogrenci1234!")
    assert response.status_code == 200
    assert "Panelim".encode("utf-8") in response.data


def test_wrong_password_is_rejected(client, students):
    response = client.post(
        "/giris",
        data={"username": students[0].student_no, "password": "yanlis"},
    )
    assert response.status_code == 401


def test_student_cannot_open_staff_pages(client, students):
    login(client, students[0].student_no, "Ogrenci1234!")
    response = client.get("/gorevli/")
    assert response.status_code == 403


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


def test_code_endpoint_requires_staff(client, open_session, students):
    login(client, students[0].student_no, "Ogrenci1234!")
    response = client.get(f"/api/oturum/{open_session.id}/kod")
    assert response.status_code == 403


def test_student_scan_endpoint_marks_attendance(client, open_session, students):
    login(client, students[0].student_no, "Ogrenci1234!")
    code = totp(open_session.secret, step=open_session.refresh_seconds)
    response = client.post(
        "/api/yoklama/okut",
        json={"payload": f"NMYO|{open_session.id}|{code}"},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True

    record = AttendanceRecord.query.filter_by(
        session_id=open_session.id, student_id=students[0].id
    ).first()
    assert record.status == STATUS_PRESENT


def test_scan_link_works_for_phone_camera(client, open_session, students):
    login(client, students[1].student_no, "Ogrenci1234!")
    code = totp(open_session.secret, step=open_session.refresh_seconds)
    response = client.get(f"/yoklama/{open_session.id}/{code}")
    assert response.status_code == 200
    assert "alındı".encode("utf-8") in response.data


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


def test_admin_dashboard_requires_staff_role(client, students):
    login(client, students[0].student_no, "Ogrenci1234!")
    assert client.get("/yonetim/").status_code == 403


def test_admin_dashboard_renders_for_admin(client, open_session):
    login(client, "admin", "Admin1234!")
    response = client.get("/yonetim/")
    assert response.status_code == 200
    assert "İstatistik".encode("utf-8") in response.data
