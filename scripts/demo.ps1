# One-command offline demo. Usage: scripts/demo.ps1 [mock|sim]
param([string]$Backend = "mock")
Set-Location (Join-Path $PSScriptRoot "..")
robotevalops demo run --backend $Backend --home "data/demo_$Backend"
Write-Host "Reports: data/demo_$Backend/reports/<session_id>/report.html"
