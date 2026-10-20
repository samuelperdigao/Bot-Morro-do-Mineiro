# deploy.ps1 - Publica um commit validado e reinicia o bot no servidor Oracle.
# Uso interativo: pwsh scripts/deploy.ps1
# Uso por agente: -ConfirmedByUser somente apos confirmacao explicita na conversa atual.

[CmdletBinding()]
param(
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

$runtimeRoots = @(
    "assets/",
    "cogs/",
    "config/",
    "core/",
    "features/",
    "infrastructure/",
    "services/",
    "ui/"
)
$runtimeFiles = @("main.py", "requirements.txt")

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

function Invoke-RemoteRollback {
    param(
        [string[]]$SshOptions,
        [string]$BackupDir
    )

    $rollbackCommand = @"
set -eu
test -d '$BackupDir/files'
cp -a '$BackupDir/files/.' '$REMOTE_DIR/'
if [ -f '$BackupDir/new-files.txt' ]; then
  while IFS= read -r path; do
    if [ -n "`$path" ]; then
      rm -f "$REMOTE_DIR/`$path"
    fi
  done < '$BackupDir/new-files.txt'
fi
"@

    & ssh @SshOptions $REMOTE $rollbackCommand | Out-Host
    return $LASTEXITCODE
}

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  Deploy seguro - Bot Morro do Mineiro" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

foreach ($command in @("git", "ssh", "scp")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        Stop-WithError "Comando obrigatorio nao encontrado: $command"
    }
}

if (-not (Test-Path -LiteralPath $SSH_KEY -PathType Leaf)) {
    Stop-WithError "Chave SSH nao encontrada no caminho configurado."
}

$repoRoot = (& git -C $PROJECT_DIR rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($repoRoot)) {
    Stop-WithError "O diretorio do projeto nao e um repositorio Git valido."
}

$resolvedProject = (Resolve-Path -LiteralPath $PROJECT_DIR).Path.TrimEnd("\")
$resolvedRepo = (Resolve-Path -LiteralPath $repoRoot.Trim()).Path.TrimEnd("\")
if ($resolvedProject -ne $resolvedRepo) {
    Stop-WithError "O script deve ser executado na raiz do repositorio esperado."
}

$workingChanges = @(& git -C $PROJECT_DIR status --porcelain --untracked-files=all)
if ($LASTEXITCODE -ne 0) {
    Stop-WithError "Nao foi possivel verificar o estado da arvore de trabalho."
}
if ($workingChanges.Count -gt 0) {
    Stop-WithError "Deploy recusado: a arvore de trabalho possui alteracoes ou arquivos nao rastreados."
}

& git -C $PROJECT_DIR diff --check
if ($LASTEXITCODE -ne 0) {
    Stop-WithError "Deploy recusado: git diff --check encontrou problemas."
}

$commit = (& git -C $PROJECT_DIR rev-parse HEAD).Trim()
$shortCommit = (& git -C $PROJECT_DIR rev-parse --short=12 HEAD).Trim()
$branch = (& git -C $PROJECT_DIR branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($commit)) {
    Stop-WithError "Nao foi possivel identificar o commit de deploy."
}
if ([string]::IsNullOrWhiteSpace($branch)) {
    Stop-WithError "Deploy recusado: HEAD destacado. Use uma branch identificada."
}

$parentCommit = (& git -C $PROJECT_DIR rev-parse "${commit}^" 2>$null).Trim()
$parentCommitExitCode = $LASTEXITCODE
if ($parentCommitExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($parentCommit)) {
    & git -C $PROJECT_DIR diff --check $parentCommit $commit --
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "Deploy recusado: o diff do commit aprovado possui problemas de whitespace."
    }
}

$python = Join-Path $PROJECT_DIR "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Stop-WithError "Python da venv nao encontrado; execute o onboarding local antes do deploy."
}

Write-Host "[1/5] Executando validacao local..." -ForegroundColor Yellow
Push-Location $PROJECT_DIR
try {
    & $python -m pytest tests/ -q
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "Deploy recusado: os testes locais falharam."
    }
} finally {
    Pop-Location
}

$postTestChanges = @(& git -C $PROJECT_DIR status --porcelain --untracked-files=all)
$postTestCommit = (& git -C $PROJECT_DIR rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $postTestChanges.Count -gt 0 -or $postTestCommit -ne $commit) {
    Stop-WithError "Deploy recusado: o repositorio mudou durante a validacao local."
}

$trackedPaths = @(& git -C $PROJECT_DIR ls-files)
if ($LASTEXITCODE -ne 0) {
    Stop-WithError "Nao foi possivel montar o manifesto de arquivos rastreados."
}

$deployPaths = @(
    $trackedPaths |
        ForEach-Object { $_.Trim().Replace("\", "/") } |
        Where-Object {
            $path = $_
            ($runtimeFiles -contains $path) -or
            ($runtimeRoots | Where-Object { $path.StartsWith($_, [System.StringComparison]::Ordinal) })
        } |
        Sort-Object -Unique
)

if ($deployPaths.Count -eq 0) {
    Stop-WithError "O manifesto de deploy ficou vazio."
}

foreach ($relativePath in $deployPaths) {
    if ($relativePath -notmatch '^[A-Za-z0-9._/-]+$' -or $relativePath -match '(^|/)\.\.(/|$)') {
        Stop-WithError "Caminho rastreado nao suportado pelo deploy seguro: $relativePath"
    }
    $localPath = Join-Path $PROJECT_DIR $relativePath.Replace('/', [IO.Path]::DirectorySeparatorChar)
    if (-not (Test-Path -LiteralPath $localPath -PathType Leaf)) {
        Stop-WithError "Arquivo rastreado nao encontrado no disco: $relativePath"
    }
    $expectedBlob = (& git -C $PROJECT_DIR rev-parse "${commit}:$relativePath").Trim()
    $actualBlob = (& git -C $PROJECT_DIR hash-object -- $localPath).Trim()
    if ($LASTEXITCODE -ne 0 -or $actualBlob -ne $expectedBlob) {
        Stop-WithError "Arquivo local diverge do commit aprovado: $relativePath"
    }
}

Write-Host "  Branch: $branch"
Write-Host "  Commit: $shortCommit"
Write-Host "  Arquivos no manifesto: $($deployPaths.Count)"
Write-Host "  Destino: producao (identificador mascarado)"

if (-not $ConfirmedByUser) {
    Write-Host ""
    $expected = "DEPLOY $shortCommit"
    $confirmation = Read-Host "Digite '$expected' para iniciar SSH e publicar"
    if ($confirmation -cne $expected) {
        Stop-WithError "Confirmacao invalida; nenhum acesso remoto foi realizado."
    }
} else {
    Write-Host "  Confirmacao externa declarada pelo operador." -ForegroundColor Yellow
}

$sshOptions = Get-SshOptions
$backupId = "$(Get-Date -Format 'yyyyMMddHHmmss')-$shortCommit"
$backupDir = "$REMOTE_DIR/.deploy-backups/$backupId"
$stagingDir = "$REMOTE_DIR/.deploy-staging/$backupId"

Write-Host "[2/6] Preparando staging e backup remoto..." -ForegroundColor Yellow
$prepareCommand = "set -eu; mkdir -p '$backupDir/files' '$stagingDir/files'; printf '%s\n' '$commit' > '$backupDir/target-commit.txt'"
& ssh @sshOptions $REMOTE $prepareCommand
if ($LASTEXITCODE -ne 0) {
    Stop-WithError "Nao foi possivel preparar staging e backup remoto."
}

Write-Host "[3/6] Enviando e verificando o manifesto validado..." -ForegroundColor Yellow
$count = 0
foreach ($relativePath in $deployPaths) {
    $count++
    $localPath = Join-Path $PROJECT_DIR $relativePath.Replace('/', [IO.Path]::DirectorySeparatorChar)
    $lastSlash = $relativePath.LastIndexOf('/')
    $relativeDir = if ($lastSlash -ge 0) { $relativePath.Substring(0, $lastSlash) } else { "" }
    $stagingFolder = if ($relativeDir) { "$stagingDir/files/$relativeDir" } else { "$stagingDir/files" }
    $stagingPath = "$stagingDir/files/$relativePath"

    $expectedBlob = (& git -C $PROJECT_DIR rev-parse "${commit}:$relativePath").Trim()
    $actualBlob = (& git -C $PROJECT_DIR hash-object -- $localPath).Trim()
    if ($LASTEXITCODE -ne 0 -or $actualBlob -ne $expectedBlob) {
        Stop-WithError "Arquivo mudou depois da confirmacao: $relativePath"
    }

    $localSha256 = (Get-FileHash -LiteralPath $localPath -Algorithm SHA256).Hash.ToLowerInvariant()

    Write-Progress -Activity "Enviando arquivos rastreados" -Status $relativePath -PercentComplete (($count / $deployPaths.Count) * 100)

    & ssh @sshOptions $REMOTE "mkdir -p '$stagingFolder'"
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "Falha ao preparar staging para $relativePath."
    }

    & scp @sshOptions $localPath "${REMOTE}:${stagingPath}"
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "Falha ao enviar $relativePath para staging; producao nao foi alterada."
    }

    $remoteHashOutput = @(& ssh @sshOptions $REMOTE "sha256sum '$stagingPath' | cut -d' ' -f1")
    $remoteHashCode = $LASTEXITCODE
    $remoteSha256 = ($remoteHashOutput -join "`n").Trim().ToLowerInvariant()
    if ($remoteHashCode -ne 0 -or $remoteSha256 -ne $localSha256) {
        Stop-WithError "Integridade do staging falhou para $relativePath; producao nao foi alterada."
    }
}
Write-Progress -Activity "Enviando arquivos rastreados" -Completed

Write-Host "[4/6] Ativando arquivos com backup..." -ForegroundColor Yellow
foreach ($relativePath in $deployPaths) {
    $remotePath = "$REMOTE_DIR/$relativePath"
    $stagingPath = "$stagingDir/files/$relativePath"
    $backupPath = "$backupDir/files/$relativePath"
    $lastSlash = $relativePath.LastIndexOf('/')
    $relativeDir = if ($lastSlash -ge 0) { $relativePath.Substring(0, $lastSlash) } else { "" }
    $remoteFolder = if ($relativeDir) { "$REMOTE_DIR/$relativeDir" } else { $REMOTE_DIR }
    $backupFolder = if ($relativeDir) { "$backupDir/files/$relativeDir" } else { "$backupDir/files" }

    $activateCommand = @"
set -eu
mkdir -p '$remoteFolder' '$backupFolder'
if [ -f '$remotePath' ]; then
  cp -p '$remotePath' '$backupPath'
else
  printf '%s\n' '$relativePath' >> '$backupDir/new-files.txt'
fi
cp -p '$stagingPath' '$remotePath'
"@
    & ssh @sshOptions $REMOTE $activateCommand
    if ($LASTEXITCODE -ne 0) {
        [void](Invoke-RemoteRollback -SshOptions $sshOptions -BackupDir $backupDir)
        Stop-WithError "Falha ao ativar $relativePath; arquivos anteriores foram restaurados."
    }
}

Write-Host "[5/6] Instalando dependencias versionadas..." -ForegroundColor Yellow
& ssh @sshOptions $REMOTE "set -eu; cd '$REMOTE_DIR'; '$REMOTE_DIR/venv/bin/pip' install -r requirements.txt -q"
if ($LASTEXITCODE -ne 0) {
    [void](Invoke-RemoteRollback -SshOptions $sshOptions -BackupDir $backupDir)
    Stop-WithError "Falha ao instalar dependencias; arquivos anteriores foram restaurados."
}

Write-Host "[6/6] Reiniciando e verificando o servico..." -ForegroundColor Yellow
& ssh @sshOptions $REMOTE "sudo systemctl restart '$SERVICE_NAME'"
if ($LASTEXITCODE -ne 0) {
    [void](Invoke-RemoteRollback -SshOptions $sshOptions -BackupDir $backupDir)
    & ssh @sshOptions $REMOTE "sudo systemctl restart '$SERVICE_NAME'" | Out-Host
    Stop-WithError "Falha no restart; rollback automatico solicitado."
}

Start-Sleep -Seconds 3
$statusOutput = @(& ssh @sshOptions $REMOTE "systemctl is-active '$SERVICE_NAME'")
$statusCode = $LASTEXITCODE
$status = ($statusOutput -join "`n").Trim()

if ($statusCode -ne 0 -or $status -ne "active") {
    $rollbackCode = Invoke-RemoteRollback -SshOptions $sshOptions -BackupDir $backupDir
    if ($rollbackCode -eq 0) {
        & ssh @sshOptions $REMOTE "sudo systemctl restart '$SERVICE_NAME'" | Out-Host
    }
    Stop-WithError "A nova versao nao ficou ativa; rollback automatico solicitado."
}

Write-Host ""
Write-Host "Deploy concluido com sucesso." -ForegroundColor Green
Write-Host "Commit publicado: $shortCommit"
Write-Host "Backup de rollback: $backupId"
Write-Host "Rollback manual: pwsh scripts/rollback_deploy.ps1 -BackupId '$backupId'"
