#!/usr/bin/env bash
# scripts/remote_deploy.sh - Executado NO SERVIDOR pelo deploy (GitHub Actions
# ou scripts/deploy.ps1). Recebe o caminho de um .tar gerado por
# `git archive` (somente arquivos versionados: nunca leva .env, chaves,
# bancos ou JSON de estado).
#
# Etapas: backup dos bancos -> snapshot do codigo atual -> extrai em staging
# -> instala dependencias -> copia para a pasta do bot -> reinicia ->
# verifica saude. Se o bot nao ficar de pe, restaura o snapshot e falha.
#
# Uso: bash remote_deploy.sh /tmp/farmbot-release.tar
set -euo pipefail

RELEASE_TAR="${1:?informe o caminho do .tar da release}"
APP_DIR="${APP_DIR:-/home/ubuntu/farmbot}"
SERVICE="${SERVICE:-farmbot}"
RELEASES_DIR="${RELEASES_DIR:-$HOME/farmbot-releases}"
HEALTH_SECONDS="${HEALTH_SECONDS:-40}"
TS="$(date +%Y%m%d-%H%M%S)"
PY="$APP_DIR/venv/bin/python"
PIP="$APP_DIR/venv/bin/pip"

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING" "$RELEASE_TAR"' EXIT

mkdir -p "$RELEASES_DIR" "$APP_DIR/backups"

echo "[1/6] Backup dos bancos antes do deploy"
"$PY" - "$APP_DIR" "$TS" <<'PY'
import gzip, pathlib, shutil, sqlite3, sys

app = pathlib.Path(sys.argv[1])
ts = sys.argv[2]
for nome, caminho in (("farm", app / "data" / "farm.db"), ("bau", app / "bau.db")):
    if not caminho.exists():
        print(f"  {nome}: banco nao encontrado, ignorado")
        continue
    tmp = app / "backups" / f"predeploy-{nome}-{ts}.db"
    src = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, timeout=30)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    with open(tmp, "rb") as f_in, gzip.open(f"{tmp}.gz", "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    tmp.unlink()
    print(f"  {nome}: {tmp}.gz")
PY
# Mantem os 10 backups pre-deploy mais recentes de cada banco.
for nome in farm bau; do
  { ls -1t "$APP_DIR"/backups/predeploy-"$nome"-*.db.gz 2>/dev/null || true; } | tail -n +11 | xargs -r rm -f
done

echo "[2/6] Snapshot do codigo atual (para rollback)"
SNAPSHOT="$RELEASES_DIR/codigo-$TS.tgz"
tar -czf "$SNAPSHOT" -C "$APP_DIR" \
  --exclude=./venv --exclude=./backups --exclude=./data --exclude=./logs \
  --exclude='*.db' --exclude='*.db-shm' --exclude='*.db-wal' \
  --exclude=./.env --exclude='*.key' --exclude='__pycache__' .
{ ls -1t "$RELEASES_DIR"/codigo-*.tgz 2>/dev/null || true; } | tail -n +6 | xargs -r rm -f
echo "  $SNAPSHOT"

echo "[3/6] Extraindo release em staging"
tar -xf "$RELEASE_TAR" -C "$STAGING"
test -f "$STAGING/main.py" || { echo "  [ERRO] release sem main.py"; exit 1; }

echo "[4/6] Instalando dependencias"
"$PIP" install -q -r "$STAGING/requirements.txt"

echo "[5/6] Aplicando release e reiniciando $SERVICE"
cp -a "$STAGING/." "$APP_DIR/"
# Chave SSH antiga enviada pelo deploy anterior: nao deve ficar no servidor.
if [ -f "$APP_DIR/scripts/oracle.key" ]; then
  rm -f "$APP_DIR/scripts/oracle.key"
  echo "  removida chave SSH esquecida em scripts/oracle.key"
fi
sudo systemctl restart "$SERVICE"

rollback() {
  echo "  [ERRO] $SERVICE nao ficou estavel. Restaurando versao anterior..."
  journalctl -u "$SERVICE" -n 40 --no-pager --output=cat || true
  tar -xzf "$SNAPSHOT" -C "$APP_DIR"
  sudo systemctl restart "$SERVICE"
  sleep 10
  echo "  status apos rollback: $(systemctl is-active "$SERVICE" || true)"
  exit 1
}

echo "[6/6] Verificando saude por ${HEALTH_SECONDS}s"
sleep 5
for _ in $(seq 1 "$HEALTH_SECONDS"); do
  if [ "$(systemctl is-active "$SERVICE" || true)" != "active" ]; then
    rollback
  fi
  sleep 1
done

echo "  STATUS: ONLINE"
journalctl -u "$SERVICE" -n 15 --no-pager --output=cat || true
echo "Deploy concluido."
