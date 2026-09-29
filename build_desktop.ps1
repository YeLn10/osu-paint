param([string]$Python = "python")

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$environment = Join-Path $root ".build-env"
$buildPython = Join-Path $environment "Scripts\python.exe"

# Keep packaging tools isolated from the user's Python installation.
if (-not (Test-Path -LiteralPath $buildPython)) {
    & $Python -m venv $environment
    if ($LASTEXITCODE -ne 0) { throw "Could not create the packaging environment." }
}
& $buildPython -m pip install --disable-pip-version-check "pyinstaller==6.22.3" -r (Join-Path $root "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Could not install packaging/video dependencies." }

& $buildPython -m PyInstaller --noconfirm --onefile --windowed --collect-all imageio_ffmpeg --name osu-paint `
    --distpath (Join-Path $root "dist") --workpath (Join-Path $root "build") `
    --specpath (Join-Path $root "build") (Join-Path $root "osu-paint.pyw")
if ($LASTEXITCODE -ne 0) { throw "Desktop packaging failed." }
Write-Host "Built: $(Join-Path $root 'dist\osu-paint.exe')"
