#Requires -RunAsAdministrator
# 建立開機自動啟動 Bot 的排程工作（需用系統管理員身分執行一次）
#   安裝：powershell -ExecutionPolicy Bypass -File D:\calorie-bot\install_autostart.ps1
#   移除：powershell -ExecutionPolicy Bypass -File D:\calorie-bot\install_autostart.ps1 -Uninstall
param([switch]$Uninstall)

$name = "calorie-bot"
if ($Uninstall) {
    Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object CommandLine -like "*uvicorn app:app*" |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Write-Host "已移除開機自動啟動，Bot 已停止"
    return
}

$root = $PSScriptRoot
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$root\run_bot.ps1`"" `
    -WorkingDirectory $root
# 開機就啟動，不需要登入 Windows
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Description "減脂小幫手 LINE Bot（D:\calorie-bot）" -Force | Out-Null
Start-ScheduledTask -TaskName $name
Write-Host "✅ 已設定開機自動啟動，Bot 已在背景啟動"
Write-Host "   執行紀錄：$root\logs\bot.log"
