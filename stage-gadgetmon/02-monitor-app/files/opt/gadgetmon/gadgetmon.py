#!/usr/bin/env python3
"""RasPiOS_GadgetMonitor — デスクトップPC稼働率モニタ (Pi側レンダラ)

PC側エージェントから UDP/JSON (docs/protocol.md) を受信し、
DRM/KMS 上の pygame でグレー基調の工学モニター風GUIを描画する。

配色は PenchantManufacture_ImageAssets の工業デカール仕様
(docs/DECAL_VARIANTS.md) に準拠:
  nickel (白銅燐光) : 安定時の数値・本文
  hazard (警戒)     : 警告時の数値・帯
  sumi   (墨)       : ラベル
フォント: PenchantManufacture.otf (ASCII+ギリシャ文字, CC BY 4.0,
(c) RadianN_kswg / ラジアン(柏木主税))
"""

import json
import os
import socket
import time
from collections import deque

import pygame

CONF_PATH = "/boot/firmware/gadgetmon.conf"
FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "fonts", "PenchantManufacture.otf")

# --- 配色 (DECAL_VARIANTS.md 準拠) -----------------------------------------
NICKEL_TOP = (0xCA, 0xCE, 0xD6)   # 白銅ボディ上端
NICKEL_BOT = (0x96, 0x9C, 0xA6)   # 白銅ボディ下端
SLATE      = (0x28, 0x2C, 0x32)   # nickel キーライン
PALE       = (0xE0, 0xE4, 0xEA)   # nickel ハロー(淡白)
MAGENTA    = (0xFF, 0x4D, 0x9D)   # nickel アクセント(燐光マゼンタ)

HAZARD_TOP = (0xE8, 0xB4, 0x30)   # 標識イエロー上端
HAZARD_BOT = (0xCD, 0x96, 0x1C)   # 標識イエロー下端
DARKSTEEL  = (0x16, 0x18, 0x1C)   # hazard キーライン(暗鋼)
OFFWHITE   = (0xE8, 0xE4, 0xD8)   # hazard ハロー(オフホワイト)
STRIPE_BK  = (0x12, 0x12, 0x14)   # hazard 黒斜線

SUMI_TOP   = (0x16, 0x18, 0x1C)   # 墨ボディ上端(近黒)
SUMI_BOT   = (0x0B, 0x0C, 0x0E)   # 墨ボディ下端

# --- 画面基調 (グレー工学モニター) -----------------------------------------
BG         = (0x24, 0x27, 0x2B)
PANEL      = (0x2B, 0x2F, 0x35)
PANEL_DK   = (0x20, 0x23, 0x27)
PANEL_EDGE = (0x3A, 0x3F, 0x47)
GRID       = (0x34, 0x39, 0x40)
PLATE      = (0x9A, 0xA0, 0xA8)   # ラベルプレート(明るい金属灰)
DIM        = (0x6E, 0x74, 0x7E)

SCHEMES = {
    "nickel": (NICKEL_TOP, NICKEL_BOT, SLATE),
    "hazard": (HAZARD_TOP, HAZARD_BOT, DARKSTEEL),
    "sumi":   (SUMI_TOP,   SUMI_BOT,   OFFWHITE),
}

HIST_LEN = 180  # グラフ履歴サンプル数


# --- 設定 -------------------------------------------------------------------
def load_conf(path):
    conf = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                conf[key.strip()] = val.strip()
    except OSError:
        pass
    return conf


def warn_thresh(conf, key, default):
    """しきい値を取得。空値は None (=無効)。"""
    if key not in conf:
        return default
    val = conf[key].strip()
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None


# --- フォント / デカール文字描画 ---------------------------------------------
_fonts = {}
_decal_cache = {}


def get_font(size):
    f = _fonts.get(size)
    if f is None:
        try:
            f = pygame.font.Font(FONT_PATH, size)
        except (OSError, pygame.error):
            f = pygame.font.Font(None, size)  # 同梱フォント欠落時の保険
        _fonts[size] = f
    return f


def _gradient(width, height, top, bot):
    surf = pygame.Surface((width, height), pygame.SRCALPHA)
    hh = max(1, height - 1)
    for y in range(height):
        t = y / hh
        col = (int(top[0] + (bot[0] - top[0]) * t),
               int(top[1] + (bot[1] - top[1]) * t),
               int(top[2] + (bot[2] - top[2]) * t),
               255)
        surf.fill(col, (0, y, width, 1))
    return surf


def decal(text, size, scheme="nickel"):
    """二重縁取り+縦グラデの『工業デカール』風テキストSurfaceを返す。"""
    key = (text, size, scheme)
    cached = _decal_cache.get(key)
    if cached is not None:
        return cached
    if len(_decal_cache) > 1024:
        _decal_cache.clear()
    top, bot, keyline = SCHEMES[scheme]
    font = get_font(size)
    base = font.render(text, True, (255, 255, 255))
    w, h = base.get_size()
    opx = max(1, size // 16)
    surf = pygame.Surface((w + opx * 2, h + opx * 2), pygame.SRCALPHA)
    edge = font.render(text, True, keyline)
    for dx in (-opx, 0, opx):
        for dy in (-opx, 0, opx):
            if dx or dy:
                surf.blit(edge, (opx + dx, opx + dy))
    body = _gradient(w, h, top, bot)
    body.blit(base, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    surf.blit(body, (opx, opx))
    _decal_cache[key] = surf
    return surf


def blit_decal(target, text, pos, size, scheme="nickel", align="left"):
    surf = decal(text, size, scheme)
    x, y = pos
    if align == "right":
        x -= surf.get_width()
    elif align == "center":
        x -= surf.get_width() // 2
    target.blit(surf, (x, y))
    return surf.get_size()


# --- 部品描画 -----------------------------------------------------------------
def draw_stripes(target, rect, period, width, color):
    """警戒帯: 45度の黒斜線。"""
    prev_clip = target.get_clip()
    target.set_clip(rect)
    x = rect.left - rect.height
    while x < rect.right + rect.height:
        pygame.draw.line(target, color,
                         (x, rect.bottom), (x + rect.height, rect.top), width)
        x += period
    target.set_clip(prev_clip)


def draw_plate(target, pos, text, size):
    """墨デカールのラベルプレート。"""
    surf = decal(text, size, "sumi")
    pad = max(3, size // 4)
    rect = pygame.Rect(pos[0], pos[1],
                       surf.get_width() + pad * 2, surf.get_height() + pad)
    pygame.draw.rect(target, PLATE, rect, border_radius=3)
    pygame.draw.rect(target, DARKSTEEL, rect, width=1, border_radius=3)
    target.blit(surf, (rect.x + pad, rect.y + pad // 2))
    return rect


_bar_cache = {}


def draw_bar(target, rect, ratio, warn):
    """使用率バー(横)。安定時はnickel、警告時はhazard+黒斜線。"""
    ratio = max(0.0, min(1.0, ratio))
    pygame.draw.rect(target, PANEL_DK, rect)
    key = (rect.w, rect.h, warn)
    grad = _bar_cache.get(key)
    if grad is None:
        if len(_bar_cache) > 32:
            _bar_cache.clear()
        top, bot = (HAZARD_TOP, HAZARD_BOT) if warn else (NICKEL_TOP, NICKEL_BOT)
        grad = _gradient(rect.w, rect.h, top, bot)
        _bar_cache[key] = grad
    fill_w = int(rect.w * ratio)
    if fill_w > 0:
        target.blit(grad, rect.topleft, area=(0, 0, fill_w, rect.h))
        if warn:
            draw_stripes(target, pygame.Rect(rect.x, rect.y, fill_w, rect.h),
                         period=max(8, rect.h), width=max(2, rect.h // 5),
                         color=STRIPE_BK)
    pygame.draw.rect(target, PANEL_EDGE, rect, width=1)


def draw_graph(target, rect, series_list, fixed_max=None, warn=False):
    """折れ線グラフ。series_list: [(deque, is_primary), ...]"""
    pygame.draw.rect(target, PANEL_DK, rect)
    for i in (1, 2, 3):
        y = rect.y + rect.h * i // 4
        pygame.draw.line(target, GRID, (rect.x + 1, y), (rect.right - 2, y), 1)
    scale = fixed_max
    if scale is None:
        peak = 0.0
        for series, _ in series_list:
            if series:
                peak = max(peak, max(series))
        scale = max(peak * 1.15, 1e-9)
    layer = pygame.Surface(rect.size, pygame.SRCALPHA)
    for series, primary in series_list:
        if len(series) < 2:
            continue
        color = (HAZARD_TOP if warn else MAGENTA) if primary else PALE
        pts = []
        n = len(series)
        for i, v in enumerate(series):
            x = rect.w - 1 - (n - 1 - i) * (rect.w - 2) / (HIST_LEN - 1)
            y = rect.h - 2 - min(1.0, v / scale) * (rect.h - 4)
            pts.append((x, y))
        if len(pts) >= 2:
            glow = max(3, rect.h // 18)
            pygame.draw.lines(layer, (*color, 70), False, pts, glow)
            pygame.draw.lines(layer, (*color, 255) if primary else (*color, 170),
                              False, pts, 2 if primary else 1)
    target.blit(layer, rect.topleft)
    pygame.draw.rect(target, PANEL_EDGE, rect, width=1)


# --- データ整形 -----------------------------------------------------------------
def fmt_num(val, pattern="{:.0f}"):
    if val is None:
        return "--"
    return pattern.format(val)


def fmt_rate(bps, bits=True):
    """転送レート整形。bits=True: bps基準(M/G), False: bytes基準(MB/s)。"""
    if bps is None:
        return "--"
    unit = "B" if bits else "MB/S"
    if bits:
        if bps >= 1e9:
            return "{:.2f}G".format(bps / 1e9)
        if bps >= 1e6:
            return "{:.1f}M".format(bps / 1e6)
        if bps >= 1e3:
            return "{:.0f}K".format(bps / 1e3)
        return "{:.0f}".format(bps)
    mbs = bps / 1e6
    if mbs >= 1000:
        return "{:.2f}GB/S".format(mbs / 1000)
    return "{:.1f}{}".format(mbs, unit)


def fmt_uptime(sec):
    if sec is None:
        return "--"
    sec = int(sec)
    days, rem = divmod(sec, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days:
        return "UP {}D {:02d}:{:02d}".format(days, hours, mins)
    return "UP {:02d}:{:02d}".format(hours, mins)


# --- 本体 -----------------------------------------------------------------------
class Monitor:
    def __init__(self):
        conf = load_conf(CONF_PATH)
        self.port = int(float(conf.get("LISTEN_PORT", "8787")))
        self.stale_sec = float(conf.get("STALE_SEC", "5") or 5)
        self.th = {
            "cpu_util": warn_thresh(conf, "WARN_CPU_UTIL", 90.0),
            "cpu_temp": warn_thresh(conf, "WARN_CPU_TEMP", 85.0),
            "gpu_temp": warn_thresh(conf, "WARN_GPU_TEMP", 83.0),
            "mem_pct": warn_thresh(conf, "WARN_MEM_PCT", 90.0),
            "vram_pct": warn_thresh(conf, "WARN_VRAM_PCT", 95.0),
            "gpu_power": warn_thresh(conf, "WARN_GPU_POWER_W", None),
            "net_mbps": warn_thresh(conf, "WARN_NET_MBPS", None),
        }
        self.data = None
        self.recv_mono = None
        self.hist = {k: deque(maxlen=HIST_LEN) for k in
                     ("cpu", "mem", "gpu", "vram",
                      "net_dn", "net_up", "dsk_rd", "dsk_wr")}
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", self.port))
        self.sock.setblocking(False)

    # -- 受信 --
    def poll(self):
        while True:
            try:
                raw, _addr = self.sock.recvfrom(65536)
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                return
            try:
                pkt = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(pkt, dict) or pkt.get("v") != 1:
                continue
            self.data = pkt
            self.recv_mono = time.monotonic()
            self._push_hist(pkt)

    def _push_hist(self, d):
        cpu = d.get("cpu") or {}
        mem = d.get("mem") or {}
        gpu = d.get("gpu") or {}
        net = d.get("net") or {}
        dsk = d.get("disk") or {}
        self.hist["cpu"].append(cpu.get("util") or 0.0)
        total = mem.get("total") or 0
        self.hist["mem"].append(
            100.0 * (mem.get("used") or 0) / total if total else 0.0)
        self.hist["gpu"].append(gpu.get("util") or 0.0)
        vt = gpu.get("vram_total") or 0
        self.hist["vram"].append(
            100.0 * (gpu.get("vram_used") or 0) / vt if vt else 0.0)
        self.hist["net_dn"].append(net.get("down_bps") or 0.0)
        self.hist["net_up"].append(net.get("up_bps") or 0.0)
        self.hist["dsk_rd"].append(dsk.get("read_bps") or 0.0)
        self.hist["dsk_wr"].append(dsk.get("write_bps") or 0.0)

    # -- 状態判定 --
    def stale_for(self):
        if self.recv_mono is None:
            return None
        return time.monotonic() - self.recv_mono

    def _over(self, key, value):
        th = self.th[key]
        return th is not None and value is not None and value >= th

    def warns(self):
        d = self.data or {}
        cpu = d.get("cpu") or {}
        mem = d.get("mem") or {}
        gpu = d.get("gpu") or {}
        net = d.get("net") or {}
        total = mem.get("total") or 0
        mem_pct = 100.0 * (mem.get("used") or 0) / total if total else None
        vt = gpu.get("vram_total") or 0
        vram_pct = 100.0 * (gpu.get("vram_used") or 0) / vt if vt else None
        net_peak = max(net.get("down_bps") or 0, net.get("up_bps") or 0) / 1e6
        w = {
            "cpu": self._over("cpu_util", cpu.get("util"))
                   or self._over("cpu_temp", cpu.get("temp_c")),
            "mem": self._over("mem_pct", mem_pct),
            "gpu": self._over("gpu_temp", gpu.get("temp_c")),
            "vram": self._over("vram_pct", vram_pct)
                    or self._over("gpu_power", gpu.get("power_w")),
            "net": self._over("net_mbps", net_peak),
            "disk": False,
        }
        w["any"] = any(w.values())
        return w

    def pc_clock(self):
        if self.data is None or self.recv_mono is None:
            return None
        ts = self.data.get("ts")
        if ts is None:
            return None
        return ts + (time.monotonic() - self.recv_mono)


# --- 描画 -----------------------------------------------------------------------
class Renderer:
    def __init__(self, screen):
        self.screen = screen
        self.w, self.h = screen.get_size()
        self.wide = self.w >= self.h * 1.45 and self.w >= 1024
        self.margin = max(8, int(self.w * 0.015))
        self.header_h = int(self.h * 0.115)
        # 単位サイズ (小型パネルでも潰れないよう下限を設ける)
        self.u = max(10, int(min(self.w / 96, self.h / 54) * 2))

    def frame(self, mon):
        scr = self.screen
        scr.fill(BG)
        warns = mon.warns()
        stale = mon.stale_for()
        lost = stale is None or stale > mon.stale_sec
        self._header(mon, warns, lost)
        self._cards(mon, warns)
        if lost:
            self._overlay(mon, stale)

    # -- ヘッダ --
    def _header(self, mon, warns, lost):
        scr = self.screen
        m = self.margin
        rect = pygame.Rect(m, m, self.w - m * 2, self.header_h - m)
        pygame.draw.rect(scr, PANEL, rect)
        pygame.draw.rect(scr, PANEL_EDGE, rect, width=1)
        band = pygame.Rect(rect.x, rect.bottom - 5, rect.w, 5)
        if warns["any"] and not lost:
            pygame.draw.rect(scr, HAZARD_BOT, band)
            draw_stripes(scr, band, period=18, width=4, color=STRIPE_BK)
        else:
            pygame.draw.rect(scr, SLATE, band)

        big = int(rect.h * 0.42)
        small = max(10, int(rect.h * 0.20))
        blit_decal(scr, "DESKTOP TELEMETRY", (rect.x + m, rect.y + int(rect.h * 0.10)),
                   big, "nickel")
        d = mon.data or {}
        host = str(d.get("host") or "UNKNOWN HOST").upper()[:24]
        sub = host + "  " + fmt_uptime(d.get("uptime_s"))
        blit_decal(scr, sub, (rect.x + m, rect.y + int(rect.h * 0.60)),
                   small, "nickel")

        clock = mon.pc_clock()
        if clock is not None:
            text = time.strftime("%H:%M:%S", time.localtime(clock))
        else:
            text = "--:--:--"
        blit_decal(scr, text, (rect.right - m, rect.y + int(rect.h * 0.10)),
                   big, "nickel", align="right")
        status = "SIGNAL LOST" if lost else ("ALERT" if warns["any"] else "NOMINAL")
        scheme = "hazard" if (lost or warns["any"]) else "nickel"
        blit_decal(scr, "STATUS " + status, (rect.right - m, rect.y + int(rect.h * 0.60)),
                   small, scheme, align="right")

    # -- カード群 --
    def _cards(self, mon, warns):
        cols, rows = (3, 2) if self.wide else (2, 3)
        m = self.margin
        top = self.header_h + m
        avail_w = self.w - m * (cols + 1)
        avail_h = self.h - top - m * rows
        cw = avail_w // cols
        ch = avail_h // rows
        d = mon.data or {}
        cpu = d.get("cpu") or {}
        mem = d.get("mem") or {}
        gpu = d.get("gpu") or {}
        net = d.get("net") or {}
        dsk = d.get("disk") or {}
        cards = [
            ("CPU", self._card_cpu, cpu, warns["cpu"]),
            ("MEMORY", self._card_mem, mem, warns["mem"]),
            ("GPU", self._card_gpu, gpu, warns["gpu"]),
            ("VRAM", self._card_vram, gpu, warns["vram"]),
            ("NETWORK", self._card_net, net, warns["net"]),
            ("DISK I/O", self._card_disk, dsk, warns["disk"]),
        ]
        for idx, (title, fn, src, warn) in enumerate(cards):
            cx = idx % cols
            cy = idx // cols
            rect = pygame.Rect(m + cx * (cw + m), top + cy * (ch + m), cw, ch)
            self._card_base(rect, title, warn)
            fn(mon, rect, src, warn)

    def _card_base(self, rect, title, warn):
        scr = self.screen
        pygame.draw.rect(scr, PANEL, rect)
        pygame.draw.rect(scr, PANEL_EDGE, rect, width=1)
        if warn:
            band = pygame.Rect(rect.x + 1, rect.y + 1, rect.w - 2, 6)
            pygame.draw.rect(scr, HAZARD_BOT, band)
            draw_stripes(scr, band, period=16, width=3, color=STRIPE_BK)
        label = max(11, int(rect.h * 0.085))
        draw_plate(scr, (rect.x + self.u // 2, rect.y + self.u // 2 + (6 if warn else 0)),
                   title, label)

    def _value_row(self, rect, value, sub, warn):
        """カード共通: 大きな値 + 補足行。戻り値はグラフ用の残り矩形。"""
        scr = self.screen
        pad = self.u // 2
        big = int(rect.h * 0.26)
        small = max(10, int(rect.h * 0.10))
        scheme = "hazard" if warn else "nickel"
        vy = rect.y + int(rect.h * 0.16)
        blit_decal(scr, value, (rect.right - pad, vy), big, scheme, align="right")
        blit_decal(scr, sub, (rect.right - pad, vy + int(big * 1.28)),
                   small, "nickel", align="right")
        gy = rect.y + int(rect.h * 0.56)
        return pygame.Rect(rect.x + pad, gy,
                           rect.w - pad * 2, rect.bottom - pad - gy)

    def _card_cpu(self, mon, rect, cpu, warn):
        util = cpu.get("util")
        temp = cpu.get("temp_c")
        freq = cpu.get("freq_mhz")
        sub = "{}  {}".format(
            fmt_num(freq / 1000.0, "{:.1f}GHZ") if freq else "--GHZ",
            fmt_num(temp, "{:.0f}C"))
        graph = self._value_row(rect, fmt_num(util, "{:.0f}%"), sub, warn)
        cores = cpu.get("per_core") or []
        if cores and graph.h > self.u * 3:
            strip = pygame.Rect(graph.x, graph.y, graph.w, int(graph.h * 0.22))
            graph = pygame.Rect(graph.x, strip.bottom + 2,
                                graph.w, graph.bottom - strip.bottom - 2)
            n = len(cores)
            bw = max(2, (strip.w - n) // max(1, n))
            for i, c in enumerate(cores[:64]):
                x = strip.x + i * (bw + 1)
                if x + bw > strip.right:
                    break
                h = max(1, int(strip.h * min(100.0, c) / 100.0))
                col = HAZARD_TOP if warn else NICKEL_BOT
                pygame.draw.rect(self.screen, PANEL_DK,
                                 (x, strip.y, bw, strip.h))
                pygame.draw.rect(self.screen, col,
                                 (x, strip.bottom - h, bw, h))
        draw_graph(self.screen, graph, [(mon.hist["cpu"], True)],
                   fixed_max=100.0, warn=warn)

    def _card_mem(self, mon, rect, mem, warn):
        total = mem.get("total") or 0
        used = mem.get("used") or 0
        pct = 100.0 * used / total if total else None
        sub = "{:.1f}/{:.1f}GB".format(used / 2**30, total / 2**30) if total else "--"
        graph = self._value_row(rect, fmt_num(pct, "{:.0f}%"), sub, warn)
        bar = pygame.Rect(graph.x, graph.y, graph.w, max(6, self.u // 2))
        draw_bar(self.screen, bar, (pct or 0) / 100.0, warn)
        graph = pygame.Rect(graph.x, bar.bottom + 3,
                            graph.w, graph.bottom - bar.bottom - 3)
        draw_graph(self.screen, graph, [(mon.hist["mem"], True)],
                   fixed_max=100.0, warn=warn)

    def _card_gpu(self, mon, rect, gpu, warn):
        util = gpu.get("util")
        temp = gpu.get("temp_c")
        name = str(gpu.get("name") or "")[:20].upper()
        sub = "{}  {}".format(fmt_num(temp, "{:.0f}C"), name or "--")
        graph = self._value_row(rect, fmt_num(util, "{:.0f}%"), sub, warn)
        draw_graph(self.screen, graph, [(mon.hist["gpu"], True)],
                   fixed_max=100.0, warn=warn)

    def _card_vram(self, mon, rect, gpu, warn):
        vt = gpu.get("vram_total") or 0
        vu = gpu.get("vram_used") or 0
        pct = 100.0 * vu / vt if vt else None
        power = gpu.get("power_w")
        sub = "{:.1f}/{:.1f}GB  {}".format(
            vu / 2**30, vt / 2**30,
            fmt_num(power, "{:.0f}W")) if vt else fmt_num(power, "{:.0f}W")
        graph = self._value_row(rect, fmt_num(pct, "{:.0f}%"), sub, warn)
        bar = pygame.Rect(graph.x, graph.y, graph.w, max(6, self.u // 2))
        draw_bar(self.screen, bar, (pct or 0) / 100.0, warn)
        graph = pygame.Rect(graph.x, bar.bottom + 3,
                            graph.w, graph.bottom - bar.bottom - 3)
        draw_graph(self.screen, graph, [(mon.hist["vram"], True)],
                   fixed_max=100.0, warn=warn)

    def _card_net(self, mon, rect, net, warn):
        dn = net.get("down_bps")
        up = net.get("up_bps")
        sub = "UP {}  DN {}".format(fmt_rate(up), fmt_rate(dn))
        graph = self._value_row(rect, "DN " + fmt_rate(dn), sub, warn)
        draw_graph(self.screen, graph,
                   [(mon.hist["net_up"], False), (mon.hist["net_dn"], True)],
                   warn=warn)

    def _card_disk(self, mon, rect, dsk, warn):
        rd = dsk.get("read_bps")
        wr = dsk.get("write_bps")
        sub = "RD {}  WR {}".format(fmt_rate(rd, bits=False),
                                    fmt_rate(wr, bits=False))
        graph = self._value_row(rect, "RD " + fmt_rate(rd, bits=False), sub, warn)
        draw_graph(self.screen, graph,
                   [(mon.hist["dsk_wr"], False), (mon.hist["dsk_rd"], True)],
                   warn=warn)

    # -- 信号途絶オーバーレイ --
    def _overlay(self, mon, stale):
        scr = self.screen
        shade = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        shade.fill((0x10, 0x11, 0x13, 200))
        scr.blit(shade, (0, 0))
        never = mon.recv_mono is None
        blink = (time.monotonic() % 1.0) < 0.65
        cy = self.h // 2
        band = pygame.Rect(0, cy - int(self.h * 0.16), self.w, int(self.h * 0.32))
        pygame.draw.rect(scr, PANEL_DK, band)
        pygame.draw.rect(scr, PANEL_EDGE, band, width=1)
        for y in (band.top + 2, band.bottom - 8):
            strip = pygame.Rect(0, y, self.w, 6)
            pygame.draw.rect(scr, HAZARD_BOT if not never else SLATE, strip)
            if not never:
                draw_stripes(scr, strip, period=20, width=4, color=STRIPE_BK)
        title = "WAITING FOR HOST" if never else "SIGNAL LOST"
        scheme = "nickel" if never else "hazard"
        if blink or never:
            blit_decal(scr, title, (self.w // 2, cy - int(self.h * 0.085)),
                       int(self.h * 0.09), scheme, align="center")
        hint = ("CONNECT USB-C TO PC AND START AGENT" if never
                else "CHECK USB LINK AND PC AGENT")
        blit_decal(scr, hint, (self.w // 2, cy + int(self.h * 0.035)),
                   max(11, int(self.h * 0.030)), "nickel", align="center")
        if not never:
            blit_decal(scr, "LAST PACKET {:.0f}S AGO".format(stale),
                       (self.w // 2, cy + int(self.h * 0.085)),
                       max(10, int(self.h * 0.024)), "nickel", align="center")


def open_display(retries=15, delay=2.0):
    last_err = None
    for _ in range(retries):
        try:
            pygame.display.init()
            pygame.font.init()
            screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            return screen
        except pygame.error as exc:
            last_err = exc
            pygame.display.quit()
            time.sleep(delay)
    raise SystemExit("display init failed: {}".format(last_err))


def main():
    os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
    screen = open_display()
    pygame.mouse.set_visible(False)
    renderer = Renderer(screen)
    mon = Monitor()
    clock = pygame.time.Clock()
    try:
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return
            mon.poll()
            renderer.frame(mon)
            pygame.display.flip()
            clock.tick(15)
    except KeyboardInterrupt:
        pass
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
