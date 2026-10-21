#!/bin/bash
# One-time setup for a fresh Claude Code cloud session (idempotent):
#  1. make the scraper's browser trust the session's outbound proxy CA (else every Maps request fails TLS)
#  2. start Docker + the scraper via recover.sh and check the API answers
cd "$(dirname "$0")/../.." || exit 1
if [ -f /root/.ccr/ca-bundle.crt ]; then
  command -v certutil >/dev/null ||
    apt-get install -y libnss3-tools >/dev/null 2>&1 ||
    { apt-get update >/dev/null 2>&1 && apt-get install -y libnss3-tools >/dev/null 2>&1; }
  D=/root/gmaps-nssdb
  if [ ! -f $D/cert9.db ]; then
    mkdir -p $D && certutil -N -d sql:$D --empty-password &&
      certutil -A -d sql:$D -n ccr-proxy -t "C,," -i /root/.ccr/ca-bundle.crt
  fi
  if [ ! -f docker-compose.override.yml ]; then
    cat > docker-compose.override.yml <<'EOF'
# Session-local only (not committed): trust the cloud session's proxy CA inside the scraper.
services:
  google-maps-scraper:
    environment:
      SSL_CERT_FILE: /etc/ssl/certs/ca-certificates.crt
    volumes:
      - /root/.ccr/ca-bundle.crt:/etc/ssl/certs/ca-certificates.crt:ro
      - /root/gmaps-nssdb:/root/.pki/nssdb
EOF
  fi
  grep -qx docker-compose.override.yml .git/info/exclude 2>/dev/null || echo docker-compose.override.yml >> .git/info/exclude
fi
bash scripts/ops/recover.sh
