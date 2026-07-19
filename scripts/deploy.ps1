# deploy.ps1 - Envia arquivos e reinicia o bot no servidor Oracle
# Uso: .\deploy.ps1

$SSH_KEY    = "$(Split-Path $PSScriptRoot -Parent)\oracle.key"
$REMOTE     = "ubuntu@163.176.143.142"
$REMOTE_DIR = "/home/ubuntu/farmbot"
$LOCAL_DIR  = Split-Path $PSScriptRoot -Parent

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  Deploy - Bot Morro do Mineiro" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Envio dos arquivos via SCP ─────────────────────────────────────────────

Write-Host "[1/4] Enviando arquivos para o servidor..." -ForegroundColor Yellow

# rsync nao esta disponivel no Windows por padrao, entao usamos scp com exclusoes manuais.
# Copiamos arquivo por arquivo/pasta por pasta, excluindo o que nao deve ir.

$excludedDirs  = @(
    "venv",
    "__pycache__",
    "_old",
    ".git",
    ".claude",
    ".codex-remote-attachments",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache"
)
$excludedExts  = @("*.db", "*.db-shm", "*.db-wal", "*.log", "*.pyc", "*.key")
$excludedNames = @(".env", "bau_painel.json", "bau_gerentes_painel.json")

# Coleta todos os itens a enviar (exclui pastas e extensoes indesejadas)
$items = Get-ChildItem -Path $LOCAL_DIR -Recurse |
    Where-Object {
        $relativePath = $_.FullName.Substring($LOCAL_DIR.Length + 1)
        $parts = $relativePath -split "\\"

        # Exclui se algum segmento do caminho for uma pasta excluida
        $inExcludedDir = $false
        foreach ($part in $parts) {
            if ($excludedDirs -contains $part) {
                $inExcludedDir = $true
                break
            }
        }

        # Exclui arquivos com extensoes indesejadas
        $hasExcludedExt = $false
        if (-not $_.PSIsContainer) {
            foreach ($ext in $excludedExts) {
                if ($_.Name -like $ext) {
                    $hasExcludedExt = $true
                    break
                }
            }
        }

        -not $inExcludedDir -and
        -not $hasExcludedExt -and
        $excludedNames -notcontains $_.Name
    }

# Garante que a estrutura de diretorios existe no servidor
$dirs = $items | Where-Object { $_.PSIsContainer } |
    ForEach-Object { $_.FullName.Substring($LOCAL_DIR.Length + 1) -replace "\\", "/" }

foreach ($dir in $dirs) {
    ssh -i $SSH_KEY $REMOTE "mkdir -p $REMOTE_DIR/$dir" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERRO] Falha ao criar diretorio remoto: $dir" -ForegroundColor Red
        exit 1
    }
}

# Envia os arquivos
$files = $items | Where-Object { -not $_.PSIsContainer }
$total = $files.Count
$count = 0

foreach ($file in $files) {
    $count++
    $relativePath = $file.FullName.Substring($LOCAL_DIR.Length + 1) -replace "\\", "/"
    $remotePath   = "$REMOTE_DIR/$relativePath"
    $pathParts    = $remotePath -split "/"
    $remoteFolder = $pathParts[0..($pathParts.Count - 2)] -join "/"

    Write-Progress -Activity "Enviando arquivos" -Status "$relativePath" -PercentComplete (($count / $total) * 100)

    scp -i $SSH_KEY `
        $file.FullName `
        "${REMOTE}:${remotePath}" 2>$null

    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERRO] Falha ao enviar: $relativePath" -ForegroundColor Red
        Write-Host "  Deploy interrompido; o servico nao sera reiniciado." -ForegroundColor Red
        exit 1
    }
}

Write-Progress -Activity "Enviando arquivos" -Completed
Write-Host "  $total arquivo(s) enviado(s)." -ForegroundColor Green

# ── 2. Instalar dependencias no servidor ─────────────────────────────────────

Write-Host ""
Write-Host "[2/4] Instalando dependencias Python no servidor..." -ForegroundColor Yellow

ssh -i $SSH_KEY $REMOTE `
    "cd $REMOTE_DIR && $REMOTE_DIR/venv/bin/pip install -r requirements.txt -q" 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERRO] Falha ao instalar dependencias; deploy interrompido." -ForegroundColor Red
    exit 1
} else {
    Write-Host "  Dependencias atualizadas." -ForegroundColor Green
}

# ── 3. Reinicio do servico ────────────────────────────────────────────────────

Write-Host ""
Write-Host "[3/4] Reiniciando servico farmbot..." -ForegroundColor Yellow

ssh -i $SSH_KEY $REMOTE `
    "sudo systemctl restart farmbot" 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERRO] Falha ao reiniciar o servico." -ForegroundColor Red
    exit 1
}

Write-Host "  Comando de restart enviado." -ForegroundColor Green

# ── 4. Verificacao de status ──────────────────────────────────────────────────

Write-Host ""
Write-Host "[4/4] Aguardando inicializacao (3s)..." -ForegroundColor Yellow
Start-Sleep -Seconds 3

$status = ssh -i $SSH_KEY $REMOTE `
    "systemctl is-active farmbot"

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan

if ($status -eq "active") {
    Write-Host "  STATUS: ONLINE" -ForegroundColor Green
    Write-Host "  Bot subiu com sucesso!" -ForegroundColor Green

    # Exibe as ultimas linhas do log para confirmar
    Write-Host ""
    Write-Host "  Ultimas linhas do log:" -ForegroundColor Cyan
    ssh -i $SSH_KEY $REMOTE `
        "journalctl -u farmbot -n 10 --no-pager --output=cat"
} else {
    Write-Host "  STATUS: $($status.ToUpper())" -ForegroundColor Red
    Write-Host "  Bot nao iniciou corretamente." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Log de erro:" -ForegroundColor Red
    ssh -i $SSH_KEY $REMOTE `
        "journalctl -u farmbot -n 20 --no-pager --output=cat"
    exit 1
}

Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""
