#!/bin/bash -e
# USBガジェットモード有効化とHDMI/コンソールのキオスク向け調整

BOOT="${ROOTFS_DIR}/boot/firmware"

# config.txt:
#  - dwc2をペリフェラル(ガジェット)モードで有効化
#  - ディスプレイ検出に失敗してもHDMI出力を継続・オーバースキャン無効
cat >> "${BOOT}/config.txt" << 'EOF'

# --- RasPiOS_GadgetMonitor ---
dtoverlay=dwc2,dr_mode=peripheral
hdmi_force_hotplug=1
disable_overscan=1
EOF

# cmdline.txt: 画面ブランキング無効・起動ロゴ/カーソル非表示・静音起動
# （cmdline.txt は1行のためその行末へ追記）
sed -i 's/$/ consoleblank=0 logo.nologo vt.global_cursor_default=0 quiet loglevel=3/' \
	"${BOOT}/cmdline.txt"
