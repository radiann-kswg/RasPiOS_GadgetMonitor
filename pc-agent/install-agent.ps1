# GadgetMonitor Windowsエージェント インストーラ
# 実行: PowerShell (通常権限) で
#   powershell -ExecutionPolicy Bypass -File .\install-agent.ps1
# 内容:
#   1. %LOCALAPPDATA%\GadgetMonAgent へエージェントをコピー
#   2. Python仮想環境を作成し依存パッケージを導入
#   3. ログオン時に自動起動するタスクスケジューラ登録 (pythonw = 無ウィンドウ)
$ErrorActionPreference = "Stop"

$SrcDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$Dest    = Join-Path $env:LOCALAPPDATA "GadgetMonAgent"
$Venv    = Join-Path $Dest "venv"
$TaskName = "GadgetMonAgent"

Write-Host "[1/3] ファイル配置: $Dest"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
Copy-Item (Join-Path $SrcDir "gadgetmon_agent.py") $Dest -Force
Copy-Item (Join-Path $SrcDir "requirements.txt")   $Dest -Force

Write-Host "[2/3] Python仮想環境と依存パッケージ"
$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) { & py -3 -m venv $Venv } else { & python -m venv $Venv }
& (Join-Path $Venv "Scripts\python.exe") -m pip install --upgrade pip | Out-Null
& (Join-Path $Venv "Scripts\python.exe") -m pip install -r (Join-Path $Dest "requirements.txt")

Write-Host "[3/3] タスクスケジューラ登録: $TaskName"
$pythonw = Join-Path $Venv "Scripts\pythonw.exe"
$agent   = Join-Path $Dest "gadgetmon_agent.py"
$action  = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$agent`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "GadgetMonitor telemetry agent" | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host ""
Write-Host "導入完了。エージェントは現在起動済みで、次回ログオン以降も自動起動します。"
Write-Host "CPU温度も表示したい場合は LibreHardwareMonitorLib.dll を用意し、"
Write-Host "タスクの引数に --lhm-dll <DLLパス> を追加してください (pythonnet も必要)。"
