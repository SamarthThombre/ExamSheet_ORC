# PowerShell CI runner wrapper
$ErrorActionPreference = "Stop"
$PythonExe = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python"
}
& $PythonExe "scripts/run_ci.py"
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
