"""QR kod üretimi ve yoklama okutma uç noktaları (JSON/PNG)."""
from io import BytesIO

import qrcode
from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from qrcode.constants import ERROR_CORRECT_M

from ..extensions import db
from ..models import PRESENT_LIKE, AttendanceSession
from ..services import AttendanceError, mark_attendance_by_code
from ..utils.audit import client_ip
from ..utils.decorators import staff_required
from ..utils.security import (
    DEVICE_COOKIE_NAME,
    build_scan_payload,
    new_device_id,
    parse_scan_payload,
    scan_limiter,
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


def _device_id() -> str:
    return request.cookies.get(DEVICE_COOKIE_NAME) or new_device_id()


def _attach_device_cookie(response, device_id: str):
    response.set_cookie(
        DEVICE_COOKIE_NAME,
        device_id,
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        samesite="Lax",
        secure=current_app.config.get("SESSION_COOKIE_SECURE", False),
    )
    return response


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
            "link": url_for(
                "api.scan_link", session_id=session_obj.id, code=code, _external=True
            ),
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
    # QR içeriği: telefonun kendi kamerasıyla okutulduğunda da çalışan tam adres
    content = url_for(
        "api.scan_link", session_id=session_obj.id, code=code, _external=True
    )

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


# --------------------------------------------------------------------------- #
# Öğrenci tarafı: okutma
# --------------------------------------------------------------------------- #
@api_bp.route("/api/yoklama/okut", methods=["POST"])
@login_required
def scan():
    """Tarayıcı içi QR okuyucudan (html5-qrcode) gelen kodu işler."""
    if not scan_limiter.allow(client_ip() or "bilinmeyen"):
        return (
            jsonify({"ok": False, "code": "rate_limit",
                     "message": "Çok fazla deneme yapıldı. Lütfen bekleyin."}),
            429,
        )

    data = request.get_json(silent=True) or request.form
    payload = (data.get("payload") or "").strip()
    session_id = data.get("session_id")
    code = (data.get("code") or "").strip()

    if payload:
        parsed_id, parsed_code = parse_scan_payload(payload)
        session_id = parsed_id if parsed_id is not None else session_id
        code = parsed_code or code

    try:
        session_id = int(session_id)
    except (TypeError, ValueError):
        return (
            jsonify({"ok": False, "code": "invalid_payload",
                     "message": "QR kod okunamadı. Tekrar deneyin."}),
            400,
        )

    device_id = _device_id()
    try:
        record = mark_attendance_by_code(
            student=current_user,
            session_id=session_id,
            code=code,
            device_id=device_id,
        )
    except AttendanceError as error:
        response = jsonify(
            {"ok": False, "code": error.code, "message": error.message}
        )
        return _attach_device_cookie(response, device_id), 400

    response = jsonify(
        {
            "ok": True,
            "message": "Yoklamanız alındı. Teşekkürler.",
            "status": record.status_label,
            "marked_at": record.marked_at.strftime("%d.%m.%Y %H:%M:%S"),
            "session_title": record.session.title,
        }
    )
    return _attach_device_cookie(response, device_id)


@api_bp.route("/yoklama/<int:session_id>/<code>")
def scan_link(session_id: int, code: str):
    """Telefonun kendi kamerası ile okutulduğunda açılan adres.

    Oturum açılmamışsa giriş sayfasına yönlendirir; giriş yapıldıktan sonra
    kullanıcı bu adrese geri döner.
    """
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login", next=request.path))

    if not current_user.is_student:
        return render_template(
            "student/scan_result.html",
            ok=False,
            message="Yalnızca öğrenci hesapları yoklama verebilir.",
            record=None,
        ), 403

    device_id = _device_id()
    try:
        record = mark_attendance_by_code(
            student=current_user,
            session_id=session_id,
            code=code,
            device_id=device_id,
        )
    except AttendanceError as error:
        response = make_response(
            render_template(
                "student/scan_result.html",
                ok=False,
                message=error.message,
                record=None,
            )
        )
        return _attach_device_cookie(response, device_id)

    response = make_response(
        render_template(
            "student/scan_result.html",
            ok=True,
            message="Yoklamanız başarıyla alındı.",
            record=record,
        )
    )
    return _attach_device_cookie(response, device_id)


@api_bp.route("/api/cihaz")
@login_required
def device_info():
    """Tarayıcıya kalıcı bir cihaz kimliği yerleştirir (ilk ziyarette)."""
    device_id = _device_id()
    response = jsonify({"device_id": device_id})
    return _attach_device_cookie(response, device_id)


# Tarayıcı içi okuyucu, CSRF başlığını JS ile gönderir; muafiyet tanımlanmaz.
@api_bp.after_request
def no_store(response):
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response
