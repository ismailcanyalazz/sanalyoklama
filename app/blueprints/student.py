"""KULLANIM DIŞI — öğrenci paneli kaldırıldı.

Öğrenciler artık sisteme giriş yapmıyor: ekrandaki QR kodu okutup açılan
formda okul numarası ile ad soyadlarını yazıyorlar. Bu akış
``app/blueprints/scan.py`` içindedir ve giriş gerektirmez.

Bu dosya hiçbir yerden içe aktarılmıyor (uygulama fabrikasında kayıtlı
değil) ve silinebilir. Aynı şekilde ``app/templates/student/`` klasörü ile
``app/static/js/scanner.js`` dosyası da kullanılmıyor.
"""
