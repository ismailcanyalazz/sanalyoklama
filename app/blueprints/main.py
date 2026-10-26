"""Genel sayfalar ve rol bazlı yönlendirme."""
from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for("admin.dashboard"))
        if current_user.is_staff:
            return redirect(url_for("staff.dashboard"))
    # Öğrenciler giriş yapmaz; karşılama sayfasından yoklama akışına geçerler.
    return render_template("index.html")


@main_bp.route("/hakkinda")
def about():
    return render_template("about.html")


@main_bp.route("/saglik")
def healthcheck():
    """Bulut servislerinin uygulamanın ayakta olup olmadığını kontrolü için."""
    return {"status": "ok"}
