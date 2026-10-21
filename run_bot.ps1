# 持續執行 Bot：當掉會在 10 秒後自動重啟，輸出寫進 logs\bot.log
# 由工作排程器在開機時執行（見 install_autostart.ps1），也可以手動執行
Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force logs | Out-Null
$log = Join-Path $PSScriptRoot "logs\bot.log"

while ($true) {
    # 超過 5MB 就換新檔，舊的留一份 bot.log.old
    if ((Test-Path $log) -and (Get-Item $log).Length -gt 5MB) {
        Move-Item $log "$log.old" -Force
    }
    # 用 cmd 轉向，log 才會是 UTF-8（PowerShell 5.1 的 >> 會寫成 UTF-16）
    cmd /c "echo [$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] bot starting >> `"$log`""
    cmd /c "`"$PSScriptRoot\.venv\Scripts\python.exe`" -m uvicorn app:app --host 127.0.0.1 --port 8000 >> `"$log`" 2>&1"
    $code = $LASTEXITCODE
    cmd /c "echo [$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] bot exited with code $code, restarting in 10s >> `"$log`""
    Start-Sleep -Seconds 10
}
