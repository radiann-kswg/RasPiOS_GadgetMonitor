#!/bin/bash
# USB Ethernetガジェット構成スクリプト (configfs/libcomposite)
#
# Pi 4B の USB-C を PC に接続し、USBネットワークデバイスとして見せる。
# 機能クラスは /boot/firmware/gadgetmon.conf の USB_FUNCTION で切替:
#   ncm   (既定) : CDC-NCM。Windows 11 / 10(21H2+) の標準ドライバで動作
#   rndis        : 旧Windows向け。MS OS Descriptorで自動バインド
#   ecm          : CDC-ECM。Linux/macOSホスト向け
set -eu

CONF="/boot/firmware/gadgetmon.conf"
GADGET="/sys/kernel/config/usb_gadget/gadgetmon"

# --- 設定読み込み（既定値 → confで上書き） ---
USB_FUNCTION="ncm"
PI_IP="10.87.0.1"
PI_PREFIX="24"
if [ -r "${CONF}" ]; then
	# shellcheck disable=SC1090
	. "${CONF}"
fi

serial="$(awk '/^Serial/ {print $3}' /proc/cpuinfo)"
[ -n "${serial}" ] || serial="0000000000000000"
# シリアル由来の決定的なMACアドレス（ローカル管理ビット付き・下位10桁を使用）
mac_base="$(printf '%s' "${serial}" | tail -c 10)"
dev_mac="02:$(echo "${mac_base}" | sed 's/\(..\)\(..\)\(..\)\(..\)\(..\)/\1:\2:\3:\4:\5/')"
host_mac="12:$(echo "${dev_mac}" | cut -c4-)"

start() {
	modprobe libcomposite

	if [ -d "${GADGET}" ]; then
		echo "gadget already configured" >&2
		return 0
	fi

	mkdir -p "${GADGET}"
	cd "${GADGET}"

	echo 0x1d6b > idVendor    # Linux Foundation
	echo 0x0104 > idProduct   # Multifunction Composite Gadget
	echo 0x0100 > bcdDevice
	echo 0x0200 > bcdUSB

	mkdir -p strings/0x409
	echo "${serial}"            > strings/0x409/serialnumber
	echo "RasPiOS GadgetMonitor" > strings/0x409/manufacturer
	echo "Desktop Telemetry Display" > strings/0x409/product

	mkdir -p configs/c.1/strings/0x409
	echo "usb-ethernet" > configs/c.1/strings/0x409/configuration
	echo 500 > configs/c.1/MaxPower

	case "${USB_FUNCTION}" in
	rndis)
		mkdir -p functions/rndis.usb0
		echo "${dev_mac}"  > functions/rndis.usb0/dev_addr
		echo "${host_mac}" > functions/rndis.usb0/host_addr
		# MS OS Descriptor: WindowsにRNDISドライバを自動選択させる
		echo 1        > os_desc/use
		echo 0xcd     > os_desc/b_vendor_code
		echo MSFT100  > os_desc/qw_sign
		echo RNDIS    > functions/rndis.usb0/os_desc/interface.rndis/compatible_id
		echo 5162001  > functions/rndis.usb0/os_desc/interface.rndis/sub_compatible_id
		ln -s functions/rndis.usb0 configs/c.1/
		ln -s configs/c.1 os_desc
		;;
	ecm)
		mkdir -p functions/ecm.usb0
		echo "${dev_mac}"  > functions/ecm.usb0/dev_addr
		echo "${host_mac}" > functions/ecm.usb0/host_addr
		ln -s functions/ecm.usb0 configs/c.1/
		;;
	ncm|*)
		mkdir -p functions/ncm.usb0
		echo "${dev_mac}"  > functions/ncm.usb0/dev_addr
		echo "${host_mac}" > functions/ncm.usb0/host_addr
		ln -s functions/ncm.usb0 configs/c.1/
		;;
	esac

	# UDC へバインド（Pi 4B は fe980000.usb）
	udc="$(ls /sys/class/udc | head -n1)"
	if [ -z "${udc}" ]; then
		echo "エラー: UDCが見つかりません。config.txt の dtoverlay=dwc2 を確認してください。" >&2
		exit 1
	fi
	echo "${udc}" > UDC

	# usb0 に静的IPを付与
	ip addr replace "${PI_IP}/${PI_PREFIX}" dev usb0
	ip link set usb0 up
}

stop() {
	if [ ! -d "${GADGET}" ]; then
		return 0
	fi
	cd "${GADGET}"
	echo "" > UDC 2>/dev/null || true
	rm -f os_desc/c.1 2>/dev/null || true
	find configs/c.1 -maxdepth 1 -type l -delete 2>/dev/null || true
	rmdir configs/c.1/strings/0x409 configs/c.1 2>/dev/null || true
	rmdir functions/* 2>/dev/null || true
	rmdir strings/0x409 2>/dev/null || true
	cd /
	rmdir "${GADGET}" 2>/dev/null || true
}

case "${1:-start}" in
	start) start ;;
	stop)  stop ;;
	*) echo "usage: $0 {start|stop}" >&2; exit 1 ;;
esac
