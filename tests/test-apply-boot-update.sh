#!/bin/bash
# apply-boot-update.sh の機能テスト。
#
# /tmp にサンドボックス（疑似ブートパーティション＋疑似rootfs）を作り、
# パスだけ差し替えたコピーを動かす。実運用のファイルには触れない。
#
# 実行条件: python3 と pygame。Pi実機上か、pygameを入れたWSL等で走らせる。
#   Pi上で走らせる例:
#     scp tests/test-apply-boot-update.sh \
#         stage-gadgetmon/02-monitor-app/files/opt/gadgetmon/apply-boot-update.sh \
#         stage-gadgetmon/02-monitor-app/files/opt/gadgetmon/fonts/PenchantManufacture.otf \
#         gadget@10.87.0.1:/tmp/
#     ssh gadget@10.87.0.1 \
#         "bash /tmp/test-apply-boot-update.sh /tmp/apply-boot-update.sh /tmp/PenchantManufacture.otf"
#
# 使い方: test-apply-boot-update.sh [被検体スクリプト] [正常なフォント]
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT="${HERE}/.."
TARGET=${1:-${ROOT}/stage-gadgetmon/02-monitor-app/files/opt/gadgetmon/apply-boot-update.sh}
GOOD_FONT=${2:-${ROOT}/stage-gadgetmon/02-monitor-app/files/opt/gadgetmon/fonts/PenchantManufacture.otf}

for f in "$TARGET" "$GOOD_FONT"; do
	[ -f "$f" ] || { echo "not found: $f" >&2; exit 2; }
done
python3 -c 'import pygame' 2>/dev/null || { echo "pygame が必要です" >&2; exit 2; }

T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/boot" "$T/root/fonts"

# 被検体のパス定数だけをサンドボックスへ向ける
sed -e "s#^BOOT_DIR=.*#BOOT_DIR=${T}/boot#" \
    -e "s#^DST_PY=.*#DST_PY=${T}/root/gadgetmon.py#" \
    -e "s#^DST_FONT=.*#DST_FONT=${T}/root/fonts/PenchantManufacture.otf#" \
    "$TARGET" > "$T/abu.sh"
chmod +x "$T/abu.sh"

# 初期状態: rootfs側に旧版がある体にする（旧フォントは正常フォントの別バイト列）
printf 'print("old")\n' > "$T/root/gadgetmon.py"
head -c 40000 "$GOOD_FONT" > "$T/root/fonts/PenchantManufacture.otf"
OLD_FONT_SUM=$(md5sum < "$T/root/fonts/PenchantManufacture.otf")
GOOD_SUM=$(md5sum < "$GOOD_FONT")
font_sum() { md5sum < "$T/root/fonts/PenchantManufacture.otf"; }

pass=0; fail=0
ck() {  # ck 名前 実測 期待
	if [ "$2" = "$3" ]; then
		echo "  PASS $1"; pass=$((pass + 1))
	else
		echo "  FAIL $1 : expected [$3] got [$2]"; fail=$((fail + 1))
	fi
}

echo "== A: 正常なフォントを取り込む =="
cp "$GOOD_FONT" "$T/boot/PenchantManufacture.otf"
"$T/abu.sh"
ck "fontが適用された" "$(font_sum)" "$GOOD_SUM"
ck "bakが残った" "$(md5sum < "$T/root/fonts/PenchantManufacture.otf.bak")" "$OLD_FONT_SUM"

echo "== B: 同一内容なら再適用しない =="
before=$(stat -c %Y "$T/root/fonts/PenchantManufacture.otf")
sleep 1.1
"$T/abu.sh"
ck "mtimeが変わらない" "$(stat -c %Y "$T/root/fonts/PenchantManufacture.otf")" "$before"

echo "== C: 切り詰められたフォントは拒否する =="
head -c 3000 "$GOOD_FONT" > "$T/boot/PenchantManufacture.otf"
"$T/abu.sh"
ck "適用されていない" "$(font_sum)" "$GOOD_SUM"
ck "REJECTEDが記録" "$(grep -c 'REJECTED.*otf' "$T/boot/gadgetmon-update.log")" "1"

echo "== D: フォントでないファイルは拒否する =="
printf 'not a font at all\n' > "$T/boot/PenchantManufacture.otf"
"$T/abu.sh"
ck "適用されていない" "$(font_sum)" "$GOOD_SUM"

echo "== E: 構文エラーの.pyは拒否する =="
printf 'def broken(\n' > "$T/boot/gadgetmon.py"
"$T/abu.sh"
ck "py据え置き" "$(cat "$T/root/gadgetmon.py")" 'print("old")'

echo "== F: 正常な.pyは取り込む =="
printf 'print("new")\n' > "$T/boot/gadgetmon.py"
"$T/abu.sh"
ck "pyが適用された" "$(cat "$T/root/gadgetmon.py")" 'print("new")'
ck "pyは755" "$(stat -c %a "$T/root/gadgetmon.py")" "755"
ck "fontは644" "$(stat -c %a "$T/root/fonts/PenchantManufacture.otf")" "644"

echo "== G: ロールバックで両方戻る =="
cp "$GOOD_FONT" "$T/boot/PenchantManufacture.otf"
touch "$T/boot/gadgetmon-rollback"
"$T/abu.sh"
ck "pyが旧版へ" "$(cat "$T/root/gadgetmon.py")" 'print("old")'
ck "fontが旧版へ" "$(font_sum)" "$OLD_FONT_SUM"
ck "boot上のpyを削除" "$([ -e "$T/boot/gadgetmon.py" ] && echo yes || echo no)" "no"
ck "boot上のfontを削除" "$([ -e "$T/boot/PenchantManufacture.otf" ] && echo yes || echo no)" "no"
ck "flagを削除" "$([ -e "$T/boot/gadgetmon-rollback" ] && echo yes || echo no)" "no"

echo
echo "RESULT pass=${pass} fail=${fail}"
[ "$fail" -eq 0 ]
