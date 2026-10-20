# rollback_deploy.ps1 - Restaura um backup criado por scripts/deploy.ps1.
# Requer confirmacao explicita porque altera producao e reinicia o servico.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupId,
    [switch]$ConfirmedByUser,
    [string]$KnownHostsFile = $env:MORRO_BOT_KNOWN_HOSTS
)

$ErrorActionPreference = "Stop"

$PROJECT_DIR = Split-Path $PSScriptRoot -Parent
$SSH_KEY = Join-Path $PROJECT_DIR "oracle.key"
$REMOTE_HOST = "163.176.143.142"
$REMOTE_USER = "ubuntu"
$REMOTE = "${REMOTE_USER}@${REMOTE_HOST}"
$REMOTE_DIR = "/home/ubuntu/farmbot"
$SERVICE_NAME = "farmbot"

function Stop-WithError {
    param([string]$Message)

    Write-Host "[ERRO] $Message" -ForegroundColor Red
    exit 1
}

if ($BackupId -notmatch '^[0-9]{14}-[0-9a-f]{7,40}$') {
    Stop-WithError "Identificador de backup invalido."
}

if (-not (Get-Command "ssh" -ErrorAction SilentlyContinue)) {
    Stop-WithError "Comando obrigatorio nao encontrado: ssh"
}

if (-not (Test-Path -LiteralPath $SSH_KEY -PathType Leaf)) {
    Stop-WithError "Chave SSH nao encontrada no caminho configurado."
}

$sshOptions = @(
    "-i", $SSH_KEY,
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=yes"
)
if (-not [string]::IsNullOrWhiteSpace($KnownHostsFile)) {
    if (-not (Test-Path -LiteralPath $KnownHostsFile -PathType Leaf)) {
        Stop-WithError "Arquivo known_hosts configurado nao foi encontrado."
    }
    $resolvedKnownHosts = (Resolve-Path -LiteralPath $KnownHostsFile).Path
    $sshOptions += @("-o", "UserKnownHostsFile=$resolvedKnownHosts")
}

if (-not $ConfirmedByUser) {
    $expected = "ROLLBACK $BackupId"
    $confirmation = Read-Host "Digite '$expected' para acessar producao e restaurar"
    if ($confirmation -cne $expected) {
        Stop-WithError "Confirmacao invalida; nenhum acesso remoto foi realizado."
    }
}

$backupDir = "$REMOTE_DIR/.deploy-backups/$BackupId"
$rollbackCommand = @"
set -eu
test -d '$backupDir/files'
cp -a '$backupDir/files/.' '$REMOTE_DIR/'
if [ -f '$backupDir/new-files.txt' ]; then
  while IFS= read -r path; do
    if [ -n "`$path" ]; then
      rm -f "$REMOTE_DIR/`$path"
    fi
  done < '$backupDir/new-files.txt'
fi
sudo systemctl restart '$SERVICE_NAME'
"@

& ssh @sshOptions $REMOTE $rollbackCommand
if ($LASTEXITCODE -ne 0) {
    Stop-WithError "Rollback remoto ou restart falhou."
}

Start-Sleep -Seconds 3
$statusOutput = @(& ssh @sshOptions $REMOTE "systemctl is-active '$SERVICE_NAME'")
$statusCode = $LASTEXITCODE
$status = ($statusOutput -join "`n").Trim()
if ($statusCode -ne 0 -or $status -ne "active") {
    Stop-WithError "Arquivos restaurados, mas o servico nao confirmou estado active."
}

Write-Host "Rollback concluido e servico ativo." -ForegroundColor Green
