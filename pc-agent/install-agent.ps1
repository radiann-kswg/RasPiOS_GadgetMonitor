# GadgetMonitor Windowsエージェント インストーラ
#
# 実行:
#   powershell -ExecutionPolicy Bypass -File .\install-agent.ps1
#
# 内容:
#   1. %LOCALAPPDATA%\GadgetMonAgent へエージェントをコピー
#   2. Python仮想環境を作成し依存パッケージを導入
#   3. 温度センサ用に LibreHardwareMonitor の net472 配布物を取得して配置
#   4. ログオン時に自動起動するタスクスケジューラ登録 (pythonw = 無ウィンドウ)
#
# CPU温度について (docs/temperature.md):
#   Windows には CPU 温度を読む標準APIが無く、カーネルドライバ経由の読み出しが
#   要る。そのため LibreHardwareMonitorLib.dll (MPL-2.0) を GitHub の公式
#   リリース配布物から取得し、タスクを「最上位の特権」で登録する。管理者権限が
#   無ければUACで昇格を求め、断られた場合は温度以外の項目だけで導入を続行する。
#   NuGetパッケージではなく配布zipを使うのは、0.9.5以降のNuGetが実体を
#   runtimes/<RID>/lib/ 配下に置きかつ依存アセンブリを同梱しないため
#   （配布zipは net472 用の依存一式が揃っている）。
param(
	# 温度取得を導入しない (DLLのダウンロードと昇格を行わない)
	[switch]$NoCpuTemp,
	# 既にダウンロード済みのDLLを使う (DLLを含むフォルダを指定。オフライン導入)
	[string]$LhmDir = "",
	# 取得するリリースタグ (既定: 最新)
	[string]$LhmTag = "",
	# 以下は昇格時の再実行で内部的に使う
	[switch]$NoElevate,
	[switch]$Pause,
	[string]$TargetUser = "",
	[string]$TargetLocalAppData = ""
)
$ErrorActionPreference = "Stop"

# 昇格して開いた別ウィンドウでは、失敗すると内容を読む間もなく閉じてしまう。
# 終了理由を必ず表示し、-Pause 時はキー入力を待ってから閉じる。
trap {
	Write-Host ""
	Write-Host "インストールに失敗しました: $_" -ForegroundColor Red
	Write-Host $_.ScriptStackTrace
	if ($Pause) { Read-Host "Enterキーでこのウィンドウを閉じます" | Out-Null }
	exit 1
}

$SrcDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$WantTemp = -not $NoCpuTemp

$IsAdmin = ([Security.Principal.WindowsPrincipal] `
	[Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
	[Security.Principal.WindowsBuiltinRole]::Administrator)

# --- 温度取得には管理者権限が要るので、必要なら昇格して実行し直す -------------
# 別の管理者アカウントで昇格された場合に備え、導入先ユーザとプロファイルの
# パスは昇格前の値を引き継ぐ。
if ($WantTemp -and -not $IsAdmin -and -not $NoElevate) {
	Write-Host "CPU温度の取得にはカーネルドライバの導入が必要なため、"
	Write-Host "管理者権限で実行し直します (UACの確認が出ます)。"
	Write-Host "温度が不要なら -NoCpuTemp を付けて実行してください。"
	$argv = @("-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"",
		"-NoElevate", "-Pause",
		"-TargetUser", "`"$env:USERDOMAIN\$env:USERNAME`"",
		"-TargetLocalAppData", "`"$env:LOCALAPPDATA`"")
	if ($LhmDir) { $argv += @("-LhmDir", "`"$LhmDir`"") }
	if ($LhmTag) { $argv += @("-LhmTag", "`"$LhmTag`"") }
	try {
		$proc = Start-Process -FilePath "powershell.exe" -ArgumentList $argv `
			-Verb RunAs -PassThru -Wait
		Write-Host "昇格側の記録: $env:TEMP\GadgetMonAgent-install.log"
		exit $proc.ExitCode
	} catch {
		Write-Warning "昇格をキャンセルしました。CPU温度なしで導入を続けます。"
		$WantTemp = $false
	}
}

if ($TargetUser) { $UserId = $TargetUser }
else { $UserId = "$env:USERDOMAIN\$env:USERNAME" }
if ($TargetLocalAppData) { $LocalAppData = $TargetLocalAppData }
else { $LocalAppData = $env:LOCALAPPDATA }

# 昇格側のウィンドウは閉じると読めなくなるので記録を残す
if ($Pause) {
	Start-Transcript -Path (Join-Path $env:TEMP "GadgetMonAgent-install.log") `
		-Force -ErrorAction SilentlyContinue | Out-Null
}

$Dest     = Join-Path $LocalAppData "GadgetMonAgent"
$Venv     = Join-Path $Dest "venv"
$LhmDest  = Join-Path $Dest "lhm"
$LogPath  = Join-Path $Dest "agent.log"
$TaskName = "GadgetMonAgent"

Write-Host "[1/4] ファイル配置: $Dest"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
Copy-Item (Join-Path $SrcDir "gadgetmon_agent.py") $Dest -Force
Copy-Item (Join-Path $SrcDir "requirements.txt")   $Dest -Force

Write-Host "[2/4] Python仮想環境と依存パッケージ"
$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) { & py -3 -m venv $Venv } else { & python -m venv $Venv }
$VenvPy = Join-Path $Venv "Scripts\python.exe"
& $VenvPy -m pip install --upgrade pip | Out-Null
& $VenvPy -m pip install -r (Join-Path $Dest "requirements.txt")

# --- 温度センサ用アセンブリ ---------------------------------------------------
# GitHub の公式リリースから net472 版の配布zip (LibreHardwareMonitor.zip) を取得し、
# 直下のDLLを一式コピーする。pythonnet の既定ランタイムが .NET Framework なので
# net472 版を使い、依存アセンブリ (HidSharp / System.Memory 等) も揃った状態にする。
$LHM_REPO = "LibreHardwareMonitor/LibreHardwareMonitor"
$LHM_ASSET = "LibreHardwareMonitor.zip"   # net472版。.NET 10版は別assetなので使わない

function Get-LhmZipUrl([string]$Tag) {
	if ($Tag) {
		return "https://github.com/$LHM_REPO/releases/download/$Tag/$LHM_ASSET"
	}
	return "https://github.com/$LHM_REPO/releases/latest/download/$LHM_ASSET"
}

function Install-LhmAssemblies([string]$DestDir, [string]$Tag) {
	$url = Get-LhmZipUrl $Tag
	$tmp = Join-Path ([IO.Path]::GetTempPath()) ("gadgetmon_" + [Guid]::NewGuid().ToString("N"))
	New-Item -ItemType Directory -Force -Path $tmp | Out-Null
	try {
		$zip = Join-Path $tmp "lhm.zip"
		try {
			Write-Host "      取得: $url"
			Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
		} catch {
			# asset名が変わっている場合に備えてリリース情報から探し直す
			Write-Host "      直接URLが取れなかったのでリリース情報を照会します"
			$api = "https://api.github.com/repos/$LHM_REPO/releases/latest"
			$rel = Invoke-RestMethod -Uri $api -UseBasicParsing `
				-Headers @{ "User-Agent" = "gadgetmon-installer" }
			$asset = $rel.assets | Where-Object {
				$_.name -like "*.zip" -and $_.name -notlike "*NET*"
			} | Select-Object -First 1
			if (-not $asset) { throw "net472版のzipが見つかりません" }
			Write-Host "      取得: $($asset.browser_download_url)"
			Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing
		}
		Expand-Archive -Path $zip -DestinationPath (Join-Path $tmp "x") -Force
		# 直下のDLLのみ（言語別リソースのサブフォルダとGUI本体は不要）
		$dlls = Get-ChildItem -Path (Join-Path $tmp "x") -Filter *.dll
		if (-not ($dlls | Where-Object { $_.Name -eq "LibreHardwareMonitorLib.dll" })) {
			throw "LibreHardwareMonitorLib.dll が配布物に含まれていません"
		}
		$dlls | ForEach-Object { Copy-Item $_.FullName $DestDir -Force }
		Write-Host "      $($dlls.Count) 個のアセンブリを配置しました"
	} finally {
		Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
	}
}

if ($WantTemp) {
	Write-Host "[3/4] 温度センサ (LibreHardwareMonitorLib)"
	New-Item -ItemType Directory -Force -Path $LhmDest | Out-Null
	& $VenvPy -m pip install "pythonnet>=3.0"
	if ($LhmDir) {
		Write-Host "      ローカルフォルダから配置: $LhmDir"
		Get-ChildItem -Path $LhmDir -Filter *.dll |
			ForEach-Object { Copy-Item $_.FullName $LhmDest -Force }
	} else {
		try {
			Install-LhmAssemblies $LhmDest $LhmTag
		} catch {
			Write-Warning "LibreHardwareMonitor の取得に失敗しました: $_"
			Write-Warning "温度なしで続行します。オフライン導入は -LhmDir を使ってください。"
		}
	}
	if (-not (Test-Path (Join-Path $LhmDest "LibreHardwareMonitorLib.dll"))) {
		$WantTemp = $false
	}
} else {
	Write-Host "[3/4] 温度センサ: スキップ (-NoCpuTemp)"
	# 以前の導入分が残っているとエージェントが読みに行くので消しておく
	if (Test-Path $LhmDest) {
		Remove-Item -Recurse -Force $LhmDest
		Write-Host "      既存の $LhmDest を削除しました"
	}
}

Write-Host "[4/4] タスクスケジューラ登録: $TaskName ($UserId)"
$pythonw = Join-Path $Venv "Scripts\pythonw.exe"
$agent = Join-Path $Dest "gadgetmon_agent.py"
$argline = "`"$agent`" --log `"$LogPath`""
if ($NoCpuTemp) { $argline += " --no-cpu-temp" }
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $argline
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId
$settings = New-ScheduledTaskSettingsSet `
	-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
	-RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
	-ExecutionTimeLimit (New-TimeSpan -Seconds 0)
# 温度センサの読み出しにはカーネルドライバが要るため最上位の特権で動かす
if ($WantTemp -and $IsAdmin) { $RunLevel = "Highest" } else { $RunLevel = "Limited" }
$principal = New-ScheduledTaskPrincipal -UserId $UserId `
	-LogonType Interactive -RunLevel $RunLevel
# 旧インスタンスが残ったまま二重送信にならないよう、止めてから登録し直す
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
	-Settings $settings -Principal $principal `
	-Description "GadgetMonitor telemetry agent" | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host ""
Write-Host "導入完了。エージェントは現在起動済みで、次回ログオン以降も自動起動します。"
Write-Host "  ログ     : $LogPath"
Write-Host "  動作確認 : `"$VenvPy`" `"$agent`" --selftest"
if ($WantTemp -and $IsAdmin) {
	Write-Host "  CPU温度  : 有効 (LibreHardwareMonitorLib / 最上位の特権で実行)"
} elseif ($NoCpuTemp) {
	Write-Host "  CPU温度  : 無効 (-NoCpuTemp 指定)"
} else {
	Write-Host "  CPU温度  : 無効。管理者権限のPowerShellから再実行すると有効になります。"
}
if ($Pause) {
	Stop-Transcript -ErrorAction SilentlyContinue | Out-Null
	Write-Host ""
	Read-Host "Enterキーでこのウィンドウを閉じます" | Out-Null
}
