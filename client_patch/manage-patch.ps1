param(
    [ValidateSet('Install', 'Uninstall')][string]$Action = 'Install',
    [string]$StorageDirectory = (Join-Path $env:APPDATA 'osu'),
    [string]$GameDirectory = (Join-Path $env:LOCALAPPDATA 'osulazer/current')
)
$ErrorActionPreference = 'Stop'
$storagePath = (Resolve-Path -LiteralPath $StorageDirectory).Path
$rulesets = [IO.Path]::GetFullPath((Join-Path $storagePath 'rulesets'))
if (-not $rulesets.StartsWith($storagePath.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Ruleset directory must be within the selected storage directory.'
}
if (Get-Process -Name 'osu!' -ErrorAction SilentlyContinue) { throw 'Close lazer before installing or uninstalling Pixel Film.' }
$name = 'osu.Game.Rulesets.PixelFilm.dll'
$target = Join-Path $rulesets $name
$receipt = Join-Path $rulesets 'pixel-film-install.json'
if ($Action -eq 'Uninstall') {
    if (-not (Test-Path -LiteralPath $receipt)) {
        if (Test-Path -LiteralPath $target) { throw 'No installation receipt; the existing DLL is left untouched.' }
        Write-Host 'Pixel Film is already uninstalled.'
        return
    }
    $installed = Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json
    if ($installed.plugin -ne $name) { throw 'Invalid installation receipt.' }
    if (Test-Path -LiteralPath $target) {
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $installed.sha256) {
            throw 'Installed DLL has changed; it is left untouched.'
        }
        Remove-Item -LiteralPath $target
    }
    Remove-Item -LiteralPath $receipt
    Write-Host 'Pixel Film removed. Restart lazer to use the original modes.'
    return
}

$gamePath = (Resolve-Path -LiteralPath $GameDirectory).Path
$package = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'package.json') -Raw | ConvertFrom-Json
foreach ($entry in $package.assemblies.PSObject.Properties) {
    if ((Get-FileHash -LiteralPath (Join-Path $gamePath $entry.Name) -Algorithm SHA256).Hash -ne $entry.Value) {
        throw "Unsupported lazer build: $($entry.Name). This package targets $($package.game_version)."
    }
}
$source = Join-Path $PSScriptRoot $name
if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $package.plugin_sha256) { throw 'Patch package hash mismatch.' }
if (Test-Path -LiteralPath $target) {
    if (-not (Test-Path -LiteralPath $receipt) -or (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $package.plugin_sha256) {
        throw 'A different or unmanaged Pixel Film DLL already exists; it is left untouched.'
    }
    Write-Host 'Pixel Film is already installed.'
    return
}
New-Item -ItemType Directory -Path $rulesets -Force | Out-Null
Copy-Item -LiteralPath $source -Destination $target
try {
    @{ plugin = $name; sha256 = $package.plugin_sha256; game_version = $package.game_version } |
        ConvertTo-Json | Set-Content -LiteralPath $receipt -Encoding UTF8
} catch {
    Remove-Item -LiteralPath $target
    throw
}
Write-Host 'Pixel Film installed. Restart lazer and select the Pixel Film mode.'
