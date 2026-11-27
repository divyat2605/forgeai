# ForgeAI one-time setup on Windows (PowerShell).
#   powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1            # standard profile
#   powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -Profile laptop
param([string]$Profile = "standard")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "== ForgeAI setup ($Profile profile) ==" -ForegroundColor Cyan
$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) { $python = "py"; $pyargs = @("-3") } else { $python = "python"; $pyargs = @() }
& $python @pyargs -c "import sys; assert sys.version_info >= (3,10), 'Python 3.10+ required'; print('Python', sys.version.split()[0])"

if (-not (Test-Path .venv)) { & $python @pyargs -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" --quiet
Write-Host "Installed forgeai into .venv" -ForegroundColor Green

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "Ollama not found. Install it from https://ollama.com/download/windows, start it, then re-run this script." -ForegroundColor Yellow
    exit 1
}
$models = @{
    "standard" = @("qwen3:8b", "gemma3:4b", "nomic-embed-text");
    "laptop"   = @("qwen3:4b", "gemma3:4b", "nomic-embed-text");
    "tiny"     = @("qwen3:1.7b", "gemma3:4b", "nomic-embed-text")
}
foreach ($m in $models[$Profile]) { Write-Host "ollama pull $m"; ollama pull $m }

.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\forge.exe doctor --profile $Profile
Write-Host "`nReady. Activate with: .\.venv\Scripts\Activate.ps1   then: forge build --help" -ForegroundColor Green
