# 温度モニタリング

CPU・GPU の温度を Pi 側の画面に表示するための仕組みと、動かないときの調べ方。

## どこの温度が、どこから来るのか

| 表示位置 | 対象 | 取得元 | 前提 |
| --- | --- | --- | --- |
| CPUカード 補足行・グラフ副線 | PCのCPU（パッケージ温度） | LibreHardwareMonitorLib | **管理者権限** |
| GPUカード 補足行・グラフ副線 | PCのGPU | NVML（NVIDIA）／無ければ LibreHardwareMonitorLib | NVIDIA GPU またはLHM |
| ヘッダ左 `Pi 52C` | **Pi自身のSoC温度** | Pi の `/sys/class/thermal/thermal_zone0/temp` | なし（常に表示可） |

CPU/GPUカードのグラフは、主線（マゼンタ／警戒時は標識イエロー）が使用率[%]、
副線（淡白）が温度[℃]。どちらも 0〜100 の同一目盛に重ねている。
補足行には現在値と、観測期間中の最高値（現在値より1℃以上高いときのみ）を
`62C max78` の形で出す。PCの再起動を検知すると最高値はリセットされる。

`WARN_CPU_TEMP` / `WARN_GPU_TEMP` を超えるとカード全体が警戒配色になり、
温度が原因のときは補足行も警戒色になる（使用率超過との区別がつく）。

## なぜ CPU 温度だけ手間がかかるのか

Windows には CPU 温度を読む標準APIが無い。実測値は CPU の PECI やマザーボードの
SuperI/O チップにあり、読み出しには **カーネルドライバ経由の I/O ポートアクセス**が要る。
`MSAcpi_ThermalZoneTemperature`（WMI）はデスクトップ機ではまず実装されていない。

そこで本エージェントは **LibreHardwareMonitorLib**（MPL-2.0）を pythonnet で
インプロセス読み込みして使う。LibreHardwareMonitor の GUI を常駐させる必要は無い。

- DLL は **本リポジトリには同梱しない**。`install-agent.ps1` が
  [GitHub の公式リリース](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases)
  から net472 版の配布zip（`LibreHardwareMonitor.zip`）を取得し、直下のDLLを
  `%LOCALAPPDATA%\GadgetMonAgent\lhm\` へまとめて置く。
  NuGetパッケージを使わないのは、0.9.5以降のパッケージが実体を
  `runtimes/<RID>/lib/` 配下に置き（`lib/` 直下は参照専用アセンブリ）、
  依存アセンブリ（HidSharp / System.Memory / System.Threading.AccessControl ほか）
  を同梱しないため。配布zipなら net472 用の依存一式が揃っている。
- センサ読み出し時、LibreHardwareMonitor は自前のカーネルドライバをサービスとして
  登録する。このため **エージェントは管理者権限で動作している必要がある**。
  `install-agent.ps1` はタスクを「最上位の特権で実行する」で登録する
  （登録操作自体に管理者権限が要るので、必要ならUACで昇格をうながす）。
- **権限が無いと例外ではなく `0.0` が返る。** LibreHardwareMonitor はドライバを
  読み込めなくてもセンサ自体は列挙し、値だけが 0.0 になる。0℃ と表示するのは
  誤情報なので、エージェント側で 1〜200℃ の範囲外を「未取得(null)」へ落としている。

「最上位の特権で実行する」が効くのは、ログオンするアカウント自身が
Administrators グループに属している場合（UACの管理者承認モード）。
標準ユーザで常用している環境では昇格できないため、CPU温度は取得できない。
その場合は `-NoCpuTemp` で導入し、GPU温度とPi本体温度だけを使う。

### メモリ整合性（HVCI / コア分離）が有効だと管理者権限でも取れない

**Windows 11 で最も多い原因。** LibreHardwareMonitor が使う `WinRing0` 系
カーネルドライバは Microsoft の**脆弱ドライバブロックリスト**の対象で、
メモリ整合性（Core Isolation / HVCI）が有効な環境では読み込めない。

このとき症状は「エラーが出ない」形で現れる。

- センサ自体は列挙される（`Core (Tctl/Tdie)` などが見える）
- **値だけが 0.0 になる**。ドライバの読み込み試行がイベントログにも残らない
- ドライバサービス（`WinRing0*`）は作成されない
- 一方、カーネルドライバを使わない NVIDIA GPU 温度（NVAPI経由）は正常に読める
  ＝ **同一プロセス内でCPUだけ 0.0** なら、ほぼこれ

確認:

```powershell
(Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity" -Name Enabled).Enabled
(Get-CimInstance -Namespace root\Microsoft\Windows\DeviceGuard -ClassName Win32_DeviceGuard).SecurityServicesRunning
```

`Enabled = 1` かつ `SecurityServicesRunning` に `2` が含まれていれば有効。
`--selftest` と `agent.log` でも `hvci=True` として報告する。

対処は次の2択で、**どちらを選ぶかは利用者の判断**。

| 選択 | 内容 | 代償 |
| --- | --- | --- |
| CPU温度を取る | Windows セキュリティ > デバイス セキュリティ > コア分離 > メモリ整合性 を**オフ**にして再起動 | カーネルレベルの保護機能を1つ落とす |
| CPU温度を諦める | `install-agent.ps1 -NoCpuTemp` で導入し直す | CPU温度は `--C` のまま。GPU温度とPi本体温度は表示される |

`MSAcpi_ThermalZoneTemperature`（WMI）はデスクトップ機ではまず実装されて
おらず、代替にならない（実測でも「サポートされていません」）。

GPU 温度は NVIDIA なら NVML（`nvidia-ml-py`）で権限不要に取れる。
AMD / Intel GPU の場合は LibreHardwareMonitorLib 側から拾う
（`--lhm-gpu auto` の既定動作。NVMLが使えないときだけ LHM の GPU を有効化する）。

## 導入

```powershell
cd pc-agent
powershell -ExecutionPolicy Bypass -File .\install-agent.ps1
```

UACの確認が出たら「はい」を選ぶ。断った場合も温度以外は導入される。

| オプション | 用途 |
| --- | --- |
| `-NoCpuTemp` | 温度取得を導入しない（DLLのダウンロードも昇格も行わない） |
| `-LhmDir <フォルダ>` | オフライン導入。net472版配布zipを展開したフォルダを指定（直下のDLLを全てコピーする） |
| `-LhmTag <タグ>` | 取得するリリースを固定（例 `v0.9.6`）。既定は最新 |

昇格した側のウィンドウの記録は `%TEMP%\GadgetMonAgent-install.log` に残る。
失敗時もエラー内容を表示してキー入力を待つので、そこで読める。

## 動かないときの確認手順

### 1. エージェントの自己診断

```powershell
& "$env:LOCALAPPDATA\GadgetMonAgent\venv\Scripts\python.exe" `
  "$env:LOCALAPPDATA\GadgetMonAgent\gadgetmon_agent.py" --selftest
```

検出できた温度センサの一覧と、実際に送信するJSONが表示される。

**注意: `--selftest` は実行したPowerShellの権限で動く。** 通常のプロンプトから
実行すると常に `elevated : NO` になり温度も 0.0 になるので、温度の確認は
**管理者権限のPowerShellから**行うこと。常駐タスク側が昇格できているかは
`agent.log` の `elevated=True` と、次で確認する。

```powershell
(Get-ScheduledTask -TaskName GadgetMonAgent).Principal.RunLevel   # Highest なら正
```

### 2. 常駐時のログ

`%LOCALAPPDATA%\GadgetMonAgent\agent.log`

| ログの記述 | 意味と対処 |
| --- | --- |
| `thermal: LibreHardwareMonitorLib.dll not found` | DLL未配置。`install-agent.ps1` を管理者権限で再実行 |
| `thermal: LibreHardwareMonitor init failed` | pythonnet 未導入、または依存アセンブリ不足（`lhm\` に配布zip直下のDLLが揃っているか） |
| `thermal: WARNING - not running elevated` | タスクが「最上位の特権」で登録されていない。管理者権限で再インストール |
| `thermal: first sample {'cpu': None, ...}` | DLLは読めたがセンサ値が無効。ほぼ権限不足（`--selftest` で `<- 無効値` を確認） |

タスクの特権レベルは次で確認できる（`HighestAvailable` なら正）。

```powershell
(Get-ScheduledTask -TaskName GadgetMonAgent).Principal.RunLevel
```

### 3. Pi側の表示

温度が取れていない項目は**補足行から消える**（CPU温度が無ければ `4.2GHz` だけになる）。
数値が出ていて警戒配色なら、しきい値超過。
グラフの副線が途切れている区間は、その間だけ温度が取れていなかったことを示す。

Pi自身の温度（ヘッダの `Pi 52C`）は `/boot/firmware/gadgetmon.conf` の
`SHOW_PI_TEMP=0` で非表示にできる。

## セキュリティ上の注意

- センサ読み出し用のカーネルドライバは I/O ポートへの低レベルアクセスを行う。
  常時稼働させることの意味を理解したうえで導入すること。温度表示が不要なら
  `-NoCpuTemp` で入れないほうがよい。
- `uninstall-agent.ps1` を管理者権限で実行すると、残留したドライバサービス
  （`WinRing0*` / `*LibreHardwareMonitor*`）も削除する。

## ライセンス

LibreHardwareMonitorLib は **MPL-2.0**、HidSharp は **Apache-2.0**。
いずれも本リポジトリには含まれず、インストーラが nuget.org から取得する。
本リポジトリの CC BY 4.0 はこれらには及ばない。
