# Cephelo_AITrader — wrapper con riavvio automatico: la gara richiede uptime >= 90%.
# Uso:  .\run.ps1          (modalita' dal config, default paper)
#       .\run.ps1 live     (forza modalita' live)
param([string]$Mode = "")

$ErrorActionPreference = "Continue"
$cmd = @("-m", "aitrade", "run")
if ($Mode -ne "") { $cmd += @("--mode", $Mode) }

while ($true) {
    Write-Host "[run.ps1] Avvio Cephelo_AITrader: python $($cmd -join ' ')" -ForegroundColor Cyan
    & python @cmd
    Write-Host "[run.ps1] Il bot si e' fermato (exit $LASTEXITCODE). Riavvio tra 10s..." -ForegroundColor Yellow
    Start-Sleep -Seconds 10
}
