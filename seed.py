"""Sunum ve test için örnek veri üretir.

Kullanım:
    python seed.py                 (varsayılan: 12 öğrenci, 10 günlük geçmiş)
    flask seed-demo --students 20 --days 20

Uyarı: Var olan kayıtları silmez, yalnızca eksik olanları ekler.
"""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from app import create_app
from app.extensions import db
from app.models import (
    METHOD_AUTO,
    METHOD_MANUAL,
    METHOD_QR,
    ROLE_ADMIN,
    ROLE_STAFF,
    ROLE_STUDENT,
    SESSION_CLOSED,
    STATUS_ABSENT,
    STATUS_EXCUSED,
    STATUS_LATE,
    STATUS_PRESENT,
    STATUS_REPORTED,
    AttendanceRecord,
    AttendanceSession,
    AuditLog,
    Leave,
    User,
)
from app.utils.security import generate_secret

FIRST_NAMES = [
    "Zeynep", "Elif", "Ayşe", "Fatma", "Merve", "Büşra", "Esra", "Hatice",
    "Sude", "İrem", "Nisa", "Beyza", "Şeyma", "Gizem", "Tuğba", "Rabia",
    "Melike", "Dilara", "Ecrin", "Kübra", "Seda", "Ceren", "Yağmur", "Hilal",
]
LAST_NAMES = [
    "Yılmaz", "Kaya", "Demir", "Şahin", "Çelik", "Yıldız", "Yıldırım", "Öztürk",
    "Aydın", "Arslan", "Doğan", "Kılıç", "Aslan", "Çetin", "Kurt", "Özkan",
    "Şimşek", "Polat", "Korkmaz", "Taş", "Erdoğan", "Güneş", "Bulut", "Aksoy",
]
PROGRAMS = [
    "Bilgisayar Programcılığı",
    "Çocuk Gelişimi",
    "İşletme Yönetimi",
    "Laborant ve Veteriner Sağlık",
    "Ormancılık ve Orman Ürünleri",
]


def _unique_name(used: set[str]) -> str:
    while True:
        name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
        if name not in used:
            used.add(name)
            return name


def run_seed(students: int = 12, days: int = 10, seed_value: int = 20260521) -> None:
    random.seed(seed_value)
    db.create_all()

    # --- Yönetici ---
    admin = User.query.filter_by(username="admin").first()
    if admin is None:
        admin = User(
            username="admin",
            full_name="Sistem Yöneticisi",
            role=ROLE_ADMIN,
            email="admin@example.com",
        )
        admin.set_password("Admin1234!")
        db.session.add(admin)

    # --- Yurt görevlileri ---
    staff_users = []
    for username, full_name in [
        ("gorevli", "Ayla Korkmaz"),
        ("gorevli2", "Hacer Demirci"),
    ]:
        user = User.query.filter_by(username=username).first()
        if user is None:
            user = User(
                username=username,
                full_name=full_name,
                role=ROLE_STAFF,
                phone="0312 000 00 00",
            )
            user.set_password("Gorevli1234!")
            db.session.add(user)
        staff_users.append(user)

    db.session.flush()

    # --- Öğrenciler ---
    used_names = {u.full_name for u in User.query.all()}
    existing_students = User.query.filter_by(role=ROLE_STUDENT).count()
    base_no = 202300100 + existing_students

    student_list = User.query.filter_by(role=ROLE_STUDENT).all()
    for index in range(students - existing_students):
        number = str(base_no + index + 1)
        full_name = _unique_name(used_names)
        student = User(
            username=number,
            student_no=number,
            full_name=full_name,
            role=ROLE_STUDENT,
            department=random.choice(PROGRAMS),
            class_year=str(random.randint(1, 2)),
            room_no=f"{random.randint(1, 3)}{random.randint(0, 9)}{random.randint(1, 4)}",
            phone=f"05{random.randint(10, 59)} {random.randint(100, 999)} "
                  f"{random.randint(10, 99)} {random.randint(10, 99)}",
        )
        student.set_password("Ogrenci1234!")
        db.session.add(student)
        student_list.append(student)

    db.session.flush()
    student_list = User.query.filter_by(role=ROLE_STUDENT).all()

    # --- İzin kayıtları ---
    if Leave.query.count() == 0 and student_list:
        for student in random.sample(student_list, k=min(3, len(student_list))):
            start = date.today() - timedelta(days=random.randint(1, days))
            leave = Leave(
                student_id=student.id,
                leave_type=random.choice(["izin", "rapor"]),
                start_date=start,
                end_date=start + timedelta(days=random.randint(0, 2)),
                note="Örnek veri ile oluşturulan kayıt.",
                created_by_id=staff_users[0].id,
            )
            db.session.add(leave)
    db.session.flush()

    # --- Geçmiş yoklama oturumları ---
    created_sessions = 0
    for offset in range(days, 0, -1):
        day = date.today() - timedelta(days=offset)
        if AttendanceSession.query.filter_by(session_date=day).first():
            continue

        start_time = time(22, 0)
        end_time = time(22, 30)
        session_obj = AttendanceSession(
            title="Akşam Yoklaması",
            session_date=day,
            start_time=start_time,
            end_time=end_time,
            opened_at=datetime.combine(day, start_time),
            closes_at=datetime.combine(day, end_time),
            closed_at=datetime.combine(day, end_time),
            status=SESSION_CLOSED,
            secret=generate_secret(),
            refresh_seconds=15,
            created_by_id=random.choice(staff_users).id,
        )
        db.session.add(session_obj)
        db.session.flush()
        created_sessions += 1

        for student in student_list:
            leave = Leave.active_for(student.id, day)
            if leave is not None:
                status, method, note = (
                    leave.mapped_status,
                    METHOD_AUTO,
                    f"{leave.type_label} kaydı nedeniyle otomatik işaretlendi.",
                )
            else:
                draw = random.random()
                if draw < 0.86:
                    status, method, note = STATUS_PRESENT, METHOD_QR, None
                elif draw < 0.92:
                    status, method, note = (
                        STATUS_LATE,
                        METHOD_MANUAL,
                        "Kütüphaneden geç döndü.",
                    )
                elif draw < 0.96:
                    status, method, note = (
                        STATUS_EXCUSED,
                        METHOD_MANUAL,
                        "Aile yanına izinli gitti.",
                    )
                elif draw < 0.98:
                    status, method, note = (
                        STATUS_REPORTED,
                        METHOD_MANUAL,
                        "Sağlık raporu teslim edildi.",
                    )
                else:
                    status, method, note = STATUS_ABSENT, METHOD_AUTO, None

            marked = datetime.combine(day, start_time) + timedelta(
                minutes=random.randint(1, 28), seconds=random.randint(0, 59)
            )
            db.session.add(
                AttendanceRecord(
                    session_id=session_obj.id,
                    student_id=student.id,
                    status=status,
                    method=method,
                    marked_at=marked,
                    note=note,
                    device_id=f"demo{student.id:04d}" if method == METHOD_QR else None,
                    ip_address="192.168.1." + str(random.randint(2, 250)),
                    user_agent="Mozilla/5.0 (Android) Örnek Cihaz",
                )
            )

        db.session.add(
            AuditLog(
                created_at=datetime.combine(day, end_time),
                user_id=session_obj.created_by_id,
                actor_name=session_obj.created_by.full_name
                if session_obj.created_by
                else "Görevli",
                actor_role=ROLE_STAFF,
                action="session_close",
                target_type="session",
                target_id=session_obj.id,
                detail="Örnek veri: oturum kapatıldı.",
                ip_address="192.168.1.10",
            )
        )

    db.session.commit()

    print("Örnek veri hazır.")
    print(f"  Öğrenci sayısı      : {len(student_list)}")
    print(f"  Yeni oturum sayısı  : {created_sessions}")
    print("  Giriş bilgileri:")
    print("    Yönetici      : admin / Admin1234!")
    print("    Yurt görevlisi: gorevli / Gorevli1234!")
    if student_list:
        print(f"    Öğrenci       : {student_list[0].student_no} / Ogrenci1234!")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        run_seed()
