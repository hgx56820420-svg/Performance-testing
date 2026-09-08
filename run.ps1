param(
  [ValidateSet("up", "down", "test", "analyze")]
  [string]$Action = "up"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

switch ($Action) {
  "up" { docker compose up --build -d; docker compose ps }
  "down" { docker compose down }
  "test" { docker compose exec service python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health').read())"; docker compose run --rm analyzer python -m compileall /app/scripts }
  "analyze" { docker compose run --rm analyzer python /app/scripts/analyze_results.py --stats /results/baseline_stats.csv --history /results/baseline_stats_history.csv --output /results/baseline_report.md }
}
