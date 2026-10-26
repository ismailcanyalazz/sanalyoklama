"""Öğrenci tarafı yoklama akışı (giriş gerektirmez).

Akış
----
1. Görevli bilgisayarının ekranında QR kod sürekli yenilenir.
2. Öğrenci kendi telefonunun kamerasıyla kodu okutur; açılan adres
   /yoklama/<oturum>/<kod> olur.
3. Bu adres kodu doğrular ve öğrenciye okul numarası + ad soyad soran formu
   gösterir. Kod yalnızca bu anda doğrulanır; forma ayrılan süre için
   cihaza bağlı, kısa ömürlü bir "okutma bileti" (imzalı belirteç) verilir.
4. Form gönderildiğinde bilet ve kimlik doğrulanır; numara ile ad soyad
   kayıtla eşleşirse yoklama "Mevcut" olarak işlenir, eşleşmezse reddedilir.

Öğrencinin sisteme kullanıcı adı/parola ile girmesi gerekmez.
"""
from __future__ import annotations

from flask import (
    Blueprint,
    current_app,
    make_response,
    render_template,
    request,
    url_for,
)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..services import (
    AttendanceError,
    get_open_session,
    mark_attendance_by_code,
    resolve_student_identity,
    verify_session_code,
)
from ..utils.audit import client_ip
from ..utils.security import (
    DEVICE_COOKIE_NAME,
    new_device_id,
    parse_scan_payload,
    scan_limiter,
)

scan_bp = Blueprint("scan", __name__)

_TICKET_SALT = "yoklama-okutma-bileti"


# --------------------------------------------------------------------------- #
# Cihaz kimliği
# --------------------------------------------------------------------------- #
def device_id_from_request() -> str:
    return request.cookies.get(DEVICE_COOKIE_NAME) or new_device_id()


def attach_device_cookie(response, device_id: str):
    response.set_cookie(
        DEVICE_COOKIE_NAME,
        device_id,
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        samesite="Lax",
        secure=current_app.config.get("SESSION_COOKIE_SECURE", False),
    )
    return response


# --------------------------------------------------------------------------- #
# Okutma bileti
# --------------------------------------------------------------------------- #
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_TICKET_SALT)


def issue_ticket(session_id: int, device_id: str) -> str:
    """Geçerli kodu okutan cihaza, formu doldurması için bilet verir."""
    return _serializer().dumps({"s": int(session_id), "d": device_id})


def read_ticket(ticket: str, device_id: str) -> int:
    """Bileti doğrular ve ait olduğu oturum numarasını döndürür.

    Bilet, kodu okutan cihaza bağlıdır: bağlantının başkasına iletilmesi
    hâlinde karşı taraftaki tarayıcının çerezi farklı olacağı için bilet
    geçersiz sayılır.
    """
    max_age = int(current_app.config["SCAN_TICKET_MAX_AGE"])
    try:
        data = _serializer().loads(ticket or "", max_age=max_age)
    except SignatureExpired:
        raise AttendanceError(
            "Form çok uzun süre açık kaldı. Lütfen QR kodu yeniden okutun.",
            "ticket_expired",
        )
    except BadSignature:
        raise AttendanceError(
            "Okutma bilgisi geçersiz. Lütfen QR kodu yeniden okutun.",
            "ticket_invalid",
        )

    if not isinstance(data, dict) or data.get("d") != device_id:
        raise AttendanceError(
            "Bu form başka bir cihazda açılmış. Yoklamayı kendi telefonunuzdan "
            "okutarak vermelisiniz.",
            "ticket_device",
        )
    return int(data["s"])


# --------------------------------------------------------------------------- #
# Yardımcılar
# --------------------------------------------------------------------------- #
def _render_result(ok: bool, message: str, record=None, status_code: int = 200):
    response = make_response(
        render_template(
            "yoklama/result.html", ok=ok, message=message, record=record
        ),
        status_code,
    )
    return response


def _rate_limited() -> bool:
    return not scan_limiter.allow(client_ip() or "bilinmeyen")


# --------------------------------------------------------------------------- #
# 1. Adım: QR kodun açtığı adres
# --------------------------------------------------------------------------- #
@scan_bp.route("/yoklama/<int:session_id>/<code>")
def identify(session_id: int, code: str):
    """Kodu doğrular ve numara + ad soyad formunu gösterir."""
    device_id = device_id_from_request()

    try:
        session_obj = verify_session_code(session_id, code)
    except AttendanceError as error:
        return attach_device_cookie(
            _render_result(False, error.message), device_id
        )

    response = make_response(
        render_template(
            "yoklama/identify.html",
            session_obj=session_obj,
            ticket=issue_ticket(session_obj.id, device_id),
            form_minutes=max(
                1, int(current_app.config["SCAN_TICKET_MAX_AGE"]) // 60
            ),
            values={},
            error=None,
        )
    )
    return attach_device_cookie(response, device_id)


# --------------------------------------------------------------------------- #
# 2. Adım: formun gönderilmesi
# --------------------------------------------------------------------------- #
@scan_bp.route("/yoklama/kaydet", methods=["POST"])
def submit():
    """Numara + ad soyad bilgisini doğrular ve yoklamayı işler."""
    device_id = device_id_from_request()

    if _rate_limited():
        return attach_device_cookie(
            _render_result(
                False,
                "Çok fazla deneme yapıldı. Lütfen biraz bekleyip tekrar deneyin.",
                status_code=429,
            ),
            device_id,
        )

    ticket = (request.form.get("ticket") or "").strip()
    student_no = (request.form.get("student_no") or "").strip()
    full_name = (request.form.get("full_name") or "").strip()

    try:
        session_id = read_ticket(ticket, device_id)
        student = resolve_student_identity(student_no, full_name)
        record = mark_attendance_by_code(
            student=student,
            session_id=session_id,
            # Bilet, kodun bu cihazda zaten doğrulandığını kanıtlar.
            code=None,
            device_id=device_id,
            code_already_verified=True,
        )
    except AttendanceError as error:
        # Düzeltilebilir hatalarda formu, girilen değerlerle birlikte geri göster
        if error.code in {"missing_identity", "identity_mismatch"}:
            session_obj = get_open_session()
            if session_obj is not None:
                response = make_response(
                    render_template(
                        "yoklama/identify.html",
                        session_obj=session_obj,
                        ticket=ticket,
                        form_minutes=max(
                            1, int(current_app.config["SCAN_TICKET_MAX_AGE"]) // 60
                        ),
                        values={"student_no": student_no, "full_name": full_name},
                        error=error.message,
                    ),
                    400,
                )
                return attach_device_cookie(response, device_id)
        return attach_device_cookie(
            _render_result(False, error.message, status_code=400), device_id
        )

    return attach_device_cookie(
        _render_result(True, "Yoklamanız başarıyla alındı.", record=record),
        device_id,
    )


# --------------------------------------------------------------------------- #
# Yedek yol: kamera çalışmazsa ekrandaki 6 haneli kodu elle girme
# --------------------------------------------------------------------------- #
@scan_bp.route("/yoklama", methods=["GET", "POST"])
def manual():
    """Kod + numara + ad soyadın tek formda girildiği yedek yol."""
    device_id = device_id_from_request()
    open_session = get_open_session()
    values: dict[str, str] = {}
    error = None

    if request.method == "POST":
        if _rate_limited():
            return attach_device_cookie(
                _render_result(
                    False,
                    "Çok fazla deneme yapıldı. Lütfen biraz bekleyip tekrar deneyin.",
                    status_code=429,
                ),
                device_id,
            )

        raw_code = (request.form.get("code") or "").strip()
        student_no = (request.form.get("student_no") or "").strip()
        full_name = (request.form.get("full_name") or "").strip()
        values = {"code": raw_code, "student_no": student_no, "full_name": full_name}

        session_id = None
        code = raw_code
        # Kutuya tam bağlantı yapıştırılmışsa oturum ve kodu ayrıştır
        parsed_id, parsed_code = parse_scan_payload(raw_code)
        if parsed_id is not None:
            session_id, code = parsed_id, parsed_code or ""
        elif open_session is not None:
            session_id = open_session.id

        if session_id is None:
            error = "Şu anda açık bir yoklama oturumu bulunmuyor."
        else:
            try:
                student = resolve_student_identity(student_no, full_name)
                record = mark_attendance_by_code(
                    student=student,
                    session_id=session_id,
                    code=code,
                    device_id=device_id,
                )
            except AttendanceError as attendance_error:
                error = attendance_error.message
            else:
                return attach_device_cookie(
                    _render_result(
                        True, "Yoklamanız başarıyla alındı.", record=record
                    ),
                    device_id,
                )

    response = make_response(
        render_template(
            "yoklama/manual.html",
            open_session=open_session,
            values=values,
            error=error,
        ),
        400 if error else 200,
    )
    return attach_device_cookie(response, device_id)


@scan_bp.route("/yoklama/cihaz")
def device_info():
    """Tarayıcıya kalıcı cihaz kimliği yerleştirir."""
    device_id = device_id_from_request()
    from flask import jsonify

    response = jsonify({"device_id": device_id, "scan_url": url_for("scan.manual")})
    return attach_device_cookie(response, device_id)
