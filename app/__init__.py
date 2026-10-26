"""Uygulama fabrikası (application factory).

Kullanım:
    from app import create_app
    app = create_app()
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

import click
from flask import Flask, render_template, request
from flask_login import current_user

from config import get_config
from .extensions import csrf, db, login_manager


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(get_config(config_name))

    # .env dosyası varsa yükle (python-dotenv kuruluysa)
    try:  # pragma: no cover
        from dotenv import load_dotenv

        load_dotenv(Path(app.root_path).parent / ".env")
    except ImportError:
        pass

    # Ters vekil sunucu arkasında (Vercel) isteğin gerçek şeması ve alan adı
    # X-Forwarded-* başlıklarından okunur; aksi hâlde QR kodun içine yazılan
    # adres "http://" ile üretilir.
    if app.config.get("TRUST_PROXY"):
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Okutma denemelerinin hız sınırını yapılandırmadan al
    from .utils.security import scan_limiter

    scan_limiter.limit = int(app.config["SCAN_RATE_LIMIT"])

    _register_blueprints(app)
    _register_error_handlers(app)
    _register_context(app)
    _register_hooks(app)
    _register_cli(app)
    _configure_logging(app)
    _warn_about_secret_key(app)
    _bootstrap_database(app)

    return app


def _warn_about_secret_key(app: Flask) -> None:
    """Yayında varsayılan gizli anahtar kullanılıyorsa uyarır."""
    default_key = "gelistirme-ortami-icin-gizli-anahtar"
    if app.config["SECRET_KEY"] == default_key and not app.debug:
        app.logger.warning(
            "SECRET_KEY ortam değişkeni tanımlanmamış; yayında mutlaka "
            "uzun ve rastgele bir değer tanımlayın."
        )


def _bootstrap_database(app: Flask) -> None:
    """Sunucusuz dağıtımlarda tabloları ve ilk yönetici hesabını hazırlar.

    Vercel gibi ortamlarda `flask init-db` çalıştırılamadığı için, AUTO_INIT_DB
    açıkken uygulama ayağa kalkarken şema bir kez oluşturulur. İşlem
    tekrarlanabilirdir (var olan tablolara dokunmaz).
    """
    if not app.config.get("AUTO_INIT_DB"):
        return
    from .models import ROLE_ADMIN, User

    try:
        with app.app_context():
            db.create_all()
            username = app.config["ADMIN_USERNAME"]
            if User.query.filter_by(username=username).first() is None:
                admin = User(
                    username=username,
                    full_name=app.config["ADMIN_FULL_NAME"],
                    role=ROLE_ADMIN,
                )
                admin.set_password(app.config["ADMIN_PASSWORD"])
                db.session.add(admin)
                db.session.commit()
                app.logger.info("İlk yönetici hesabı oluşturuldu: %s", username)
    except Exception as error:  # pragma: no cover - dağıtım ortamına özel
        db.session.rollback()
        app.logger.warning("Veritabanı hazırlanamadı: %s", error)


# --------------------------------------------------------------------------- #
def _register_blueprints(app: Flask) -> None:
    from .blueprints.admin import admin_bp
    from .blueprints.api import api_bp
    from .blueprints.auth import auth_bp
    from .blueprints.main import main_bp
    from .blueprints.scan import scan_bp
    from .blueprints.staff import staff_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    # Öğrenci tarafı: giriş gerektirmeyen yoklama akışı
    app.register_blueprint(scan_bp)
    app.register_blueprint(staff_bp, url_prefix="/gorevli")
    app.register_blueprint(admin_bp, url_prefix="/yonetim")
    app.register_blueprint(api_bp)


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(403)
    def forbidden(error):  # noqa: ANN001
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(error):  # noqa: ANN001
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(error):  # noqa: ANN001
        db.session.rollback()
        app.logger.exception("Sunucu hatası: %s", error)
        return render_template("errors/500.html"), 500


def _register_context(app: Flask) -> None:
    from .models import ROLE_LABELS, STATUS_BADGES, STATUS_LABELS, now

    @app.context_processor
    def inject_globals():
        return {
            "APP_NAME": app.config["APP_NAME"],
            "DORM_NAME": app.config["DORM_NAME"],
            "STATUS_LABELS": STATUS_LABELS,
            "STATUS_BADGES": STATUS_BADGES,
            "ROLE_LABELS": ROLE_LABELS,
            "current_time": now(),
        }

    @app.template_filter("dt")
    def format_datetime(value, fmt: str = "%d.%m.%Y %H:%M"):
        return value.strftime(fmt) if value else "-"

    @app.template_filter("d")
    def format_date(value, fmt: str = "%d.%m.%Y"):
        return value.strftime(fmt) if value else "-"

    @app.template_filter("t")
    def format_time(value, fmt: str = "%H:%M"):
        return value.strftime(fmt) if value else "-"


def _register_hooks(app: Flask) -> None:
    from .services import autoclose_expired_sessions

    @app.before_request
    def close_expired_sessions():
        """Süresi dolan yoklama oturumlarını otomatik kapatır."""
        if request.endpoint in (None, "static") or request.path.startswith("/static"):
            return
        try:
            autoclose_expired_sessions()
        except Exception:  # veritabanı henüz hazır değilse sessizce geç
            db.session.rollback()

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response


def _configure_logging(app: Flask) -> None:
    """Günlükleri dosyaya yazar; salt okunur ortamlarda konsola düşer."""
    formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
    app.logger.setLevel(logging.INFO)

    from config import DATA_DIR

    try:
        handler = RotatingFileHandler(
            DATA_DIR / "uygulama.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError:  # pragma: no cover - sunucusuz/salt okunur dosya sistemi
        if not app.logger.handlers:
            app.logger.addHandler(logging.StreamHandler())
        return

    handler.setFormatter(formatter)
    handler.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) for h in app.logger.handlers):
        app.logger.addHandler(handler)


# --------------------------------------------------------------------------- #
# CLI komutları
# --------------------------------------------------------------------------- #
def _register_cli(app: Flask) -> None:
    from .models import ROLE_ADMIN, User

    @app.cli.command("init-db")
    def init_db():
        """Tabloları oluşturur ve ilk yönetici hesabını ekler."""
        db.create_all()
        username = app.config["ADMIN_USERNAME"]
        if User.query.filter_by(username=username).first() is None:
            admin = User(
                username=username,
                full_name=app.config["ADMIN_FULL_NAME"],
                role=ROLE_ADMIN,
            )
            admin.set_password(app.config["ADMIN_PASSWORD"])
            db.session.add(admin)
            db.session.commit()
            click.echo(
                f"Yönetici hesabı oluşturuldu: {username} / "
                f"{app.config['ADMIN_PASSWORD']}"
            )
        else:
            click.echo("Yönetici hesabı zaten mevcut.")
        click.echo("Veritabanı hazır.")

    @app.cli.command("seed-demo")
    @click.option("--students", default=12, help="Oluşturulacak örnek öğrenci sayısı.")
    @click.option("--days", default=10, help="Geçmişe dönük örnek yoklama günü sayısı.")
    def seed_demo(students: int, days: int):
        """Sunum/test için örnek veri üretir."""
        from seed import run_seed

        run_seed(students=students, days=days)

    @app.cli.command("reset-password")
    @click.argument("username")
    @click.argument("new_password")
    def reset_password(username: str, new_password: str):
        """Bir kullanıcının parolasını sıfırlar."""
        user = User.query.filter_by(username=username).first()
        if user is None:
            click.echo(f"Kullanıcı bulunamadı: {username}")
            return
        user.set_password(new_password)
        db.session.commit()
        click.echo(f"{username} kullanıcısının parolası güncellendi.")
