"""WTForms tabanlı formlar (CSRF koruması Flask-WTF ile sağlanır)."""
from datetime import date

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
    TimeField,
)
from wtforms.validators import (
    DataRequired,
    EqualTo,
    Length,
    Optional,
    Regexp,
    ValidationError,
)

from .models import LEAVE_TYPES, ROLE_ADMIN, ROLE_LABELS, ROLE_STAFF, STATUS_LABELS


class LoginForm(FlaskForm):
    username = StringField(
        "Kullanıcı Adı",
        validators=[DataRequired("Kullanıcı adı zorunludur."), Length(max=64)],
    )
    password = PasswordField(
        "Parola", validators=[DataRequired("Parola zorunludur.")]
    )
    remember_me = BooleanField("Beni hatırla")
    submit = SubmitField("Giriş Yap")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField(
        "Mevcut Parola", validators=[DataRequired("Mevcut parolanızı girin.")]
    )
    new_password = PasswordField(
        "Yeni Parola",
        validators=[
            DataRequired("Yeni parola zorunludur."),
            Length(min=8, message="Parola en az 8 karakter olmalıdır."),
        ],
    )
    confirm_password = PasswordField(
        "Yeni Parola (Tekrar)",
        validators=[EqualTo("new_password", message="Parolalar eşleşmiyor.")],
    )
    submit = SubmitField("Parolayı Güncelle")


class SessionForm(FlaskForm):
    title = StringField(
        "Oturum Başlığı",
        default="Akşam Yoklaması",
        validators=[DataRequired("Başlık zorunludur."), Length(max=160)],
    )
    session_date = DateField(
        "Tarih", default=date.today, validators=[DataRequired("Tarih zorunludur.")]
    )
    start_time = TimeField("Başlangıç Saati", validators=[DataRequired()])
    end_time = TimeField("Bitiş Saati", validators=[DataRequired()])
    refresh_seconds = SelectField(
        "QR Yenileme Süresi",
        choices=[("10", "10 saniye"), ("15", "15 saniye"), ("30", "30 saniye"),
                 ("60", "60 saniye")],
        default="15",
    )
    note = TextAreaField("Not", validators=[Optional(), Length(max=500)])
    submit = SubmitField("Yoklamayı Başlat")

    def validate_end_time(self, field):
        if self.start_time.data and field.data and field.data <= self.start_time.data:
            raise ValidationError("Bitiş saati başlangıçtan sonra olmalıdır.")


class RecordEditForm(FlaskForm):
    status = SelectField(
        "Durum",
        choices=[(key, label) for key, label in STATUS_LABELS.items()],
        validators=[DataRequired()],
    )
    note = TextAreaField(
        "Açıklama", validators=[Optional(), Length(max=500)]
    )
    submit = SubmitField("Kaydet")


class StudentForm(FlaskForm):
    """Öğrenci kaydı: yalnızca okul numarası ve ad soyad zorunludur.

    Öğrenciler sisteme giriş yapmadığı için kullanıcı adı ve parola alanı
    yoktur; yoklamada kimlik, bu iki bilgi ile doğrulanır.
    """

    student_no = StringField(
        "Okul Numarası",
        validators=[DataRequired("Okul numarası zorunludur."), Length(max=32)],
    )
    full_name = StringField(
        "Ad Soyad",
        validators=[DataRequired("Ad soyad zorunludur."), Length(min=3, max=120)],
    )
    room_no = StringField("Oda No", validators=[Optional(), Length(max=16)])
    department = StringField("Program/Bölüm", validators=[Optional(), Length(max=120)])
    class_year = StringField("Sınıf", validators=[Optional(), Length(max=16)])
    phone = StringField("Telefon", validators=[Optional(), Length(max=32)])
    email = StringField("E-posta", validators=[Optional(), Length(max=120)])
    is_active_account = BooleanField("Kayıt aktif", default=True)
    submit = SubmitField("Kaydet")

    def validate_full_name(self, field):
        if len((field.data or "").split()) < 2:
            raise ValidationError("Ad ve soyadı birlikte yazın.")


class StudentBulkForm(FlaskForm):
    """Birden çok öğrenciyi tek seferde ekleme (her satır: numara ; ad soyad)."""

    rows = TextAreaField(
        "Öğrenci Listesi",
        validators=[DataRequired("En az bir satır girin.")],
        description=(
            "Her satıra bir öğrenci yazın: okul numarası, ad soyad "
            "(ayraç olarak virgül, noktalı virgül veya sekme kullanılabilir). "
            "İstenirse üçüncü alan olarak oda numarası eklenebilir."
        ),
    )
    submit = SubmitField("Listeyi Ekle")


class UserForm(FlaskForm):
    """Görevli / yönetici hesabı (öğrenciler için StudentForm kullanılır)."""

    full_name = StringField(
        "Ad Soyad", validators=[DataRequired("Ad soyad zorunludur."), Length(max=120)]
    )
    username = StringField(
        "Kullanıcı Adı",
        validators=[
            DataRequired("Kullanıcı adı zorunludur."),
            Length(min=3, max=64),
            Regexp(
                r"^[A-Za-z0-9_.@-]+$",
                message="Yalnızca harf, rakam ve . _ - @ kullanılabilir.",
            ),
        ],
    )
    role = SelectField(
        "Rol",
        choices=[
            (ROLE_STAFF, ROLE_LABELS[ROLE_STAFF]),
            (ROLE_ADMIN, ROLE_LABELS[ROLE_ADMIN]),
        ],
        default=ROLE_STAFF,
    )
    email = StringField("E-posta", validators=[Optional(), Length(max=120)])
    phone = StringField("Telefon", validators=[Optional(), Length(max=32)])
    is_active_account = BooleanField("Hesap aktif", default=True)
    password = PasswordField(
        "Parola",
        validators=[Optional(), Length(min=8, message="En az 8 karakter olmalıdır.")],
        description="Yeni hesapta zorunlu; düzenlemede boş bırakılırsa parola değişmez.",
    )
    submit = SubmitField("Kaydet")


class AdminPasswordForm(FlaskForm):
    """Yöneticinin, bir görevli/yönetici hesabının parolasını sıfırlaması."""

    new_password = PasswordField(
        "Yeni Parola",
        validators=[
            DataRequired("Yeni parola zorunludur."),
            Length(min=8, message="Parola en az 8 karakter olmalıdır."),
        ],
    )
    confirm_password = PasswordField(
        "Yeni Parola (Tekrar)",
        validators=[EqualTo("new_password", message="Parolalar eşleşmiyor.")],
    )
    submit = SubmitField("Parolayı Sıfırla")


class LeaveForm(FlaskForm):
    student_id = SelectField("Öğrenci", coerce=int, validators=[DataRequired()])
    leave_type = SelectField(
        "Tür", choices=[(key, label) for key, label in LEAVE_TYPES.items()]
    )
    start_date = DateField("Başlangıç", default=date.today, validators=[DataRequired()])
    end_date = DateField("Bitiş", default=date.today, validators=[DataRequired()])
    note = TextAreaField("Açıklama", validators=[Optional(), Length(max=500)])
    submit = SubmitField("İzin Kaydet")

    def validate_end_date(self, field):
        if self.start_date.data and field.data and field.data < self.start_date.data:
            raise ValidationError("Bitiş tarihi başlangıçtan önce olamaz.")


class ReportFilterForm(FlaskForm):
    class Meta:
        csrf = False  # GET ile çalışan filtre formu

    start_date = DateField("Başlangıç", validators=[Optional()])
    end_date = DateField("Bitiş", validators=[Optional()])
    student_id = SelectField("Öğrenci", coerce=int, validators=[Optional()])
    submit = SubmitField("Filtrele")
