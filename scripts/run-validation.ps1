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
& $python -m autoresearch_harness run examples\model_param_tuning\task.json
& $python -m autoresearch_harness run examples\recommender_bpr\task.json
& $python -m autoresearch_harness run examples\external_command\task.json
& $python -m autoresearch_harness adaptive-run examples\external_command\task.json --repo-root .
& $python -m autoresearch_harness verify-run examples\external_command\task.json examples\external_command\baseline_params.json examples\external_command\candidate_params.json --repo-root .
& $python -m autoresearch_harness research examples\prompt_tuning\task.json --branch-mode record
& $python -m autoresearch_harness research examples\model_param_tuning\task.json --branch-mode record
& $python -m autoresearch_harness research examples\recommender_bpr\task.json --branch-mode record
