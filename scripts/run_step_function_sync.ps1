# Avvia la Step Function (STANDARD), attende SUCCEEDED e scrive l'output JSON in out.json.
# Uso (dalla root del repo): .\scripts\run_step_function_sync.ps1
# Opzionale: -StateMachineArn, -Region, -InputFile, -OutFile

param(
  [string]$StateMachineArn = $env:SFN_ARN,
  [string]$Region = $env:AWS_DEFAULT_REGION,
  [string]$InputFile = "",
  [string]$OutFile = "",
  [int]$PollSeconds = 10,
  [int]$TimeoutSeconds = 7200
)

$RepoRoot = Split-Path $PSScriptRoot -Parent
if (-not $InputFile) { $InputFile = Join-Path $RepoRoot "examples\step-function-input.json" }
if (-not $OutFile) { $OutFile = Join-Path $RepoRoot "out.json" }

if (-not $StateMachineArn) {
  $tfDir = Join-Path $RepoRoot "terraform"
  if (-not (Test-Path $tfDir)) {
    Write-Error "Cartella terraform non trovata sotto $RepoRoot. Imposta SFN_ARN o -StateMachineArn."
    exit 1
  }
  Write-Host "ARN da: terraform output -raw state_machine_arn"
  $StateMachineArn = terraform -chdir="$tfDir" output -raw state_machine_arn
  if (-not $StateMachineArn) {
    Write-Error "terraform output state_machine_arn vuoto. Esegui terraform apply dalla cartella terraform."
    exit 1
  }
}

$ArnRegion = $null
if ($StateMachineArn -match "^arn:aws:states:([^:]+):") {
  $ArnRegion = $Matches[1]
}

if (-not $Region) {
  if ($ArnRegion) {
    $Region = $ArnRegion
    Write-Host "Regione da ARN: $Region"
  }
  else {
    $Region = "eu-south-1"
    Write-Host "Uso regione predefinita: $Region (o imposta AWS_DEFAULT_REGION / -Region)"
  }
}

$inputPath = (Resolve-Path $InputFile).Path
$startOut = aws stepfunctions start-execution `
  --region $Region `
  --state-machine-arn $StateMachineArn `
  --input "file://$inputPath" `
  --output json | ConvertFrom-Json

$execArn = $startOut.executionArn
Write-Host "Esecuzione avviata: $execArn"

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ($true) {
  $d = aws stepfunctions describe-execution `
    --region $Region `
    --execution-arn $execArn `
    --output json | ConvertFrom-Json

  if ($d.status -eq 'SUCCEEDED') {
    $raw = $d.output
    if ($raw -is [string]) {
      $pretty = $raw | ConvertFrom-Json | ConvertTo-Json -Depth 100
    }
    else {
      $pretty = $raw | ConvertTo-Json -Depth 100
    }
    $pretty | Set-Content -Encoding utf8 $OutFile
    Write-Host "OK -> $OutFile"
    exit 0
  }
  if ($d.status -in @('FAILED', 'TIMED_OUT', 'ABORTED')) {
    Write-Error "Esecuzione $($d.status) error=$($d.error) cause=$($d.cause)"
    exit 1
  }
  if ((Get-Date) -gt $deadline) {
    Write-Error "Timeout dopo ${TimeoutSeconds}s (ancora $($d.status))."
    exit 1
  }
  Write-Host "Stato: $($d.status) ... attendo ${PollSeconds}s"
  Start-Sleep -Seconds $PollSeconds
}
