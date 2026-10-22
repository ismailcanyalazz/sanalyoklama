"""Öğrenci sayfaları: durum özeti, QR okutma ekranı, geçmiş kayıtlar."""
from datetime import date

from flask import Blueprint, abort, render_template, request
from flask_login import current_user, login_required

from ..extensions import db
from ..models import (
    ABSENT_LIKE,
    PRESENT_LIKE,
    STATUS_LABELS,
    AttendanceRecord,
    AttendanceSession,
    Leave,
)
from ..services import get_open_session

student_bp = Blueprint("student", __name__)


@student_bp.before_request
@login_required
def only_students():
    if not current_user.is_student:
        abort(403)
    return None


def _my_records_query():
    return (
        AttendanceRecord.query.filter_by(student_id=current_user.id)
        .join(AttendanceSession)
        .order_by(AttendanceSession.session_date.desc())
    )


@student_bp.route("/")
def dashboard():
    open_session = get_open_session()
    today_record = None
    if open_session is not None:
        today_record = AttendanceRecord.query.filter_by(
            session_id=open_session.id, student_id=current_user.id
        ).first()

    records = _my_records_query().limit(10).all()
    all_records = _my_records_query().all()
    total = len(all_records)
    present = sum(1 for r in all_records if r.status in PRESENT_LIKE)
    absent = sum(1 for r in all_records if r.status in ABSENT_LIKE)

    active_leave = Leave.active_for(current_user.id, date.today())

    return render_template(
        "student/dashboard.html",
        open_session=open_session,
        today_record=today_record,
        records=records,
        stats={
            "total": total,
            "present": present,
            "absent": absent,
            "rate": round(present / total * 100, 1) if total else 0.0,
        },
        active_leave=active_leave,
        already_marked=bool(today_record and today_record.status in PRESENT_LIKE),
    )


@student_bp.route("/yoklama")
def scan_page():
    """Tarayıcı içi QR okuyucu (html5-qrcode) ekranı."""
    open_session = get_open_session()
    record = None
    if open_session is not None:
        record = AttendanceRecord.query.filter_by(
            session_id=open_session.id, student_id=current_user.id
        ).first()
    return render_template(
        "student/scan.html",
        open_session=open_session,
        record=record,
        already_marked=bool(record and record.status in PRESENT_LIKE),
    )


@student_bp.route("/kayitlarim")
def my_records():
    status_filter = request.args.get("durum", "")
    page = request.args.get("page", 1, type=int)
    query = _my_records_query()
    if status_filter in STATUS_LABELS:
        query = query.filter(AttendanceRecord.status == status_filter)
    pagination = query.paginate(page=page, per_page=20, error_out=False)
    return render_template(
        "student/records.html",
        pagination=pagination,
        status_filter=status_filter,
    )


@student_bp.route("/izinlerim")
def my_leaves():
    leaves = (
        Leave.query.filter_by(student_id=current_user.id)
        .order_by(Leave.start_date.desc())
        .all()
    )
    return render_template("student/leaves.html", leaves=leaves)
