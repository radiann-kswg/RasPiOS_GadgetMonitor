#!/bin/bash -e
# USBガジェット(Ethernet)ネットワーク一式をrootfsへ設置し、サービスを有効化する

FILES="${BASH_SOURCE%/*}/files"

# ディレクトリ
install -d -m 755 "${ROOTFS_DIR}/opt/gadgetmon"

# ガジェット構成スクリプト
install -m 755 "${FILES}/opt/gadgetmon/usb-gadget.sh" \
	"${ROOTFS_DIR}/opt/gadgetmon/usb-gadget.sh"

# systemdユニット
install -m 644 "${FILES}/etc/systemd/system/usb-gadget.service" \
	"${ROOTFS_DIR}/etc/systemd/system/usb-gadget.service"

# dnsmasq: usb0 に対する DHCP サーバ設定
install -m 644 "${FILES}/etc/dnsmasq.d/usb0.conf" \
	"${ROOTFS_DIR}/etc/dnsmasq.d/usb0.conf"

# NetworkManager から usb0 を除外（本スクリプトが静的に管理する）
install -m 644 "${FILES}/etc/NetworkManager/conf.d/90-gadgetmon.conf" \
	"${ROOTFS_DIR}/etc/NetworkManager/conf.d/90-gadgetmon.conf"

# カーネルモジュールの自動ロード
install -m 644 "${FILES}/etc/modules-load.d/gadgetmon.conf" \
	"${ROOTFS_DIR}/etc/modules-load.d/gadgetmon.conf"

# 利用者向け設定ファイル（ブートパーティション: Windowsから編集可能）
install -m 644 "${FILES}/boot/gadgetmon.conf" \
	"${ROOTFS_DIR}/boot/firmware/gadgetmon.conf"

# サービス有効化
on_chroot << EOF
systemctl enable usb-gadget.service
systemctl enable dnsmasq.service
EOF
