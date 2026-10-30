# rollback.ps1 - Volta o codigo do servidor ao estado do ultimo backup.
# Uso: .\rollback.ps1                 (restaura so o CODIGO do ultimo backup)
#      .\rollback.ps1 -Banco          (restaura tambem os bancos .db - PERDE dados lancados depois do backup)
#      .\rollback.ps1 -Backup 20261030_120000   (escolhe um backup especifico da pasta backups\)
# A pasta data\ e os segredos do servidor nao sao alterados ao restaurar o codigo.

param([string]$Backup = "", [switch]$Banco)

$SSH_KEY    = Join-Path $PSScriptRoot "oracle.key"
$REMOTE     = "ubuntu@163.176.143.142"
$REMOTE_DIR = "/home/ubuntu/farmbot"
$LOCAL_DIR  = $PSScriptRoot
$SSH_OPTS   = @("-i", $SSH_KEY, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes")
if ($env:MORRO_BOT_KNOWN_HOSTS) { $SSH_OPTS += @("-o", "UserKnownHostsFile=$env:MORRO_BOT_KNOWN_HOSTS") }

$backupsDir = Join-Path $LOCAL_DIR "backups"

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  Rollback - Bot Morro do Mineiro" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

if (-not $Backup) {
    $arq = Join-Path $backupsDir "ULTIMO.txt"
    if (-not (Test-Path $arq)) {
        Write-Host "  [ERRO] Nenhum backup encontrado em $backupsDir" -ForegroundColor Red
        exit 1
    }
    $Backup = (Get-Content $arq -Raw).Trim()
}

# Se existe deploy pendente, o backup certo e o do "antes de tudo"
$pendente = Join-Path $backupsDir "deploy_pendente.txt"
if (Test-Path $pendente) {
    $tsPend = (Get-Content $pendente -Raw).Trim()
    if ($tsPend -and -not $PSBoundParameters.ContainsKey("Backup")) { $Backup = $tsPend }
}

$tarLocal = Join-Path $backupsDir "$Backup\codigo.tar.gz"
if (-not (Test-Path $tarLocal)) {
    Write-Host "  [ERRO] Backup '$Backup' nao encontrado. Disponiveis:" -ForegroundColor Red
    Get-ChildItem $backupsDir -Directory | ForEach-Object { Write-Host "    $($_.Name)" }
    exit 1
}

Write-Host "  Backup que sera restaurado: $Backup" -ForegroundColor Yellow
Write-Host "  - O CODIGO do servidor volta para o estado desse backup." -ForegroundColor Yellow
if ($Banco) {
    Write-Host "  - Os BANCOS tambem voltam. Tudo que foi lancado no bot depois do backup SERA PERDIDO." -ForegroundColor Red
} else {
    Write-Host "  - Os bancos NAO sao alterados (as tabelas novas ficam la e nao atrapalham o codigo antigo)." -ForegroundColor Yellow
}
Write-Host ""
$ok = Read-Host "  Digite SIM para continuar"
if ($ok -ne "SIM") {
    Write-Host "  Cancelado. Nada foi alterado." -ForegroundColor Yellow
    exit 0
}

# -- 1. Envia o tar ----------------------------------------------------------
Write-Host ""
Write-Host "[1/3] Enviando backup do codigo para o servidor..." -ForegroundColor Yellow
scp @SSH_OPTS $tarLocal "${REMOTE}:/tmp/rollback_${Backup}.tar.gz"
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERRO] Falha ao enviar o backup." -ForegroundColor Red
    exit 1
}

# -- 2. Restaura -------------------------------------------------------------
Write-Host ""
Write-Host "[2/3] Restaurando no servidor..." -ForegroundColor Yellow

$restoreScript = @'
TS="$1"
DIR="$2"
RESTORE_DB="$3"
TAR="/tmp/rollback_$TS.tar.gz"

if [ ! -s "$TAR" ]; then
  echo "ERRO: arquivo $TAR nao encontrado no servidor"
  exit 1
fi

tar xzf "$TAR" -C "$DIR" --exclude='./data' || exit 1
rm -f "$TAR"
find "$DIR" -path '*/venv' -prune -o -name __pycache__ -type d -print0 | xargs -0 -r rm -rf

if [ "$RESTORE_DB" = "1" ]; then
  SRC="$DIR/backups/$TS"
  if [ ! -d "$SRC" ]; then
    echo "ERRO: pasta de backup $SRC nao existe no servidor"
    exit 1
  fi
  sudo systemctl stop farmbot || exit 1
  for f in "$SRC"/*.db; do
    [ -e "$f" ] || continue
    name="$(basename "$f")"
    rel="${name//__//}"
    rm -f "$DIR/$rel-wal" "$DIR/$rel-shm"
    cp "$f" "$DIR/$rel" || exit 1
    echo "BANCO_RESTAURADO=$rel"
  done
fi

echo "RESTORE_OK"
exit 0
'@
$restoreScript = ($restoreScript -replace "`r", "") + "`n"
# Envia em base64 para nao sofrer com quebras de linha do Windows (CRLF)
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($restoreScript))

$flagBanco = "0"
if ($Banco) { $flagBanco = "1" }

$saida = ssh @SSH_OPTS $REMOTE "echo $b64 | base64 -d | bash -s -- $Backup $REMOTE_DIR $flagBanco"
$saida | ForEach-Object { Write-Host "    $_" }
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERRO] A restauracao falhou (veja acima). O servico NAO foi reiniciado." -ForegroundColor Red
    exit 1
}

# -- 3. Reinicia e confere ---------------------------------------------------
Write-Host ""
Write-Host "[3/3] Reiniciando o servico farmbot..." -ForegroundColor Yellow
$inicio = "$(ssh @SSH_OPTS $REMOTE "date '+%Y-%m-%d %H:%M:%S'")".Trim()
ssh @SSH_OPTS $REMOTE "sudo systemctl restart farmbot"

$online = $false
$status = ""
$log    = @()
for ($i = 0; $i -lt 10; $i++) {
    Start-Sleep -Seconds 3
    $status = "$(ssh @SSH_OPTS $REMOTE "systemctl is-active farmbot")".Trim()
    $log    = @(ssh @SSH_OPTS $REMOTE "journalctl -u farmbot --since '$inicio' --no-pager --output=cat")
    if ($status -ne "active") { break }
    if (@($log | Where-Object { $_ -match "Bot online" }).Count -gt 0) { $online = $true; break }
}

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
if ($status -eq "active" -and $online) {
    Remove-Item $pendente -ErrorAction SilentlyContinue
    Write-Host "  ROLLBACK OK - bot online na versao anterior" -ForegroundColor Green
} else {
    Write-Host "  STATUS: $($status.ToUpper()) - confira o log:" -ForegroundColor Red
    $log | Select-Object -Last 20 | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Write-Host "  Me chame com esse log colado." -ForegroundColor Yellow
}
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""
