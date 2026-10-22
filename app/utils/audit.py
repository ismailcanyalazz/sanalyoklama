"""Tüm kritik işlemleri zaman damgasıyla günlüğe yazar."""
from flask import has_request_context, request
from flask_login import current_user

from ..extensions import db
from ..models import AuditLog


def client_ip() -> str | None:
    if not has_request_context():
        return None
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.remote_addr or "")[:64] or None


def user_agent() -> str | None:
    if not has_request_context():
        return None
    return (request.headers.get("User-Agent") or "")[:255] or None


def log_action(action: str, *, target_type: str | None = None,
               target_id: int | None = None, detail: str | None = None,
               user=None, commit: bool = False) -> AuditLog:
    """Günlük kaydı oluşturur.

    commit=True verilmezse kayıt, çağıran işlemin transaction'ı ile birlikte
    kaydedilir (tek bir atomik işlem).
    """
    actor = user
    if actor is None and current_user and getattr(current_user, "is_authenticated", False):
        actor = current_user

    entry = AuditLog(
        user_id=getattr(actor, "id", None),
        actor_name=getattr(actor, "full_name", None) or "Anonim",
        actor_role=getattr(actor, "role", None),
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        ip_address=client_ip(),
        user_agent=user_agent(),
    )
    db.session.add(entry)
    if commit:
        db.session.commit()
    return entry
