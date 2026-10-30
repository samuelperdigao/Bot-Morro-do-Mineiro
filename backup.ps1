# backup.ps1 - Backup do servidor (bancos, JSONs e codigo) para a pasta local backups\
# Uso: .\backup.ps1
# Nao altera nada no servidor alem de criar a pasta backups\ dentro do projeto remoto.
# Segredos (.env, .env.*, *.key) ficam fora do backup de codigo.

$SSH_KEY    = Join-Path $PSScriptRoot "oracle.key"
$REMOTE     = "ubuntu@163.176.143.142"
$REMOTE_DIR = "/home/ubuntu/farmbot"
$LOCAL_DIR  = $PSScriptRoot
$SSH_OPTS   = @("-i", $SSH_KEY, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes")
if ($env:MORRO_BOT_KNOWN_HOSTS) { $SSH_OPTS += @("-o", "UserKnownHostsFile=$env:MORRO_BOT_KNOWN_HOSTS") }

$TS = Get-Date -Format "yyyyMMdd_HHmmss"

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  Backup - Bot Morro do Mineiro" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# -- 1. Testa a conexao ------------------------------------------------------
Write-Host "[1/3] Testando conexao com o servidor..." -ForegroundColor Yellow
$teste = ssh @SSH_OPTS $REMOTE "echo conectado"
if ($LASTEXITCODE -ne 0 -or "$teste".Trim() -ne "conectado") {
    Write-Host "  [ERRO] Nao consegui conectar no servidor. Confira internet e a chave SSH." -ForegroundColor Red
    exit 1
}
Write-Host "  Conectado." -ForegroundColor Green

# -- 2. Cria o backup no servidor --------------------------------------------
Write-Host ""
Write-Host "[2/3] Criando backup no servidor ($TS)..." -ForegroundColor Yellow

$remoteScript = @'
TS="$1"
DIR="$2"
OUT="$DIR/backups/$TS"
mkdir -p "$OUT" || exit 1

n=0
while IFS= read -r f; do
  rel="${f#$DIR/}"
  name="${rel//\//__}"
  python3 - "$f" "$OUT/$name" <<'PY' || exit 1
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close()
src.close()
PY
  n=$((n+1))
done < <(find "$DIR" -maxdepth 3 -name '*.db' -not -path '*/venv/*' -not -path '*/backups/*' -not -path '*/.deploy-*')

find "$DIR" -maxdepth 3 \( -name 'ausencias.json' -o -name 'channel_map.json' \) -not -path '*/venv/*' -not -path '*/backups/*' -not -path '*/.deploy-*' | while IFS= read -r f; do
  rel="${f#$DIR/}"
  cp "$f" "$OUT/${rel//\//__}"
done

tar czf "$OUT/codigo.tar.gz" -C "$DIR" --exclude='venv' --exclude='backups' --exclude='.deploy-backups' --exclude='.deploy-staging' --exclude='__pycache__' --exclude='logs' --exclude='.env' --exclude='.env.*' --exclude='*.key' --exclude='*.db' --exclude='*.db-wal' --exclude='*.db-shm' --exclude='*.log' .
rc=$?
if [ "$rc" -gt 1 ]; then
  echo "ERRO: tar falhou (codigo $rc)"
  exit 1
fi

if [ "$n" -eq 0 ]; then
  echo "AVISO: nenhum arquivo .db encontrado em $DIR"
fi
echo "BANCOS_COPIADOS=$n"
ls -la "$OUT"
exit 0
'@
$remoteScript = ($remoteScript -replace "`r", "") + "`n"
# Envia em base64 para nao sofrer com quebras de linha do Windows (CRLF)
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($remoteScript))

$saida = ssh @SSH_OPTS $REMOTE "echo $b64 | base64 -d | bash -s -- $TS $REMOTE_DIR"
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERRO] O backup falhou no servidor:" -ForegroundColor Red
    $saida | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    exit 1
}
$saida | ForEach-Object { Write-Host "    $_" }

$bancos = 0
$linhaBancos = $saida | Where-Object { $_ -like "BANCOS_COPIADOS=*" } | Select-Object -First 1
if ($linhaBancos) { $bancos = [int]($linhaBancos -replace "BANCOS_COPIADOS=", "") }
if ($bancos -eq 0) {
    Write-Host "  [ERRO] Nenhum banco .db foi encontrado no servidor. Por seguranca, parei aqui." -ForegroundColor Red
    exit 2
}

# -- 3. Baixa o backup para o seu PC -----------------------------------------
Write-Host ""
Write-Host "[3/3] Baixando backup para o seu PC..." -ForegroundColor Yellow

$destRoot = Join-Path $LOCAL_DIR "backups"
New-Item -ItemType Directory -Force -Path $destRoot | Out-Null

scp @SSH_OPTS -r "${REMOTE}:${REMOTE_DIR}/backups/${TS}" $destRoot
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERRO] Falha ao baixar o backup." -ForegroundColor Red
    exit 1
}

$tarLocal = Join-Path $destRoot "$TS\codigo.tar.gz"
if (-not (Test-Path $tarLocal) -or (Get-Item $tarLocal).Length -le 0) {
    Write-Host "  [ERRO] O backup baixado esta incompleto (codigo.tar.gz ausente ou vazio)." -ForegroundColor Red
    exit 1
}

Set-Content -Path (Join-Path $destRoot "ULTIMO.txt") -Value $TS -Encoding ASCII

Write-Host ""
Write-Host "  Backup salvo em: $destRoot\$TS" -ForegroundColor Green
Get-ChildItem (Join-Path $destRoot $TS) | ForEach-Object {
    Write-Host ("    {0}  ({1:N0} bytes)" -f $_.Name, $_.Length)
}
Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  BACKUP OK" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""
exit 0
