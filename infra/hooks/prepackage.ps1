$ErrorActionPreference = "Stop"

$TMP_DIR = "infra/tmp"

if (Test-Path $TMP_DIR) {
    Write-Host "Cleaning existing $TMP_DIR..."
    Remove-Item -Recurse -Force "$TMP_DIR/*"
} else {
    Write-Host "Creating $TMP_DIR..."
    New-Item -ItemType Directory -Path $TMP_DIR -Force | Out-Null
}

Write-Host "Copying src contents to $TMP_DIR..."
Copy-Item -Recurse -Force "src/*" $TMP_DIR

Write-Host "Copying infra/assets contents to $TMP_DIR..."
Copy-Item -Recurse -Force "infra/assets/*" $TMP_DIR

$extraReq = Join-Path $TMP_DIR "extra-requirements.txt"
$mainReq = Join-Path $TMP_DIR "requirements.txt"
if (Test-Path $extraReq) {
    Write-Host "Merging extra-requirements.txt into requirements.txt..."
    Add-Content -Path $mainReq -Value ""
    Get-Content $extraReq | Add-Content -Path $mainReq
    Remove-Item $extraReq
}

Write-Host "prepackage completed successfully."
