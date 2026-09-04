"""VAPID anahtar çifti üretici — Web Push bildirimleri için.

Kullanım:
    python scripts/generate_vapid_keys.py

Çıktıdaki iki değeri ortam değişkenlerine (Coolify / .env) yaz:
    VAPID_PRIVATE_KEY           → backend ortamına (32-byte RAW, URL-safe base64)
    NEXT_PUBLIC_VAPID_PUBLIC_KEY → frontend BUILD argümanına (65-byte, URL-safe base64)

pywebpush 2.x `Vapid.from_string` private key'i base64url decode edip 32 bayt
ise RAW kabul eder (PEM başlıkları DEĞİL). Bu yüzden düz 32-byte private key
base64'ü üretiyoruz.

Not: Anahtarlar eşleşmelidir — ikisi aynı çiftten üretilir. Birini değiştirirsen
ikisini de yeniden üretip hem backend'i hem frontend'i yeniden deploy et.
"""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

private_key = ec.generate_private_key(ec.SECP256R1())

# Public key: 65-byte uncompressed P-256 noktası → URL-safe base64 (frontend)
public_bytes = private_key.public_key().public_bytes(
    serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
)
public_b64 = base64.urlsafe_b64encode(public_bytes).rstrip(b"=").decode()

# Private key: 32-byte RAW (SEC1 düz skaler) → URL-safe base64 (backend)
private_numbers = private_key.private_numbers().private_value
private_raw = private_numbers.to_bytes(32, byteorder="big")
private_b64 = base64.urlsafe_b64encode(private_raw).rstrip(b"=").decode()

print("=" * 60)
print("VAPID ANAHTAR CIFTI - asagidaki iki degeri kaydedin")
print("=" * 60)
print()
print("NEXT_PUBLIC_VAPID_PUBLIC_KEY (frontend build arg):")
print(public_b64)
print()
print("VAPID_PRIVATE_KEY (backend env):")
print(private_b64)
print()
print("VAPID_SUBJECT (backend env, istege bagli):")
print("mailto:alerts@example.com")
print("=" * 60)
