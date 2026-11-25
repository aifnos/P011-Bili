param([ValidateSet('Play','Catalog')][string]$Mode = 'Play')
$ErrorActionPreference = 'Stop'
$biliRoot = Split-Path -Parent $PSScriptRoot
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Python is required on the development PC.' }
if (-not (Get-Command adb -ErrorAction SilentlyContinue)) { throw 'ADB is required on the development PC.' }
$biliBundle = if ($Mode -eq 'Play') { 'media-64a23814886cfaef' } else { 'media-58ba2068ad4b7ee3' }
$biliArgs = @('-B', (Join-Path $PSScriptRoot 'run_media_probe.py'), '--bundle', (Join-Path $biliRoot ('out/' + $biliBundle)))
if ($Mode -eq 'Play') {
    Write-Host 'P011: about 60 seconds, volume 20%, tap screen to stop. Stock files/processes are not replaced.'
    $biliArgs += '--play'
} else {
    Write-Host 'P011: anonymous recommendation/search/bangumi API probe; no UI or login.'
    $biliArgs += '--catalog'
}
& python @biliArgs
if ($LASTEXITCODE -ne 0) { throw 'Probe did not pass. Keep the raw logs and result ZIP; do not assume playback/restoration succeeded.' }
Write-Host 'Probe process and stock identity checks passed. Physical picture/sound require your observation.'
