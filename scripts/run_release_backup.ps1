[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$AgeRecipient,

    [Parameter(Mandatory = $true)]
    [string]$AgeIdentityFile,

    [Parameter(Mandatory = $true)]
    [string]$OffsiteDirectory,

    [string]$BackupDirectory = (Join-Path $env:USERPROFILE ".smart-ev\backups\postgres"),
    [string]$EnvFile,
    [string]$ComposeFile,
    [string]$PythonCommand = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-BackupCli {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    & $PythonCommand $backupCli @Arguments *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Encrypted backup operation failed with exit code $LASTEXITCODE."
    }
}

try {
    if ($OffsiteDirectory -notmatch '^\\\\[^\\]+\\[^\\]+') {
        throw "OffsiteDirectory must be an explicit UNC network share path."
    }

    $repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    $backupCli = Join-Path $repositoryRoot "data_platform\scripts\backup_database.py"
    if (-not $EnvFile) {
        $EnvFile = Join-Path $repositoryRoot ".env.release"
    }
    if (-not $ComposeFile) {
        $ComposeFile = Join-Path $repositoryRoot "compose.release.yaml"
    }
    $envPath = (Resolve-Path $EnvFile).Path
    $composePath = (Resolve-Path $ComposeFile).Path
    $identityPath = (Resolve-Path $AgeIdentityFile).Path
    $localBackupPath = [System.IO.Path]::GetFullPath($BackupDirectory)
    $offsitePath = [System.IO.Path]::GetFullPath($OffsiteDirectory)

    if (-not (Test-Path -LiteralPath $offsitePath -PathType Container)) {
        throw "Offsite UNC share is unavailable to this task account."
    }
    if (-not (Test-Path -LiteralPath $identityPath -PathType Leaf)) {
        throw "Age identity file is unavailable to this task account."
    }
    New-Item -ItemType Directory -Force -Path $localBackupPath | Out-Null

    $startedAt = [DateTime]::UtcNow
    Invoke-BackupCli @(
        "create", "--output-dir", $localBackupPath, "--env-file", $envPath,
        "--compose-file", $composePath, "--age-recipient", $AgeRecipient,
        "--age-identity-file", $identityPath
    )

    $archives = @(
        Get-ChildItem -LiteralPath $localBackupPath -File -Filter "*.dump.age" |
            Where-Object { $_.LastWriteTimeUtc -ge $startedAt } |
            Sort-Object LastWriteTimeUtc -Descending
    )
    if ($archives.Count -ne 1) {
        throw "Expected exactly one new encrypted backup archive."
    }

    $archive = $archives[0]
    $manifest = "$($archive.FullName).json"
    if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) {
        throw "Backup manifest was not created."
    }
    Invoke-BackupCli @(
        "verify", $archive.FullName, "--env-file", $envPath,
        "--compose-file", $composePath, "--age-identity-file", $identityPath
    )

    $setName = "$($archive.Name).set"
    $finalSet = Join-Path $offsitePath $setName
    if (Test-Path -LiteralPath $finalSet) {
        throw "Offsite backup set already exists; refusing to overwrite it."
    }
    $stagingSet = Join-Path $offsitePath ".partial-$setName-$([guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Path $stagingSet | Out-Null
    Copy-Item -LiteralPath $archive.FullName -Destination $stagingSet
    Copy-Item -LiteralPath $manifest -Destination $stagingSet

    $offsiteArchive = Join-Path $stagingSet $archive.Name
    Invoke-BackupCli @(
        "verify", $offsiteArchive, "--env-file", $envPath,
        "--compose-file", $composePath, "--age-identity-file", $identityPath
    )
    Move-Item -LiteralPath $stagingSet -Destination $finalSet
    Write-Output "Encrypted backup verified and replicated to offsite set: $finalSet"
}
catch {
    Write-Error "Release backup failed: $($_.Exception.Message)"
    exit 1
}
