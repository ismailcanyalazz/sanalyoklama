# Sanal Yoklama Sistemi

Nallıhan Meslek Yüksekokulu kız öğrenci yurdunda kâğıt üzerinde yürütülen akşam
yoklamasını dijital ortama taşıyan web tabanlı uygulama. Yurt görevlisinin
bilgisayarı ekranda belirli aralıklarla yenilenen dinamik bir QR kod gösterir;
öğrenci kendi telefonuyla bu kodu okutur, açılan formda **okul numarası** ile
**ad soyadını** yazar ve bilgiler yurt kayıtlarıyla eşleşirse yoklamada
"mevcut" olarak işaretlenir.

> **Öğrenciler sisteme giriş yapmaz.** Öğrenci hesapları parolasızdır; kimlik,
> yoklama anında girilen okul numarası + ad soyad ikilisiyle doğrulanır.
> Sisteme yalnızca yurt görevlisi ve yönetici giriş yapar.

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
| Öğrenci | — | Giriş yapmaz (parolasız kayıt) |

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

0. **Yönetici** öğrencileri sisteme tanıtır: `Kullanıcılar > Yeni Öğrenci`
   ekranından okul numarası ve ad soyad girilir. Çok sayıda öğrenci için
   `Listeyle Ekle` ekranına her satıra bir öğrenci yazılır
   (`202300101 ; Ayşe Yılmaz ; 101`).
1. **Yurt görevlisi** `Yoklama` panelinden gün, saat aralığı ve QR yenileme
   süresini seçip oturumu başlatır.
2. Açılan **canlı ekranda** QR kod 10–60 saniyede bir yenilenir; altında aynı
   kodun 6 haneli metin karşılığı ve kapanışa kalan süre görünür. Sağdaki liste
   okutma yapıldıkça kendiliğinden güncellenir.
3. **Öğrenci** telefonunun kamera uygulamasıyla ekrandaki QR kodu okutur.
   Açılan sayfa kodu doğrular ve **okul numarası ile ad soyad** ister. Bilgiler
   kayıtla eşleşirse yoklama "Mevcut" olarak işlenir; eşleşmezse okutma
   reddedilir ve deneme günlüğe yazılır. Öğrencinin giriş yapması gerekmez.
4. Oturum, tanımlanan bitiş saatinde **otomatik kapanır**; okutma yapmamış
   öğrenciler "Yok" olarak tamamlanır.
5. Görevli; izinli, raporlu veya geç gelen öğrencileri **manuel olarak**
   düzenleyip açıklama ekleyebilir. Her düzenleme günlüğe yazılır.
6. **Yönetici**, istatistik panelinden devamsızlık oranlarını grafiklerle izler;
   dönemlik raporları Excel ve PDF olarak indirir.

### Okutma bileti (kod süresi hakkında)

QR kod 10–60 saniyede bir yenilendiği için, öğrenci formu doldururken koddaki
süre dolar. Bu yüzden kod yalnızca QR'ın açtığı **ilk istekte** doğrulanır;
ardından forma, okutan cihaza bağlı ve kısa ömürlü (varsayılan 3 dakika,
`SCAN_TICKET_MAX_AGE`) imzalı bir **okutma bileti** verilir. Form bu biletle
gönderilir. Bilet başka bir telefona iletilirse çerez eşleşmeyeceği için
geçersiz sayılır.

### Yönetici ekranından yapılabilenler

`Kullanıcılar` sayfasında (yalnızca yönetici rolü):

| İşlem | Nasıl |
|---|---|
| Öğrenci ekleme | **Yeni Öğrenci** — okul numarası + ad soyad (parola yok) |
| Toplu öğrenci ekleme | **Listeyle Ekle** — her satıra `numara ; ad soyad ; oda` |
| Öğrenci düzenleme / silme | Satırdaki kalem ve çöp kutusu düğmeleri |
| Görevli / yönetici ekleme | **Yeni Görevli/Yönetici** — kullanıcı adı + parola |
| Parola sıfırlama | Satırdaki kilit düğmesi (görevli ve yönetici hesapları) |
| Hesabı pasife alma | Güç düğmesi — kayıt silinmeden yoklama dışı bırakılır |
| Kendi parolasını değiştirme | Sağ üst menü → **Parola Değiştir** |

Silme kuralları: öğrenci silindiğinde o öğrenciye ait **tüm yoklama kayıtları**
da silinir (onay sorulur). Yoklama oturumu veya izin kaydı açmış bir görevli
silinemez — geçmiş kayıtların sahibi kaybolmasın diye; bunun yerine pasife
alınır. Yöneticinin kendi hesabını ve sistemdeki son yönetici hesabını silmesi
engellidir.

### Kamera çalışmazsa

Öğrenci, telefonun kendi kamera uygulamasını kullandığı için tarayıcı kamera
izni gerekmez. Kamera hiç okumuyorsa `/yoklama` adresinden ekrandaki 6 haneli
kod, okul numarası ve ad soyad tek formda girilebilir (kod yenilenmeden
gönderilmelidir).

### Yerel ağda test: QR'daki adres

QR kodun içine, görevli panelinin açıldığı adres yazılır. Panel
`http://localhost:5000` ile açılırsa QR da `localhost` gösterir ve telefon
okuyamaz. Yerel ağda test ederken paneli bilgisayarın ağ adresiyle açın
(`http://192.168.x.x:5000`) veya `.env` dosyasına
`PUBLIC_BASE_URL=http://192.168.x.x:5000` yazın. Yayına alındığında bu ayar
gerekmez; kendi alan adı otomatik kullanılır.

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
│   │   ├── auth.py          Giriş / çıkış / parola değiştirme (görevli, yönetici)
│   │   ├── scan.py          Öğrenci yoklama akışı: kimlik formu, bilet, kayıt
│   │   ├── staff.py         Görevli paneli, canlı oturum, izinler, oturum raporu
│   │   ├── admin.py         İstatistik, kullanıcı/öğrenci yönetimi, günlük, rapor
│   │   └── api.py           Görevli ekranı için dinamik kod/QR ve canlı durum
│   ├── utils/
│   │   ├── security.py      TOTP üretimi/doğrulaması, cihaz kimliği, hız sınırı
│   │   ├── text.py          Ad soyad normalleştirme (Türkçe karakter duyarsız)
│   │   ├── decorators.py    Rol tabanlı yetkilendirme
│   │   ├── audit.py         Zaman damgalı günlük kaydı
│   │   └── reports.py       Excel (openpyxl) ve PDF (ReportLab) raporları
│   ├── templates/           Jinja2 şablonları (base, auth, yoklama, staff, admin)
│   └── static/
│       ├── css/style.css
│       ├── js/live_session.js   QR yenileme + canlı liste
│       ├── fonts/               PDF için DejaVu (Türkçe karakter desteği)
│       └── vendor/              Bootstrap, Bootstrap Icons, Chart.js
├── tests/                   51 adet pytest testi
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
| Aynı öğrencinin tekrar kaydı | `(session_id, student_id)` tekillik kısıtı + "zaten yoklama verdiniz" kontrolü |
| Başkasının adına yoklama verme | Okul numarası **ve** ad soyadın yurt kayıtlarıyla birlikte eşleşmesi zorunlu; eşleşmeyen deneme reddedilir ve günlüğe yazılır |
| QR bağlantısının başkasına iletilmesi | Forma verilen **okutma bileti** okutan cihaza bağlıdır ve kısa ömürlüdür (`SCAN_TICKET_MAX_AGE`) |
| Öğrenci listesinin deneme yanılmayla çıkarılması | Kimlik yalnızca **geçerli bir koddan sonra** sorgulanır; hata mesajı hangi alanın yanlış olduğunu söylemez |
| Kaba kuvvet kod/kimlik denemesi | IP başına dakikalık **hız sınırı** (`SCAN_RATE_LIMIT`) + geçersiz denemelerin günlüğe yazılması |
| Yetkisiz erişim | Flask-Login oturumu + `role_required` dekoratörleri; öğrenci hesaplarıyla giriş tümüyle engellenir |
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
| `users` | Öğrenci / yurt görevlisi / yönetici; okul no, oda, program, aktiflik. Öğrenci kayıtları parolasızdır (`password_hash` boş) ve giriş yapamaz |
| `attendance_sessions` | Oturum başlığı, tarih, saat aralığı, gizli anahtar, yenileme süresi, durum |
| `attendance_records` | Oturum-öğrenci kaydı: durum, yöntem (QR/manuel/otomatik), saat, cihaz, IP, açıklama, düzenleyen |
| `leaves` | İzin / rapor kayıtları; tarih aralığındaki yoklamalarda otomatik işaretleme |
| `audit_logs` | Tüm kritik işlemlerin zaman damgalı günlüğü |

Durumlar: `Mevcut`, `Geç Geldi`, `İzinli`, `Raporlu`, `Yok`.

---

## 6. Yayına Alma

Depo: <https://github.com/ismailcanyalazz/sanalyoklama>

Yayına alındığında QR kodun içindeki adres `https://<proje>.vercel.app/...`
olur; öğrenciler yurt ağına bağlı olmadan, kendi internetleriyle de yoklama
verebilir. Yerel ağ ve "localhost" sorunları ortadan kalkar.

### 6.1 Vercel (önerilen)

`api/index.py` uygulamayı WSGI olarak dışa verir, `vercel.json` tüm istekleri
bu fonksiyona yönlendirir.

**Önce veritabanı:** Vercel panelinde **Storage → Create Database → Postgres**
ile bir veritabanı oluşturup projeye bağlayın. Vercel, `DATABASE_URL` ve
`POSTGRES_URL` değişkenlerini otomatik tanımlar; uygulama ikisini de tanır.

> Neden gerekli? Vercel'de uygulama **sunucusuz fonksiyon** olarak çalışır:
> dosya sistemi salt okunurdur ve her istek farklı bir örneğe düşebilir.
> SQLite dosyası kalıcı olmaz, yoklama kayıtları kaybolur.

**Adımlar**

1. <https://vercel.com/new> → **Import Git Repository** → `sanalyoklama`.
2. Framework Preset: **Other**. Build/Output ayarlarına dokunmayın.
3. **Settings → Environment Variables**:

   | Anahtar | Değer |
   |---|---|
   | `SECRET_KEY` | uzun, rastgele bir metin (zorunlu) |
   | `ADMIN_PASSWORD` | ilk yönetici parolası |
   | `DATABASE_URL` | Postgres bağlandıysa otomatik gelir |
   | `FLASK_CONFIG` | `production` (sunucusuz ortamda varsayılan) |

4. **Deploy** → birkaç dakika içinde `https://<proje>.vercel.app` hazır olur.
5. İlk açılışta tablolar ve yönetici hesabı kendiliğinden oluşur
   (`AUTO_INIT_DB`, sunucusuz ortamda varsayılan olarak açıktır).
   `admin` hesabıyla girip parolayı değiştirin ve öğrencileri ekleyin.

Örnek veri eklemek isterseniz yerelde `DATABASE_URL`'i aynı adrese ayarlayıp
`python seed.py` çalıştırmanız yeterlidir.

### 6.2 Render / Railway (alternatif)

Proje `Procfile` ile de hazırdır:

* Build komutu: `pip install -r requirements.txt`
* Start komutu: `gunicorn "app:create_app()" --bind 0.0.0.0:$PORT`
* Ortam değişkenleri: `SECRET_KEY`, `FLASK_CONFIG=production`,
  `SESSION_COOKIE_SECURE=1`, `DATABASE_URL`
* İlk dağıtımdan sonra bir kez `flask init-db` çalıştırın.

### 6.3 Netlify neden olmuyor?

Netlify yalnızca statik dosya ve JavaScript/Go fonksiyonları barındırır; Python
(Flask) bir uygulamayı sunucu olarak çalıştıramaz.

---

## 7. Testler

```bash
python -m pytest -q
```

58 test; TOTP doğrulaması, süresi geçmiş/başka oturuma ait kod reddi, okul
numarası + ad soyad eşleşmesi (Türkçe karakter ve ad-soyad sırası farklarının
kabulü, yanlış ad/olmayan numara reddi), okutma biletinin başka cihazda
geçersizliği, çift kayıt ve aynı cihaz engeli, oturumun otomatik kapanması,
izin kaydının otomatik işaretlemesi, öğrenci girişinin engellenmesi, yönetici
öğrenci ekleme/silme, parola sıfırlama ve Excel/PDF rapor üretimi kapsanır.

Geliştirme bağımlılıkları (pytest) ayrı dosyadadır:
`pip install -r requirements-dev.txt`

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
itsdangerous · SQLite / PostgreSQL · HTML5 · CSS · Bootstrap 5 · JavaScript ·
Chart.js · qrcode (Pillow) · openpyxl · ReportLab · pytest · Git/GitHub
