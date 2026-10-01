param([Parameter(Mandatory = $true)][string]$PackageDirectory)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../build/client-patch'))
$fixture = Join-Path $root ('install-test-' + [Guid]::NewGuid().ToString('N'))
$storage = Join-Path $fixture 'storage'
$game = Join-Path $fixture 'game'
$package = Join-Path $fixture 'package'
New-Item -ItemType Directory -Path $storage, $game, $package -Force | Out-Null
# Isolate the process inventory as well as all files; this never closes the user's game.
function Get-Process { param($Name, $ErrorAction) @() }
function Assert-True($Passed, $Name) { if (-not $Passed) { throw "FAIL: $Name" } }
function Expect-Failure([scriptblock]$Run, $Name) {
    $failed = $false
    try { & $Run } catch { $failed = $true }
    Assert-True $failed $Name
}
try {
    $name = 'osu.Game.Rulesets.PixelFilm.dll'
    Copy-Item -LiteralPath (Join-Path $PackageDirectory $name), (Join-Path $PackageDirectory 'manage-patch.ps1') -Destination $package
    $hashes = @{}
    foreach ($file in @('osu.Game.dll', 'osu.Game.Rulesets.Mania.dll', 'osu.Framework.dll')) {
        [IO.File]::WriteAllText((Join-Path $game $file), "fixture-original-$file")
        $hashes[$file] = (Get-FileHash -LiteralPath (Join-Path $game $file) -Algorithm SHA256).Hash
    }
    [IO.File]::WriteAllText((Join-Path $storage 'client.realm'), 'untouched-fixture')
    New-Item -ItemType Directory -Path (Join-Path $storage 'rulesets') -Force | Out-Null
    $other = Join-Path $storage 'rulesets/other.dll'
    [IO.File]::WriteAllText($other, 'another-plugin')
    $manifest = @{ game_version = 'test-fixture'; assemblies = $hashes;
        plugin_sha256 = (Get-FileHash -LiteralPath (Join-Path $package $name) -Algorithm SHA256).Hash }
    $manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $package 'package.json') -Encoding UTF8
    $manage = Join-Path $package 'manage-patch.ps1'
    $target = Join-Path $storage "rulesets/$name"
    $receipt = Join-Path $storage 'rulesets/pixel-film-install.json'

    [IO.File]::WriteAllText((Join-Path $game 'osu.Game.dll'), 'changed-version')
    Expect-Failure { & $manage -StorageDirectory $storage -GameDirectory $game } 'unsupported game rejected'
    Assert-True (-not (Test-Path -LiteralPath $target)) 'rejected installation writes nothing'
    [IO.File]::WriteAllText((Join-Path $game 'osu.Game.dll'), 'fixture-original-osu.Game.dll')
    & $manage -StorageDirectory $storage -GameDirectory $game
    Assert-True ((Get-FileHash -LiteralPath $target).Hash -eq $manifest.plugin_sha256) 'plugin copied exactly'
    $before = [IO.File]::ReadAllText($receipt)
    & $manage -StorageDirectory $storage -GameDirectory $game
    Assert-True ([IO.File]::ReadAllText($receipt) -eq $before) 'repeat install is unchanged'
    [IO.File]::WriteAllText($target, 'user-modified-plugin')
    Expect-Failure { & $manage -Action Uninstall -StorageDirectory $storage } 'modified plugin preserved'
    Assert-True ([IO.File]::ReadAllText($target) -eq 'user-modified-plugin') 'modified bytes unchanged'
    Copy-Item -LiteralPath (Join-Path $package $name) -Destination $target -Force
    & $manage -Action Uninstall -StorageDirectory $storage
    & $manage -Action Uninstall -StorageDirectory $storage
    Assert-True (-not (Test-Path -LiteralPath $target) -and -not (Test-Path -LiteralPath $receipt)) 'uninstall removes only owned files'
    [IO.File]::WriteAllText($target, 'unmanaged-plugin')
    Expect-Failure { & $manage -StorageDirectory $storage -GameDirectory $game } 'unmanaged plugin is not overwritten'
    Expect-Failure { & $manage -Action Uninstall -StorageDirectory $storage } 'unmanaged plugin is not deleted'
    Assert-True ([IO.File]::ReadAllText($target) -eq 'unmanaged-plugin') 'unmanaged bytes unchanged'
    function Get-Process { param($Name, $ErrorAction) [PSCustomObject]@{ ProcessName = 'osu!' } }
    Expect-Failure { & $manage -StorageDirectory $storage -GameDirectory $game } 'running client blocks installation'
    Assert-True ([IO.File]::ReadAllText((Join-Path $storage 'client.realm')) -eq 'untouched-fixture') 'game data preserved'
    Assert-True ([IO.File]::ReadAllText($other) -eq 'another-plugin') 'other plugin preserved'
    foreach ($file in $hashes.Keys) {
        Assert-True ((Get-FileHash -LiteralPath (Join-Path $game $file)).Hash -eq $hashes[$file]) 'official client files preserved'
    }
    Write-Host 'PASS: install/uninstall, repeat operations, version guard, modified and unmanaged files, running game, original files and data.'
} finally {
    $resolved = (Resolve-Path -LiteralPath $fixture).Path
    if (-not $resolved.StartsWith($root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Unsafe fixture cleanup path.'
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
