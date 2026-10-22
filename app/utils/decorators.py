"""Rol tabanlı yetkilendirme yardımcıları."""
from functools import wraps

from flask import abort, flash, redirect, request, url_for
from flask_login import current_user

from ..models import ROLE_ADMIN, ROLE_STAFF


def role_required(*roles):
    """Yalnızca verilen rollerin erişebileceği görünümler için dekoratör."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("Devam etmek için giriş yapın.", "warning")
                return redirect(url_for("auth.login", next=request.full_path))
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def staff_required(view):
    """Yurt görevlisi veya yönetici."""
    return role_required(ROLE_STAFF, ROLE_ADMIN)(view)


def admin_required(view):
    """Yalnızca yönetici."""
    return role_required(ROLE_ADMIN)(view)
