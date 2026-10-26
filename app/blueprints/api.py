"""Görevli ekranı için QR kod üretimi ve canlı durum uç noktaları (JSON/PNG).

Öğrenci tarafındaki okutma akışı bu modülde değil, blueprints/scan.py
içindedir (öğrenciler sisteme giriş yapmadığı için giriş gerektirmez).
"""
from io import BytesIO

import qrcode
from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    make_response,
    request,
    send_file,
    url_for,
)
from qrcode.constants import ERROR_CORRECT_M

from ..extensions import db
from ..models import PRESENT_LIKE, AttendanceSession
from ..utils.decorators import staff_required
from ..utils.security import (
    build_scan_payload,
    seconds_until_refresh,
    totp,
)

api_bp = Blueprint("api", __name__)


# --------------------------------------------------------------------------- #
# Yardımcılar
# --------------------------------------------------------------------------- #
def _get_session_or_404(session_id: int) -> AttendanceSession:
    session_obj = db.session.get(AttendanceSession, session_id)
    if session_obj is None:
        abort(404)
    return session_obj


def scan_url(session_id: int, code: str) -> str:
    """QR kodun içine yazılacak tam adres.

    PUBLIC_BASE_URL tanımlıysa o kullanılır; böylece panel "localhost" ile
    açılsa bile QR, telefondan erişilebilen adresi gösterir.
    """
    path = url_for("scan.identify", session_id=session_id, code=code)
    base = current_app.config.get("PUBLIC_BASE_URL")
    if base:
        return f"{base}{path}"
    return url_for("scan.identify", session_id=session_id, code=code, _external=True)


def _current_code(session_obj: AttendanceSession) -> str:
    return totp(session_obj.secret, step=session_obj.refresh_seconds)


# --------------------------------------------------------------------------- #
# Görevli tarafı: dinamik kod ve QR görüntüsü
# --------------------------------------------------------------------------- #
@api_bp.route("/api/oturum/<int:session_id>/kod")
@staff_required
def session_code(session_id: int):
    """Ekranda gösterilen QR kodun güncel içeriğini döndürür."""
    session_obj = _get_session_or_404(session_id)
    if not session_obj.is_open:
        return jsonify(
            {
                "is_open": False,
                "message": "Oturum kapandı.",
                "seconds_left": 0,
            }
        )
    code = _current_code(session_obj)
    return jsonify(
        {
            "is_open": True,
            "session_id": session_obj.id,
            "code": code,
            "payload": build_scan_payload(session_obj.id, code),
            "link": scan_url(session_obj.id, code),
            "refresh_seconds": session_obj.refresh_seconds,
            "refresh_in": seconds_until_refresh(session_obj.refresh_seconds),
            "seconds_left": session_obj.seconds_left,
            "qr_url": url_for("api.session_qr", session_id=session_obj.id),
        }
    )


@api_bp.route("/api/oturum/<int:session_id>/qr.png")
@staff_required
def session_qr(session_id: int):
    """Güncel kodu içeren QR görüntüsünü PNG olarak üretir."""
    session_obj = _get_session_or_404(session_id)
    if not session_obj.is_open:
        abort(410)  # Gone

    code = _current_code(session_obj)
    # QR içeriği: telefonun kamerasıyla okutulduğunda açılan tam adres.
    # Bu adres kodu doğrular ve öğrenciye numara + ad soyad formunu gösterir.
    content = scan_url(session_obj.id, code)

    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(content)
    qr.make(fit=True)
    image = qr.make_image(fill_color="#10233f", back_color="white")

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    response = make_response(send_file(buffer, mimetype="image/png"))
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@api_bp.route("/api/oturum/<int:session_id>/durum")
@staff_required
def session_state(session_id: int):
    """Görevli ekranındaki canlı listenin beslenmesi için anlık durum."""
    session_obj = _get_session_or_404(session_id)
    summary = session_obj.summary()
    records = sorted(
        session_obj.records, key=lambda r: (r.status not in PRESENT_LIKE, r.student.full_name)
    )
    return jsonify(
        {
            "is_open": session_obj.is_open,
            "seconds_left": session_obj.seconds_left,
            "summary": summary,
            "records": [
                {
                    "id": r.id,
                    "student": r.student.full_name,
                    "student_no": r.student.student_no or "-",
                    "room_no": r.student.room_no or "-",
                    "status": r.status,
                    "status_label": r.status_label,
                    "badge": r.status_badge,
                    "method": r.method_label,
                    "marked_at": r.marked_at.strftime("%H:%M:%S")
                    if r.marked_at
                    else "-",
                    "note": r.note or "",
                }
                for r in records
            ],
        }
    )


@api_bp.after_request
def no_store(response):
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response
