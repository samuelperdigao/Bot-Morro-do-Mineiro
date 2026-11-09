#!/usr/bin/env bash
# scripts/remote_deploy.sh - Executado NO SERVIDOR pelo GitHub Actions
# (.github/workflows/deploy.yml). Recebe o caminho de um .tar gerado por
# `git archive HEAD` (somente arquivos versionados).
#
# Etapas:
#   1. backup dos bancos (API de backup do SQLite) em backups/predeploy-*.db.gz
#   2. snapshot do codigo atual em ~/farmbot-releases/
#   3. extrai a release em pasta temporaria e instala as dependencias
#      (se falhar, aborta sem alterar o codigo do bot)
#   4. copia para a pasta do bot apenas o manifesto de runtime (o mesmo do
#      scripts/deploy.ps1); .env, data/, bancos e chaves nunca sao tocados
#   5. reinicia o servico e confere `systemctl is-active` a cada 1s; se cair,
#      restaura os arquivos anteriores, reinicia e sai com erro
#
# Uso: bash remote_deploy.sh /tmp/farmbot-release.tar
# Variaveis opcionais (usadas nos testes): APP_DIR, SERVICE, RELEASES_DIR,
# HEALTH_SECONDS, PY, PIP.
set -euo pipefail

RELEASE_TAR="${1:?informe o caminho do .tar da release}"
APP_DIR="${APP_DIR:-/home/ubuntu/farmbot}"
SERVICE="${SERVICE:-farmbot}"
RELEASES_DIR="${RELEASES_DIR:-$HOME/farmbot-releases}"
HEALTH_SECONDS="${HEALTH_SECONDS:-40}"
PY="${PY:-$APP_DIR/venv/bin/python}"
PIP="${PIP:-$APP_DIR/venv/bin/pip}"
TS="$(date +%Y%m%d-%H%M%S)"

# Mesmo manifesto de runtime do scripts/deploy.ps1.
RUNTIME_ROOTS=(assets cogs config core features infrastructure services ui)
RUNTIME_FILES=(main.py requirements.txt)

STAGING="$(mktemp -d)"
META="$(mktemp -d)"
cleanup() { rm -rf "$STAGING" "$META"; rm -f "$RELEASE_TAR"; }
trap cleanup EXIT

test -d "$APP_DIR" || { echo "[ERRO] pasta do bot nao encontrada: $APP_DIR"; exit 1; }
mkdir -p "$RELEASES_DIR" "$APP_DIR/backups"

echo "[1/5] Backup dos bancos"
"$PY" - "$APP_DIR" "$TS" <<'PY'
import gzip
import pathlib
import shutil
import sqlite3
import sys

app = pathlib.Path(sys.argv[1])
ts = sys.argv[2]
backups = app / "backups"
bancos = sorted((app / "data").glob("*.db")) + [app / "bau.db"]
for caminho in bancos:
    nome = caminho.stem
    if not caminho.exists():
        print(f"  {nome}: banco nao encontrado, ignorado")
        continue
    tmp = backups / f"predeploy-{nome}-{ts}.db"
    src = sqlite3.connect(caminho.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    with open(tmp, "rb") as f_in, gzip.open(f"{tmp}.gz", "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    tmp.unlink()
    print(f"  {nome}: {tmp.name}.gz")
    # Mantem os 10 backups pre-deploy mais recentes de cada banco.
    antigos = sorted(backups.glob(f"predeploy-{nome}-*.db.gz"), reverse=True)[10:]
    for velho in antigos:
        velho.unlink()
PY

echo "[2/5] Snapshot do codigo atual"
SNAPSHOT="$RELEASES_DIR/codigo-$TS.tgz"
tar -czf "$SNAPSHOT" -C "$APP_DIR" \
  --exclude=./venv --exclude=./data --exclude=./backups --exclude=./logs \
  --exclude='*.db' --exclude='*.db-shm' --exclude='*.db-wal' --exclude='*.db.gz' \
  --exclude=./.env --exclude='*.key' --exclude='__pycache__' \
  --exclude=./.deploy-backups --exclude=./.deploy-staging .
{ ls -1t "$RELEASES_DIR"/codigo-*.tgz 2>/dev/null || true; } | tail -n +6 | xargs -r rm -f
echo "  $SNAPSHOT"

echo "[3/5] Extraindo release e instalando dependencias"
tar -xf "$RELEASE_TAR" -C "$STAGING"
test -f "$STAGING/main.py" || { echo "  [ERRO] release sem main.py"; exit 1; }
test -f "$STAGING/requirements.txt" || { echo "  [ERRO] release sem requirements.txt"; exit 1; }
"$PIP" install -q -r "$STAGING/requirements.txt"

# Manifesto: arquivos de runtime da release, sem nada sensivel ou de estado.
(
  cd "$STAGING"
  for raiz in "${RUNTIME_ROOTS[@]}"; do
    if [ -d "$raiz" ]; then find "$raiz" -type f; fi
  done
  for arquivo in "${RUNTIME_FILES[@]}"; do
    if [ -f "$arquivo" ]; then echo "$arquivo"; fi
  done
) | grep -Ev '(^|/)\.env|\.key$|\.db($|-shm$|-wal$)|(^|/)__pycache__/' | sort -u > "$META/manifest.txt"
test -s "$META/manifest.txt" || { echo "  [ERRO] manifesto de deploy vazio"; exit 1; }
: > "$META/sobrescritos.txt"
: > "$META/novos.txt"
while IFS= read -r caminho; do
  if [ -e "$APP_DIR/$caminho" ]; then
    echo "./$caminho" >> "$META/sobrescritos.txt"
  else
    echo "$caminho" >> "$META/novos.txt"
  fi
done < "$META/manifest.txt"
echo "  $(wc -l < "$META/manifest.txt") arquivos ($(wc -l < "$META/novos.txt") novos)"

rollback() {
  echo "  [ERRO] $1. Restaurando a versao anterior..."
  set +e
  journalctl -u "$SERVICE" -n 40 --no-pager --output=cat 2>/dev/null
  if [ -s "$META/sobrescritos.txt" ]; then
    tar -xzf "$SNAPSHOT" -C "$APP_DIR" -T "$META/sobrescritos.txt" \
      || echo "  [ERRO] falha ao restaurar o snapshot $SNAPSHOT"
  fi
  while IFS= read -r caminho; do
    rm -f "$APP_DIR/$caminho"
  done < "$META/novos.txt"
  sudo systemctl restart "$SERVICE"
  sleep 10
  echo "  status apos rollback: $(systemctl is-active "$SERVICE")"
  exit 1
}

aplicar() {
  local caminho
  while IFS= read -r caminho; do
    mkdir -p "$APP_DIR/$(dirname "$caminho")" || return 1
    cp -p "$STAGING/$caminho" "$APP_DIR/$caminho" || return 1
  done < "$META/manifest.txt"
}

echo "[4/5] Aplicando release"
aplicar || rollback "falha ao copiar os arquivos"

echo "[5/5] Reiniciando $SERVICE e verificando por ${HEALTH_SECONDS}s"
sudo systemctl restart "$SERVICE" || rollback "falha no restart"
for _ in $(seq 1 "$HEALTH_SECONDS"); do
  sleep 1
  estado="$(systemctl is-active "$SERVICE" || true)"
  if [ "$estado" != "active" ]; then
    rollback "$SERVICE ficou '$estado'"
  fi
done

echo "  STATUS: ONLINE"
journalctl -u "$SERVICE" -n 15 --no-pager --output=cat 2>/dev/null || true
echo "Deploy concluido."
