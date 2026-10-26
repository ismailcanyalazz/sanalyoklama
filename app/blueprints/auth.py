"""Kimlik doğrulama: giriş, çıkış, parola değiştirme."""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import or_

from ..extensions import db
from ..forms import ChangePasswordForm, LoginForm
from ..models import User, now
from ..utils.audit import log_action

auth_bp = Blueprint("auth", __name__)


def _safe_next(target: str | None) -> str:
    """Açık yönlendirme (open redirect) açığını engeller."""
    if not target or not target.startswith("/") or target.startswith("//"):
        return url_for("main.index")
    return target


@auth_bp.route("/giris", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    form = LoginForm()
    if form.validate_on_submit():
        identifier = form.username.data.strip()
        user = User.query.filter(
            or_(User.username == identifier, User.student_no == identifier)
        ).first()

        # Öğrenciler sisteme giriş yapmaz; yoklama için QR kodu okutmaları yeterli.
        if user is not None and user.is_student:
            log_action(
                "login_blocked",
                detail=f"Öğrenci hesabı ile giriş denemesi: {identifier}",
                commit=True,
            )
            flash(
                "Öğrenciler sisteme giriş yapmaz. Yoklama için yurt görevlisinin "
                "ekranındaki QR kodu okutmanız yeterlidir.",
                "info",
            )
            return render_template("auth/login.html", form=form), 403

        if user is None or not user.check_password(form.password.data):
            log_action(
                "login_failed",
                detail=f"Başarısız giriş denemesi: {identifier}",
                commit=True,
            )
            flash("Kullanıcı adı veya parola hatalı.", "danger")
            return render_template("auth/login.html", form=form), 401

        if not user.is_active_account:
            flash("Hesabınız pasif durumda. Yurt yönetimine başvurun.", "warning")
            return render_template("auth/login.html", form=form), 403

        login_user(user, remember=bool(form.remember_me.data))
        user.last_login_at = now()
        log_action("login", target_type="user", target_id=user.id,
                   detail=f"{user.full_name} giriş yaptı.", user=user)
        db.session.commit()
        flash(f"Hoş geldiniz, {user.full_name}.", "success")
        return redirect(_safe_next(request.args.get("next")))

    return render_template("auth/login.html", form=form)


@auth_bp.route("/cikis")
@login_required
def logout():
    log_action("logout", target_type="user", target_id=current_user.id,
               detail=f"{current_user.full_name} çıkış yaptı.", commit=True)
    logout_user()
    flash("Çıkış yapıldı.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/profil", methods=["GET", "POST"])
@login_required
def profile():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("Mevcut parolanız hatalı.", "danger")
        else:
            current_user.set_password(form.new_password.data)
            log_action(
                "password_change",
                target_type="user",
                target_id=current_user.id,
                detail="Kullanıcı kendi parolasını değiştirdi.",
            )
            db.session.commit()
            flash("Parolanız güncellendi.", "success")
            return redirect(url_for("auth.profile"))
    return render_template("auth/profile.html", form=form)
