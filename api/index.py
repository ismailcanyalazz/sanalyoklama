"""Vercel Python çalışma zamanı için giriş noktası.

Vercel, bu dosyadaki `app` nesnesini bir WSGI uygulaması olarak çalıştırır.
Tüm istekler vercel.json içindeki yönlendirme ile buraya gelir.

Gerekli ortam değişkenleri (Vercel > Project > Settings > Environment Variables):
    SECRET_KEY            uzun ve rastgele bir anahtar
    DATABASE_URL          PostgreSQL adresi (Neon/Supabase/Vercel Postgres)
    FLASK_CONFIG          production
    SESSION_COOKIE_SECURE 1
    ADMIN_PASSWORD        ilk yönetici parolası
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402

app = create_app(os.environ.get("FLASK_CONFIG", "production"))
