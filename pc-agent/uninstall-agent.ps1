# GadgetMonitor Windowsエージェント アンインストーラ
$ErrorActionPreference = "SilentlyContinue"
Stop-ScheduledTask -TaskName "GadgetMonAgent"
Unregister-ScheduledTask -TaskName "GadgetMonAgent" -Confirm:$false
Remove-Item -Recurse -Force (Join-Path $env:LOCALAPPDATA "GadgetMonAgent")
Write-Host "GadgetMonAgent を削除しました。"
