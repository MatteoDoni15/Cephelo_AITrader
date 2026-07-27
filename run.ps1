# Cephelo_AITrader — wrapper con riavvio automatico: la gara richiede uptime >= 90%.
# Uso:  .\run.ps1          (modalita' dal config, default paper)
#       .\run.ps1 live     (forza modalita' live)
param([string]$Mode = "")

$ErrorActionPreference = "Continue"
$cmd = @("-m", "aitrade", "run")
if ($Mode -ne "") { $cmd += @("--mode", $Mode) }

# Signal Agent + Strategy Agent (BeeAI, A2A su localhost): opzionali, il bot
# principale funziona anche se non partono o muoiono (fallback neutro in
# advisor.py). Girano come job in background cosi' un solo script gestisce
# tutto l'uptime del bot.
$agentsJob = Start-Job -ScriptBlock { python -m aitrade.agents.run_agents }

while ($true) {
    if ($agentsJob.State -ne "Running") {
        Write-Host "[run.ps1] Job agenti AI non attivo (stato $($agentsJob.State)): riavvio..." -ForegroundColor DarkCyan
        Remove-Job $agentsJob -Force -ErrorAction SilentlyContinue
        $agentsJob = Start-Job -ScriptBlock { python -m aitrade.agents.run_agents }
    }
    Write-Host "[run.ps1] Avvio Cephelo_AITrader: python $($cmd -join ' ')" -ForegroundColor Cyan
    & python @cmd
    Write-Host "[run.ps1] Il bot si e' fermato (exit $LASTEXITCODE). Riavvio tra 10s..." -ForegroundColor Yellow
    Start-Sleep -Seconds 10
}
