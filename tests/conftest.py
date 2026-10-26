"""Pytest ortak hazırlıkları."""
import os
import re
import sys
from datetime import date, time, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import ROLE_ADMIN, ROLE_STAFF, ROLE_STUDENT, User, now  # noqa: E402
from app.services import create_session  # noqa: E402
from app.utils.security import scan_limiter, totp  # noqa: E402


@pytest.fixture()
def app():
    application = create_app("testing")
    with application.app_context():
        db.create_all()
        scan_limiter.reset()

        admin = User(username="admin", full_name="Yönetici", role=ROLE_ADMIN)
        admin.set_password("Admin1234!")
        staff = User(username="gorevli", full_name="Görevli Kişi", role=ROLE_STAFF)
        staff.set_password("Gorevli1234!")
        db.session.add_all([admin, staff])

        # Öğrenciler parolasızdır: sisteme giriş yapmaz, yoklamada numara +
        # ad soyad ile doğrulanırlar.
        student_names = ["Ayşe Yılmaz", "Elif Demir", "Zeynep Kaya"]
        for index, full_name in enumerate(student_names, start=1):
            student = User(
                username=f"2023001{index:02d}",
                student_no=f"2023001{index:02d}",
                full_name=full_name,
                role=ROLE_STUDENT,
                room_no=f"10{index}",
            )
            student.set_password(None)
            db.session.add(student)

        db.session.commit()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def staff_user(app):
    return User.query.filter_by(username="gorevli").first()


@pytest.fixture()
def students(app):
    return User.query.filter_by(role=ROLE_STUDENT).order_by(User.username).all()


@pytest.fixture()
def open_session(app, staff_user):
    """Şu an açık, 30 dakika sürecek bir oturum."""
    start = now()
    end = start + timedelta(minutes=30)
    return create_session(
        creator=staff_user,
        title="Test Yoklaması",
        session_date=date.today(),
        start_time=start.time().replace(microsecond=0),
        end_time=end.time().replace(microsecond=0),
        refresh_seconds=15,
    )


def login(client, username: str, password: str):
    return client.post(
        "/giris",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


def open_scan_form(client, session_obj, code: str | None = None):
    """QR kodun açtığı adresi ister ve sayfadaki okutma biletini döndürür."""
    code = code or totp(session_obj.secret, step=session_obj.refresh_seconds)
    response = client.get(f"/yoklama/{session_obj.id}/{code}")
    match = re.search(
        r'name="ticket"\s+value="([^"]+)"', response.get_data(as_text=True)
    )
    return response, (match.group(1) if match else "")


def scan_with_identity(client, session_obj, student_no: str, full_name: str,
                       code: str | None = None):
    """Öğrencinin tam akışı: QR'ı okut, formu numara + ad soyad ile gönder."""
    _, ticket = open_scan_form(client, session_obj, code)
    return client.post(
        "/yoklama/kaydet",
        data={"ticket": ticket, "student_no": student_no, "full_name": full_name},
    )
