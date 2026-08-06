#!/usr/bin/env python3
r"""GadgetMonitor Windowsエージェント

デスクトップPCの稼働状況を収集し、USBリンク先の Raspberry Pi
(既定 10.87.0.1:8787) へ UDP/JSON で毎秒送信する。
プロトコルは docs/protocol.md を参照。

依存:
  psutil       (必須)  CPU/メモリ/ネット/ディスク
  nvidia-ml-py (推奨)  NVIDIA GPU の利用率・VRAM・温度・電力
  pythonnet    (温度)  LibreHardwareMonitorLib.dll をインプロセス利用

温度取得について (docs/temperature.md):
  Windows には CPU 温度を読む標準APIが無く、PECI/SuperI/O へアクセスする
  カーネルドライバが要る。本エージェントは LibreHardwareMonitorLib.dll
  (MPL-2.0) を pythonnet 経由で読み込んで取得する。DLL は
  install-agent.ps1 が nuget.org から取得して
  %LOCALAPPDATA%\GadgetMonAgent\lhm\ へ配置する (本リポジトリは再配布しない)。
  ドライバの導入・読み出しには **管理者権限が必要**。権限が無い場合や
  DLL が無い場合、cpu.temp_c は null となり Pi 側は "--" と表示する。

動作確認:
  python gadgetmon_agent.py --selftest
    検出できた温度センサを全て一覧し、送信するJSONを1件表示して終了する。
"""

import argparse
import ctypes
import json
import os
import socket
import sys
import time

import psutil

LHM_DLL_NAME = "LibreHardwareMonitorLib.dll"

# 代表CPU温度として優先採用するセンサ名 (小文字。先頭ほど優先)
CPU_TEMP_PREFERRED = (
    "core (tctl/tdie)",   # AMD Ryzen
    "core (tdie)",        # AMD (一部世代)
    "cpu package",        # Intel
    "package",
)
# 代表GPU温度として優先採用するセンサ名 (NVMLが使えない環境の代替)
GPU_TEMP_PREFERRED = ("gpu core", "gpu temperature", "core", "gpu hot spot")

# 実温度としてありうる範囲。範囲外は「未取得」として扱う。
# LibreHardwareMonitor はカーネルドライバを読み込めないとき (非管理者で実行した
# 場合など) 例外を出さずセンサ値 0.0 を返す。0℃ をそのまま送ると Pi 側が
# 「0度」と表示してしまうため、ここで弾いて null に落とす。
TEMP_MIN_C = 1.0
TEMP_MAX_C = 200.0


def plausible_temp(value):
    return value is not None and TEMP_MIN_C <= value <= TEMP_MAX_C


# --- ログ ---------------------------------------------------------------------
# pythonw.exe で常駐する場合 sys.stderr は None のため、--log でファイルへ出す。
_log_fh = None


def log_init(path):
    global _log_fh
    if not path:
        return
    try:
        if os.path.isfile(path) and os.path.getsize(path) > 1_000_000:
            os.replace(path, path + ".1")
        _log_fh = open(path, "a", encoding="utf-8", errors="replace")
    except OSError:
        _log_fh = None


def log(msg):
    line = "[{}] {}".format(time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    if _log_fh is not None:
        try:
            _log_fh.write(line + "\n")
            _log_fh.flush()
        except OSError:
            pass
    elif sys.stderr is not None:
        print(line, file=sys.stderr, flush=True)


def is_admin():
    """管理者権限で動作しているか。非Windowsでは False。"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def hvci_enabled():
    """メモリ整合性(HVCI)が有効か。不明なら None。

    有効だと Microsoft の脆弱ドライバブロックリスト対象である WinRing0 系
    ドライバが読み込めず、LibreHardwareMonitor は管理者権限でもCPU温度を
    取得できない（センサは列挙されるが値が 0.0 になる）。
    """
    try:
        import winreg
        key = (r"SYSTEM\CurrentControlSet\Control\DeviceGuard"
               r"\Scenarios\HypervisorEnforcedCodeIntegrity")
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
            return winreg.QueryValueEx(handle, "Enabled")[0] == 1
    except (ImportError, OSError):
        return None


def temp_failure_hints():
    """CPU温度が取れないときの原因候補。"""
    hints = []
    if not is_admin():
        hints.append("プロセスが管理者権限で動作していない。"
                     "タスクを「最上位の特権」で登録し直す "
                     "(install-agent.ps1 を管理者権限で実行)。")
    if hvci_enabled():
        hints.append("メモリ整合性(HVCI/コア分離)が有効。"
                     "LibreHardwareMonitor が使う WinRing0 系カーネル"
                     "ドライバは脆弱ドライバブロックリスト対象のため、"
                     "管理者権限でも読み込めない。"
                     "CPU温度が必要なら Windows セキュリティ > デバイス"
                     "セキュリティ > コア分離 でメモリ整合性をオフにして"
                     "再起動する (セキュリティ機能を1つ落とすことになる)。"
                     "外したくない場合は install-agent.ps1 -NoCpuTemp で"
                     "CPU温度なしの構成にできる。")
    if not hints:
        hints.append("原因不明。--selftest のセンサ一覧を確認すること。")
    return hints


# --- NVIDIA GPU (任意) -------------------------------------------------------
_nv = None


def nv_init():
    global _nv
    try:
        import pynvml
        pynvml.nvmlInit()
        _nv = pynvml
    except Exception as exc:  # NVMLが無い環境でも動作継続
        log("NVML unavailable: {}".format(exc))
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


# --- 温度センサ (LibreHardwareMonitor) ----------------------------------------
def find_lhm_dll(explicit=""):
    """LibreHardwareMonitorLib.dll を既定の場所から探す。"""
    cands = []
    if explicit:
        path = os.path.abspath(explicit)
        cands.append(path if path.lower().endswith(".dll")
                     else os.path.join(path, LHM_DLL_NAME))
    env_dir = os.environ.get("GADGETMON_LHM_DIR")
    if env_dir:
        cands.append(os.path.join(env_dir, LHM_DLL_NAME))
    here = os.path.dirname(os.path.abspath(__file__))
    cands.append(os.path.join(here, "lhm", LHM_DLL_NAME))
    cands.append(os.path.join(here, LHM_DLL_NAME))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        cands.append(os.path.join(local, "GadgetMonAgent", "lhm", LHM_DLL_NAME))
    for path in cands:
        if os.path.isfile(path):
            return path
    return None


def pick_temp(temps, preferred):
    """センサ名→値の辞書から代表値を選ぶ。優先名→コア最大→全体最大の順。

    ありえない値 (0.0 等) のセンサは最初に除外する。
    """
    temps = {n: v for n, v in temps.items() if plausible_temp(v)}
    for name in preferred:
        if name in temps:
            return temps[name]
    cores = [v for n, v in temps.items() if n.startswith("cpu core #")]
    if cores:
        return max(cores)
    return max(temps.values()) if temps else None


class ThermalSource:
    """LibreHardwareMonitorLib による温度読み出し (任意機能)。

    pythonnet(clr) で .NET アセンブリをインプロセス読み込みするため、
    LibreHardwareMonitor のGUIを常駐させる必要はない。
    センサ値の取得にはカーネルドライバが要るため管理者権限が必要。
    """

    def __init__(self, dll_path, with_gpu=False, with_extra=False):
        directory = os.path.dirname(os.path.abspath(dll_path))
        if directory not in sys.path:
            sys.path.insert(0, directory)
        import clr  # pythonnet
        try:
            clr.AddReference("LibreHardwareMonitorLib")
        except Exception:
            clr.AddReference(os.path.abspath(dll_path))
        from LibreHardwareMonitor import Hardware

        self._temp_type = Hardware.SensorType.Temperature
        self._cpu_type = Hardware.HardwareType.Cpu
        self._gpu_types = tuple(
            t for t in (getattr(Hardware.HardwareType, name, None)
                        for name in ("GpuNvidia", "GpuAmd", "GpuIntel"))
            if t is not None)
        computer = Hardware.Computer()
        computer.IsCpuEnabled = True
        computer.IsGpuEnabled = bool(with_gpu)
        computer.IsMotherboardEnabled = bool(with_extra)
        computer.IsStorageEnabled = bool(with_extra)
        computer.Open()
        self._computer = computer

    def close(self):
        try:
            self._computer.Close()
        except Exception:
            pass

    def _walk(self, hardware):
        """hardware と配下のサブハードウェアを更新しつつ列挙する。

        マザーボードの温度は SuperI/O チップ (サブハードウェア) 側にある。
        """
        try:
            hardware.Update()
        except Exception:
            return
        yield hardware
        try:
            subs = list(hardware.SubHardware)
        except Exception:
            return
        for sub in subs:
            try:
                sub.Update()
            except Exception:
                continue
            yield sub

    def _temps(self, hardware):
        """1つのハードウェアの温度センサを {センサ名(小文字): ℃} で返す。"""
        out = {}
        for hw in self._walk(hardware):
            try:
                sensors = list(hw.Sensors)
            except Exception:
                continue
            for sensor in sensors:
                try:
                    if sensor.SensorType != self._temp_type:
                        continue
                    value = sensor.Value
                    if value is None:
                        continue
                    out[str(sensor.Name).strip().lower()] = float(value)
                except Exception:
                    continue
        return out

    def sample(self):
        """{"cpu": ℃|None, "gpu": ℃|None} を返す。"""
        result = {"cpu": None, "gpu": None}
        try:
            hardware = list(self._computer.Hardware)
        except Exception:
            return result
        for hw in hardware:
            try:
                htype = hw.HardwareType
            except Exception:
                continue
            if htype == self._cpu_type:
                if result["cpu"] is None:
                    result["cpu"] = pick_temp(self._temps(hw), CPU_TEMP_PREFERRED)
            elif htype in self._gpu_types and result["gpu"] is None:
                result["gpu"] = pick_temp(self._temps(hw), GPU_TEMP_PREFERRED)
        return result

    def dump(self):
        """[(ハードウェア名, 種別, センサ名, 値), ...] を返す (--selftest用)。"""
        rows = []
        try:
            hardware = list(self._computer.Hardware)
        except Exception:
            return rows
        for hw in hardware:
            for node in self._walk(hw):
                try:
                    sensors = list(node.Sensors)
                    hw_name = str(node.Name)
                    hw_type = str(node.HardwareType)
                except Exception:
                    continue
                for sensor in sensors:
                    try:
                        if sensor.SensorType != self._temp_type:
                            continue
                        rows.append((hw_name, hw_type, str(sensor.Name),
                                     None if sensor.Value is None
                                     else float(sensor.Value)))
                    except Exception:
                        continue
        return rows


_thermal = None


def thermal_init(dll_arg, enabled, with_gpu, with_extra=False):
    """温度取得を初期化する。失敗しても常駐は継続する (温度は null)。"""
    global _thermal
    if not enabled:
        log("thermal: disabled by --no-cpu-temp")
        return
    path = find_lhm_dll(dll_arg)
    if path is None:
        log("thermal: {} not found. CPU temp stays null. "
            "Run install-agent.ps1 (it downloads the DLL) or pass --lhm-dll."
            .format(LHM_DLL_NAME))
        return
    try:
        _thermal = ThermalSource(path, with_gpu=with_gpu, with_extra=with_extra)
    except Exception as exc:
        log("thermal: LibreHardwareMonitor init failed ({}): {}".format(path, exc))
        _thermal = None
        return
    log("thermal: LibreHardwareMonitor loaded from {}".format(path))
    sample = _thermal.sample()
    log("thermal: first sample {} (elevated={}, hvci={})".format(
        sample, is_admin(), hvci_enabled()))
    if sample["cpu"] is None:
        for hint in temp_failure_hints():
            log("thermal: CPU temp unavailable - {}".format(hint))


def thermal_sample():
    if _thermal is None:
        return {"cpu": None, "gpu": None}
    try:
        return _thermal.sample()
    except Exception as exc:
        log("thermal: sample failed: {}".format(exc))
        return {"cpu": None, "gpu": None}


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


# --- サンプリング --------------------------------------------------------------
class Sampler:
    def __init__(self):
        self.host = socket.gethostname()
        self.net_meter = RateMeter()
        self.dsk_meter = RateMeter()
        psutil.cpu_percent(interval=None)  # 初回呼び出しのプライミング

    def packet(self):
        per_core = psutil.cpu_percent(interval=None, percpu=True)
        util = sum(per_core) / len(per_core) if per_core else 0.0
        freq = psutil.cpu_freq()
        vm = psutil.virtual_memory()
        nio = psutil.net_io_counters()
        dio = psutil.disk_io_counters()
        up_Bps, dn_Bps = self.net_meter.rate(nio.bytes_sent, nio.bytes_recv)
        rd_Bps, wr_Bps = self.dsk_meter.rate(dio.read_bytes, dio.write_bytes)

        temps = thermal_sample()
        gpu = gpu_sample()
        if gpu and gpu.get("temp_c") is None and temps["gpu"] is not None:
            gpu["temp_c"] = temps["gpu"]      # NVMLが温度を返さない場合の補完
        elif not gpu and temps["gpu"] is not None:
            gpu = {"temp_c": temps["gpu"]}    # 非NVIDIA GPU: 温度のみ

        return {
            "v": 1,
            "ts": time.time(),
            "host": self.host,
            "uptime_s": time.time() - psutil.boot_time(),
            "cpu": {
                "util": round(util, 1),
                "per_core": [round(c, 1) for c in per_core],
                "freq_mhz": round(freq.current, 0) if freq else None,
                "temp_c": temps["cpu"],
            },
            "mem": {"used": vm.total - vm.available, "total": vm.total},
            "gpu": gpu,
            "net": {"up_bps": up_Bps * 8, "down_bps": dn_Bps * 8},
            "disk": {"read_bps": rd_Bps, "write_bps": wr_Bps},
        }


def selftest(args):
    """温度センサの検出状況と送信パケットを表示して終了する。"""
    print("GadgetMonitor agent selftest")
    print("  python     : {}".format(sys.version.split()[0]))
    print("  elevated   : {}".format(
        "yes" if is_admin() else "NO (このプロセスでは温度を取得できません。"
        "常駐タスク側の権限は agent.log を参照)"))
    hvci = hvci_enabled()
    print("  memory integrity (HVCI) : {}".format(
        "不明" if hvci is None else ("ON  <- CPU温度は取得不可" if hvci else "off")))
    dll = find_lhm_dll(args.lhm_dll)
    print("  LHM dll    : {}".format(dll or "(見つかりません)"))
    nv_init()
    print("  NVML       : {}".format("ok" if _nv is not None else "unavailable"))
    # 自己診断ではマザーボード/ストレージも開き、利用可能なセンサを全て見せる
    thermal_init(args.lhm_dll, enabled=not args.no_cpu_temp,
                 with_gpu=True, with_extra=True)
    print("")
    if _thermal is not None:
        rows = _thermal.dump()
        if rows:
            print("  検出した温度センサ:")
            for hw_name, hw_type, name, value in rows:
                mark = "" if plausible_temp(value) else "   <- 無効値"
                print("    [{}] {} / {} = {}{}".format(
                    hw_type, hw_name, name,
                    "null" if value is None else "{:.1f}C".format(value),
                    mark))
        else:
            print("  温度センサを1件も検出できませんでした"
                  "（管理者権限で実行しているか確認してください）")
        print("")
        print("  代表値: {}".format(_thermal.sample()))
        cpu_rows = [v for _n, t, _s, v in rows if t == "Cpu"]
        if cpu_rows and not any(plausible_temp(v) for v in cpu_rows):
            print("")
            print("  → CPUのセンサが全て無効値です。カーネルドライバを読み込め"
                  "ていません。原因候補:")
            for hint in temp_failure_hints():
                print("     - {}".format(hint))
        print("")
    sampler = Sampler()
    sampler.packet()      # レート計算のプライミング
    time.sleep(1.0)
    packet = sampler.packet()
    print("  送信パケット:")
    print(json.dumps(packet, indent=2, ensure_ascii=False))
    print("")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(json.dumps(packet).encode("utf-8"),
                    (args.target, args.port))
        print("  送信テスト: {}:{} へ送出しました (UDPのため到達確認は"
              "Pi側の画面で行ってください)".format(args.target, args.port))
    except OSError as exc:
        print("  送信テスト: 失敗 {}:{} — {}".format(
            args.target, args.port, exc))
    finally:
        sock.close()
    if _thermal is not None:
        _thermal.close()
    return 0


def main():
    ap = argparse.ArgumentParser(description="GadgetMonitor PC agent")
    ap.add_argument("--target", default="10.87.0.1", help="Pi address")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--lhm-dll", default="",
                    help="LibreHardwareMonitorLib.dll (省略時は既定の場所を自動探索)")
    ap.add_argument("--no-cpu-temp", action="store_true",
                    help="温度取得を行わない")
    ap.add_argument("--lhm-gpu", choices=("auto", "on", "off"), default="auto",
                    help="LHMでGPU温度も取得する。auto=NVMLが使えない時のみ")
    ap.add_argument("--log", default="", help="ログ出力先ファイル")
    ap.add_argument("--selftest", action="store_true",
                    help="センサ検出状況と送信パケットを表示して終了")
    args = ap.parse_args()

    log_init(args.log)
    if args.selftest:
        return selftest(args)

    log("agent start: target={}:{} interval={}s elevated={}".format(
        args.target, args.port, args.interval, is_admin()))
    nv_init()
    want_gpu = (args.lhm_gpu == "on"
                or (args.lhm_gpu == "auto" and _nv is None))
    thermal_init(args.lhm_dll, enabled=not args.no_cpu_temp, with_gpu=want_gpu)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sampler = Sampler()
    last_err = 0.0

    try:
        while True:
            t0 = time.monotonic()
            try:
                pkt = sampler.packet()
                sock.sendto(json.dumps(pkt).encode("utf-8"),
                            (args.target, args.port))
            except Exception as exc:
                # 一時的な失敗(リンク未接続等)でも常駐を続ける。
                # ケーブル抜去中に毎秒書き込まないよう60秒に1回へ間引く。
                now = time.monotonic()
                if now - last_err > 60.0:
                    last_err = now
                    log("send error: {}".format(exc))
            time.sleep(max(0.1, args.interval - (time.monotonic() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        if _thermal is not None:
            _thermal.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
