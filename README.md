# Sanal Yoklama Sistemi

Nallıhan Meslek Yüksekokulu kız öğrenci yurdunda kâğıt üzerinde yürütülen akşam
yoklamasını dijital ortama taşıyan web tabanlı uygulama. Yurt görevlisi ekranda
belirli aralıklarla yenilenen dinamik bir QR kod gösterir; öğrenciler kendi
telefonlarıyla bu kodu okutarak yoklamada "mevcut" olarak işaretlenir.

---

## 1. Hızlı Başlangıç (Windows)

```bat
cd C:\Users\msipc\Desktop\sanalyoklama

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env          :: isteğe bağlı, ayarları düzenlemek için

set FLASK_APP=run.py
flask init-db                   :: tabloları oluşturur + yönetici hesabı açar
python seed.py                  :: (isteğe bağlı) örnek öğrenci ve yoklama verisi

python run.py
```

Tarayıcıdan <http://localhost:5000> adresini açın.

Kolaylık olması için `kurulum.bat` (ilk kurulum) ve `baslat.bat` (çalıştırma)
dosyaları da hazırlanmıştır; çift tıklamanız yeterlidir.

### Varsayılan hesaplar

| Rol | Kullanıcı adı | Parola |
|---|---|---|
| Yönetici | `admin` | `Admin1234!` |
| Yurt görevlisi | `gorevli` | `Gorevli1234!` (seed.py ile) |
| Öğrenci | öğrenci numarası (ör. `202300101`) | `Ogrenci1234!` (seed.py ile) |

> Gerçek kullanımda bu parolaları ilk girişten sonra mutlaka değiştirin
> (`Profil > Parola Değiştir` veya `flask reset-password <kullanıcı> <parola>`).

### Linux / macOS

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export FLASK_APP=run.py
flask init-db
python seed.py
python run.py
```

---

## 2. Kullanım Akışı

1. **Yurt görevlisi** `Yoklama` panelinden gün, saat aralığı ve QR yenileme
   süresini seçip oturumu başlatır.
2. Açılan **canlı ekranda** QR kod 10–60 saniyede bir yenilenir; altında aynı
   kodun 6 haneli metin karşılığı ve kapanışa kalan süre görünür. Sağdaki liste
   okutma yapıldıkça kendiliğinden güncellenir.
3. **Öğrenci** telefonundan sisteme girip `Yoklama Ver` ekranını açar, kamerayı
   koda doğrultur. Telefonun kendi kamera uygulaması ile okutulduğunda da aynı
   adres açılır (giriş yapılmamışsa önce giriş ekranına yönlendirilir).
4. Oturum, tanımlanan bitiş saatinde **otomatik kapanır**; okutma yapmamış
   öğrenciler "Yok" olarak tamamlanır.
5. Görevli; izinli, raporlu veya geç gelen öğrencileri **manuel olarak**
   düzenleyip açıklama ekleyebilir. Her düzenleme günlüğe yazılır.
6. **Yönetici**, istatistik panelinden devamsızlık oranlarını grafiklerle izler;
   dönemlik raporları Excel ve PDF olarak indirir.

### Telefonla kamera testi hakkında (önemli)

Tarayıcılar kameraya yalnızca **HTTPS** veya **localhost** üzerinden izin verir.
Yerel ağda `http://192.168.x.x:5000` adresinden test ederken kamera açılmazsa:

* `pip install pyopenssl` kurup `USE_SSL=1` ile çalıştırın
  (`set USE_SSL=1 & python run.py`) ve `https://192.168.x.x:5000` adresini
  kullanın (sertifika uyarısını kabul edin), **veya**
* Okutma ekranındaki "Kodu elle girin" seçeneği ile 6 haneli kodu girin, **veya**
* Uygulamayı HTTPS sağlayan bir bulut servisine yükleyin (bkz. 6. bölüm).

---

## 3. Proje Yapısı

```
sanalyoklama/
├── app/
│   ├── __init__.py          Uygulama fabrikası, hata sayfaları, CLI komutları
│   ├── extensions.py        SQLAlchemy, Login, CSRF nesneleri
│   ├── models.py            User, AttendanceSession, AttendanceRecord, Leave, AuditLog
│   ├── forms.py             Flask-WTF formları (CSRF korumalı)
│   ├── services.py          İş kuralları: oturum, okutma, manuel düzenleme, istatistik
│   ├── blueprints/
│   │   ├── main.py          Açılış, hakkında, sağlık kontrolü
│   │   ├── auth.py          Giriş / çıkış / parola değiştirme
│   │   ├── student.py       Öğrenci paneli, okutma ekranı, kayıtlar
│   │   ├── staff.py         Görevli paneli, canlı oturum, izinler, oturum raporu
│   │   ├── admin.py         İstatistik, kullanıcı yönetimi, günlük, dönem raporu
│   │   └── api.py           Dinamik kod/QR üretimi, okutma uç noktası
│   ├── utils/
│   │   ├── security.py      TOTP üretimi/doğrulaması, cihaz kimliği, hız sınırı
│   │   ├── decorators.py    Rol tabanlı yetkilendirme
│   │   ├── audit.py         Zaman damgalı günlük kaydı
│   │   └── reports.py       Excel (openpyxl) ve PDF (ReportLab) raporları
│   ├── templates/           Jinja2 şablonları (base, auth, student, staff, admin)
│   └── static/
│       ├── css/style.css
│       ├── js/scanner.js        html5-qrcode ile tarayıcı içi okuyucu
│       ├── js/live_session.js   QR yenileme + canlı liste
│       ├── fonts/               PDF için DejaVu (Türkçe karakter desteği)
│       └── vendor/              Bootstrap, Bootstrap Icons, Chart.js, html5-qrcode
├── tests/                   33 adet pytest testi
├── config.py                Ortam bazlı yapılandırma
├── run.py                   Geliştirme sunucusu
├── seed.py                  Örnek veri üretici
├── requirements.txt
├── Procfile                 Bulut dağıtımı (gunicorn)
└── .env.example
```

Ön yüz kütüphaneleri `app/static/vendor/` içinde yerel olarak bulunur; uygulama
internet bağlantısı olmadan da arayüzü eksiksiz görüntüler.

---

## 4. Güvenlik Mekanizmaları

| Risk | Alınan önlem |
|---|---|
| QR kodun ekran görüntüsünün paylaşılması | Oturuma özel gizli anahtarla üretilen **TOTP** (RFC 6238); kod 10–60 sn'de bir değişir, eski kodlar reddedilir |
| Yoklama saatinden sonra kayıt | Oturum bitiş saatinde **otomatik kapanır** (`before_request` kontrolü) |
| Bir öğrencinin birden çok arkadaşı için okutması | Aynı oturumda **cihaz başına tek kayıt**: cihaz kimliği çerezi + `(session_id, device_id)` tekillik kısıtı |
| Aynı öğrencinin tekrar kaydı | `(session_id, student_id)` tekillik kısıtı |
| Kaba kuvvet kod denemesi | IP başına dakikalık **hız sınırı** + geçersiz denemelerin günlüğe yazılması |
| Yetkisiz erişim | Flask-Login oturumu + `role_required` dekoratörleri (öğrenci / görevli / yönetici) |
| Parola sızıntısı | Parolalar `werkzeug.security` ile **özetlenerek (hash)** saklanır |
| Form sahteciliği (CSRF) | Tüm formlarda ve JSON isteklerinde Flask-WTF CSRF belirteci |
| İzlenebilirlik | Giriş, oturum açma/kapama, okutma, reddedilen deneme, manuel düzenleme ve rapor indirme işlemleri **zaman damgası, IP ve tarayıcı bilgisiyle** `audit_logs` tablosuna yazılır |

TOTP uygulaması harici bir kütüphaneye bağlı değildir; `hmac`/`hashlib` ile
`app/utils/security.py` içinde yazılmıştır. Saat kaymalarına karşı bir önceki ve
bir sonraki zaman penceresi de kabul edilir (`TOTP_VALID_WINDOW`).

---

## 5. Veri Modeli

| Tablo | Açıklama |
|---|---|
| `users` | Öğrenci / yurt görevlisi / yönetici; öğrenci no, oda, program, aktiflik |
| `attendance_sessions` | Oturum başlığı, tarih, saat aralığı, gizli anahtar, yenileme süresi, durum |
| `attendance_records` | Oturum-öğrenci kaydı: durum, yöntem (QR/manuel/otomatik), saat, cihaz, IP, açıklama, düzenleyen |
| `leaves` | İzin / rapor kayıtları; tarih aralığındaki yoklamalarda otomatik işaretleme |
| `audit_logs` | Tüm kritik işlemlerin zaman damgalı günlüğü |

Durumlar: `Mevcut`, `Geç Geldi`, `İzinli`, `Raporlu`, `Yok`.

---

## 6. Yayına Alma (Bulut)

Uygulama `Procfile` ile hazırdır ve ücretsiz servislerde (Render, Railway,
PythonAnywhere vb.) çalışır.

1. Projeyi GitHub'a gönderin:
   ```bash
   git init
   git add .
   git commit -m "Sanal yoklama sistemi ilk sürüm"
   git branch -M main
   git remote add origin https://github.com/<kullanici>/<depo>.git
   git push -u origin main
   ```
2. Servis üzerinde yeni bir **Web Service** oluşturup depoyu bağlayın.
   * Build komutu: `pip install -r requirements.txt`
   * Start komutu: `gunicorn "app:create_app()" --bind 0.0.0.0:$PORT`
3. Ortam değişkenlerini tanımlayın: `SECRET_KEY`, `FLASK_CONFIG=production`,
   `SESSION_COOKIE_SECURE=1`, (PostgreSQL kullanacaksanız) `DATABASE_URL`.
4. İlk dağıtımdan sonra bir kez `flask init-db` çalıştırın.

Bulut servisleri HTTPS sağladığı için öğrenci telefonlarında kamera erişimi
sorunsuz çalışır.

---

## 7. Testler

```bash
python -m pytest -q
```

33 test; TOTP doğrulaması, süresi geçmiş/başka oturuma ait kod reddi, çift kayıt
ve aynı cihaz engeli, oturumun otomatik kapanması, izin kaydının otomatik
işaretlemesi, rol bazlı erişim kontrolleri ve Excel/PDF rapor üretimi kapsanır.

---

## 7b. Vercel ile Yayına Alma

Depo: <https://github.com/ismailcanyalazz/sanalyoklama>

Proje Vercel'in Python çalışma zamanı için hazırdır: `api/index.py` uygulamayı
WSGI olarak dışa verir, `vercel.json` tüm istekleri bu fonksiyona yönlendirir.

1. <https://vercel.com/new> → **Import Git Repository** → `sanalyoklama` deposunu seçin.
2. Framework Preset: **Other**. Build/Output ayarlarına dokunmayın.
3. **Environment Variables** bölümüne şunları ekleyin:

   | Anahtar | Değer |
   |---|---|
   | `SECRET_KEY` | uzun, rastgele bir metin |
   | `FLASK_CONFIG` | `production` |
   | `SESSION_COOKIE_SECURE` | `1` |
   | `DATABASE_URL` | PostgreSQL bağlantı adresi (aşağıya bakın) |
   | `ADMIN_PASSWORD` | ilk yönetici parolası |

4. **Deploy** → birkaç dakika içinde `https://<proje>.vercel.app` adresi hazır olur.

### Veritabanı neden gerekli?

Vercel'de uygulama **sunucusuz (serverless) fonksiyon** olarak çalışır: dosya
sistemi salt okunurdur ve her istek farklı bir örneğe düşebilir. Bu nedenle
SQLite dosyası kalıcı değildir — yoklama oturumu bir örnekte açılıp diğerinde
görünmeyebilir. Ücretsiz bir PostgreSQL yeterlidir:

* **Neon** (<https://neon.tech>) veya **Supabase** üzerinde ücretsiz bir veritabanı
  oluşturun, verilen `postgresql://...` adresini `DATABASE_URL` olarak girin.
* Alternatif: Vercel panelinde **Storage > Create Database > Postgres**;
  `DATABASE_URL` otomatik tanımlanır.

Tablolar ve ilk yönetici hesabı, uygulama ilk ayağa kalktığında otomatik
oluşturulur (`AUTO_INIT_DB`, sunucusuz ortamda varsayılan olarak açıktır).
Örnek veri eklemek için yerelde `DATABASE_URL`'i aynı adrese ayarlayıp
`python seed.py` çalıştırmanız yeterlidir.

### Netlify neden kullanılmıyor?

Netlify yalnızca statik dosya ve JavaScript/Go fonksiyonları barındırır; Python
(Flask) bir uygulamayı sunucu olarak çalıştıramaz. Bu proje için uygun ücretsiz
seçenekler **Vercel**, **Render** veya **PythonAnywhere**'dir.

---

## 8. Yönetim Komutları

| Komut | Açıklama |
|---|---|
| `flask init-db` | Tabloları oluşturur, yönetici hesabını açar |
| `flask seed-demo --students 20 --days 20` | Örnek veri üretir |
| `flask reset-password <kullanıcı> <yeni parola>` | Parola sıfırlar |
| `python run.py` | Geliştirme sunucusunu başlatır |

Uygulama günlüğü: `instance/uygulama.log`. SQLite veritabanı:
`instance/yoklama.db`.

---

## 9. Kullanılan Teknolojiler

Python 3.11+ · Flask · Flask-SQLAlchemy · Flask-Login · Flask-WTF ·
SQLite / PostgreSQL · HTML5 · CSS · Bootstrap 5 · JavaScript · html5-qrcode ·
Chart.js · qrcode (Pillow) · openpyxl · ReportLab · pytest · Git/GitHub
