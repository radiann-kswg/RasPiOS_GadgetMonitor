# RasPiOS_GadgetMonitor

Raspberry Pi **4B** をデスクトップPCの「稼働率モニターガジェット」にする
オリジナルOSイメージ（pi-gen / arm64 / Debian trixie ベース）。

PCのUSBポートとPiのUSB-Cを1本のケーブルで接続すると、**給電とデータ通信を同時に**行い、
PC側常駐エージェントが送るテレメトリ（CPU・メモリ・GPU・VRAM・ネットワーク・ディスクI/O、
負荷や温度）を、HDMI接続のディスプレイへ**グレー基調の工学モニター風GUI**で常時表示する。

```
┌──────────────┐ USB-C (電源+USBガジェットEthernet) ┌─────────────┐   HDMI   ┌─────────┐
│ デスクトップPC │ ─────────────────────────────────→ │ Raspberry Pi │ ───────→ │ ディスプレイ │
│  (Windows)    │        UDP/JSON 10.87.0.1:8787      │     4B       │          │           │
└──────────────┘                                     └─────────────┘          └─────────┘
```

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
│   ├── 03-boot-config/         #   dwc2有効化・HDMI・静音起動
│   └── 04-purge-cloud-init/    #   cloud-init除去（最後に置く）
├── pc-agent/                   # Windows側エージェント一式
└── docs/protocol.md            # UDP/JSONテレメトリ仕様
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
5. 数秒でテレメトリ表示が始まる。

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
| `WARN_*` | 各種 | 警戒色しきい値。空で無効（docs/protocol.md 参照） |

## トラブルシュート

| 症状 | 対処 |
| --- | --- |
| PCがネットワークデバイスを認識しない | `gadgetmon.conf` で `USB_FUNCTION=rndis` に変更して再起動（Windows 10 初期版等） |
| 充電専用ケーブルで通信不可 | データ線入りのUSB-Cケーブルへ交換 |
| WAITING FOR HOST のまま | PC側タスク `GadgetMonAgent` の起動確認、`ping 10.87.0.1`、ファイアウォールの送信UDP許可 |
| CPU温度が `--` | Windows標準では取得不可。LibreHardwareMonitorLib.dll＋pythonnet導入後、タスクの引数へ `--lhm-dll` を追加 |
| 画面が映らない | HDMI0（USB-C隣）ポートを使用。`config.txt` は `hdmi_force_hotplug=1` 設定済み |

## クレジット / ライセンス

- フォント **PenchantManufacture** および工業デカール配色仕様:
  [PenchantManufacture_ImageAssets](https://github.com/radiann-kswg/PenchantManufacture_ImageAssets)
  — © RadianN_kswg / ラジアン（柏木主税）、
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.ja)。
  本イメージは同フォント（`PenchantManufacture.otf`）を同梱する。
- ビルド基盤: [pi-gen](https://github.com/RPi-Distro/pi-gen)（BSD 3-Clause）
