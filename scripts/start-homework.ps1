[CmdletBinding()]
param(
    [ValidateSet('Start', 'Restart', 'SyncKnowledge', 'Status', 'Logs')]
    [string]$Action = 'Start',
    [switch]$SkipBuild,
    [switch]$Follow,
    # Optional workaround when Docker Desktop cannot mount the source drive.
    # Each Start refreshes a private snapshot; edit the original source as usual.
    [string]$DockerBindCache
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
$cacheSetting = Join-Path $projectRoot '.docker/bind-cache-path.txt'
if (-not $DockerBindCache -and (Test-Path -LiteralPath $cacheSetting -PathType Leaf)) {
    $DockerBindCache = (Get-Content -LiteralPath $cacheSetting -Raw).Trim()
}
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

if ($DockerBindCache) {
    $cacheRoot = [IO.Path]::GetFullPath($DockerBindCache)
    $sourceRoot = [IO.Path]::GetFullPath($projectRoot).TrimEnd('\') + '\'
    if (($cacheRoot.TrimEnd('\') + '\').StartsWith($sourceRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'DockerBindCache must be outside the source repository.'
    }
    $overridePath = Join-Path $cacheRoot 'compose.bind-cache.json'
    if ($Action -in @('Start', 'Restart', 'SyncKnowledge')) {
        $snapshotPath = Join-Path $cacheRoot ('snapshot-' + [Guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $snapshotPath -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $projectRoot 'scripts') -Destination (Join-Path $snapshotPath 'scripts') -Recurse
        Copy-Item -LiteralPath (Join-Path $projectRoot 'knowledge/ezstore') -Destination (Join-Path $snapshotPath 'knowledge') -Recurse
        $override = @{ services = @{
            db = @{ volumes = @(@{ type = 'bind'; source = (Join-Path $snapshotPath 'scripts'); target = '/scripts'; read_only = $true }) }
            advisor = @{ volumes = @(@{ type = 'bind'; source = (Join-Path $snapshotPath 'knowledge'); target = '/knowledge/ezstore'; read_only = $true }) }
        } }
        $override | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $overridePath -Encoding utf8
        New-Item -ItemType Directory -Path (Split-Path -Parent $cacheSetting) -Force | Out-Null
        Set-Content -LiteralPath $cacheSetting -Value $cacheRoot -Encoding utf8
        Write-Host "Docker bind snapshots refreshed in $snapshotPath"
    } elseif (-not (Test-Path -LiteralPath $overridePath -PathType Leaf)) {
        throw 'Run -Action Start with this DockerBindCache first.'
    }
    $composeArgs += @('-f', $overridePath)
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
    'Restart' {
        # A refreshed snapshot changes the mount source; restart alone ignores it.
        $operationArgs = if ($DockerBindCache) { @('up', '-d', '--no-build', '--pull', 'never', '--force-recreate') } else { @('restart') }
    }
    'SyncKnowledge' {
        $operationArgs = @('up', '-d', '--no-build', '--pull', 'never', '--no-deps', '--force-recreate', 'advisor')
    }
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

# A caller-provided cache can contain unrelated data, and a directory name is
# not proof of ownership. Preserve all existing snapshots on every action.
# Cleanup is intentionally manual, after checking ownership and active mounts.
