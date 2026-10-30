#!/bin/sh
# Container entrypoint: plain HTTP on port 8000, and with HTTPS=true also HTTPS on 8443
# (see app/serve.py). A second laptop on the same Wi-Fi needs the HTTPS one: browsers
# only allow the microphone and camera on https:// pages or on localhost.
set -e
if [ "${HTTPS:-false}" = "true" ]; then
  CERT_DIR="${CERT_DIR:-/models/cert}"
  # HTTPS_HOSTS: extra certificate names/IPs, e.g. "IP:192.168.1.20", so the certificate
  # matches the address laptop B types (and can be trusted, e.g. with mkcert's CA)
  SAN="DNS:localhost,IP:127.0.0.1${HTTPS_HOSTS:+,$HTTPS_HOSTS}"
  mkdir -p "$CERT_DIR"
  if [ ! -f "$CERT_DIR/cert.pem" ] || [ "$(cat "$CERT_DIR/san.txt" 2>/dev/null)" != "$SAN" ]; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 825 -subj "/CN=Transmeet demo" \
      -addext "subjectAltName=$SAN" -addext "extendedKeyUsage=serverAuth" \
      -keyout "$CERT_DIR/key.pem" -out "$CERT_DIR/cert.pem" 2>/dev/null
    echo "$SAN" > "$CERT_DIR/san.txt"
    echo "self-signed certificate for $SAN written to $CERT_DIR"
  fi
fi
exec python -m app.serve
