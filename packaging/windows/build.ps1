param(
    [string]$AppVersion
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repoRoot

$basePython = (Get-Command python -ErrorAction Stop).Source
$buildVenv = Join-Path $repoRoot ".venv-windows-build"
$python = Join-Path $buildVenv "Scripts\python.exe"
if (-not (Test-Path $python)) {
    & $basePython -m venv $buildVenv
    if ($LASTEXITCODE -ne 0) { throw "Falha criando o ambiente de build." }
}
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Falha instalando dependências do motor." }
& $python -m pip install -r packaging/windows/requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Falha instalando dependências de empacotamento Windows." }

$dist = Join-Path $repoRoot "dist\windows"
$work = Join-Path $repoRoot "build\windows"
$assets = Join-Path $repoRoot "posvirtual\assets"
if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }
New-Item -ItemType Directory -Force -Path $dist, $work | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $dist "installer") | Out-Null

& $python -m PyInstaller --noconfirm --clean --onedir --console `
    --name POSvirtualServer --distpath $dist --workpath $work --specpath $work `
    --collect-submodules reportlab.graphics.barcode `
    --add-data "$assets;posvirtual/assets" `
    packaging/windows/server_entry.py
if ($LASTEXITCODE -ne 0) { throw "Falha empacotando o servidor POSvirtual." }

& $python -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name POSvirtualTray --distpath $dist --workpath $work --specpath $work `
    --collect-all pystray `
    --collect-submodules reportlab.graphics.barcode `
    --hidden-import tkinter --hidden-import tkinter.ttk `
    --add-data "$assets;posvirtual/assets" `
    packaging/windows/tray_entry.py
if ($LASTEXITCODE -ne 0) { throw "Falha empacotando a bandeja POSvirtual." }

$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $iscc) {
    $candidate = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
    if (Test-Path $candidate) { $iscc = @{ Source = $candidate } }
}
if (-not $iscc) { throw "Instale Inno Setup 6 para gerar o instalador EXE." }

if ($AppVersion -and $AppVersion -notmatch '^\d+(\.\d+){1,3}$') {
    throw "Versão Windows inválida: $AppVersion"
}

$compilerArgs = @()
if ($AppVersion) { $compilerArgs += "/DAppVersion=$AppVersion" }
$compilerArgs += "packaging/windows/posvirtual.iss"
& $iscc.Source @compilerArgs
if ($LASTEXITCODE -ne 0) { throw "Falha gerando o instalador Windows." }
