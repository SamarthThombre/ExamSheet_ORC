# scripts/verify_docker.ps1
# Builds and tests containerized Exam Paper OCR Extractor service if Docker is available.

Write-Host "Checking for Docker installation..."
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue

if (-not $dockerCmd) {
    Write-Warning "Docker CLI is not installed or not in PATH."
    Write-Host "Criterion 8 must be reported as NOT EVALUATED (Docker unavailable on host)."
    exit 0
}

Write-Host "Building Docker image 'exam-paper-extractor:deploy1'..."
docker build -t exam-paper-extractor:deploy1 -f Dockerfile .
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker build failed."
    exit 1
}

Write-Host "Starting container..."
docker run -d --name exam-extractor-test -p 8000:8000 exam-paper-extractor:deploy1
Start-Sleep -Seconds 5

Write-Host "Checking /ready healthcheck endpoint..."
try {
    $readyResp = Invoke-RestMethod -Uri "http://localhost:8000/ready" -Method Get
    Write-Host "/ready response: $($readyResp | ConvertTo-Json -Compress)"
} catch {
    Write-Error "Failed to reach /ready endpoint: $_"
    docker stop exam-extractor-test
    docker rm exam-extractor-test
    exit 1
}

Write-Host "Cleaning up container..."
docker stop exam-extractor-test
docker rm exam-extractor-test
Write-Host "Docker verification completed successfully."
