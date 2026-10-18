[CmdletBinding()]
param([switch]$SkipBuild)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $projectRoot 'docker-compose.e2e.yml'
$dockerCommand = Get-Command docker -CommandType Application -ErrorAction Stop | Select-Object -First 1
$projectName = 'ezstore-e2e-' + [guid]::NewGuid().ToString('N')
# An explicit empty env file prevents Compose from reading the main .env.
$emptyEnvFile = [IO.Path]::GetTempFileName()
$composeArgs = @(
    'compose', '--project-name', $projectName, '--project-directory', $projectRoot,
    '--env-file', $emptyEnvFile, '-f', $composeFile
)

function Invoke-TestCompose {
    param([string[]]$CommandArgs)
    & $dockerCommand.Source @composeArgs @CommandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Isolated E2E command failed (exit code $LASTEXITCODE): $($CommandArgs -join ' ')"
    }
}

Write-Host "Disposable E2E project: $projectName"
try {
    if (-not $SkipBuild) {
        Invoke-TestCompose -CommandArgs @('build')
    }
    Invoke-TestCompose -CommandArgs @('up', '-d', '--no-build', '--wait', '--wait-timeout', '120', 'db', 'backend', 'frontend')
    # backend is healthy only after its schema migration completes. This db
    # belongs to the unique test project and uses a new, project-scoped volume.
    Invoke-TestCompose -CommandArgs @('exec', '-T', 'db', 'psql', '-v', 'ON_ERROR_STOP=1', '-U', 'ezstore', '-d', 'ezstore', '-f', '/scripts/seed-test-data.sql')
    Invoke-TestCompose -CommandArgs @('run', '--rm', '--no-deps', 'e2e')
} catch {
    & $dockerCommand.Source @composeArgs logs --tail 60
    throw
} finally {
    # Clean only this newly generated project, including on build/test failure.
    & $dockerCommand.Source @composeArgs down --volumes --remove-orphans --timeout 5
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Cleanup failed for $projectName; remove only this test project's resources."
    }
    Remove-Item -LiteralPath $emptyEnvFile -ErrorAction SilentlyContinue
}
