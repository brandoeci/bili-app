"""Arranca el servidor con HTTPS para poder usar la cámara desde un celular en la misma red.

Los navegadores móviles solo permiten getUserMedia en HTTPS (o localhost). Este script genera un
certificado autofirmado para las IP locales del equipo, lo guarda en data/certs/ y lanza uvicorn.

    python scripts/serve_https.py            # https://<ip-del-pc>:8443/movil

La primera vez el celular mostrará "conexión no privada": es el certificado autofirmado; hay que
aceptarlo una vez. El puerto queda abierto a toda la red local mientras el script corre.
"""
from __future__ import annotations

import datetime
import ipaddress
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CERT_DIR = ROOT / 'data' / 'certs'
PORT = int(os.environ.get('BILI_PORT', '8443'))  # otro puerto para correr una segunda copia sin parar la primera


def local_ips() -> list[str]:
    ips = {'127.0.0.1'}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('8.8.8.8', 80))  # no envía nada; solo elige la interfaz de salida
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(ips)


def ensure_cert(ips: list[str]) -> tuple[Path, Path]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    cert_path, key_path = CERT_DIR / 'bili.crt', CERT_DIR / 'bili.key'
    if cert_path.exists() and key_path.exists():
        current = x509.load_pem_x509_certificate(cert_path.read_bytes())
        have = {str(v) for v in current.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)}
        if set(ips) <= have and current.not_valid_after_utc > datetime.datetime.now(datetime.timezone.utc):
            return cert_path, key_path

    CERT_DIR.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'bili-local')])
    now = datetime.datetime.now(datetime.timezone.utc)
    san = x509.SubjectAlternativeName(
        [x509.DNSName('localhost')] + [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ips]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(san, critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    return cert_path, key_path


def main() -> None:
    sys.path.insert(0, str(ROOT))
    ips = local_ips()
    cert, key = ensure_cert(ips)
    print('\nAbra en el celular (misma red Wi-Fi):')
    for ip in ips:
        if ip != '127.0.0.1':
            print(f'  https://{ip}:{PORT}/movil')
    print('Acepte el aviso del certificado la primera vez. Ctrl+C para detener.\n')

    import uvicorn

    uvicorn.run('app.main:app', host='0.0.0.0', port=PORT, workers=1, ssl_certfile=str(cert), ssl_keyfile=str(key))


if __name__ == '__main__':
    main()
