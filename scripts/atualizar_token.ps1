# atualizar_token.ps1 - Valida e atualiza somente DISCORD_TOKEN em producao.
# O .env completo nunca e enviado, exibido ou copiado por este script.

[CmdletBinding()]
param(
    [switch]$ConfirmedByUser,
    [string]$KnownHostsFile = $env:MORRO_BOT_KNOWN_HOSTS
)

$ErrorActionPreference = "Stop"

$PROJECT_DIR = Split-Path $PSScriptRoot -Parent
$SSH_KEY = Join-Path $PROJECT_DIR "oracle.key"
$LOCAL_ENV = Join-Path $PROJECT_DIR ".env"
$REMOTE_HOST = "163.176.143.142"
$REMOTE_USER = "ubuntu"
$REMOTE = "${REMOTE_USER}@${REMOTE_HOST}"
$REMOTE_DIR = "/home/ubuntu/farmbot"
$REMOTE_ENV = "$REMOTE_DIR/.env"
$REMOTE_TOKEN_ENV = "$REMOTE_DIR/.env.token"
$SERVICE_NAME = "farmbot"

function Stop-WithError {
    param([string]$Message)

    Write-Host "[ERRO] $Message" -ForegroundColor Red
    exit 1
}

function Get-SshOptions {
    $options = @(
        "-i", $SSH_KEY,
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes"
    )

    if (-not [string]::IsNullOrWhiteSpace($KnownHostsFile)) {
        if (-not (Test-Path -LiteralPath $KnownHostsFile -PathType Leaf)) {
            Stop-WithError "Arquivo known_hosts configurado nao foi encontrado."
        }
        $resolvedKnownHosts = (Resolve-Path -LiteralPath $KnownHostsFile).Path
        $options += @("-o", "UserKnownHostsFile=$resolvedKnownHosts")
    }

    return $options
}

function Protect-LocalSecretFile {
    param([string]$Path)

    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $acl = [System.Security.AccessControl.FileSecurity]::new()
    $acl.SetOwner($identity.User)
    $acl.SetAccessRuleProtection($true, $false)
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
        $identity.User,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.Security.AccessControl.AccessControlType]::Allow
    )
    [void]$acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Invoke-TokenRollback {
    param(
        [string[]]$SshOptions,
        [string]$PreviousTokenPath,
        [string]$RemoteTokenPath,
        [string]$NewTokenMarker
    )

    $rollbackCommand = @"
set -eu
if [ -f '$PreviousTokenPath' ]; then
  mv -f '$PreviousTokenPath' '$REMOTE_TOKEN_ENV'
  rm -f '$RemoteTokenPath' '$NewTokenMarker'
  exit 0
elif [ -f '$NewTokenMarker' ]; then
  rm -f '$REMOTE_TOKEN_ENV'
  rm -f '$RemoteTokenPath' '$NewTokenMarker'
  exit 0
elif [ -f '$RemoteTokenPath' ]; then
  rm -f '$RemoteTokenPath'
  exit 0
fi
exit 10
"@

    & ssh @SshOptions $REMOTE $rollbackCommand | Out-Host
    return $LASTEXITCODE
}

function Invoke-TokenCleanup {
    param(
        [string[]]$SshOptions,
        [string]$PreviousTokenPath,
        [string]$RemoteTokenPath,
        [string]$NewTokenMarker
    )

    $cleanupCommand = @"
set -eu
rm -f '$RemoteTokenPath' '$NewTokenMarker' '$PreviousTokenPath'
"@

    & ssh @SshOptions $REMOTE $cleanupCommand | Out-Host
    return $LASTEXITCODE
}

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  Atualizacao segura de token" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

foreach ($command in @("ssh", "scp")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        Stop-WithError "Comando obrigatorio nao encontrado: $command"
    }
}

if (-not (Test-Path -LiteralPath $LOCAL_ENV -PathType Leaf)) {
    Stop-WithError ".env local nao encontrado."
}
if (-not (Test-Path -LiteralPath $SSH_KEY -PathType Leaf)) {
    Stop-WithError "Chave SSH nao encontrada no caminho configurado."
}

$tokenLine = Get-Content -LiteralPath $LOCAL_ENV |
    Where-Object { $_ -match '^DISCORD_TOKEN=' } |
    Select-Object -First 1
if (-not $tokenLine) {
    Stop-WithError "A variavel DISCORD_TOKEN nao foi encontrada no .env local."
}

$token = ($tokenLine -replace '^DISCORD_TOKEN=', '').Trim().Trim('"').Trim("'")
if ([string]::IsNullOrWhiteSpace($token)) {
    Stop-WithError "A variavel DISCORD_TOKEN esta vazia."
}

Write-Host "  Operacao: substituir somente DISCORD_TOKEN"
Write-Host "  Destino: producao (identificador mascarado)"
Write-Host "  O arquivo .env completo nao sera enviado."

if (-not $ConfirmedByUser) {
    Write-Host ""
    $expected = "ATUALIZAR TOKEN"
    $confirmation = Read-Host "Digite '$expected' para validar o token e iniciar o acesso externo"
    if ($confirmation -cne $expected) {
        Stop-WithError "Confirmacao invalida; nenhum acesso externo foi realizado."
    }
} else {
    Write-Host "  Confirmacao externa declarada pelo operador." -ForegroundColor Yellow
}

$sha = [System.Security.Cryptography.SHA256]::Create()
try {
    $tokenBytes = [System.Text.Encoding]::UTF8.GetBytes($token)
    $localHash = (($sha.ComputeHash($tokenBytes) | ForEach-Object { $_.ToString("x2") }) -join "")
} finally {
    $sha.Dispose()
}

Write-Host "[1/4] Validando credencial na API do Discord..." -ForegroundColor Yellow
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try {
    [void](Invoke-RestMethod -Uri "https://discord.com/api/v10/users/@me" `
        -Headers @{ Authorization = "Bot $token" } `
        -Method Get -TimeoutSec 20 -ErrorAction Stop)
} catch {
    $code = $null
    if ($_.Exception.Response) {
        $code = $_.Exception.Response.StatusCode.value__
    }
    Stop-WithError "Token recusado pelo Discord (HTTP $code); nada foi enviado ao servidor."
}
Write-Host "  Credencial validada; valor mantido oculto." -ForegroundColor Green

$sshOptions = Get-SshOptions
$suffix = [Guid]::NewGuid().ToString("N")
$localTokenPath = Join-Path ([IO.Path]::GetTempPath()) "morro-discord-token-$suffix.tmp"
$remoteTokenPath = "$REMOTE_DIR/.discord-token-$suffix.tmp"
$previousTokenPath = "$REMOTE_DIR/.discord-token-previous-$suffix.tmp"
$newTokenMarker = "$REMOTE_DIR/.discord-token-new-$suffix.marker"
$remoteTransferAttempted = $false
$remoteSwapAttempted = $false
$failureMessage = $null

try {
    [IO.File]::Create($localTokenPath).Dispose()
    Protect-LocalSecretFile -Path $localTokenPath
    [IO.File]::WriteAllText(
        $localTokenPath,
        "DISCORD_TOKEN=$token`n",
        [System.Text.UTF8Encoding]::new($false)
    )

    Write-Host "[2/4] Enviando somente a credencial selecionada..." -ForegroundColor Yellow
    $remoteTransferAttempted = $true
    & scp @sshOptions $localTokenPath "${REMOTE}:${remoteTokenPath}"
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao transferir a credencial selecionada."
    }

    & ssh @sshOptions $REMOTE "chmod 600 '$remoteTokenPath'"
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao restringir o arquivo temporario remoto."
    }

    Write-Host "[3/4] Atualizando DISCORD_TOKEN de forma atomica..." -ForegroundColor Yellow
    $updateCommand = @"
set -eu
test -f '$REMOTE_ENV'
test -s '$remoteTokenPath'
umask 077
if [ -f '$REMOTE_TOKEN_ENV' ]; then
  cp -p '$REMOTE_TOKEN_ENV' '$previousTokenPath'
else
  : > '$newTokenMarker'
  chmod 600 '$newTokenMarker'
fi
chown --reference='$REMOTE_ENV' '$remoteTokenPath'
chmod 600 '$remoteTokenPath'
mv -f '$remoteTokenPath' '$REMOTE_TOKEN_ENV'
"@
    $remoteSwapAttempted = $true
    & ssh @sshOptions $REMOTE $updateCommand
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao atualizar a variavel remota; o servico nao foi reiniciado."
    }

    $hashCommand = @'
set -eu
token="$(grep '^DISCORD_TOKEN=' '__REMOTE_TOKEN_ENV__' | head -n 1 | cut -d= -f2-)"
printf '%s' "$token" | sha256sum | cut -d' ' -f1
'@.Replace('__REMOTE_TOKEN_ENV__', $REMOTE_TOKEN_ENV)
    $remoteHashOutput = @(& ssh @sshOptions $REMOTE $hashCommand)
    $hashExitCode = $LASTEXITCODE
    $remoteHash = ($remoteHashOutput -join "`n").Trim()
    if ($hashExitCode -ne 0 -or $remoteHash -ne $localHash) {
        throw "A verificacao remota da credencial falhou."
    }

    Write-Host "[4/4] Reiniciando e verificando o servico..." -ForegroundColor Yellow
    & ssh @sshOptions $REMOTE "sudo systemctl reset-failed '$SERVICE_NAME'; sudo systemctl restart '$SERVICE_NAME'"
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao reiniciar o servico com a nova credencial."
    }

    Start-Sleep -Seconds 12
    $statusOutput = @(& ssh @sshOptions $REMOTE "systemctl is-active '$SERVICE_NAME'")
    $statusCode = $LASTEXITCODE
    $status = ($statusOutput -join "`n").Trim()
    if ($statusCode -ne 0 -or $status -ne "active") {
        throw "O servico nao confirmou estado active com a nova credencial."
    }

    $cleanupCode = Invoke-TokenCleanup `
        -SshOptions $sshOptions `
        -PreviousTokenPath $previousTokenPath `
        -RemoteTokenPath $remoteTokenPath `
        -NewTokenMarker $newTokenMarker
    if ($cleanupCode -ne 0) {
        throw "A limpeza remota da credencial nao foi confirmada."
    }

    Write-Host "Token atualizado e servico ativo; valor mantido oculto." -ForegroundColor Green
} catch {
    $failureMessage = $_.Exception.Message

    if ($remoteTransferAttempted) {
        Write-Host "  Falha detectada; restaurando a credencial anterior..." -ForegroundColor Yellow
        $rollbackCode = Invoke-TokenRollback `
            -SshOptions $sshOptions `
            -PreviousTokenPath $previousTokenPath `
            -RemoteTokenPath $remoteTokenPath `
            -NewTokenMarker $newTokenMarker
        if ($rollbackCode -eq 0) {
            if ($remoteSwapAttempted) {
                & ssh @sshOptions $REMOTE "sudo systemctl reset-failed '$SERVICE_NAME'; sudo systemctl restart '$SERVICE_NAME'" | Out-Host
                if ($LASTEXITCODE -ne 0) {
                    Write-Host "[ERRO] A credencial anterior foi restaurada, mas o servico nao reiniciou; intervencao manual e necessaria." -ForegroundColor Red
                }
            }
        } elseif ($rollbackCode -eq 10) {
            Write-Host "  Nenhum artefato temporario remoto pendente foi encontrado; nenhuma restauracao adicional foi necessaria." -ForegroundColor Yellow
        } else {
            Write-Host "[ERRO] Nao foi possivel confirmar rollback ou limpeza; a credencial anterior foi preservada para recuperacao manual." -ForegroundColor Red
        }
    }
} finally {
    if (Test-Path -LiteralPath $localTokenPath -PathType Leaf) {
        [IO.File]::Delete($localTokenPath)
    }
    $token = $null
    $tokenLine = $null
    $tokenBytes = $null
}

if ($failureMessage) {
    Stop-WithError $failureMessage
}
