# Fluxo guiado para commit, push e deploy do Morro do Mineiro Bot.
# Uso: pwsh scripts/publicar.ps1

[CmdletBinding()]
param(
    [string]$CommitMessage
)

$ErrorActionPreference = "Stop"
$PROJECT_DIR = Split-Path $PSScriptRoot -Parent
$DEPLOY_SCRIPT = Join-Path $PSScriptRoot "deploy.ps1"

function Stop-WithError {
    param([string]$Message)

    Write-Host "[ERRO] $Message" -ForegroundColor Red
    exit 1
}

function Confirm-Action {
    param(
        [string]$Message,
        [string]$Target
    )

    Write-Host ""
    Write-Host $Target -ForegroundColor Yellow
    return (Read-Host "$Message Digite SIM para continuar") -ceq "SIM"
}

foreach ($command in @("git", "pwsh")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        Stop-WithError "Comando obrigatorio nao encontrado: $command"
    }
}

$branch = (& git -C $PROJECT_DIR branch --show-current 2>$null).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($branch)) {
    Stop-WithError "Nao foi possivel identificar a branch atual."
}

$upstream = (& git -C $PROJECT_DIR rev-parse --abbrev-ref --symbolic-full-name "@{u}" 2>$null).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($upstream)) {
    Stop-WithError "Esta branch nao tem upstream configurado. Configure origin/$branch antes de publicar."
}

$remoteName = ($upstream -split "/", 2)[0]
$upstreamBranch = ($upstream -split "/", 2)[1]
if ([string]::IsNullOrWhiteSpace($upstreamBranch)) {
    Stop-WithError "Upstream invalido: $upstream"
}

$changePaths = @(
    & git -C $PROJECT_DIR diff --name-only
    & git -C $PROJECT_DIR diff --cached --name-only
    & git -C $PROJECT_DIR ls-files --others --exclude-standard
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Sort-Object -Unique

if ($LASTEXITCODE -ne 0) {
    Stop-WithError "Nao foi possivel identificar os arquivos alterados."
}

if ($changePaths.Count -gt 0) {
    $unsafePaths = @(
        $changePaths | Where-Object {
            $normalized = $_.Replace("\", "/")
            $normalized -match '(^|/)(\.env(?:\.[^/]*)?|oracle\.key|data|logs)(/|$)' -or
            $normalized -match '\.(db|sqlite|sqlite3|pem|key)$'
        }
    )
    if ($unsafePaths.Count -gt 0) {
        Write-Host "Arquivos operacionais ou sensiveis nao podem entrar neste commit:" -ForegroundColor Red
        $unsafePaths | ForEach-Object { Write-Host "  $_" }
        Stop-WithError "Remova esses arquivos da selecao no Controle do Codigo-Fonte e tente novamente."
    }

    Write-Host "Arquivos que serao incluidos:" -ForegroundColor Cyan
    $changePaths | ForEach-Object { Write-Host "  $_" }
    if (-not (Confirm-Action -Message "Incluir todos os arquivos listados?" -Target "Branch: $branch")) {
        Stop-WithError "Operacao cancelada; nenhum arquivo foi preparado para commit."
    }

    & git -C $PROJECT_DIR add --all
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "Falha ao preparar os arquivos para commit."
    }

    & git -C $PROJECT_DIR diff --cached --check
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "git diff --cached --check encontrou problemas."
    }

    $stagedPaths = @(& git -C $PROJECT_DIR diff --cached --name-only)
    if ($LASTEXITCODE -ne 0 -or $stagedPaths.Count -eq 0) {
        Stop-WithError "Nenhum arquivo ficou preparado para commit."
    }

    if ([string]::IsNullOrWhiteSpace($CommitMessage)) {
        $CommitMessage = Read-Host "Mensagem do commit"
    }
    if ([string]::IsNullOrWhiteSpace($CommitMessage)) {
        Stop-WithError "A mensagem do commit nao pode ficar vazia."
    }

    Write-Host ""
    Write-Host "Arquivos preparados para o commit:" -ForegroundColor Cyan
    $stagedPaths | ForEach-Object { Write-Host "  $_" }
    Write-Host "Mensagem: $CommitMessage"
    if (-not (Confirm-Action -Message "Criar este commit local?" -Target "Branch: $branch")) {
        Stop-WithError "Commit cancelado. Os arquivos continuam preparados no Git."
    }

    Write-Host "Executando testes antes do commit..." -ForegroundColor Yellow
    Push-Location $PROJECT_DIR
    try {
        & .\venv\Scripts\python.exe -m pytest tests/ -q
        if ($LASTEXITCODE -ne 0) {
            Stop-WithError "Testes reprovados; o commit e a publicacao foram cancelados."
        }
    } finally {
        Pop-Location
    }

    & git -C $PROJECT_DIR commit -m $CommitMessage
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "O commit nao foi criado."
    }
} else {
    Write-Host "Nenhuma alteracao local para commitar. Vou verificar se ha commits pendentes." -ForegroundColor Cyan
}

$unstaged = @(& git -C $PROJECT_DIR diff --name-only)
$remainingUntracked = @(& git -C $PROJECT_DIR ls-files --others --exclude-standard)
if ($LASTEXITCODE -ne 0 -or $unstaged.Count -gt 0 -or $remainingUntracked.Count -gt 0) {
    Stop-WithError "A arvore ainda tem alteracoes fora do commit. Revise-as antes do deploy."
}

$behindCount = (& git -C $PROJECT_DIR rev-list --count "HEAD..$upstream" 2>$null).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($behindCount)) {
    Stop-WithError "Nao foi possivel comparar a branch local com o upstream $upstream."
}
if ([int]$behindCount -gt 0) {
    Stop-WithError "A branch local esta atrasada em relacao a $upstream. Use Sync Changes no VS Code e tente novamente."
}

$aheadCount = (& git -C $PROJECT_DIR rev-list --count "$upstream..HEAD" 2>$null).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($aheadCount)) {
    Stop-WithError "Nao foi possivel identificar os commits pendentes de envio."
}
if ([int]$aheadCount -gt 0) {
    $commit = (& git -C $PROJECT_DIR rev-parse --short=12 HEAD).Trim()
    $commitList = @(& git -C $PROJECT_DIR log --oneline "$upstream..HEAD")
    Write-Host "Commits que serao enviados:" -ForegroundColor Cyan
    $commitList | ForEach-Object { Write-Host "  $_" }
    if (-not (Confirm-Action -Message "Enviar os commits acima?" -Target "Destino: $upstream | Commit mais recente: $commit")) {
        Stop-WithError "Push cancelado; nenhum deploy foi iniciado."
    }

    & git -C $PROJECT_DIR push $remoteName $upstreamBranch
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "O push falhou. Nenhum deploy foi iniciado."
    }
} else {
    Write-Host "A branch ja esta sincronizada com $upstream." -ForegroundColor Green
}

$finalCommit = (& git -C $PROJECT_DIR rev-parse --short=12 HEAD).Trim()
$fullCommit = (& git -C $PROJECT_DIR rev-parse HEAD).Trim()
$deployTarget = "Ambiente: producao | Branch: $branch | Commit: $finalCommit ($fullCommit) | Servico: farmbot"
if (-not (Confirm-Action -Message "Publicar e reiniciar o bot?" -Target $deployTarget)) {
    Stop-WithError "Deploy cancelado. O commit permanece no GitHub, se o push ja foi aprovado."
}

Write-Host "Iniciando o deploy seguro. O script executara novamente os testes e validara os arquivos antes do SSH." -ForegroundColor Yellow
& pwsh -NoProfile -File $DEPLOY_SCRIPT -ConfirmedByUser
if ($LASTEXITCODE -ne 0) {
    Stop-WithError "O deploy nao concluiu. Consulte a mensagem do script de deploy para o resultado e o rollback."
}

Write-Host "Fluxo de publicacao concluido." -ForegroundColor Green
