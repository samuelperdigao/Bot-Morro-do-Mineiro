from __future__ import annotations

import json
import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "scripts" / "deploy.ps1"
TOKEN_UPDATE = ROOT / "scripts" / "atualizar_token.ps1"
ROLLBACK = ROOT / "scripts" / "rollback_deploy.ps1"
PRICE_UPDATE = ROOT / "scripts" / "atualizar_precos.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_price_update_module():
    spec = importlib.util.spec_from_file_location("price_update_under_test", PRICE_UPDATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("script", [DEPLOY, TOKEN_UPDATE, ROLLBACK])
def test_operational_scripts_require_host_key_validation(script: Path) -> None:
    source = read(script)
    assert "StrictHostKeyChecking=yes" in source
    assert "StrictHostKeyChecking=no" not in source
    assert "BatchMode=yes" in source


def test_deploy_uses_validated_tracked_manifest() -> None:
    source = read(DEPLOY)

    assert "status --porcelain --untracked-files=all" in source
    assert "diff --check" in source
    assert "-m pytest tests/ -q" in source
    assert "ls-files" in source
    assert "hash-object" in source
    assert "o repositorio mudou durante a validacao local" in source
    assert "$runtimeRoots" in source
    assert "Get-ChildItem -Path $LOCAL_DIR -Recurse" not in source
    assert "Read-Host" in source
    assert "DEPLOY $shortCommit" in source
    assert ".deploy-backups" in source
    assert ".deploy-staging" in source
    assert "Get-FileHash" in source
    assert "sha256sum" in source
    assert "Invoke-RemoteRollback" in source


def test_root_deploy_wrapper_forwards_arguments() -> None:
    source = read(ROOT / "deploy.ps1")
    assert 'scripts\\deploy.ps1" @args' in source


def test_token_update_never_sends_complete_env() -> None:
    source = read(TOKEN_UPDATE)
    scp_lines = [line for line in source.splitlines() if "scp @sshOptions" in line]

    assert scp_lines == [
        '    & scp @sshOptions $localTokenPath "${REMOTE}:${remoteTokenPath}"'
    ]
    assert "$LOCAL_ENV \"${REMOTE}:${REMOTE_DIR}/.env\"" not in source
    assert "$REMOTE_TOKEN_ENV" in source
    assert "mv -f '$remoteTokenPath' '$REMOTE_TOKEN_ENV'" in source
    assert ".env.next" not in source
    assert "Invoke-TokenRollback" in source
    assert "ATUALIZAR TOKEN" in source


def test_token_update_recovers_from_ambiguous_remote_failures() -> None:
    source = read(TOKEN_UPDATE)

    assert "$remoteTransferAttempted = $false" in source
    assert "$remoteTransferAttempted = $true" in source
    assert source.index("$remoteTransferAttempted = $true") < source.index(
        "& scp @sshOptions"
    )
    assert "$remoteSwapAttempted = $true" in source
    assert "if ($remoteTransferAttempted)" in source
    assert "Invoke-TokenRollback" in source
    assert "Invoke-TokenCleanup" in source
    assert "rm -f '$RemoteTokenPath' '$NewTokenMarker'" in source
    assert "exit 10" in source
    assert "A credencial anterior foi restaurada" in source
    assert "$remoteTokenUploaded" not in source
    assert "$remoteEnvUpdated" not in source


def test_runtime_supports_dedicated_token_override() -> None:
    source = read(ROOT / "core" / "config.py")

    assert 'BASE_DIR / ".env.token"' in source
    assert "dotenv_values(TOKEN_OVERRIDE_FILE)" in source
    assert 'os.environ["DISCORD_TOKEN"] = token_override' in source
    assert "load_dotenv(dotenv_path=TOKEN_OVERRIDE_FILE" not in source


def test_token_update_does_not_report_secret_metadata() -> None:
    source = read(TOKEN_UPDATE)
    write_lines = "\n".join(
        line for line in source.splitlines() if "Write-Host" in line
    )

    assert not re.search(
        r"Write-Host.*(?:\$token|\$localHash|\$remoteHash|fingerprint|chars)",
        write_lines,
        flags=re.IGNORECASE,
    )


def test_shared_agent_settings_do_not_auto_allow_external_actions() -> None:
    settings = json.loads(read(ROOT / ".claude" / "settings.json"))
    allowed = "\n".join(settings["permissions"]["allow"]).lower()

    for forbidden in (
        "ssh",
        "scp",
        "deploy",
        "systemctl",
        "git push",
        "git commit",
        "git add",
        "rm -rf",
        "pip install",
        "python -c",
        "curl",
    ):
        assert forbidden not in allowed

    assert settings["permissions"]["additionalDirectories"] == []


def test_price_update_requires_confirmation_before_external_access() -> None:
    source = read(PRICE_UPDATE)
    main_body = source[source.index("def main(") :]

    assert "require_confirmation(confirmed_by_user)" in main_body
    assert main_body.index("require_confirmation(confirmed_by_user)") < main_body.index(
        "load_dotenv()"
    )
    assert "--confirmed-by-user" in source


def test_price_confirmation_names_channel_and_destructive_scope(monkeypatch) -> None:
    module = load_price_update_module()
    prompts: list[str] = []
    expected = f"ATUALIZAR PRECOS {module.CHANNEL_ID}"

    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: (prompts.append(prompt), expected)[1],
    )

    module.require_confirmation(False)

    assert prompts
    assert module.CHANNEL_ID in prompts[0]
    assert "publicar a tabela" in prompts[0]
    assert "remover as mensagens anteriores" in prompts[0]


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell indisponivel")
@pytest.mark.parametrize(
    "script",
    [ROOT / "deploy.ps1", DEPLOY, TOKEN_UPDATE, ROLLBACK],
)
def test_powershell_scripts_parse_without_errors(script: Path) -> None:
    escaped_path = str(script).replace("'", "''")
    command = (
        "$tokens=$null; $errors=$null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{escaped_path}', "
        "[ref]$tokens, [ref]$errors); "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { $_.Message }; exit 1 }"
    )
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
