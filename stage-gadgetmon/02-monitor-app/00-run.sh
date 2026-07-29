#!/bin/bash -e
# モニタレンダラ一式をrootfsへ設置し、サービスを有効化する

FILES="${BASH_SOURCE%/*}/files"

# ディレクトリ
install -d -m 755 "${ROOTFS_DIR}/opt/gadgetmon"
install -d -m 755 "${ROOTFS_DIR}/opt/gadgetmon/fonts"

# レンダラ本体
install -m 755 "${FILES}/opt/gadgetmon/gadgetmon.py" \
	"${ROOTFS_DIR}/opt/gadgetmon/gadgetmon.py"

# フォント (PenchantManufacture, CC BY 4.0,
#  (c) RadianN_kswg / ラジアン(柏木主税))
install -m 644 "${FILES}/opt/gadgetmon/fonts/PenchantManufacture.otf" \
	"${ROOTFS_DIR}/opt/gadgetmon/fonts/PenchantManufacture.otf"

# systemdユニット
install -m 644 "${FILES}/etc/systemd/system/gadgetmon.service" \
	"${ROOTFS_DIR}/etc/systemd/system/gadgetmon.service"

# サービス有効化・tty1のログインプロンプト無効化（画面をモニタ専用に）
on_chroot << EOF
systemctl enable gadgetmon.service
systemctl disable getty@tty1.service
EOF
