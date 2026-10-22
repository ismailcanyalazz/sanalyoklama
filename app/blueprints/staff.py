"""Yurt görevlisi paneli: oturum açma, canlı QR ekranı, manuel düzenleme, izinler."""
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

from ..extensions import db
from ..forms import LeaveForm, RecordEditForm, SessionForm
from ..models import (
    PRESENT_LIKE,
    STATUS_LABELS,
    AttendanceRecord,
    AttendanceSession,
    Leave,
    now,
)
from ..services import (
    AttendanceError,
    active_students,
    close_session,
    create_session,
    ensure_records,
    get_open_session,
    update_record_manually,
)
from ..utils.audit import log_action
from ..utils.decorators import staff_required
from ..utils.reports import session_excel, session_pdf

staff_bp = Blueprint("staff", __name__)


@staff_bp.before_request
@staff_required
def restrict_to_staff():
    """Tüm görevli sayfaları için yetki kontrolü."""
    return None


# --------------------------------------------------------------------------- #
# Panel
# --------------------------------------------------------------------------- #
@staff_bp.route("/")
def dashboard():
    open_session = get_open_session()
    today_sessions = (
        AttendanceSession.query.filter_by(session_date=date.today())
        .order_by(AttendanceSession.opened_at.desc())
        .all()
    )
    recent_sessions = (
        AttendanceSession.query.order_by(
            AttendanceSession.session_date.desc(), AttendanceSession.opened_at.desc()
        )
        .limit(10)
        .all()
    )

    default_start = now().time().replace(second=0, microsecond=0)
    default_end = (
        now() + timedelta(minutes=current_app.config["DEFAULT_SESSION_MINUTES"])
    ).time().replace(second=0, microsecond=0)

    form = SessionForm(
        start_time=default_start,
        end_time=default_end,
        refresh_seconds=str(current_app.config["QR_REFRESH_SECONDS"]),
    )

    return render_template(
        "staff/dashboard.html",
        form=form,
        open_session=open_session,
        today_sessions=today_sessions,
        recent_sessions=recent_sessions,
        student_count=len(active_students()),
    )


@staff_bp.route("/oturum/baslat", methods=["POST"])
def start_session():
    form = SessionForm()
    if not form.validate_on_submit():
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{getattr(form, field).label.text}: {error}", "danger")
        return redirect(url_for("staff.dashboard"))

    try:
        session_obj = create_session(
            creator=current_user,
            title=form.title.data,
            session_date=form.session_date.data,
            start_time=form.start_time.data,
            end_time=form.end_time.data,
            refresh_seconds=int(form.refresh_seconds.data),
            note=form.note.data,
        )
    except AttendanceError as error:
        db.session.rollback()
        flash(error.message, "warning")
        return redirect(url_for("staff.dashboard"))

    flash("Yoklama oturumu başlatıldı. QR kodu öğrencilere gösterin.", "success")
    return redirect(url_for("staff.live_session", session_id=session_obj.id))


# --------------------------------------------------------------------------- #
# Canlı oturum (QR ekranı)
# --------------------------------------------------------------------------- #
@staff_bp.route("/oturum/<int:session_id>/canli")
def live_session(session_id: int):
    session_obj = db.session.get(AttendanceSession, session_id) or abort(404)
    return render_template(
        "staff/live_session.html",
        session=session_obj,
        summary=session_obj.summary(),
    )


@staff_bp.route("/oturum/<int:session_id>/kapat", methods=["POST"])
def close(session_id: int):
    session_obj = db.session.get(AttendanceSession, session_id) or abort(404)
    close_session(session_obj, actor=current_user, reason="görevli tarafından")
    flash("Oturum kapatıldı. Eksik kayıtlar 'Yok' olarak tamamlandı.", "info")
    return redirect(url_for("staff.session_detail", session_id=session_obj.id))


# --------------------------------------------------------------------------- #
# Oturum listesi ve detay
# --------------------------------------------------------------------------- #
@staff_bp.route("/oturumlar")
def sessions():
    page = request.args.get("page", 1, type=int)
    pagination = (
        AttendanceSession.query.order_by(
            AttendanceSession.session_date.desc(), AttendanceSession.opened_at.desc()
        ).paginate(page=page, per_page=15, error_out=False)
    )
    return render_template("staff/sessions.html", pagination=pagination)


@staff_bp.route("/oturum/<int:session_id>")
def session_detail(session_id: int):
    session_obj = db.session.get(AttendanceSession, session_id) or abort(404)
    if session_obj.is_open:
        ensure_records(session_obj)
        db.session.commit()

    status_filter = request.args.get("durum", "")
    query = (
        AttendanceRecord.query.filter_by(session_id=session_obj.id)
        .join(AttendanceRecord.student)
        .order_by(db.text("users.full_name"))
    )
    if status_filter in STATUS_LABELS:
        query = query.filter(AttendanceRecord.status == status_filter)

    return render_template(
        "staff/session_detail.html",
        session=session_obj,
        records=query.all(),
        summary=session_obj.summary(),
        status_filter=status_filter,
    )


@staff_bp.route("/kayit/<int:record_id>/duzenle", methods=["GET", "POST"])
def edit_record(record_id: int):
    record = db.session.get(AttendanceRecord, record_id) or abort(404)
    form = RecordEditForm(status=record.status, note=record.note)

    if form.validate_on_submit():
        try:
            update_record_manually(
                record=record,
                status=form.status.data,
                note=form.note.data,
                actor=current_user,
            )
        except AttendanceError as error:
            flash(error.message, "danger")
        else:
            flash(
                f"{record.student.full_name} için kayıt güncellendi "
                f"({record.status_label}).",
                "success",
            )
            return redirect(
                url_for("staff.session_detail", session_id=record.session_id)
            )

    return render_template("staff/edit_record.html", form=form, record=record)


@staff_bp.route("/kayit/<int:record_id>/hizli/<status>", methods=["POST"])
def quick_mark(record_id: int, status: str):
    """Listeden tek tıkla durum değiştirme."""
    record = db.session.get(AttendanceRecord, record_id) or abort(404)
    if status not in STATUS_LABELS:
        abort(400)
    update_record_manually(
        record=record, status=status, note=record.note, actor=current_user
    )
    flash(
        f"{record.student.full_name}: {record.status_label} olarak işaretlendi.",
        "success",
    )
    return redirect(
        request.referrer or url_for("staff.session_detail", session_id=record.session_id)
    )


# --------------------------------------------------------------------------- #
# İzin / rapor kayıtları
# --------------------------------------------------------------------------- #
@staff_bp.route("/izinler", methods=["GET", "POST"])
def leaves():
    form = LeaveForm()
    form.student_id.choices = [
        (s.id, f"{s.full_name} ({s.student_no or s.username})")
        for s in active_students()
    ]

    if form.validate_on_submit():
        leave = Leave(
            student_id=form.student_id.data,
            leave_type=form.leave_type.data,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            note=(form.note.data or "").strip() or None,
            created_by_id=current_user.id,
        )
        db.session.add(leave)
        log_action(
            "leave_create",
            target_type="leave",
            detail=(
                f"{leave.student.full_name if leave.student else leave.student_id} için "
                f"{form.start_date.data} - {form.end_date.data} "
                f"{leave.type_label} kaydı oluşturuldu."
            ),
        )
        db.session.commit()

        # Aynı güne ait açık oturum varsa kaydı hemen güncelle
        affected = 0
        for session_obj in AttendanceSession.query.filter(
            AttendanceSession.session_date.between(leave.start_date, leave.end_date)
        ).all():
            record = AttendanceRecord.query.filter_by(
                session_id=session_obj.id, student_id=leave.student_id
            ).first()
            if record is not None and record.status not in PRESENT_LIKE:
                record.status = leave.mapped_status
                record.note = f"{leave.type_label} kaydı nedeniyle güncellendi."
                record.updated_by_id = current_user.id
                record.updated_at = now()
                affected += 1
        if affected:
            db.session.commit()

        flash(
            f"İzin kaydı eklendi. {affected} yoklama kaydı güncellendi.", "success"
        )
        return redirect(url_for("staff.leaves"))

    upcoming = (
        Leave.query.filter(Leave.end_date >= date.today() - timedelta(days=30))
        .order_by(Leave.start_date.desc())
        .all()
    )
    return render_template("staff/leaves.html", form=form, leaves=upcoming)


@staff_bp.route("/izin/<int:leave_id>/sil", methods=["POST"])
def delete_leave(leave_id: int):
    leave = db.session.get(Leave, leave_id) or abort(404)
    detail = (
        f"{leave.student.full_name} ({leave.start_date} - {leave.end_date}) "
        f"{leave.type_label} kaydı silindi."
    )
    db.session.delete(leave)
    log_action("leave_delete", target_type="leave", target_id=leave_id, detail=detail)
    db.session.commit()
    flash("İzin kaydı silindi.", "info")
    return redirect(url_for("staff.leaves"))


# --------------------------------------------------------------------------- #
# Öğrenci listesi (görüntüleme)
# --------------------------------------------------------------------------- #
@staff_bp.route("/ogrenciler")
def students():
    query = request.args.get("q", "").strip()
    students_list = active_students()
    if query:
        lowered = query.lower()
        students_list = [
            s
            for s in students_list
            if lowered in s.full_name.lower()
            or lowered in (s.student_no or "").lower()
            or lowered in (s.room_no or "").lower()
        ]
    return render_template("staff/students.html", students=students_list, q=query)


# --------------------------------------------------------------------------- #
# Oturum bazlı rapor indirme
# --------------------------------------------------------------------------- #
@staff_bp.route("/oturum/<int:session_id>/rapor.xlsx")
def session_report_excel(session_id: int):
    session_obj = db.session.get(AttendanceSession, session_id) or abort(404)
    stream = session_excel(session_obj, dorm_name=current_app.config["DORM_NAME"])
    log_action(
        "report_export",
        target_type="session",
        target_id=session_obj.id,
        detail="Oturum raporu Excel olarak indirildi.",
        commit=True,
    )
    return send_file(
        stream,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"yoklama_{session_obj.session_date:%Y%m%d}_{session_obj.id}.xlsx",
    )


@staff_bp.route("/oturum/<int:session_id>/rapor.pdf")
def session_report_pdf(session_id: int):
    session_obj = db.session.get(AttendanceSession, session_id) or abort(404)
    stream = session_pdf(session_obj, dorm_name=current_app.config["DORM_NAME"])
    log_action(
        "report_export",
        target_type="session",
        target_id=session_obj.id,
        detail="Oturum raporu PDF olarak indirildi.",
        commit=True,
    )
    return send_file(
        stream,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"yoklama_{session_obj.session_date:%Y%m%d}_{session_obj.id}.pdf",
    )
