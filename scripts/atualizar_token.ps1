# atualizar_token.ps1 - Valida o DISCORD_TOKEN local, envia o .env e reinicia o bot
# Uso: .\scripts\atualizar_token.ps1
#
# O deploy.ps1 nao envia o .env (esta na lista de exclusoes), entao trocar o token
# exige este envio manual. O script so sobe o arquivo se o token autenticar no Discord.

$SSH_KEY    = "$(Split-Path $PSScriptRoot -Parent)\oracle.key"
$REMOTE     = "ubuntu@163.176.143.142"
$REMOTE_DIR = "/home/ubuntu/farmbot"
$LOCAL_ENV  = "$(Split-Path $PSScriptRoot -Parent)\.env"

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  Atualizacao de token - Morro do Mineiro" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Leitura do token local ─────────────────────────────────────────────────

Write-Host "[1/5] Lendo o token do .env local..." -ForegroundColor Yellow

if (-not (Test-Path $LOCAL_ENV)) {
    Write-Host "  [ERRO] .env nao encontrado em: $LOCAL_ENV" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $SSH_KEY)) {
    Write-Host "  [ERRO] Chave SSH nao encontrada em: $SSH_KEY" -ForegroundColor Red
    exit 1
}

$linha = Get-Content $LOCAL_ENV | Where-Object { $_ -match '^DISCORD_TOKEN=' } | Select-Object -First 1

if (-not $linha) {
    Write-Host "  [ERRO] Linha DISCORD_TOKEN= nao encontrada no .env." -ForegroundColor Red
    exit 1
}

$token = $linha -replace '^DISCORD_TOKEN=', ''
$token = $token.Trim().Trim('"').Trim("'")

if ([string]::IsNullOrWhiteSpace($token)) {
    Write-Host "  [ERRO] DISCORD_TOKEN esta vazio no .env." -ForegroundColor Red
    exit 1
}

# Fingerprint (12 primeiros chars do SHA256) para conferir o envio sem expor o token
$sha       = [System.Security.Cryptography.SHA256]::Create()
$bytes     = [System.Text.Encoding]::UTF8.GetBytes($token)
$localFp   = (($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") }) -join "").Substring(0, 12)

Write-Host "  Token lido ($($token.Length) chars, fingerprint $localFp)." -ForegroundColor Green

# ── 2. Validacao contra a API do Discord ──────────────────────────────────────

Write-Host ""
Write-Host "[2/5] Validando o token na API do Discord..." -ForegroundColor Yellow

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

try {
    $me = Invoke-RestMethod -Uri "https://discord.com/api/v10/users/@me" `
        -Headers @{ Authorization = "Bot $token" } `
        -Method Get -TimeoutSec 20 -ErrorAction Stop
} catch {
    $code = $null
    if ($_.Exception.Response) {
        $code = $_.Exception.Response.StatusCode.value__
    }
    Write-Host "  [ERRO] Token recusado pelo Discord (HTTP $code)." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Gere um token novo em:" -ForegroundColor Yellow
    Write-Host "    Developer Portal > sua aplicacao > aba Bot > Reset Token" -ForegroundColor Yellow
    Write-Host "  Copie com o botao Copy (ele so aparece uma vez), cole no .env e rode de novo." -ForegroundColor Yellow
    Write-Host "  Nada foi enviado ao servidor." -ForegroundColor Yellow
    exit 1
}

Write-Host "  Token valido: $($me.username) (ID: $($me.id))" -ForegroundColor Green

# ── 3. Envio do .env ──────────────────────────────────────────────────────────

Write-Host ""
Write-Host "[3/5] Enviando .env para o servidor..." -ForegroundColor Yellow

scp -i $SSH_KEY -o StrictHostKeyChecking=no $LOCAL_ENV "${REMOTE}:${REMOTE_DIR}/.env"

if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERRO] Falha ao enviar o .env." -ForegroundColor Red
    exit 1
}

Write-Host "  .env enviado." -ForegroundColor Green

# ── 4. Conferencia do arquivo remoto ──────────────────────────────────────────

Write-Host ""
Write-Host "[4/5] Conferindo o token no servidor..." -ForegroundColor Yellow

$fpCmd = @"
printf '%s' "`$(grep '^DISCORD_TOKEN=' $REMOTE_DIR/.env | cut -d= -f2- | tr -d '\r')" | sha256sum | cut -c1-12
"@

$remoteFp = ssh -i $SSH_KEY -o StrictHostKeyChecking=no $REMOTE $fpCmd

if ("$remoteFp".Trim() -ne $localFp) {
    Write-Host "  [ERRO] Fingerprint remoto ($remoteFp) difere do local ($localFp)." -ForegroundColor Red
    Write-Host "  O arquivo no servidor nao corresponde ao local. Servico nao reiniciado." -ForegroundColor Red
    exit 1
}

Write-Host "  Fingerprint confere ($localFp)." -ForegroundColor Green

# ── 5. Reinicio e verificacao ─────────────────────────────────────────────────

Write-Host ""
Write-Host "[5/5] Reiniciando o servico farmbot..." -ForegroundColor Yellow

# reset-failed zera o contador de reinicios acumulado enquanto o token estava invalido
ssh -i $SSH_KEY -o StrictHostKeyChecking=no $REMOTE `
    "sudo systemctl reset-failed farmbot; sudo systemctl restart farmbot"

if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERRO] Falha ao reiniciar o servico." -ForegroundColor Red
    exit 1
}

Write-Host "  Aguardando inicializacao (12s)..." -ForegroundColor Yellow
Start-Sleep -Seconds 12

$status = ssh -i $SSH_KEY -o StrictHostKeyChecking=no $REMOTE "systemctl is-active farmbot"

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan

if ("$status".Trim() -eq "active") {
    Write-Host "  STATUS: ONLINE" -ForegroundColor Green
    Write-Host "  Token atualizado e bot no ar!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Ultimas linhas do log:" -ForegroundColor Cyan
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $REMOTE `
        "journalctl -u farmbot -n 10 --no-pager --output=cat"
} else {
    Write-Host "  STATUS: $("$status".Trim().ToUpper())" -ForegroundColor Red
    Write-Host "  Bot nao iniciou corretamente." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Log de erro:" -ForegroundColor Red
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $REMOTE `
        "journalctl -u farmbot -n 20 --no-pager --output=cat"
    exit 1
}

Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""
