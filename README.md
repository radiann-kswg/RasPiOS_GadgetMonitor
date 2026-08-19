# RasPiOS_GadgetMonitor

Raspberry Pi **4B** をデスクトップPCの「稼働率モニターガジェット」にする
オリジナルOSイメージ（pi-gen / arm64 / Debian trixie ベース）。

> **License**: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.ja)
> © ラジアン（柏木主税） / RadianN_kswg

PCのUSBポートとPiのUSB-Cを1本のケーブルで接続すると、**給電とデータ通信を同時に**行い、
PC側常駐エージェントが送るテレメトリ（CPU・メモリ・GPU・VRAM・ネットワーク・ディスクI/O、
負荷や温度）を、HDMI接続のディスプレイへ**グレー基調の工学モニター風GUI**で常時表示する。

```
┌──────────────┐ USB-C (電源+USBガジェットEthernet) ┌─────────────┐   HDMI   ┌─────────┐
│ デスクトップPC │ ─────────────────────────────────→ │ Raspberry Pi │ ───────→ │ ディスプレイ │
│  (Windows)    │        UDP/JSON 10.87.0.1:8787      │     4B       │          │           │
└──────────────┘                                     └─────────────┘          └─────────┘
```

## 対応ハードウェア

- **Raspberry Pi 4B**（主対象・実機検証済み。arm64・64bitイメージ）
- USB-C は給電＋USBガジェットEthernetで占有する。USBメディアからの起動と併用しないこと
- HDMI は本体の **HDMI0**（USB-C 電源端子に近い側）を使う
- 画面描画は `/dev/fb0` 直描画（`DISPLAY_BACKEND=fb` 既定）。Pi 4 の `kmsdrm` 経路は
  モード設定に成功しても映像が出ない事象を実機で確認済み

1台の Pi 4B を本プロジェクトの他イメージ（DigitalSignage / UnityConsole）と切り換えて使う手順は
[../docs/pi4b-image-switching.md](../docs/pi4b-image-switching.md) を参照。

## 表示デザイン

書体・配色は [PenchantManufacture_ImageAssets](https://github.com/radiann-kswg/PenchantManufacture_ImageAssets)
の工業デカール仕様（`docs/DECAL_VARIANTS.md`）に準拠する。

| 用途 | バリアント | 配色 |
| --- | --- | --- |
| 安定時の数値・本文 | **白銅燐光 (nickel)** | 白銅 `#CACED6→#969CA6`・キーライン `#282C32`・アクセント燐光マゼンタ `#FF4D9D`（グラフ線） |
| 警告時の数値・警戒帯 | **警戒 (hazard)** | 標識イエロー `#E8B430→#CD961C`・暗鋼縁取り・黒斜線 `#121214` |
| ラベルプレート | **墨 (sumi)** | 近黒 `#16181C→#0B0C0E`＋オフホワイト縁取り。明るい金属灰プレート上に印字 |

テキストは全てデカール流儀の「縦グラデボディ＋キーライン縁取り」で描画。
背景はグレー基調（`#24272B` / パネル `#2B2F35`）。しきい値超過したカードは
値・グラフ・上端帯が警戒色（黒斜線入り）へ切り替わる。
解像度は自動追従し、横長（FHD等）は3×2、小型パネル（800×480等）は2×3の
カードグリッドに切り替わる。

フォント: **PenchantManufacture**（ASCII＋ギリシャ文字収録のため表示は英数字のみ）。

## リポジトリ構成

```
RasPiOS_GadgetMonitor/
├── build-image.sh              # pi-gen(arm64)クローン・SKIP設定・ビルドのラッパー
├── config                      # pi-gen 設定
├── stage-gadgetmon/            # 独自ステージ
│   ├── 00-install-packages/    #   python3-pygame / dnsmasq
│   ├── 01-usb-gadget/          #   USB Ethernetガジェット(configfs)＋DHCP＋設定ファイル
│   ├── 02-monitor-app/         #   レンダラ(gadgetmon.py)＋フォント＋サービス
│   │                           #   ＋ブート経由更新(apply-boot-update.sh)
│   ├── 03-boot-config/         #   dwc2有効化・HDMI・静音起動
│   └── 04-purge-cloud-init/    #   cloud-init除去（最後に置く）
├── pc-agent/                   # Windows側エージェント一式
└── docs/
    ├── protocol.md             # UDP/JSONテレメトリ仕様
    └── temperature.md          # 温度モニタリングの仕組みと診断手順
```

## ビルド（WSL2想定）

サンドボックスや Windows ファイルシステム上ではビルドできない。
リポジトリを WSL2 内の Linux ファイルシステムへコピーして実行する。

```bash
# WSL2 (Ubuntu/Debian) 内で
cp -r /mnt/d/Claude\ Coworks\ Projectfile/RaspberryPiOSEditor/RasPiOS_GadgetMonitor ~/build/RasPiOS_GadgetMonitor
cd ~/build/RasPiOS_GadgetMonitor
sudo apt install -y coreutils quilt parted qemu-user-static debootstrap zerofree zip dosfstools \
  libarchive-tools libcap2-bin grep rsync xz-utils file git curl bc gpg pigz xxd arch-test binfmt-support
sudo ./build-image.sh native      # または Docker Desktop 環境で ./build-image.sh docker
```

成果物は `pi-gen/deploy/*.img.xz`。Raspberry Pi Imager 等でSDカードへ書き込む。
binfmtエラー時は `sudo update-binfmts --enable`。

## セットアップ手順

1. **SDカード書き込み後**（必要なら）ブートパーティションの `gadgetmon.conf` を編集
   （しきい値・USB機能クラス等。Windowsからそのまま開ける）。
2. Pi 4B にSDカードを挿し、HDMIをディスプレイへ接続。
3. **PiのUSB-Cポート**とPCのUSBポートをデータ通信対応ケーブルで接続
   （PiはPCから給電され自動起動。「WAITING FOR HOST」表示になる）。
4. PC側でエージェントを導入:
   ```powershell
   cd pc-agent
   powershell -ExecutionPolicy Bypass -File .\install-agent.ps1
   ```
   （Python 3 が必要。ログオン時自動起動のタスク `GadgetMonAgent` が登録される）
   CPU温度の取得にはカーネルドライバが要るため、途中でUACの昇格確認が出る。
   温度が不要なら `-NoCpuTemp` を付ける。
5. 数秒でテレメトリ表示が始まる。
6. 表示が想定どおりか確認する:
   ```powershell
   & "$env:LOCALAPPDATA\GadgetMonAgent\venv\Scripts\python.exe" `
     "$env:LOCALAPPDATA\GadgetMonAgent\gadgetmon_agent.py" --selftest
   ```

## 温度モニタリング

- **CPU温度** — Windows に標準APIが無いため、LibreHardwareMonitorLib（MPL-2.0、
  GitHub公式リリースの net472 配布物をインストーラが取得）を pythonnet 経由で使う。
  読み出しにカーネルドライバが要るので、タスクは「最上位の特権」で登録される。
  **メモリ整合性（コア分離）が有効な環境では取得できない**（`WinRing0` が
  脆弱ドライバブロックリスト対象のため）。不要なら `-NoCpuTemp` で導入する。
- **GPU温度** — NVIDIA は NVML（権限不要）。AMD/Intel は LibreHardwareMonitorLib から取得。
- **Pi自身のSoC温度** — ヘッダ左に `Pi 52C` として常時表示（`SHOW_PI_TEMP=0` で非表示）。
- CPU/GPUカードのグラフは主線＝使用率[%]、副線（淡白）＝温度[℃]を 0〜100 の
  同一目盛に重ねて描く。補足行は `62C max78`（観測期間中の最高値）。
  温度がしきい値を超えるとカードと補足行が警戒配色になる。
- **取得できない温度は項目ごと表示しない**（`--C` を出し続けても情報量が無いため）。
  センサが無い環境ではCPUカードの補足行はクロックだけになる。

仕組み・診断手順・ライセンスは [docs/temperature.md](docs/temperature.md) を参照。

## Pi側レンダラ・フォントだけを差し替える

イメージを焼き直さずに `gadgetmon.py` とフォントを更新する方法は2つ。

### A. ブートパーティション経由（SSH不要・推奨）

ブートパーティションは **FAT なので Windows からそのまま見える**。ここに
`gadgetmon.py` や `PenchantManufacture.otf` を置いて再起動すると、
`gadgetmon.service` の `ExecStartPre`
（[apply-boot-update.sh](stage-gadgetmon/02-monitor-app/files/opt/gadgetmon/apply-boot-update.sh)）
が rootfs 側へ取り込む。SSHもキーボードも要らない。

1. Piの電源を落とし、SDカードをPCに挿す（またはPiを起動したままなら次回起動時に反映）
2. ブートパーティション（`bootfs`）へ差し替えたいファイルをコピー
3. SDカードをPiへ戻して起動

| ブートパーティション上のファイル | 役割 |
| --- | --- |
| `gadgetmon.py` | 置くと次回起動時に `/opt/gadgetmon/gadgetmon.py` へ取り込む |
| `PenchantManufacture.otf` | 置くと次回起動時に `/opt/gadgetmon/fonts/` へ取り込む |
| `gadgetmon-update.log` | 取り込み結果。拒否された場合は理由（構文エラー等）も記録される |
| `gadgetmon-rollback` | 空ファイルを置いて再起動すると直前の版（`.bak`）へ戻す |

安全策として、**検証を通ったものだけ**を適用する（`.py` はPythonの構文チェック、
`.otf` は FreeType が実際に開いて描画できるか）。差し替え前の版は
`<対象>.bak` に残る。同じ内容なら何もしない。
`gadgetmon.conf` の `BOOT_UPDATE=0` で機能ごと無効化できる。

この取り込み処理には機能テストがある（要 python3 + pygame）:

```bash
bash tests/test-apply-boot-update.sh
```

> **注意:** この仕組みは「ブートパーティションに書ける ＝ Pi 上で root として
> 任意のコードを実行できる」ことを意味する。SDカードを物理的に扱える人には
> どのみち rootfs も書けるため実質的な差は小さいが、共有環境に置くなど
> 気になる用途では `BOOT_UPDATE=0` にすること。

### B. SSH経由

```powershell
scp -O stage-gadgetmon/02-monitor-app/files/opt/gadgetmon/gadgetmon.py gadget@10.87.0.1:/tmp/
ssh -t gadget@10.87.0.1 "sudo install -m 755 /tmp/gadgetmon.py /opt/gadgetmon/gadgetmon.py && sudo systemctl restart gadgetmon"
```

フォントの場合:

```powershell
scp -O stage-gadgetmon/02-monitor-app/files/opt/gadgetmon/fonts/PenchantManufacture.otf gadget@10.87.0.1:/tmp/
ssh -t gadget@10.87.0.1 "sudo install -m 644 /tmp/PenchantManufacture.otf /opt/gadgetmon/fonts/PenchantManufacture.otf && sudo systemctl restart gadgetmon"
```

ユーザ名・パスワードは `config` の `FIRST_USER_NAME` / `FIRST_USER_PASS`
（既定 `gadget` / `gadget`）。

- **`ssh -t` の `-t` は必須。** 付けないと擬似端末が割り当てられず、
  `sudo: パスワードを読み取るために端末が必要です` で失敗する。
- `scp` が `Connection closed` になる場合は `-O`（旧SCPプロトコル）を付ける。

## 給電に関する注意（重要）

- Pi 4B の推奨電源は 5V/3A。**PCのUSBポート給電はUSB 3.0で規格上900mA**であり、
  本OSは表示専用の軽負荷構成のため多くの環境で動作するが、規格上は保証外。
  **USB-Cポート（1.5A〜3A供給可）または高出力ポートへの接続を推奨**する。
- 起動しない・再起動を繰り返す場合は給電不足を疑い、電源供給付きUSBハブや
  「電源はACアダプタ・データは別ケーブル」構成（PiのUSB-Cは電源専用にできないため
  この場合はネットワークをWi-Fi等へ変更する改修が必要）を検討すること。
- PCのスリープ中は給電が止まる設定のポートがある。BIOS/UEFIやデバイスマネージャの
  「USBセレクティブサスペンド」設定で常時給電にできる場合がある。

## USBネットワークの仕組み

- Pi側は configfs (libcomposite) で USB Ethernet ガジェットを構成
  （既定 **NCM** = Windows 11/10(21H2+) 標準ドライバ対応）。
- Pi は `usb0` に静的IP `10.87.0.1/24` を持ち、dnsmasq が PC 側へ
  `10.87.0.10〜20` を自動配布（ゲートウェイ・DNSは配布しないため、
  PCの通常のインターネット接続には影響しない）。
- エージェントは `10.87.0.1:8787` へ UDP/JSON を毎秒送信（[docs/protocol.md](docs/protocol.md)）。
- メンテナンスは `ssh gadget@10.87.0.1`（初期パスワード `gadget` — **運用前に変更**）。

## 設定リファレンス（/boot/firmware/gadgetmon.conf）

| キー | 既定 | 説明 |
| --- | --- | --- |
| `USB_FUNCTION` | `ncm` | `ncm` / `rndis`（古いWindows） / `ecm`（Linux/macOSホスト） |
| `PI_IP` / `PI_PREFIX` | `10.87.0.1` / `24` | Pi側アドレス（変更時は `/etc/dnsmasq.d/usb0.conf` も揃える） |
| `LISTEN_PORT` | `8787` | テレメトリ受信ポート |
| `STALE_SEC` | `5` | この秒数無受信で SIGNAL LOST 表示 |
| `SHOW_PI_TEMP` | `1` | ヘッダにPi自身のSoC温度を表示（`0`で非表示） |
| `BOOT_UPDATE` | `1` | ブートパーティションに置いた `gadgetmon.py` を起動時に取り込む（`0`で無効） |
| `WARN_*` | 各種 | 警戒色しきい値。空で無効（docs/protocol.md 参照） |

## トラブルシュート

| 症状 | 対処 |
| --- | --- |
| PCがネットワークデバイスを認識しない | `gadgetmon.conf` で `USB_FUNCTION=rndis` に変更して再起動（Windows 10 初期版等） |
| 充電専用ケーブルで通信不可 | データ線入りのUSB-Cケーブルへ交換 |
| WAITING FOR HOST のまま | PC側タスク `GadgetMonAgent` の起動確認、`ping 10.87.0.1`、ファイアウォールの送信UDP許可 |
| CPU温度が `--C` | まず`install-agent.ps1` を**管理者権限**で再実行。それでも駄目なら**メモリ整合性(コア分離)が有効**で `WinRing0` ドライバが遮断されている可能性大 → [docs/temperature.md](docs/temperature.md) |
| SSHが `Permission denied` | 初期ユーザ/パスワードは `config` の `FIRST_USER_NAME` / `FIRST_USER_PASS`（既定 `gadget` / `gadget`）。SDカードを差し替えて WSL2 の `wsl --mount` で rootfs を直接編集する手もある |
| 画面が映らない | HDMI0（USB-C隣）ポートを使用。`config.txt` は `hdmi_force_hotplug=1` 設定済み |

## ライセンス

本リポジトリの独自制作物（ビルド構成・スクリプト・GUIレンダラ・PCエージェント・
ドキュメント・画面デザイン）は
**[Creative Commons 表示 4.0 国際 (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/deed.ja)**
で公開されています。ライセンス正文は [LICENSE](LICENSE) を参照してください。

**著作者（ライセンス主）: ラジアン（柏木主税） / RadianN_kswg**

利用時のクレジット表記例:

```
RasPiOS_GadgetMonitor by ラジアン（柏木主税） / RadianN_kswg
CC BY 4.0 https://creativecommons.org/licenses/by/4.0/
```

### 同梱物・サードパーティ

- フォント **PenchantManufacture**（`PenchantManufacture.otf` を同梱）および
  工業デカール配色仕様:
  [PenchantManufacture_ImageAssets](https://github.com/radiann-kswg/PenchantManufacture_ImageAssets)
  — © ラジアン（柏木主税） / RadianN_kswg、CC BY 4.0（本リポジトリと同一著作者・同一ライセンス）。
- ビルド基盤 [pi-gen](https://github.com/RPi-Distro/pi-gen)（BSD 3-Clause）は
  **本リポジトリには含まれず**、ビルド時に `build-image.sh` が取得します。
- CPU温度取得に使う
  [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor)（MPL-2.0）
  の net472 版配布物（`LibreHardwareMonitorLib.dll` と同梱の依存アセンブリ。
  HidSharp ほかそれぞれのライセンスに従います）は **本リポジトリには含まれず**、
  `pc-agent/install-agent.ps1` が GitHub の公式リリースから取得します。
- ビルドで生成される **OSイメージには Raspberry Pi OS / Debian の
  各パッケージが含まれ、それぞれのライセンス**（GPL ほか）に従います。
  CC BY 4.0 が適用されるのは本リポジトリ収録の独自制作物のみです。

### クレジット

- **Claude（Anthropic）** — Cowork の Agent 機能による設計・実装・実機デバッグ支援。
