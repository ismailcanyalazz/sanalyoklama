"""Yönetici paneli: grafikli özet, kullanıcı yönetimi, günlük kayıtları, raporlar."""
from datetime import date, datetime, timedelta

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user
from sqlalchemy import or_

from ..extensions import db
from ..forms import UserForm
from ..models import (
    ROLE_LABELS,
    ROLE_STUDENT,
    STATUS_LABELS,
    AttendanceRecord,
    AttendanceSession,
    AuditLog,
    Leave,
    User,
)
from ..services import (
    active_students,
    dashboard_data,
    student_statistics,
)
from ..utils.audit import log_action
from ..utils.decorators import admin_required, staff_required
from ..utils.reports import build_matrix, period_excel, period_pdf

admin_bp = Blueprint("admin", __name__)


# --------------------------------------------------------------------------- #
# Yardımcılar
# --------------------------------------------------------------------------- #
def _parse_range() -> tuple[date, date]:
    """Rapor filtresindeki tarih aralığını okur (varsayılan: son 30 gün)."""
    today = date.today()
    default_start = today - timedelta(days=29)

    def _parse(name: str, fallback: date) -> date:
        raw = request.args.get(name, "")
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return fallback

    start = _parse("baslangic", default_start)
    end = _parse("bitis", today)
    if end < start:
        start, end = end, start
    return start, end


def _report_context(start: date, end: date, student_id: int | None = None) -> dict:
    sessions = (
        AttendanceSession.query.filter(
            AttendanceSession.session_date.between(start, end)
        )
        .order_by(AttendanceSession.session_date, AttendanceSession.start_time)
        .all()
    )
    session_ids = [s.id for s in sessions]

    students = active_students()
    if student_id:
        students = [s for s in students if s.id == student_id]

    records_by_student = []
    if session_ids:
        for student in students:
            rows = (
                AttendanceRecord.query.filter(
                    AttendanceRecord.student_id == student.id,
                    AttendanceRecord.session_id.in_(session_ids),
                ).all()
            )
            records_by_student.append(
                (student, {row.session_id: row.status for row in rows})
            )
    else:
        records_by_student = [(student, {}) for student in students]

    stats = student_statistics(start, end)
    if student_id:
        stats = [s for s in stats if s["student_id"] == student_id]

    return {
        "sessions": sessions,
        "students_stats": stats,
        "matrix": build_matrix(sessions, records_by_student),
        "start": start,
        "end": end,
    }


# --------------------------------------------------------------------------- #
# Panel
# --------------------------------------------------------------------------- #
@admin_bp.route("/")
@staff_required
def dashboard():
    days = request.args.get("gun", 30, type=int)
    days = max(7, min(days, 180))
    data = dashboard_data(days=days)
    return render_template(
        "admin/dashboard.html",
        data=data,
        days=days,
        last_sessions=(
            AttendanceSession.query.order_by(
                AttendanceSession.session_date.desc()
            )
            .limit(8)
            .all()
        ),
        recent_logs=(
            AuditLog.query.order_by(AuditLog.created_at.desc()).limit(10).all()
        ),
    )


# --------------------------------------------------------------------------- #
# Kullanıcı yönetimi
# --------------------------------------------------------------------------- #
@admin_bp.route("/kullanicilar")
@admin_required
def users():
    query = request.args.get("q", "").strip()
    role = request.args.get("rol", "")
    page = request.args.get("page", 1, type=int)

    q = User.query
    if query:
        like = f"%{query}%"
        q = q.filter(
            or_(
                User.full_name.ilike(like),
                User.username.ilike(like),
                User.student_no.ilike(like),
                User.room_no.ilike(like),
            )
        )
    if role in ROLE_LABELS:
        q = q.filter(User.role == role)

    pagination = q.order_by(User.role, User.full_name).paginate(
        page=page, per_page=20, error_out=False
    )
    return render_template(
        "admin/users.html", pagination=pagination, q=query, role=role
    )


@admin_bp.route("/kullanici/yeni", methods=["GET", "POST"])
@admin_required
def user_create():
    form = UserForm()
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data.strip()).first():
            flash("Bu kullanıcı adı zaten kayıtlı.", "danger")
        elif not form.password.data:
            flash("Yeni kullanıcı için parola zorunludur.", "danger")
        else:
            user = User(
                username=form.username.data.strip(),
                full_name=form.full_name.data.strip(),
                role=form.role.data,
                student_no=(form.student_no.data or "").strip() or None,
                department=(form.department.data or "").strip() or None,
                class_year=(form.class_year.data or "").strip() or None,
                room_no=(form.room_no.data or "").strip() or None,
                email=(form.email.data or "").strip() or None,
                phone=(form.phone.data or "").strip() or None,
                is_active_account=bool(form.is_active_account.data),
            )
            user.set_password(form.password.data)
            db.session.add(user)
            log_action(
                "user_create",
                target_type="user",
                detail=f"{user.full_name} ({user.role_label}) hesabı oluşturuldu.",
            )
            db.session.commit()
            flash(f"{user.full_name} eklendi.", "success")
            return redirect(url_for("admin.users"))

    return render_template("admin/user_form.html", form=form, user=None)


@admin_bp.route("/kullanici/<int:user_id>/duzenle", methods=["GET", "POST"])
@admin_required
def user_edit(user_id: int):
    user = db.session.get(User, user_id) or abort(404)
    form = UserForm(obj=user)

    if form.validate_on_submit():
        duplicate = User.query.filter(
            User.username == form.username.data.strip(), User.id != user.id
        ).first()
        if duplicate:
            flash("Bu kullanıcı adı başka bir hesapta kullanılıyor.", "danger")
        else:
            user.username = form.username.data.strip()
            user.full_name = form.full_name.data.strip()
            user.role = form.role.data
            user.student_no = (form.student_no.data or "").strip() or None
            user.department = (form.department.data or "").strip() or None
            user.class_year = (form.class_year.data or "").strip() or None
            user.room_no = (form.room_no.data or "").strip() or None
            user.email = (form.email.data or "").strip() or None
            user.phone = (form.phone.data or "").strip() or None
            user.is_active_account = bool(form.is_active_account.data)
            if form.password.data:
                user.set_password(form.password.data)
            log_action(
                "user_update",
                target_type="user",
                target_id=user.id,
                detail=f"{user.full_name} hesabı güncellendi.",
            )
            db.session.commit()
            flash("Kullanıcı güncellendi.", "success")
            return redirect(url_for("admin.users"))

    return render_template("admin/user_form.html", form=form, user=user)


@admin_bp.route("/kullanici/<int:user_id>/durum", methods=["POST"])
@admin_required
def user_toggle(user_id: int):
    user = db.session.get(User, user_id) or abort(404)
    if user.id == current_user.id:
        flash("Kendi hesabınızı pasife alamazsınız.", "warning")
        return redirect(url_for("admin.users"))
    user.is_active_account = not user.is_active_account
    log_action(
        "user_toggle",
        target_type="user",
        target_id=user.id,
        detail=f"{user.full_name} hesabı "
        f"{'aktif' if user.is_active_account else 'pasif'} yapıldı.",
    )
    db.session.commit()
    flash("Hesap durumu güncellendi.", "info")
    return redirect(url_for("admin.users"))


@admin_bp.route("/ogrenci/<int:user_id>")
@staff_required
def student_detail(user_id: int):
    student = db.session.get(User, user_id) or abort(404)
    if student.role != ROLE_STUDENT:
        abort(404)
    start, end = _parse_range()
    records = (
        AttendanceRecord.query.filter_by(student_id=student.id)
        .join(AttendanceSession)
        .filter(AttendanceSession.session_date.between(start, end))
        .order_by(AttendanceSession.session_date.desc())
        .all()
    )
    stats = [s for s in student_statistics(start, end) if s["student_id"] == student.id]
    leaves = (
        Leave.query.filter_by(student_id=student.id)
        .order_by(Leave.start_date.desc())
        .all()
    )
    return render_template(
        "admin/student_detail.html",
        student=student,
        records=records,
        stat=stats[0] if stats else None,
        leaves=leaves,
        start=start,
        end=end,
    )


# --------------------------------------------------------------------------- #
# Günlük kayıtları (log)
# --------------------------------------------------------------------------- #
@admin_bp.route("/gunluk")
@admin_required
def logs():
    page = request.args.get("page", 1, type=int)
    action = request.args.get("islem", "")
    query = AuditLog.query
    if action:
        query = query.filter(AuditLog.action == action)
    pagination = query.order_by(AuditLog.created_at.desc()).paginate(
        page=page, per_page=40, error_out=False
    )
    actions = [row[0] for row in db.session.query(AuditLog.action).distinct().all()]
    return render_template(
        "admin/logs.html", pagination=pagination, actions=sorted(actions), action=action
    )


# --------------------------------------------------------------------------- #
# Raporlar
# --------------------------------------------------------------------------- #
@admin_bp.route("/raporlar")
@staff_required
def reports():
    start, end = _parse_range()
    student_id = request.args.get("ogrenci", type=int)
    context = _report_context(start, end, student_id)
    return render_template(
        "admin/reports.html",
        **context,
        students=active_students(),
        selected_student=student_id,
        status_labels=STATUS_LABELS,
    )


@admin_bp.route("/raporlar/donem.xlsx")
@staff_required
def report_excel():
    start, end = _parse_range()
    student_id = request.args.get("ogrenci", type=int)
    context = _report_context(start, end, student_id)
    stream = period_excel(
        **context, dorm_name=current_app.config["DORM_NAME"]
    )
    log_action(
        "report_export",
        detail=f"Dönem raporu Excel ({start} - {end}) indirildi.",
        commit=True,
    )
    return send_file(
        stream,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"donem_raporu_{start:%Y%m%d}_{end:%Y%m%d}.xlsx",
    )


@admin_bp.route("/raporlar/donem.pdf")
@staff_required
def report_pdf():
    start, end = _parse_range()
    student_id = request.args.get("ogrenci", type=int)
    context = _report_context(start, end, student_id)
    stream = period_pdf(**context, dorm_name=current_app.config["DORM_NAME"])
    log_action(
        "report_export",
        detail=f"Dönem raporu PDF ({start} - {end}) indirildi.",
        commit=True,
    )
    return send_file(
        stream,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"donem_raporu_{start:%Y%m%d}_{end:%Y%m%d}.pdf",
    )
