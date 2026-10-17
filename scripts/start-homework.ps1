[CmdletBinding()]
param(
    [ValidateSet('Start', 'Restart', 'Status', 'Logs')]
    [string]$Action = 'Start',
    [switch]$SkipBuild,
    [switch]$Follow
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($SkipBuild -and $Action -ne 'Start') {
    throw '-SkipBuild is only available with -Action Start.'
}
if ($Follow -and $Action -ne 'Logs') {
    throw '-Follow is only available with -Action Logs.'
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot '.env'
if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw 'Create the root .env from .env.example and configure your model first. Existing settings are never overwritten.'
}

$dockerCommand = Get-Command docker -CommandType Application -ErrorAction Stop | Select-Object -First 1
$composeArgs = @(
    'compose', '--project-name', 'ezstore', '--project-directory', $projectRoot,
    '--env-file', $envFile
)
foreach ($name in @('docker-compose.yml', 'docker-compose.build.yml', 'docker-compose.advisor.yml')) {
    $path = Join-Path $projectRoot $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Missing Compose file: $path"
    }
    $composeArgs += @('-f', $path)
}

switch ($Action) {
    'Start' {
        if ($SkipBuild) {
            # Use only previously built/tagged ezstore-*:local images.
            $operationArgs = @('up', '-d', '--no-build', '--pull', 'never')
        } else {
            $operationArgs = @('up', '-d', '--build')
        }
    }
    'Restart' { $operationArgs = @('restart') }
    'Status' { $operationArgs = @('ps') }
    'Logs' {
        $operationArgs = @('logs', '--tail', '100')
        if ($Follow) { $operationArgs += '--follow' }
    }
}

# Compose reads the existing .env; this script neither prints nor edits it.
# Database seeding is deliberately separate from every action above.
& $dockerCommand.Source @composeArgs @operationArgs
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose action '$Action' failed (exit code $LASTEXITCODE)."
}
