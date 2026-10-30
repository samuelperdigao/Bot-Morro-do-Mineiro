# deploy_seguro.ps1 - Faz backup dos bancos, publica com scripts\deploy.ps1 e confere o log.
# Uso: .\deploy_seguro.ps1
# O envio fica a cargo de scripts\deploy.ps1, que publica somente arquivos rastreados
# pelo Git: .env, chaves, bancos e dados nunca sobem.
# Se algo der errado depois do envio, use: .\rollback.ps1

$SSH_KEY    = Join-Path $PSScriptRoot "oracle.key"
$REMOTE     = "ubuntu@163.176.143.142"
$LOCAL_DIR  = $PSScriptRoot
$SSH_OPTS   = @("-i", $SSH_KEY, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes")
if ($env:MORRO_BOT_KNOWN_HOSTS) { $SSH_OPTS += @("-o", "UserKnownHostsFile=$env:MORRO_BOT_KNOWN_HOSTS") }

function Falhar([string]$msg) {
    Write-Host ""
    Write-Host "  [ERRO] $msg" -ForegroundColor Red
    Write-Host ""
    exit 1
}

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  Deploy seguro - Bot Morro do Mineiro" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path (Join-Path $LOCAL_DIR "main.py"))) {
    Falhar "main.py nao encontrado ao lado deste script. Rode o script de dentro da pasta do projeto."
}

# Evita um backup inutil quando o deploy seria recusado logo em seguida
$alteracoes = @(git -C $LOCAL_DIR status --porcelain --untracked-files=all)
if ($LASTEXITCODE -ne 0) { Falhar "Nao foi possivel verificar o estado do Git." }
if ($alteracoes.Count -gt 0) {
    Falhar "Ha alteracoes sem commit na pasta. O deploy publica somente commits."
}

# -- 1. Backup ---------------------------------------------------------------
Write-Host "[1/3] Backup do servidor..." -ForegroundColor Yellow

$backupsDir = Join-Path $LOCAL_DIR "backups"
$pendente   = Join-Path $backupsDir "deploy_pendente.txt"
$reaproveitou = $false

if (Test-Path $pendente) {
    $tsAnterior = (Get-Content $pendente -Raw).Trim()
    if ($tsAnterior -and (Test-Path (Join-Path $backupsDir "$tsAnterior\codigo.tar.gz"))) {
        Write-Host "  Deploy anterior nao terminou limpo. Reaproveitando o backup $tsAnterior" -ForegroundColor Yellow
        Write-Host "  (ele guarda o estado de ANTES das suas correcoes, que e o que o rollback precisa)." -ForegroundColor Yellow
        $reaproveitou = $true
    }
}

if (-not $reaproveitou) {
    & (Join-Path $LOCAL_DIR "backup.ps1")
    if ($LASTEXITCODE -ne 0) { Falhar "O backup falhou. Por seguranca o deploy foi cancelado." }
    $tsNovo = (Get-Content (Join-Path $backupsDir "ULTIMO.txt") -Raw).Trim()
    Set-Content -Path $pendente -Value $tsNovo -Encoding ASCII
}

# -- 2. Publicacao -----------------------------------------------------------
Write-Host ""
Write-Host "[2/3] Publicando (testes, manifesto, confirmacao e restart)..." -ForegroundColor Yellow

& (Join-Path $LOCAL_DIR "scripts\deploy.ps1")
if ($LASTEXITCODE -ne 0) {
    Falhar "A publicacao nao foi concluida (veja acima). O backup foi mantido para a proxima tentativa."
}

# -- 3. Verificacao ----------------------------------------------------------
Write-Host ""
Write-Host "[3/3] Conferindo se o bot subiu (ate 30s)..." -ForegroundColor Yellow

# Le o log a partir deste restart, para nao confundir com o processo antigo
$inicio = "$(ssh @SSH_OPTS $REMOTE "systemctl show farmbot -p ActiveEnterTimestamp --value")".Trim()
if (-not $inicio) { $inicio = "-5min" }

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

$erros = @($log | Where-Object { $_ -match "Traceback|Falha ao carregar|\[ERROR\]|NoEntryPoint|ExtensionFailed" })

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan

if ($status -ne "active") {
    Write-Host "  STATUS: $($status.ToUpper())  - O BOT NAO SUBIU" -ForegroundColor Red
    Write-Host ""
    $log | Select-Object -Last 30 | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Write-Host ""
    Write-Host "  Para voltar a versao anterior rode:  .\rollback.ps1" -ForegroundColor Yellow
    Write-Host "======================================" -ForegroundColor Cyan
    exit 1
}

if ($erros.Count -gt 0) {
    Write-Host "  STATUS: ONLINE, MAS O LOG TEM ERROS" -ForegroundColor Yellow
    Write-Host ""
    $erros | Select-Object -First 15 | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
    Write-Host ""
    Write-Host "  Uma extensao pode nao ter carregado. Se algum comando sumiu ou quebrou:" -ForegroundColor Yellow
    Write-Host "  .\rollback.ps1   (volta o codigo ao estado de antes do deploy)" -ForegroundColor Yellow
    Write-Host "======================================" -ForegroundColor Cyan
    exit 1
}

if (-not $online) {
    Write-Host "  STATUS: ACTIVE, mas ainda nao vi a linha 'Bot online' no log." -ForegroundColor Yellow
    Write-Host "  Rode .\deploy_seguro.ps1 de novo so se precisar publicar outra correcao." -ForegroundColor Yellow
    Write-Host "  (o backup deste deploy foi mantido)" -ForegroundColor Yellow
    Write-Host "======================================" -ForegroundColor Cyan
    exit 1
}

Remove-Item $pendente -ErrorAction SilentlyContinue
Write-Host "  STATUS: ONLINE" -ForegroundColor Green
Write-Host "  Bot subiu sem erros no log." -ForegroundColor Green
Write-Host ""
Write-Host "  Ultimas linhas do log:" -ForegroundColor Cyan
$log | Select-Object -Last 10 | ForEach-Object { Write-Host "  $_" }
Write-Host ""
Write-Host "  Proximo passo: faca os testes do arquivo TESTE_POS_DEPLOY.md no Discord." -ForegroundColor Cyan
Write-Host "  Se algo estiver errado:  .\rollback.ps1" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""
exit 0
