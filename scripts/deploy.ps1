# deploy.ps1 - Publica o bot no servidor Oracle a partir do Windows.
# Uso: .\deploy.ps1
#
# Envia SOMENTE os arquivos versionados no git (git archive HEAD): nunca leva
# .env, chaves, bancos ou JSON de estado. No servidor, scripts/remote_deploy.sh
# faz backup dos bancos, guarda um snapshot do codigo atual, instala as
# dependencias, reinicia e, se o bot nao subir, restaura a versao anterior.
#
# Alternativa sem PC: GitHub > Actions > Deploy > Run workflow.

$ErrorActionPreference = "Stop"

$SSH_KEY    = "$PSScriptRoot\oracle.key"
$REMOTE     = "ubuntu@163.176.143.142"
$LOCAL_DIR  = Split-Path $PSScriptRoot -Parent
$SSH_OPTS   = @("-i", $SSH_KEY, "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=20")
$STAMP      = Get-Date -Format "yyyyMMdd-HHmmss"
$TAR_LOCAL  = Join-Path $env:TEMP "farmbot-release-$STAMP.tar"
$TAR_REMOTE = "/tmp/farmbot-release-$STAMP.tar"
$SCRIPT_REMOTE = "/tmp/farmbot-remote-deploy-$STAMP.sh"

function Invoke-Checked {
    param([string]$Descricao, [scriptblock]$Comando)
    & $Comando
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERRO] $Descricao (codigo $LASTEXITCODE). Deploy abortado." -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  Deploy - Bot Morro do Mineiro" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $SSH_KEY)) {
    Write-Host "  [ERRO] Chave SSH nao encontrada em $SSH_KEY" -ForegroundColor Red
    exit 1
}

Push-Location $LOCAL_DIR
try {
    $pendentes = git status --porcelain
    if ($pendentes) {
        Write-Host "  [AVISO] Ha alteracoes nao commitadas. Elas NAO serao enviadas:" -ForegroundColor Yellow
        $pendentes | ForEach-Object { Write-Host "    $_" -ForegroundColor Yellow }
        $resp = Read-Host "  Continuar com o ultimo commit? (s/N)"
        if ($resp -ne "s") { exit 1 }
    }

    Write-Host "[1/3] Gerando release do commit $(git rev-parse --short HEAD)..." -ForegroundColor Yellow
    Invoke-Checked "git archive" { git archive --format=tar -o $TAR_LOCAL HEAD }

    Write-Host "[2/3] Enviando para o servidor..." -ForegroundColor Yellow
    Invoke-Checked "envio da release" { scp @SSH_OPTS $TAR_LOCAL "${REMOTE}:${TAR_REMOTE}" }
    Invoke-Checked "envio do script" { scp @SSH_OPTS "$PSScriptRoot\remote_deploy.sh" "${REMOTE}:${SCRIPT_REMOTE}" }

    Write-Host "[3/3] Aplicando no servidor..." -ForegroundColor Yellow
    Write-Host ""
    # sed remove CR caso o script tenha sido salvo com quebra de linha do Windows.
    ssh @SSH_OPTS $REMOTE "sed -i 's/\r$//' $SCRIPT_REMOTE && bash $SCRIPT_REMOTE $TAR_REMOTE; rc=`$?; rm -f $SCRIPT_REMOTE; exit `$rc"
    $rc = $LASTEXITCODE
}
finally {
    Remove-Item $TAR_LOCAL -ErrorAction SilentlyContinue
    Pop-Location
}

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
if ($rc -eq 0) {
    Write-Host "  STATUS: ONLINE - deploy concluido." -ForegroundColor Green
} else {
    Write-Host "  [ERRO] Deploy falhou (codigo $rc). Veja o log acima." -ForegroundColor Red
    Write-Host "  Se o bot nao subiu, a versao anterior foi restaurada." -ForegroundColor Red
}
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""
exit $rc
