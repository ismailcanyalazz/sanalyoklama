"""Ad-soyad karşılaştırması için metin normalleştirme.

Öğrenci, QR kodu okuttuktan sonra adını kendi yazdığı için küçük yazım
farkları (büyük/küçük harf, Türkçe karakter, fazladan boşluk, ad-soyad
sırası) yüzünden yoklamanın reddedilmemesi gerekir. Buradaki yardımcılar
kayıttaki ad ile girilen adı bu farklara karşı duyarsız biçimde eşler.

Örnek:
    names_match("Ayşe Yılmaz", "ayse  yilmaz")  -> True
    names_match("Ayşe Yılmaz", "Yılmaz Ayşe")   -> True
    names_match("Ayşe Yılmaz", "Ayşe Kaya")     -> False
"""
from __future__ import annotations

import re
import unicodedata

# Türkçe harflerin ASCII karşılıkları. Python'un lower()/upper() işlemleri
# "I/ı" ve "İ/i" çiftlerini Türkçe kurallarına göre çevirmediği için eşleme
# elle yapılır.
_TR_MAP = str.maketrans(
    {
        "ı": "i", "I": "i", "İ": "i", "i": "i",
        "ğ": "g", "Ğ": "g",
        "ü": "u", "Ü": "u",
        "ş": "s", "Ş": "s",
        "ö": "o", "Ö": "o",
        "ç": "c", "Ç": "c",
        "â": "a", "Â": "a",
        "î": "i", "Î": "i",
        "û": "u", "Û": "u",
    }
)

_NON_WORD = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")


def normalize_name(value: str | None) -> str:
    """Adı karşılaştırmaya uygun biçime indirger.

    Türkçe harfler ASCII'ye çevrilir, noktalama atılır, harfler küçültülür ve
    fazladan boşluklar teke indirilir.
    """
    if not value:
        return ""
    text = str(value).translate(_TR_MAP)
    # Kalan aksanlı harfleri (é, ñ gibi) de sadeleştir
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = _NON_WORD.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def name_tokens(value: str | None) -> tuple[str, ...]:
    """Normalleştirilmiş adı sözcüklere ayırıp sıralar (ad-soyad sırası serbest)."""
    normalized = normalize_name(value)
    return tuple(sorted(normalized.split())) if normalized else ()


def names_match(expected: str | None, given: str | None) -> bool:
    """İki adın aynı kişiye ait sayılıp sayılmayacağını döndürür."""
    expected_tokens = name_tokens(expected)
    given_tokens = name_tokens(given)
    if not expected_tokens or not given_tokens:
        return False
    return expected_tokens == given_tokens


def normalize_student_no(value: str | None) -> str:
    """Okul numarasındaki boşluk ve ayraçları temizler."""
    if not value:
        return ""
    return re.sub(r"[\s.\-_/]+", "", str(value)).strip()
