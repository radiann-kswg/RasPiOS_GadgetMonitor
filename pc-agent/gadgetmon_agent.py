#!/usr/bin/env python3
"""GadgetMonitor Windowsエージェント

デスクトップPCの稼働状況を収集し、USBリンク先の Raspberry Pi
(既定 10.87.0.1:8787) へ UDP/JSON で毎秒送信する。
プロトコルは docs/protocol.md を参照。

依存: psutil (必須), nvidia-ml-py (NVIDIA GPU情報, 推奨)
CPU温度 (任意): pythonnet + LibreHardwareMonitorLib.dll
  --lhm-dll でDLLパスを指定すると取得を試みる。管理者権限が必要な場合あり。
"""

import argparse
import json
import socket
import sys
import time

import psutil

# --- NVIDIA GPU (任意) -------------------------------------------------------
_nv = None


def nv_init():
    global _nv
    try:
        import pynvml
        pynvml.nvmlInit()
        _nv = pynvml
    except Exception as exc:  # NVMLが無い環境でも動作継続
        print("NVML unavailable: {}".format(exc), file=sys.stderr)
        _nv = None


def gpu_sample():
    if _nv is None:
        return {}
    try:
        h = _nv.nvmlDeviceGetHandleByIndex(0)
        util = _nv.nvmlDeviceGetUtilizationRates(h)
        mem = _nv.nvmlDeviceGetMemoryInfo(h)
        temp = _nv.nvmlDeviceGetTemperature(h, _nv.NVML_TEMPERATURE_GPU)
        name = _nv.nvmlDeviceGetName(h)
        if isinstance(name, bytes):
            name = name.decode("utf-8", "replace")
        try:
            power = _nv.nvmlDeviceGetPowerUsage(h) / 1000.0  # mW -> W
        except Exception:
            power = None
        return {
            "util": float(util.gpu),
            "temp_c": float(temp),
            "vram_used": int(mem.used),
            "vram_total": int(mem.total),
            "power_w": power,
            "name": name,
        }
    except Exception:
        return {}


# --- CPU温度 (任意: LibreHardwareMonitor) -------------------------------------
_lhm = None


def lhm_init(dll_path):
    """LibreHardwareMonitorLib.dll 経由でCPU温度取得を初期化する(任意機能)。"""
    global _lhm
    if not dll_path:
        return
    try:
        import clr  # pythonnet
        clr.AddReference(dll_path)
        from LibreHardwareMonitor import Hardware
        pc = Hardware.Computer()
        pc.IsCpuEnabled = True
        pc.Open()
        _lhm = (pc, Hardware)
    except Exception as exc:
        print("LHM unavailable: {}".format(exc), file=sys.stderr)
        _lhm = None


def cpu_temp():
    if _lhm is None:
        return None
    try:
        pc, hardware = _lhm
        temps = []
        for hw in pc.Hardware:
            if hw.HardwareType == hardware.HardwareType.Cpu:
                hw.Update()
                for sensor in hw.Sensors:
                    if (sensor.SensorType == hardware.SensorType.Temperature
                            and sensor.Value is not None):
                        temps.append(float(sensor.Value))
        return max(temps) if temps else None
    except Exception:
        return None


# --- レート計算 ----------------------------------------------------------------
class RateMeter:
    """カウンタ差分から毎秒レートを求める。"""

    def __init__(self):
        self.prev = None
        self.prev_t = None

    def rate(self, *counters):
        now = time.monotonic()
        cur = tuple(counters)
        if self.prev is None or now <= self.prev_t:
            self.prev, self.prev_t = cur, now
            return tuple(0.0 for _ in cur)
        dt = now - self.prev_t
        rates = tuple(max(0.0, (c - p) / dt) for c, p in zip(cur, self.prev))
        self.prev, self.prev_t = cur, now
        return rates


def main():
    ap = argparse.ArgumentParser(description="GadgetMonitor PC agent")
    ap.add_argument("--target", default="10.87.0.1", help="Pi address")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--lhm-dll", default="",
                    help="LibreHardwareMonitorLib.dll path (CPU temp, optional)")
    args = ap.parse_args()

    nv_init()
    lhm_init(args.lhm_dll)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    host = socket.gethostname()
    net_meter = RateMeter()
    dsk_meter = RateMeter()
    psutil.cpu_percent(interval=None)  # 初回呼び出しのプライミング

    while True:
        t0 = time.monotonic()
        try:
            per_core = psutil.cpu_percent(interval=None, percpu=True)
            util = sum(per_core) / len(per_core) if per_core else 0.0
            freq = psutil.cpu_freq()
            vm = psutil.virtual_memory()
            nio = psutil.net_io_counters()
            dio = psutil.disk_io_counters()
            up_Bps, dn_Bps = net_meter.rate(nio.bytes_sent, nio.bytes_recv)
            rd_Bps, wr_Bps = dsk_meter.rate(dio.read_bytes, dio.write_bytes)

            pkt = {
                "v": 1,
                "ts": time.time(),
                "host": host,
                "uptime_s": time.time() - psutil.boot_time(),
                "cpu": {
                    "util": round(util, 1),
                    "per_core": [round(c, 1) for c in per_core],
                    "freq_mhz": round(freq.current, 0) if freq else None,
                    "temp_c": cpu_temp(),
                },
                "mem": {"used": vm.total - vm.available, "total": vm.total},
                "gpu": gpu_sample(),
                "net": {"up_bps": up_Bps * 8, "down_bps": dn_Bps * 8},
                "disk": {"read_bps": rd_Bps, "write_bps": wr_Bps},
            }
            sock.sendto(json.dumps(pkt).encode("utf-8"),
                        (args.target, args.port))
        except Exception as exc:
            # 一時的な失敗(リンク未接続等)でも常駐を続ける
            print("send error: {}".format(exc), file=sys.stderr)
        time.sleep(max(0.1, args.interval - (time.monotonic() - t0)))


if __name__ == "__main__":
    main()
