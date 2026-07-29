# テレメトリプロトコル仕様

PC側エージェント → Pi側レンダラ間の通信仕様。

## トランスポート

| 項目 | 値 |
| --- | --- |
| 方式 | UDP ユニキャスト（片方向・ACKなし） |
| 宛先 | `10.87.0.1:8787`（`/boot/firmware/gadgetmon.conf` の `PI_IP` / `LISTEN_PORT`） |
| 送信間隔 | 1秒（エージェント `--interval` で変更可） |
| ペイロード | UTF-8 の JSON 1オブジェクト / 1データグラム |

UDPを採用する理由: 表示用途では最新値のみが意味を持ち、再送や順序保証が不要。
ケーブル抜去時もソケットエラーにならず、Pi側は「最終受信からの経過秒」
（`STALE_SEC` 既定5秒）だけで SIGNAL LOST 判定できる。

## ペイロード (v1)

```json
{
  "v": 1,
  "ts": 1769000000.123,
  "host": "MY-DESKTOP",
  "uptime_s": 86400.0,
  "cpu": {
    "util": 42.5,
    "per_core": [10.0, 95.5],
    "freq_mhz": 4200,
    "temp_c": 65.0
  },
  "mem": { "used": 17179869184, "total": 34359738368 },
  "gpu": {
    "util": 33.0,
    "temp_c": 55.0,
    "vram_used": 4294967296,
    "vram_total": 12884901888,
    "power_w": 120.5,
    "name": "GeForce RTX 4070"
  },
  "net": { "up_bps": 1500000.0, "down_bps": 95000000.0 },
  "disk": { "read_bps": 52428800.0, "write_bps": 1048576.0 }
}
```

## フィールド定義

| パス | 型 | 単位 | 備考 |
| --- | --- | --- | --- |
| `v` | int | - | プロトコル版。`1` 以外はPi側で破棄 |
| `ts` | float | UNIX秒 | PCの現在時刻。Pi側の時計表示の源（PiはRTC・NTPなしでも正しい時刻を表示できる） |
| `host` | str | - | コンピュータ名 |
| `uptime_s` | float | 秒 | PC稼働時間 |
| `cpu.util` | float | % | 全コア平均 |
| `cpu.per_core` | float[] | % | 論理コアごと。省略可 |
| `cpu.freq_mhz` | float | MHz | 現在クロック |
| `cpu.temp_c` | float/null | ℃ | 取得不能時は null（表示は `--`） |
| `mem.used` / `mem.total` | int | bytes | used は total - available |
| `gpu.*` | - | - | NVML由来。GPU無し/取得失敗時は `{}` |
| `gpu.vram_used` / `vram_total` | int | bytes | |
| `gpu.power_w` | float/null | W | |
| `net.up_bps` / `down_bps` | float | **bit/s** | 全NIC合算。表示はMbps系 |
| `disk.read_bps` / `write_bps` | float | **byte/s** | 全ドライブ合算。表示はMB/s系 |

欠落フィールドはPi側で null 扱い（`--` 表示）。未知フィールドは無視される
（前方互換）。

## 警告（警戒色）判定

Pi側 `/boot/firmware/gadgetmon.conf` のしきい値と比較し、超過した項目のカードを
hazard 配色へ切り替える。しきい値を空にするとその判定は無効。

| 設定キー | 対象 | 既定値 |
| --- | --- | --- |
| `WARN_CPU_UTIL` | `cpu.util` | 90 |
| `WARN_CPU_TEMP` | `cpu.temp_c` | 85 |
| `WARN_GPU_TEMP` | `gpu.temp_c` | 83 |
| `WARN_MEM_PCT` | メモリ使用率 | 90 |
| `WARN_VRAM_PCT` | VRAM使用率 | 95 |
| `WARN_GPU_POWER_W` | `gpu.power_w` | （無効） |
| `WARN_NET_MBPS` | up/down最大値(Mbps) | （無効） |
