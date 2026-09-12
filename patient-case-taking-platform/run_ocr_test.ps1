# OCR Test Script — runs prescription through real PP-OCRv5-mobile model
# Usage: .\run_ocr_test.ps1

$prescriptionPath = "C:\Users\yashkumar\Desktop\pre\prescription.jpeg"
$apiPath = "C:\Users\yashkumar\Desktop\SIH\OSS\NotMID\patient-case-taking-platform\test_ocr.py"
$composePath = "C:\Users\yashkumar\Desktop\SIH\OSS\NotMID\patient-case-taking-platform"

Write-Host "Starting OCR test on: $prescriptionPath" -ForegroundColor Cyan
Write-Host "This may take 30-60 seconds on first run (model warmup)..." -ForegroundColor Yellow

$result = docker compose `
    -f "$composePath\docker-compose.yml" `
    run --rm --no-deps `
    --workdir /app `
    -e APP_ENV=development `
    -e DATABASE_MAINTENANCE_URL=postgresql://notmid:notmid-local-only@postgres:5432/notmid `
    -e S3_ENDPOINT=http://minio:9000 `
    -e S3_BUCKET=notmid-clinical `
    -e S3_ACCESS_KEY=notmid-local `
    -e S3_SECRET_KEY=notmid-local-only-change-me `
    -e OCR_PROVIDER=paddleocr_fast `
    -e PADDLE_PDX_MODEL_SOURCE=BOS `
    --volume "${prescriptionPath}:/images/prescription.jpeg:ro" `
    --volume "${apiPath}:/app/test_ocr.py:ro" `
    document-ocr-worker `
    python test_ocr.py /images/prescription.jpeg

Write-Host $result
