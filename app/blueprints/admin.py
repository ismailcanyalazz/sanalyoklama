"""Yönetici paneli: grafikli özet, kullanıcı yönetimi, günlük kayıtları, raporlar."""
import re
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
from ..forms import AdminPasswordForm, StudentBulkForm, StudentForm, UserForm
from ..models import (
    ROLE_ADMIN,
    ROLE_LABELS,
    ROLE_STUDENT,
    STATUS_LABELS,
    AttendanceRecord,
    AttendanceSession,
    AuditLog,
    Leave,
    User,
    today,
)
from ..services import (
    active_students,
    dashboard_data,
    student_statistics,
)
from ..utils.audit import log_action
from ..utils.decorators import admin_required, staff_required
from ..utils.reports import build_matrix, period_excel, period_pdf
from ..utils.text import normalize_student_no

admin_bp = Blueprint("admin", __name__)


# --------------------------------------------------------------------------- #
# Yardımcılar
# --------------------------------------------------------------------------- #
def _parse_range() -> tuple[date, date]:
    """Rapor filtresindeki tarih aralığını okur (varsayılan: son 30 gün)."""
    today_date = today()
    default_start = today_date - timedelta(days=29)

    def _parse(name: str, fallback: date) -> date:
        raw = request.args.get(name, "")
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return fallback

    start = _parse("baslangic", default_start)
    end = _parse("bitis", today_date)
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
    """Görevli / yönetici hesabı oluşturur (öğrenciler için student_create)."""
    form = UserForm()
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data.strip()).first():
            flash("Bu kullanıcı adı zaten kayıtlı.", "danger")
        elif not form.password.data:
            flash("Yeni hesap için parola zorunludur.", "danger")
        else:
            user = User(
                username=form.username.data.strip(),
                full_name=form.full_name.data.strip(),
                role=form.role.data,
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
    if user.is_student:
        return redirect(url_for("admin.student_edit", user_id=user.id))

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


# --------------------------------------------------------------------------- #
# Öğrenci kayıtları (okul numarası + ad soyad)
# --------------------------------------------------------------------------- #
def _student_no_taken(student_no: str, *, exclude_id: int | None = None) -> bool:
    """Numara başka bir öğrenciye ait mi? (boşluk/ayraç farkları da sayılır)"""
    cleaned = normalize_student_no(student_no)
    for candidate in User.query.filter_by(role=ROLE_STUDENT).all():
        if exclude_id is not None and candidate.id == exclude_id:
            continue
        if normalize_student_no(candidate.student_no) == cleaned:
            return True
    return False


@admin_bp.route("/ogrenci/yeni", methods=["GET", "POST"])
@admin_required
def student_create():
    """Öğrenciyi okul numarası ve ad soyad ile kaydeder (parola yok)."""
    form = StudentForm()
    if form.validate_on_submit():
        student_no = normalize_student_no(form.student_no.data)
        if _student_no_taken(student_no):
            flash("Bu okul numarası zaten kayıtlı.", "danger")
        elif User.query.filter_by(username=student_no).first():
            flash("Bu numara başka bir hesapta kullanılıyor.", "danger")
        else:
            student = User(
                # Kullanıcı adı alanı veritabanında zorunlu; öğrencide okul
                # numarası ile aynı tutulur (giriş için kullanılmaz).
                username=student_no,
                student_no=student_no,
                full_name=form.full_name.data.strip(),
                role=ROLE_STUDENT,
                room_no=(form.room_no.data or "").strip() or None,
                department=(form.department.data or "").strip() or None,
                class_year=(form.class_year.data or "").strip() or None,
                phone=(form.phone.data or "").strip() or None,
                email=(form.email.data or "").strip() or None,
                is_active_account=bool(form.is_active_account.data),
            )
            student.set_password(None)  # öğrenci hesapları parolasızdır
            db.session.add(student)
            log_action(
                "student_create",
                target_type="user",
                detail=f"Öğrenci eklendi: {student.full_name} ({student_no}).",
            )
            db.session.commit()
            flash(f"{student.full_name} ({student_no}) eklendi.", "success")
            return redirect(url_for("admin.users", rol=ROLE_STUDENT))

    return render_template("admin/student_form.html", form=form, student=None)


@admin_bp.route("/ogrenci/<int:user_id>/duzenle", methods=["GET", "POST"])
@admin_required
def student_edit(user_id: int):
    student = db.session.get(User, user_id) or abort(404)
    if not student.is_student:
        abort(404)

    form = StudentForm(obj=student)
    if form.validate_on_submit():
        student_no = normalize_student_no(form.student_no.data)
        if _student_no_taken(student_no, exclude_id=student.id):
            flash("Bu okul numarası başka bir öğrencide kullanılıyor.", "danger")
        else:
            previous_no = student.student_no
            student.student_no = student_no
            # Kullanıcı adı numara ile birlikte güncellenir (giriş için
            # kullanılmaz; yalnızca benzersizlik içindir).
            if student.username == previous_no or not student.username:
                student.username = student_no
            student.full_name = form.full_name.data.strip()
            student.room_no = (form.room_no.data or "").strip() or None
            student.department = (form.department.data or "").strip() or None
            student.class_year = (form.class_year.data or "").strip() or None
            student.phone = (form.phone.data or "").strip() or None
            student.email = (form.email.data or "").strip() or None
            student.is_active_account = bool(form.is_active_account.data)
            log_action(
                "student_update",
                target_type="user",
                target_id=student.id,
                detail=f"Öğrenci kaydı güncellendi: {student.full_name} ({student_no}).",
            )
            db.session.commit()
            flash("Öğrenci kaydı güncellendi.", "success")
            return redirect(url_for("admin.users", rol=ROLE_STUDENT))

    return render_template("admin/student_form.html", form=form, student=student)


@admin_bp.route("/ogrenci/liste-ekle", methods=["GET", "POST"])
@admin_required
def student_bulk():
    """Çok sayıda öğrenciyi 'numara ; ad soyad' satırlarıyla ekler."""
    form = StudentBulkForm()
    added: list[str] = []
    skipped: list[str] = []

    if form.validate_on_submit():
        for line_no, raw_line in enumerate(form.rows.data.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            parts = [p.strip() for p in re.split(r"[;,\t]+", line) if p.strip()]
            if len(parts) < 2:
                skipped.append(f"{line_no}. satır: numara ve ad soyad ayrılamadı")
                continue

            student_no = normalize_student_no(parts[0])
            full_name = parts[1]
            room_no = parts[2] if len(parts) > 2 else None

            if not student_no or len(full_name.split()) < 2:
                skipped.append(f"{line_no}. satır: eksik bilgi ({line})")
                continue
            if _student_no_taken(student_no) or User.query.filter_by(
                username=student_no
            ).first():
                skipped.append(f"{line_no}. satır: {student_no} zaten kayıtlı")
                continue

            student = User(
                username=student_no,
                student_no=student_no,
                full_name=full_name,
                role=ROLE_STUDENT,
                room_no=room_no or None,
            )
            student.set_password(None)
            db.session.add(student)
            db.session.flush()
            added.append(f"{student_no} - {full_name}")

        if added:
            log_action(
                "student_bulk_create",
                target_type="user",
                detail=f"Listeyle {len(added)} öğrenci eklendi.",
            )
        db.session.commit()

        if added:
            flash(f"{len(added)} öğrenci eklendi.", "success")
        if skipped:
            flash(
                "Eklenemeyen satırlar: " + "; ".join(skipped[:10])
                + (" …" if len(skipped) > 10 else ""),
                "warning",
            )
        if added and not skipped:
            return redirect(url_for("admin.users", rol=ROLE_STUDENT))

    return render_template(
        "admin/student_bulk.html", form=form, added=added, skipped=skipped
    )


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


# --------------------------------------------------------------------------- #
# Parola sıfırlama ve hesap silme
# --------------------------------------------------------------------------- #
@admin_bp.route("/kullanici/<int:user_id>/parola", methods=["GET", "POST"])
@admin_required
def user_password(user_id: int):
    """Yönetici, bir görevli/yönetici hesabının parolasını sıfırlar."""
    user = db.session.get(User, user_id) or abort(404)
    if user.is_student:
        flash("Öğrenci hesaplarının parolası yoktur; öğrenciler giriş yapmaz.", "info")
        return redirect(url_for("admin.users", rol=ROLE_STUDENT))

    form = AdminPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.new_password.data)
        log_action(
            "password_reset",
            target_type="user",
            target_id=user.id,
            detail=f"{user.full_name} hesabının parolası yönetici tarafından sıfırlandı.",
        )
        db.session.commit()
        flash(f"{user.full_name} hesabının parolası güncellendi.", "success")
        return redirect(url_for("admin.users"))

    return render_template("admin/password_form.html", form=form, user=user)


def _detach_user_references(user: User) -> None:
    """Silinecek kullanıcıya işaret eden kayıtları koparır.

    Günlük kayıtları silinmez; yalnızca kullanıcı bağlantısı boşaltılır
    (işlemi yapanın adı `actor_name` alanında metin olarak zaten saklı).
    """
    AuditLog.query.filter_by(user_id=user.id).update(
        {"user_id": None}, synchronize_session=False
    )
    AttendanceRecord.query.filter_by(updated_by_id=user.id).update(
        {"updated_by_id": None}, synchronize_session=False
    )


@admin_bp.route("/kullanici/<int:user_id>/sil", methods=["POST"])
@admin_required
def user_delete(user_id: int):
    """Görevli / yönetici hesabını siler."""
    user = db.session.get(User, user_id) or abort(404)

    if user.is_student:
        return redirect(url_for("admin.student_delete", user_id=user.id), code=307)

    if user.id == current_user.id:
        flash("Kendi hesabınızı silemezsiniz.", "warning")
        return redirect(url_for("admin.users"))

    if user.is_admin and User.query.filter_by(
        role=ROLE_ADMIN, is_active_account=True
    ).count() <= 1:
        flash("Sistemdeki tek yönetici hesabı silinemez.", "danger")
        return redirect(url_for("admin.users"))

    # Oturum veya izin kaydı açmış bir görevli silinirse geçmiş yoklamaların
    # sahibi kaybolur; bu yüzden silme engellenir, pasife alma önerilir.
    session_count = AttendanceSession.query.filter_by(created_by_id=user.id).count()
    leave_count = Leave.query.filter_by(created_by_id=user.id).count()
    if session_count or leave_count:
        flash(
            f"{user.full_name} silinemez: {session_count} yoklama oturumu ve "
            f"{leave_count} izin kaydı bu hesaba bağlı. Geçmiş kayıtların "
            "bozulmaması için hesabı silmek yerine pasife alın.",
            "danger",
        )
        return redirect(url_for("admin.users"))

    name, role_label = user.full_name, user.role_label
    _detach_user_references(user)
    db.session.delete(user)
    log_action(
        "user_delete",
        target_type="user",
        target_id=user_id,
        detail=f"{name} ({role_label}) hesabı silindi.",
    )
    db.session.commit()
    flash(f"{name} silindi.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/ogrenci/<int:user_id>/sil", methods=["POST"])
@admin_required
def student_delete(user_id: int):
    """Öğrenci kaydını ve ona ait yoklama/izin kayıtlarını siler."""
    student = db.session.get(User, user_id) or abort(404)
    if not student.is_student:
        abort(404)

    record_count = AttendanceRecord.query.filter_by(student_id=student.id).count()
    name = student.full_name
    student_no = student.student_no or "-"

    _detach_user_references(student)
    # Öğrencinin yoklama ve izin kayıtları ilişki tanımındaki cascade ile
    # birlikte silinir.
    db.session.delete(student)
    log_action(
        "student_delete",
        target_type="user",
        target_id=user_id,
        detail=(
            f"Öğrenci silindi: {name} ({student_no}); "
            f"{record_count} yoklama kaydı da silindi."
        ),
    )
    db.session.commit()
    flash(
        f"{name} ({student_no}) ve {record_count} yoklama kaydı silindi.", "success"
    )
    return redirect(url_for("admin.users", rol=ROLE_STUDENT))


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
