# GadgetMonitor Windowsエージェント アンインストーラ
#
# 温度取得を使っていた場合、LibreHardwareMonitor がセンサ読み出し用の
# カーネルドライバをサービスとして登録している。エージェントが強制終了
# された場合これが残ることがあるため、管理者権限で実行すると併せて削除する。
$ErrorActionPreference = "SilentlyContinue"

Stop-ScheduledTask -TaskName "GadgetMonAgent"
Unregister-ScheduledTask -TaskName "GadgetMonAgent" -Confirm:$false
Remove-Item -Recurse -Force (Join-Path $env:LOCALAPPDATA "GadgetMonAgent")
Write-Host "GadgetMonAgent を削除しました。"

$IsAdmin = ([Security.Principal.WindowsPrincipal] `
	[Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
	[Security.Principal.WindowsBuiltinRole]::Administrator)

$drivers = Get-Service | Where-Object {
	$_.Name -like "WinRing0*" -or $_.Name -like "*LibreHardwareMonitor*"
}
foreach ($svc in $drivers) {
	if ($IsAdmin) {
		Write-Host "センサ用ドライバサービスを削除: $($svc.Name)"
		Stop-Service -Name $svc.Name -Force
		& sc.exe delete $svc.Name | Out-Null
	} else {
		Write-Host "センサ用ドライバサービスが残っています: $($svc.Name)"
		Write-Host "  削除するには管理者権限で本スクリプトを実行してください。"
	}
}
