"""Geliştirme sunucusunu başlatan dosya.

Kullanım:
    python run.py

Telefondan kamera ile test etmek için (tarayıcılar HTTPS olmayan adreslerde
kameraya izin vermez) kendinden imzalı sertifika ile başlatın:
    set USE_SSL=1   (Windows)   /   export USE_SSL=1   (Linux-macOS)
    python run.py
Bu seçenek için `pip install pyopenssl` gerekir.
"""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 5000))
    use_ssl = os.environ.get("USE_SSL", "").lower() in {"1", "true", "yes"}
    app.run(
        host=host,
        port=port,
        debug=os.environ.get("FLASK_DEBUG", "1") == "1",
        ssl_context="adhoc" if use_ssl else None,
    )
