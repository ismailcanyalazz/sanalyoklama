"""Pytest ortak hazırlıkları."""
import os
import sys
from datetime import date, time, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import ROLE_ADMIN, ROLE_STAFF, ROLE_STUDENT, User, now  # noqa: E402
from app.services import create_session  # noqa: E402
from app.utils.security import scan_limiter  # noqa: E402


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

        for index in range(1, 4):
            student = User(
                username=f"2023001{index:02d}",
                student_no=f"2023001{index:02d}",
                full_name=f"Öğrenci {index}",
                role=ROLE_STUDENT,
                room_no=f"10{index}",
            )
            student.set_password("Ogrenci1234!")
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
