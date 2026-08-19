#!/bin/bash
# ブートパーティションに置かれたレンダラ／フォントでrootfs側を更新する。
# gadgetmon.service の ExecStartPre から root 権限で実行される。
#
# 目的:
#   SSHもキーボードも使わずに表示物を差し替えられるようにする。
#   /boot/firmware は FAT なので、SDカードをWindowsに挿せば
#   ファイルをコピーするだけで次回起動時に反映される。
#
# 対象:
#   gadgetmon.py                → /opt/gadgetmon/gadgetmon.py
#   PenchantManufacture.otf     → /opt/gadgetmon/fonts/PenchantManufacture.otf
#
# 安全策:
#   - 検証を通ったものだけ適用する（壊れたファイルで画面が出なくなると、
#     SSH無しの構成では復旧手段が無くなるため）
#       .py  … Pythonの構文チェック
#       .otf … FreeType が実際に開けるか
#   - 適用前の版を <対象>.bak へ退避する
#   - 内容が同一なら何もしない（毎起動のコピーを避ける）
#   - 結果を /boot/firmware/gadgetmon-update.log に残す（Windowsから読める）
#   - gadgetmon.conf の BOOT_UPDATE=0 で無効化できる
#   - /boot/firmware/gadgetmon-rollback を置いて再起動すると .bak へ戻す
#
# 本スクリプトが異常終了しても起動は止めない（unit側で `-` 接頭辞）。

set -u

BOOT_DIR=/boot/firmware
CONF="${BOOT_DIR}/gadgetmon.conf"
FLAG_ROLLBACK="${BOOT_DIR}/gadgetmon-rollback"
LOG="${BOOT_DIR}/gadgetmon-update.log"
LOG_MAX=65536

SRC_PY="${BOOT_DIR}/gadgetmon.py"
DST_PY=/opt/gadgetmon/gadgetmon.py
SRC_FONT="${BOOT_DIR}/PenchantManufacture.otf"
DST_FONT=/opt/gadgetmon/fonts/PenchantManufacture.otf

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

# --- 検証 ---------------------------------------------------------------------
# 判定は終了ステータスで行う（警告がstderrに出ても拒否しないため）。
# 出力は拒否時のログにだけ使う。

check_py() {
	# py_compile は .pyc を書き出してFATを汚すのでメモリ上で行う。
	python3 -c 'import sys
path = sys.argv[1]
with open(path, "rb") as f:
    compile(f.read(), path, "exec")' "$1" 2>&1
}

check_font() {
	# レンダラと同じ FreeType で実際に開いて確かめる。
	# 切り詰め・破損・フォント以外のファイルはここで弾かれる。
	#
	# 注意: pygame.font.Font() は中身がフォントでなくても例外を出さない
	# （内部ポインタがNULLのオブジェクトが返る）。実際に render() まで
	# 通して初めて "Passed a NULL pointer" で失敗する。render() は必須。
	PYGAME_HIDE_SUPPORT_PROMPT=1 python3 -c 'import sys, pygame
pygame.font.init()
f = pygame.font.Font(sys.argv[1], 24)
f.render("0123456789 CPU", True, (255, 255, 255))' "$1" 2>&1
}

# --- 適用 ---------------------------------------------------------------------

apply_update() {  # apply_update SRC DST MODE CHECK_FN
	local src=$1 dst=$2 mode=$3 check=$4 err
	[ -f "$src" ] || return 0
	cmp -s "$src" "$dst" && return 0   # 適用済み

	if ! err=$("$check" "$src"); then
		log "REJECTED ${src}: validation failed"
		printf '%s\n' "$err" | sed 's/^/    /' >> "$LOG" 2>/dev/null || true
		return 0
	fi

	cp -f "$dst" "${dst}.bak" 2>/dev/null || true
	if install -D -m "$mode" "$src" "$dst"; then
		log "applied ${src} -> ${dst} (previous kept as ${dst}.bak)"
	else
		log "FAILED to install ${src} -> ${dst}"
	fi
}

rollback_one() {  # rollback_one SRC DST MODE
	local src=$1 dst=$2 mode=$3
	if [ -f "${dst}.bak" ]; then
		install -D -m "$mode" "${dst}.bak" "$dst" && log "rolled back ${dst} from ${dst}.bak"
	else
		log "no backup for ${dst}, skipped"
	fi
	# 更新元も消しておかないと次回起動で再適用されてしまう
	rm -f "$src" 2>/dev/null || true
}

# --- 本体 ---------------------------------------------------------------------

case "$(conf_get BOOT_UPDATE 1 | tr 'A-Z' 'a-z')" in
	0|no|off|false) exit 0 ;;
esac

if [ -f "$FLAG_ROLLBACK" ]; then
	rollback_one "$SRC_PY"   "$DST_PY"   755
	rollback_one "$SRC_FONT" "$DST_FONT" 644
	rm -f "$FLAG_ROLLBACK" 2>/dev/null || true
	sync
	exit 0
fi

apply_update "$SRC_PY"   "$DST_PY"   755 check_py
apply_update "$SRC_FONT" "$DST_FONT" 644 check_font
sync
exit 0
