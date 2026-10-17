[CmdletBinding()]
param([string]$LogPath)

$ErrorActionPreference = 'Stop'
$backendRoot = Split-Path -Parent $PSScriptRoot
$dockerCommand = Get-Command docker -CommandType Application -ErrorAction Stop | Select-Object -First 1
$networkName = 'ezstore-db-regression-' + [guid]::NewGuid().ToString('N')
$containerName = $networkName + '-db'
$exitCode = 1

function Invoke-TestDocker {
    param([string[]]$Arguments)
    & $dockerCommand.Source @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Test Docker command failed: $($Arguments[0])" }
}

# No Compose file, application .env, host port, existing database, or models.
# Uses the Go module/build caches populated by the ordinary backend test build.
try {
    Invoke-TestDocker @('network', 'create', '--internal', $networkName)
    Invoke-TestDocker @('run', '-d', '--name', $containerName, '--network', $networkName, '--network-alias', 'testdb',
        '--tmpfs', '/var/lib/postgresql/data', '-e', 'POSTGRES_DB=ezstore_recheck', '-e', 'POSTGRES_USER=regression',
        '-e', 'POSTGRES_PASSWORD=disposable-only', 'postgres:16-alpine')
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        & $dockerCommand.Source exec $containerName pg_isready -U regression -d ezstore_recheck *> $null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Disposable database did not become ready' }

    $testArgs = @('run', '--rm', '--network', $networkName,
        '-e', 'EZSTORE_INTEGRATION_DSN=host=testdb user=regression password=disposable-only dbname=ezstore_recheck sslmode=disable',
        '-e', 'GOPROXY=off', '-e', 'GOTOOLCHAIN=local', '-e', 'GOMODCACHE=/gomod', '-e', 'GOCACHE=/gocache',
        '-v', ($backendRoot + ':/src:ro'), '-v', 'ezstore-audit-gomod:/gomod', '-v', 'ezstore-audit-gocache:/gocache',
        '-w', '/src', 'golang:1.26-alpine', 'go', 'test', '-mod=readonly', '-count=1', '-v', './...')
    if ($LogPath) {
        & $dockerCommand.Source @testArgs *> $LogPath
        $exitCode = $LASTEXITCODE
        Get-Content -LiteralPath $LogPath
    } else {
        & $dockerCommand.Source @testArgs
        $exitCode = $LASTEXITCODE
    }
} finally {
    # These names are freshly generated here; never remove any other resource.
    & $dockerCommand.Source rm -f $containerName
    & $dockerCommand.Source network rm $networkName
}
exit $exitCode
