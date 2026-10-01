param([string]$GameDirectory = (Join-Path $env:LOCALAPPDATA 'osulazer/current'))
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$gamePath = (Resolve-Path -LiteralPath $GameDirectory).Path
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'compatibility.json') -Raw | ConvertFrom-Json
foreach ($entry in $manifest.assemblies.PSObject.Properties) {
    if ((Get-FileHash -LiteralPath (Join-Path $gamePath $entry.Name) -Algorithm SHA256).Hash -ne $entry.Value) {
        throw "Unsupported lazer assembly: $($entry.Name). Build targets $($manifest.game_version)."
    }
}
$output = Join-Path $root 'build/client-patch'
New-Item -ItemType Directory -Path $output -Force | Out-Null
$sdk = (& dotnet --list-sdks | Select-Object -Last 1)
if (-not $sdk) { throw 'A .NET SDK is required to build the patch.' }
$sdkVersion = $sdk.Split(' ')[0]
$sdkRoot = [regex]::Match($sdk, '\[(.*)\]').Groups[1].Value
$compiler = Join-Path $sdkRoot "$sdkVersion/Roslyn/bincore/csc.dll"
$library = Join-Path $output 'osu.Game.Rulesets.PixelFilm.dll'
$arguments = @('/nologo', '/nostdlib+', '/nullable:enable', '/langversion:latest', '/deterministic+', '/target:library',
    ('/out:"' + $library + '"'), ('/resource:"' + (Join-Path $PSScriptRoot 'compatibility.json') + '",PixelFilm.compatibility'))
foreach ($file in Get-ChildItem -LiteralPath $gamePath -Filter '*.dll') {
    try { [Reflection.AssemblyName]::GetAssemblyName($file.FullName) | Out-Null }
    catch { continue }
    $arguments += '/reference:"' + $file.FullName + '"'
}
$references = $arguments | Where-Object { $_ -like '/reference:*' }
foreach ($source in Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'src') -Filter '*.cs') {
    $arguments += '"' + $source.FullName + '"'
}
$response = Join-Path $output 'build.rsp'
$arguments | Set-Content -LiteralPath $response -Encoding UTF8
& dotnet exec $compiler "@$response"
if ($LASTEXITCODE -ne 0) { throw 'Patch compilation failed.' }

$testLibrary = Join-Path $output 'ClientTests.dll'
$testArguments = @('/nologo', '/nostdlib+', '/nullable:enable', '/target:exe', ('/out:"' + $testLibrary + '"'),
    ('/reference:"' + $library + '"')) + $references
foreach ($source in Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'tests') -Filter '*.cs') {
    $testArguments += '"' + $source.FullName + '"'
}
$testResponse = Join-Path $output 'tests.rsp'
$testArguments | Set-Content -LiteralPath $testResponse -Encoding UTF8
& dotnet exec $compiler "@$testResponse"
if ($LASTEXITCODE -ne 0) { throw 'Client test compilation failed.' }
& dotnet exec --runtimeconfig (Join-Path $gamePath 'osu!.runtimeconfig.json') --depsfile (Join-Path $gamePath 'osu!.deps.json') $testLibrary $gamePath
if ($LASTEXITCODE -ne 0) { throw 'Client regression failed.' }

$package = Join-Path $root 'dist/pixel-film-patch'
New-Item -ItemType Directory -Path $package -Force | Out-Null
Copy-Item -LiteralPath $library -Destination $package
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'manage-patch.ps1'), (Join-Path $PSScriptRoot 'install.cmd'), (Join-Path $PSScriptRoot 'uninstall.cmd') -Destination $package
Copy-Item -LiteralPath (Join-Path $root 'docs/client-patch.md') -Destination (Join-Path $package 'README.md')
$packageManifest = @{ game_version = $manifest.game_version; assemblies = $manifest.assemblies;
    plugin_sha256 = (Get-FileHash -LiteralPath $library -Algorithm SHA256).Hash.ToLowerInvariant() }
$packageManifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $package 'package.json') -Encoding UTF8
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'tests/InstallTests.ps1') -PackageDirectory $package
if ($LASTEXITCODE -ne 0) { throw 'Install/uninstall regression failed.' }
Compress-Archive -Path (Join-Path $package '*') -DestinationPath (Join-Path $root 'dist/pixel-film-patch.zip') -Force
Write-Host "Built and tested: $package"
