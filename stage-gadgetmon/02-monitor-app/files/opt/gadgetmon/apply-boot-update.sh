#!/bin/bash
# ブートパーティションに置かれたレンダラでrootfs側を更新する。
# gadgetmon.service の ExecStartPre から root 権限で実行される。
#
# 目的:
#   SSHもキーボードも使わずにレンダラを差し替えられるようにする。
#   /boot/firmware は FAT なので、SDカードをWindowsに挿せば
#   gadgetmon.py をコピーするだけで次回起動時に反映される。
#
# 安全策:
#   - 構文チェックを通ったものだけ適用する（壊れたスクリプトで
#     画面が出なくなると、SSH無しの構成では復旧手段が無くなるため）
#   - 適用前の版を gadgetmon.py.bak へ退避する
#   - 内容が同一なら何もしない（毎起動のコピーを避ける）
#   - 結果を /boot/firmware/gadgetmon-update.log に残す（Windowsから読める）
#   - gadgetmon.conf の BOOT_UPDATE=0 で無効化できる
#   - /boot/firmware/gadgetmon-rollback を置いて再起動すると .bak へ戻す
#
# 本スクリプトが異常終了しても起動は止めない（unit側で `-` 接頭辞）。

set -u

BOOT_DIR=/boot/firmware
CONF="${BOOT_DIR}/gadgetmon.conf"
SRC="${BOOT_DIR}/gadgetmon.py"
FLAG_ROLLBACK="${BOOT_DIR}/gadgetmon-rollback"
DST=/opt/gadgetmon/gadgetmon.py
BAK="${DST}.bak"
LOG="${BOOT_DIR}/gadgetmon-update.log"
LOG_MAX=65536

log() {
	# FATが読み取り専用でマウントされている場合もあるので失敗は無視する
	if [ -f "$LOG" ] && [ "$(stat -c %s "$LOG" 2>/dev/null || echo 0)" -gt "$LOG_MAX" ]; then
		: > "$LOG" 2>/dev/null
	fi
	printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "$LOG" 2>/dev/null || true
}

conf_get() {  # conf_get KEY DEFAULT
	local val
	val=$(sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*\(.*\)$/\1/p" \
		"$CONF" 2>/dev/null | tail -n 1)
	val=${val%%#*}
	val=$(printf '%s' "$val" | tr -d '[:space:]')
	if [ -z "$val" ]; then printf '%s' "$2"; else printf '%s' "$val"; fi
}

case "$(conf_get BOOT_UPDATE 1 | tr 'A-Z' 'a-z')" in
	0|no|off|false) exit 0 ;;
esac

# --- ロールバック要求 ---------------------------------------------------------
if [ -f "$FLAG_ROLLBACK" ]; then
	if [ -f "$BAK" ]; then
		install -m 755 "$BAK" "$DST" && log "rolled back ${DST} from ${BAK}"
	else
		log "rollback requested but ${BAK} not found"
	fi
	# 更新元も消しておかないと次回起動で再適用されてしまう
	rm -f "$FLAG_ROLLBACK" "$SRC" 2>/dev/null || true
	sync
	exit 0
fi

# --- 通常の更新 ---------------------------------------------------------------
[ -f "$SRC" ] || exit 0
cmp -s "$SRC" "$DST" && exit 0   # 適用済み

# 構文チェック。py_compile は .pyc を書き出してFATを汚すのでメモリ上で行う。
# 判定は終了ステータスで行う（警告がstderrに出ても拒否しないため）。
if ! err=$(python3 -c 'import sys
path = sys.argv[1]
with open(path, "rb") as f:
    compile(f.read(), path, "exec")' "$SRC" 2>&1); then
	log "REJECTED ${SRC}: syntax check failed"
	printf '%s\n' "$err" | sed 's/^/    /' >> "$LOG" 2>/dev/null || true
	sync
	exit 0
fi

cp -f "$DST" "$BAK" 2>/dev/null || true
if install -m 755 "$SRC" "$DST"; then
	log "applied ${SRC} -> ${DST} (previous kept as ${BAK})"
else
	log "FAILED to install ${SRC} -> ${DST}"
fi
sync
exit 0
