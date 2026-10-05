#!/usr/bin/env bash
# Start the scraper inside a Claude Code cloud sandbox (not needed on your own computer).
#
# Why this exists: in the sandbox, outbound traffic must go through the session's egress proxy,
# which re-signs TLS with its own CA. This script
#   1. starts the Docker daemon if it isn't running,
#   2. builds an NSS certificate store (.sandbox-nssdb/) holding that CA so Chromium trusts it,
#   3. starts the container with docker-compose.sandbox.yml (host network + proxy + CA).
# The environment's network access must allow *.google.com (Custom or a broader level).
set -euo pipefail
cd "$(dirname "$0")/.."
CA=/root/.ccr/ca-bundle.crt
[ -f "$CA" ] || { echo "✗ $CA not found — this script is only for Claude Code cloud sandboxes." >&2; exit 1; }

if ! docker info >/dev/null 2>&1; then
  echo "▶ Starting Docker daemon…"
  (sudo dockerd >/tmp/dockerd.log 2>&1 &)
  for _ in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 1; done
  docker info >/dev/null 2>&1 || { echo "✗ dockerd didn't start (see /tmp/dockerd.log)" >&2; exit 1; }
fi

if [ ! -f .sandbox-nssdb/cert9.db ]; then
  echo "▶ Building NSS certificate store for Chromium…"
  command -v certutil >/dev/null || { sudo apt-get update -qq >/dev/null; sudo apt-get install -y -qq libnss3-tools >/dev/null; }
  mkdir -p .sandbox-nssdb
  certutil -N -d sql:.sandbox-nssdb --empty-password
  python3 - "$CA" <<'PY'
import re, subprocess, sys
pem = open(sys.argv[1]).read()
for i, c in enumerate(re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", pem, re.S)):
    subprocess.run(["certutil", "-A", "-d", "sql:.sandbox-nssdb", "-n", f"sandbox-ca-{i}", "-t", "C,,", "-a"],
                   input=c.encode(), check=True)
PY
fi

echo "▶ Starting scraper container…"
docker compose -f docker-compose.yml -f docker-compose.sandbox.yml up -d

for _ in $(seq 1 30); do curl -s -m 3 http://localhost:8080/api/v1/jobs >/dev/null && { echo "✓ Scraper up at http://localhost:8080"; exit 0; }; sleep 2; done
echo "✗ Scraper didn't come up — check: docker logs gmaps-scraper" >&2; exit 1
