$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

$env:PYTHONPATH = Join-Path $repoRoot "src"
Set-Location $repoRoot

& $python -m compileall src
& $python -m unittest discover -s tests
& $python -m autoresearch_harness run examples\ranking_param_tuning\task.json
& $python -m autoresearch_harness run examples\prompt_tuning\task.json

