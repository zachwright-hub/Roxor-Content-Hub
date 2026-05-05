$input_json = $input | Out-String
try {
    $data = $input_json | ConvertFrom-Json
    $prompt = ($data.user_prompt -replace '\s+', ' ').Trim().ToLower()
} catch {
    exit 0
}

if ($prompt -ne 'push') {
    exit 0
}

Set-Location "C:\Users\Zach.Wright\Desktop\Projects\chairman mao"

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm"
git add -A 2>&1 | Out-Null
$commitResult = git commit -m "Save: $timestamp" 2>&1
$pushResult = git push 2>&1

if ($LASTEXITCODE -eq 0) {
    $msg = "Pushed to GitHub at $timestamp"
} else {
    $msg = "Push failed: $pushResult"
}

@{ continue = $false; stopReason = $msg } | ConvertTo-Json -Compress
