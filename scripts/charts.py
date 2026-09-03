#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""charts.py — SVG 图表构建器（render_report 拆分模块，v4.8.2 重构）

内容：SVG 色板常量、数值/格式/几何工具（_pad_domain/_lin_map/_text_w/_wrap_label/
_ticks）、公共骨架 helper（_svg_open/_svg_close/_vgrid_ticks/_anchor_fit/
_anchor_clamp）、十图 build_* 构建器 + 三情景表（build_scenario_block）与
3.1/3.2 锚点注入（_inject_l1_charts）。只依赖 scoring（共享常量），不依赖主模块状态。
"""
import math
import sys

from scoring import (DIMS, LAYER_NAMES, badge_class, _dim_verdict,
                     _num, _fmt, _esc)


# SVG 色板（全站图表共用暖灰/钢蓝色系，唯一权威处；改色只动这里）
_C_LABEL = "#8a8375"       # 轴刻度/灰字说明/虚线时点刻
_C_GRID = "#ece7db"        # 细网格线
_C_AXIS = "#e0d7c3"        # 轴主线/细描边
_C_BLUE = "#4a6fa5"        # 钢蓝：目标公司/合理带/最新值/PE 发丝
_C_PAPER = "#fffdf9"       # 近白：白刻/描边/带内白字
_C_INK = "#3a362e"         # 深墨：名称文字/发丝线/图例
_C_BLACK = "#2b2620"       # 最重色：首变量名/当前值刻
_C_STONE = "#57524a"       # 中灰：散点同业标签/图例小字
_C_OLIVE = "#66604f"       # 散点图非目标点
_C_SAND = "#b3ab93"        # 暖沙：历史柱/连线曲线/中轴/图例块
_C_SAND_LT = "#ddd3bd"     # 浅沙：分带虚线/分位段
_C_TRACK = "#efe9db"       # 条底轨道/历史带底/面积填充
_C_GOOD_LINE = "#c9bfa8"   # 7.0 良好线虚线
_C_YEAR_GRID = "#f0ebdf"   # 发丝图年份竖网格
_C_GREEN = "#6ba86b"       # 绿：有利/上调/乐观
_C_RED = "#c75b5b"         # 红：不利/下调/悲观
_C_ORANGE = "#c08a2e"      # 橙：中档/基础情景


def _fmt_price(v):
    """走廊图价格标签：最多 4 位有效数字（472.3 / 46.15），精度匹配不确定性。"""
    return f"{v:.4g}"


def _fmt_amt(v) -> str:
    """亿元金额标签：≥1000 带千位符，去尾零（1,156.0 → 1,156；56.8 → 56.8）。v4.8 业务构成图用。"""
    if v is None:
        return "—"
    s = f"{float(v):,.1f}"
    return s[:-2] if s.endswith(".0") else s



_SCENARIO_COLORS = {"pess": _C_RED, "base": _C_ORANGE, "opt": _C_GREEN}
_SCENARIO_NAMES = {"pess": "悲观", "base": "基础", "opt": "乐观"}


def _pad_domain(lo: float, hi: float, ratio: float, floor=None):
    """值域向两端各扩 ratio 比例（防贴边）；floor 给下限（如 ROE 不为负）。"""
    pad = (hi - lo) * ratio or 1
    lo -= pad
    hi += pad
    if floor is not None:
        lo = max(floor, lo)
    return lo, hi


def _lin_map(a: float, b: float, A: float, B: float):
    """线性映射：数值域 [a,b] → 像素域 [A,B]（a→A，b→B）。"""
    return lambda v: A + (v - a) / (b - a) * (B - A)


def _text_w(s: str, font_size: float) -> float:
    """粗估 SVG 文本像素宽（中文/全角≈1em、ASCII≈0.56em），用于标签避让与碰撞检测。"""
    return sum(1.0 if ord(ch) > 0x2E7F else 0.56 for ch in str(s)) * font_size


def _wrap_label(s: str, max_w: float, fs: float) -> list:
    """文本超宽时按视觉宽度对半折两行（断点取两侧宽度最均衡处）；未超宽原样返回 [s]。"""
    if _text_w(s, fs) <= max_w:
        return [s]
    best, best_diff = len(s) // 2, float("inf")
    for i in range(2, len(s) - 1):
        d = abs(_text_w(s[:i], fs) - _text_w(s[i:], fs))
        if d < best_diff:
            best, best_diff = i, d
    return [s[:best], s[best:]]


def _ticks(lo: float, hi: float, n: int = 5) -> list:
    """nice-number 刻度：步长取 1/2/2.5/5×10^k，返回落在 [lo,hi] 内的步长整数倍刻度。
    取代旧版「等距后取整」（会产出 19/32/44/57/69 这类间隔观感不齐的读数）。"""
    span = hi - lo
    if not span > 0:
        return [lo]
    raw = span / (n - 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = mag
    for m in (1, 2, 2.5, 5, 10):
        if m * mag >= raw:
            step = m * mag
            break
    t = math.ceil(lo / step - 1e-9) * step
    out = []
    while t <= hi + 1e-9:
        out.append(round(t, 9))
        t += step
    return out





_SVG_STYLE = "width:100%;min-width:760px;height:auto;display:block;font-family:inherit;"


def _svg_open(w, h, label: str) -> str:
    """图表骨架开头：plot-wrap 容器 + viewBox + aria-label + 全站统一 style。"""
    return (f'<div class="plot-wrap"><svg viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="{label}" style="{_SVG_STYLE}">')


def _svg_close() -> str:
    return '</svg></div>'


def _vgrid_ticks(parts: list, X, vals: list, y1, y2, ty, suffix: str = "") -> None:
    """竖向网格线 + 居中刻度文字（走廊/评分/PE带/业务构成/哑铃五图共用）。
    y1/y2 为网格线纵坐标、ty 为刻度文字纵坐标，数值由调用方按各图布局给出；
    suffix 为刻度数字后的单位（如 x / %）。"""
    for v in vals:
        gx = X(v)
        parts.append(f'<line x1="{gx:.1f}" y1="{y1}" x2="{gx:.1f}" y2="{y2}" stroke="{_C_GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{gx:.1f}" y="{ty}" text-anchor="middle" font-size="11" fill="{_C_LABEL}">{_fmt(v)}{suffix}</text>')


def _anchor_fit(x: float, w: float, lo: float, hi: float, inset: float):
    """居中标签近边缘改对齐：左缘先查，越界改 start/end 且锚点内缩 inset
    （走廊现价标签 / PE 带当前值标签）。返回 (text-anchor, x)。"""
    if x - w / 2 < lo:
        return "start", max(x - inset, lo)
    if x + w / 2 > hi:
        return "end", min(x + inset, hi)
    return "middle", x


def _anchor_clamp(x: float, w: float, lo: float, hi: float):
    """居中标签近边缘改对齐：右缘先查，越界直接夹到 hi/lo 边界
    （走廊中枢标签 / 卖方一致带标签 / PE 带关键时点标签）。返回 (text-anchor, x)。"""
    if x + w / 2 > hi:
        return "end", hi
    if x - w / 2 < lo:
        return "start", lo
    return "middle", x


def build_scenario_spectrum(fill: dict, calc: dict = None) -> str:
    """05 目标价走廊（横版区间条）：x 轴=价格（nice 刻度+单位），每情景一条横向实心区间条
    （悲观→乐观 从上到下，与三情景表列序一致），白条刻=区间中枢，条上方=中枢值与较现价
    涨跌幅，竖虚线=现价（全部脚本计算）。横版取代旧竖版：窄区间不再退化成幽灵胶囊。
    calc（compute_valuation 结果）存在时用其算出的目标价区间；
    否则回退到 fill["scenarios"] 手写区间。缺数据 → 返回空串（模板条件块整块删除）。"""
    price = _num(fill.get("price"))
    cur = str(fill.get("currency") or "元")
    if calc:
        cols = [{"label": r["label"], "low": r["low"], "high": r["high"], "mid": r["mid"],
                 "color": r["color"]} for r in calc["rows"]]
    else:
        cols = []
        for s in fill.get("scenarios") or []:
            lo, hi = _num(s.get("low")), _num(s.get("high"))
            if lo is None or hi is None or hi <= lo:
                continue
            key = str(s.get("key") or "").lower()
            cols.append({"key": key,
                         "label": s.get("label") or _SCENARIO_NAMES.get(key, "情景"),
                         "low": lo, "high": hi, "mid": (lo + hi) / 2,
                         "color": _SCENARIO_COLORS.get(key, _C_LABEL)})
    if not cols or not price:
        return ""
    if not calc:
        order = {"pess": 0, "base": 1, "opt": 2}
        cols.sort(key=lambda r: order.get(r.get("key", ""), 1))  # 悲观/基础/乐观 从上到下

    W = 1000
    L, R, T = 128, 24, 34           # 左列=情景名+区间；上=现价标签
    ROW_H, BAR_H = 52, 28
    AXIS_PAD = 46                   # 末行条到刻度标签的纵向空间
    H = T + len(cols) * ROW_H + AXIS_PAD
    # 卖方一致目标价带（v4.8，可选 fill["consensus"]={"lo":…,"hi":…}，E5 数据）：
    # 灰带垫在情景区间条下方，「卖方怎么看 vs 我们怎么算」一眼对照
    cons = fill.get("consensus") or {}
    c_lo, c_hi = _num(cons.get("lo")), _num(cons.get("hi"))
    cons_ok = c_lo is not None and c_hi is not None and c_hi > c_lo
    dom_lo = [c["low"] for c in cols] + [price] + ([c_lo] if cons_ok else [])
    dom_hi = [c["high"] for c in cols] + [price] + ([c_hi] if cons_ok else [])
    lo_d, hi_d = _pad_domain(min(dom_lo), max(dom_hi), 0.06)
    X = _lin_map(lo_d, hi_d, L, W - R)

    parts = [_svg_open(W, H, "目标价走廊")]
    axis_y = T + len(cols) * ROW_H + 6
    # 价格轴：竖向浅网格线 + nice 刻度 + 单位注
    _vgrid_ticks(parts, X, _ticks(lo_d, hi_d), T - 10, axis_y, axis_y + 17)
    parts.append(f'<line x1="{L}" y1="{axis_y}" x2="{W - R}" y2="{axis_y}" stroke="{_C_AXIS}" stroke-width="1.2"/>')
    parts.append(f'<text x="4" y="{axis_y + 17}" font-size="11" fill="{_C_LABEL}">单位：{_esc(cur)}</text>')
    # 卖方一致目标价灰带（垫在情景条下方）+ 轴下标签
    if cons_ok:
        x1, x2 = X(c_lo), X(c_hi)
        parts.append(f'<rect x="{x1:.1f}" y="{T - 10}" width="{x2 - x1:.1f}" '
                     f'height="{axis_y - (T - 10):.1f}" fill="{_C_LABEL}" fill-opacity="0.13"/>')
        clabel = f'卖方目标价 {_fmt_price(c_lo)}–{_fmt_price(c_hi)}'
        cw = _text_w(clabel, 10.5)
        cx_c = (x1 + x2) / 2
        c_anchor, c_tx = _anchor_clamp(cx_c, cw, L, W - 4)
        parts.append(f'<text x="{c_tx:.1f}" y="{axis_y + 32}" text-anchor="{c_anchor}" '
                     f'font-size="10.5" fill="{_C_LABEL}">{clabel}</text>')
    # 现价竖虚线 + 顶部标签（近边缘时改对齐防溢出）
    px = X(price)
    parts.append(f'<line x1="{px:.1f}" y1="{T - 12}" x2="{px:.1f}" y2="{axis_y}" '
                 f'stroke="{_C_BLUE}" stroke-width="1.5" stroke-dasharray="5 4"/>')
    price_label = f"现价 {_fmt(price)}"
    anchor, tx = _anchor_fit(px, _text_w(price_label, 12), L, W - R, 2)
    parts.append(f'<text x="{tx:.1f}" y="{T - 18}" text-anchor="{anchor}" font-size="12" '
                 f'font-weight="700" fill="{_C_BLUE}">{price_label}</text>')
    # 情景区间条
    for i, c in enumerate(cols):
        cy = T + i * ROW_H + (ROW_H - BAR_H) / 2
        x_lo, x_hi, x_mid = X(c["low"]), X(c["high"]), X(c["mid"])
        parts.append(f'<text x="{L - 12}" y="{cy + 11}" text-anchor="end" font-size="13" '
                     f'font-weight="600" fill="{_C_INK}">{_esc(c["label"])}</text>')
        parts.append(f'<text x="{L - 12}" y="{cy + 25}" text-anchor="end" font-size="10.5" '
                     f'fill="{_C_LABEL}">{_fmt_price(c["low"])}–{_fmt_price(c["high"])}</text>')
        parts.append(f'<rect x="{x_lo:.1f}" y="{cy:.1f}" width="{max(x_hi - x_lo, 3):.1f}" '
                     f'height="{BAR_H}" rx="8" fill="{c["color"]}"/>')
        parts.append(f'<line x1="{x_mid:.1f}" y1="{cy + 5:.1f}" x2="{x_mid:.1f}" y2="{cy + BAR_H - 5:.1f}" '
                     f'stroke="{_C_PAPER}" stroke-width="3"/>')
        pct = c["mid"] / price - 1
        vlabel = f'{_fmt_price(c["mid"])}（{pct * 100:+.1f}%）'
        # 中枢标签统一放条上方（v4.7.1：原"条外右侧放不下塞条内白字"与白刻交叠且手机上更挤）
        vw = _text_w(vlabel, 12.5)
        cx_mid = (x_lo + x_hi) / 2
        anchor, tx = _anchor_clamp(cx_mid, vw, L, W - 4)
        parts.append(f'<text x="{tx:.1f}" y="{cy - 6:.1f}" text-anchor="{anchor}" font-size="12.5" '
                     f'font-weight="700" fill="{c["color"]}">{vlabel}</text>')
    parts.append(_svg_close())
    parts.append('<span class="source">目标价走廊（脚本按 valuation/scenarios 字段生成）：横条=情景目标价区间，'
                 '白条刻=区间中枢，竖虚线=现价；条上方=中枢值与较现价涨跌幅'
                 + ('；灰带=卖方一致目标价区间（E5 研报）' if cons_ok else '') + '</span>')
    return "".join(parts)


def build_scenario_block(calc: dict, cur: str = "元") -> str:
    """由 compute_valuation 结果生成三情景对比表 + 三指标卡条（scenario-table/metric-card 骨架，
    类名全部脚本写死，杜绝幻觉类名与手算错误）。cur 为目标价币种单位（默认「元」，港股传「港元」）。"""
    if not calc:
        return ""
    rows = calc["rows"]
    head = ('<tr><th>指标</th>' + "".join(
        f'<th class="center">{_esc(r["label"])}情景</th>' for r in rows) + "</tr>")

    def row(name, fmt, cls="num"):
        cells = "".join(f'<td class="{cls}">{fmt(r)}</td>' if cls else f"<td>{fmt(r)}</td>" for r in rows)
        return f"<tr><td>{name}</td>{cells}</tr>"

    if calc.get("mode") == "mcap":
        # 市值口径（NAV/rNPV/SOTP 行业附录）：无净利/EPS/PE 行，改显示目标市值区间
        driver_rows = [row("目标市值", lambda r: f"{r['mcap_lo']:,.0f}-{r['mcap_hi']:,.0f} 亿")]
    else:
        driver_rows = [
            row("归母净利", lambda r: f"{r['profit']:,.0f} 亿"),
            row("EPS", lambda r: f"{r['eps']:.2f}"),
            row("PE", lambda r: f"{r['pe_lo']:g}-{r['pe_hi']:g}x"),
        ]
    body = "".join([
        row("时间维度", lambda r: _esc(r["horizon"]), "center"),
        row("触发条件", lambda r: _esc(r["trigger"]), ""),
        *driver_rows,
        row("目标价", lambda r: f"{r['low']:.0f}-{r['high']:.0f} {_esc(cur)}"),
        row("较现价", lambda r: f'<span class="{"up" if r["upside"] >= 0 else "down"}">{r["upside"] * 100:+.1f}%</span>（中值{r["mid"]:.0f}）'),
    ])
    table = ('<div class="table-scroll"><table class="scenario-table"><thead>'
             + head + "</thead><tbody>" + body + "</tbody></table></div>")

    c, odds, disp = calc["central"], calc["odds"], calc["dispersion"]
    c_cls = "up" if c >= 0 else "down"
    c_sub = f'基础中值 {calc["rows"][1]["mid"] if len(calc["rows"])>1 else calc["rows"][0]["mid"]:.0f} ÷ 现价 {calc["price"]:g} − 1（{calc["horizon"]}）'
    if c < 0:
        c_sub += "；中枢为负 → 回避"
    if odds is None:
        o_val, o_cls, o_sub = "∞", "up", "悲观下限高于现价——最强不对称信号，仓位可上浮一档"
    else:
        o_val, o_cls = f"{odds:.2f}", "up" if odds >= 1.5 else "down"
        o_sub = "(基础中值−现价)÷(现价−悲观下限)；>1.5 为良好不对称"
    if disp < 0.40:
        d_cls, d_note = "up", "可预测"
    elif disp <= 0.90:
        d_cls, d_note = "mid", "中不确定"
    else:
        d_cls, d_note = "down", "高发散，仓位降一档"
    cards = (
        '<div class="metric-row">'
        f'<div class="metric-card"><div class="label">年化中枢期望收益</div>'
        f'<div class="value {c_cls}">{c * 100:+.1f}%</div><div class="sub">{c_sub}</div></div>'
        f'<div class="metric-card"><div class="label">赔率（上行/下行）</div>'
        f'<div class="value {o_cls}">{o_val}</div><div class="sub">{o_sub}</div></div>'
        f'<div class="metric-card"><div class="label">情景离散度</div>'
        f'<div class="value {d_cls}">{disp * 100:.1f}%</div>'
        f'<div class="sub">（乐观中值−悲观中值）÷ 现价；{d_note}</div></div>'
        '</div>')
    return table + cards


def build_peers_plot(fill: dict) -> str:
    """07 估值-质量散点图：直角坐标系精确点位（x=PE, y=ROE），3×3 分带背景，
    目标公司钢蓝大点 + 白色描边。输入 fill["peers_plot"]：
    {"points":[{"name":"宁德时代","roe":24.7,"pe":21.3,"target":true}, ...],
     "pe_bands":[15,25], "roe_bands":[8,15]}（bands 可省，数组形式亦可）。
    缺数据 → 返回空串（peers_html 里的 matrix-table 兜底）。"""
    pp = fill.get("peers_plot")
    if not pp:
        return ""
    if isinstance(pp, list):
        points, pe_bands, roe_bands = pp, [15.0, 25.0], [8.0, 15.0]
    else:
        points = pp.get("points") or []
        pe_bands = pp.get("pe_bands") or [15.0, 25.0]
        roe_bands = pp.get("roe_bands") or [8.0, 15.0]
    pts = []
    for p in points:
        roe, pe = _num(p.get("roe")), _num(p.get("pe"))
        if roe is None or pe is None:
            continue
        pts.append({"name": str(p.get("name") or "?"), "roe": roe, "pe": pe,
                    "target": bool(p.get("target"))})
    if len(pts) < 2:
        return ""

    W, H, L, R, T, B = 1000, 460, 64, 30, 34, 52
    pe_lo, pe_hi = _pad_domain(min([p["pe"] for p in pts] + pe_bands),
                               max([p["pe"] for p in pts] + pe_bands), 0.10)
    roe_lo, roe_hi = _pad_domain(min([p["roe"] for p in pts] + roe_bands),
                                 max([p["roe"] for p in pts] + roe_bands), 0.12, floor=0.0)
    X = _lin_map(pe_lo, pe_hi, L, W - R)
    Y = _lin_map(roe_lo, roe_hi, H - B, T)

    xb = [X(b) for b in pe_bands]
    yb = [Y(b) for b in roe_bands]  # roe_bands[0]=8 → 下方线 yb[0] 更大；[1]=15 → 上方线

    parts = [_svg_open(W, H, "估值-质量散点图")]
    # 最优/最差象限底色（高ROE·低PE = 左上绿；低ROE·高PE = 右下红）
    parts.append(f'<rect x="{L}" y="{T}" width="{xb[0] - L:.1f}" height="{yb[1] - T:.1f}" fill="{_C_GREEN}" fill-opacity="0.12"/>')
    parts.append(f'<rect x="{xb[1]:.1f}" y="{yb[0]:.1f}" width="{W - R - xb[1]:.1f}" height="{H - B - yb[0]:.1f}" fill="{_C_RED}" fill-opacity="0.12"/>')
    # 象限角标签
    parts.append(f'<text x="{L + 8}" y="{T + 16}" font-size="11" fill="{_C_LABEL}">高质量 · 低估值</text>')
    parts.append(f'<text x="{W - R - 8}" y="{T + 16}" text-anchor="end" font-size="11" fill="{_C_LABEL}">高质量 · 高估值</text>')
    parts.append(f'<text x="{L + 8}" y="{H - B - 8}" font-size="11" fill="{_C_LABEL}">低质量 · 低估值</text>')
    parts.append(f'<text x="{W - R - 8}" y="{H - B - 8}" text-anchor="end" font-size="11" fill="{_C_LABEL}">低质量 · 高估值</text>')
    # 分带虚线
    for bx in xb:
        parts.append(f'<line x1="{bx:.1f}" y1="{T}" x2="{bx:.1f}" y2="{H - B}" stroke="{_C_SAND_LT}" stroke-width="1" stroke-dasharray="4 4"/>')
    for by in yb:
        parts.append(f'<line x1="{L}" y1="{by:.1f}" x2="{W - R}" y2="{by:.1f}" stroke="{_C_SAND_LT}" stroke-width="1" stroke-dasharray="4 4"/>')
    # 坐标轴 + 刻度
    parts.append(f'<line x1="{L}" y1="{H - B}" x2="{W - R}" y2="{H - B}" stroke="{_C_AXIS}" stroke-width="1.2"/>')
    parts.append(f'<line x1="{L}" y1="{T}" x2="{L}" y2="{H - B}" stroke="{_C_AXIS}" stroke-width="1.2"/>')
    for v in _ticks(pe_lo, pe_hi):
        parts.append(f'<text x="{X(v):.1f}" y="{H - B + 18}" text-anchor="middle" font-size="11" fill="{_C_LABEL}">{_fmt(v)}x</text>')
    for v2 in _ticks(roe_lo, roe_hi):
        parts.append(f'<text x="{L - 8}" y="{Y(v2) + 4:.1f}" text-anchor="end" font-size="11" fill="{_C_LABEL}">{_fmt(v2)}%</text>')
    parts.append(f'<text x="{W - R}" y="{H - 8}" text-anchor="end" font-size="11" fill="{_C_LABEL}">PE(TTM)</text>')
    parts.append(f'<text x="{L}" y="{T - 12}" font-size="11" fill="{_C_LABEL}">ROE</text>')
    # 数据点（直接标注，免图例；可选 size 字段编码市值——面积 ∝ 市值，sqrt 换算半径；
    # 标签按候选位做简单碰撞避让，目标公司 上/右/下/左，同业 右/左/上/下）
    def _box(lx, ly, anchor, w, fs):
        x0 = lx - w / 2 if anchor == "middle" else (lx - w if anchor == "end" else lx)
        return (x0, ly - fs, x0 + w, ly + 4)

    def _overlap(b, boxes):
        return any(not (b[2] < p[0] or b[0] > p[2] or b[3] < p[1] or b[1] > p[3]) for p in boxes)

    def _pick_label(cands, fw, fs, boxes):
        """按偏好顺序取第一个「不越出 SVG 边界且不压已有标签」的位置；
        全都压标签时退回首个不越界位（v4.8 修复：右缘公司标签曾越界被裁）。"""
        in_bounds = [c for c in cands
                     if 8 <= _box(c[0], c[1], c[2], fw, fs)[0]
                     and _box(c[0], c[1], c[2], fw, fs)[2] <= W - 8]
        pool = in_bounds or cands
        for c in pool:
            if not _overlap(_box(c[0], c[1], c[2], fw, fs), boxes):
                return c
        return pool[0]

    placed = [  # 四个象限角标的近似盒，数据标签先让它们
        (L + 6, T + 4, L + 150, T + 20), (W - R - 156, T + 4, W - R - 6, T + 20),
        (L + 6, H - B - 20, L + 150, H - B - 4), (W - R - 156, H - B - 20, W - R - 6, H - B - 4),
    ]
    sizes = [sv for sv in (_num(p.get("size")) for p in pts) if sv]
    max_size = max(sizes) if sizes else None
    for p in pts:
        cx, cy = X(p["pe"]), Y(p["roe"])
        r = 6.0
        if max_size:
            sv = _num(p.get("size")) or 0.0
            r = max(5.0, min(12.0, 4 + 8 * math.sqrt(max(sv, 0.0) / max_size)))
        label = f'{p["name"]} {_fmt(p["roe"])}%/{_fmt(p["pe"])}x'
        if p["target"]:
            rr = r + 2
            parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{rr:.1f}" fill="{_C_BLUE}" stroke="{_C_PAPER}" stroke-width="2">'
                         f'<title>{_esc(label)}</title></circle>')
            # 近顶优先放下方，近右优先放左侧；其余放上方；再与已放置标签做碰撞避让
            cands = []
            if cy < T + 50:
                cands.append((cx, cy + rr + 16, "middle"))
            if cx > L + (W - L - R) * 0.75:
                cands.append((cx - rr - 10, cy + 4, "end"))
            cands += [(cx, cy - rr - 8, "middle"), (cx + rr + 10, cy + 4, "start"),
                      (cx - rr - 10, cy + 4, "end"), (cx, cy + rr + 16, "middle")]
            fs, fw = 12, _text_w(label, 12)
            lx, ly, anchor = _pick_label(cands, fw, fs, placed)
            placed.append(_box(lx, ly, anchor, fw, fs))
            parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" font-size="12" '
                         f'font-weight="700" fill="{_C_BLUE}">{_esc(label)}</text>')
        else:
            parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{_C_OLIVE}">'
                         f'<title>{_esc(label)}</title></circle>')
            cands = [(cx + r + 10, cy + 4, "start"), (cx - r - 10, cy + 4, "end"),
                     (cx, cy - r - 8, "middle"), (cx, cy + r + 16, "middle")]
            fs, fw = 12, _text_w(label, 12)
            lx, ly, anchor = _pick_label(cands, fw, fs, placed)
            placed.append(_box(lx, ly, anchor, fw, fs))
            parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" font-size="12" '
                         f'fill="{_C_STONE}">{_esc(label)}</text>')
    parts.append(_svg_close())
    size_note = '；点大小 ∝ 总市值（sqrt 缩放）' if max_size else ''
    parts.append('<span class="source">估值-质量散点图（脚本按 peers_plot 字段生成）：横轴 PE(TTM)、纵轴 ROE，'
                 '虚线为低/中/高分带；左上绿底=优质低估区，右下红底=低质高估区' + size_note + '；'
                 '目标公司与同业须同口径（A/H 股、IFRS/经调整），混排须在 peers_meta 注明</span>')
    return "".join(parts)


def build_score_bars(sc: dict) -> str:
    """06 质量分汇总·九维评分横条图：条长=维度得分（0-10 定域，跨报告可比），条色=徽章档，
    条端=得分，最右列=层内权重；按层分组（公司本质/未来预期），虚线=7.0 良好线。
    数据全部来自 compute_scores（adj_scores/weights，与汇总表同一份口径）。"""
    adj, weights, ls = sc.get("adj_scores") or {}, sc.get("weights") or {}, sc["layer_share"]
    if not adj:
        return ""
    W = 1000
    NL, BAR_A, BAR_B = 200, 210, 820  # 名称列右缘 / 条形起点（0 分） / 条形终点（10 分）
    WT_X = 965                        # 权重·加权列右缘
    T, ROW_H, BAR_H, GROUP_GAP = 34, 32, 18, 26
    H = T + 9 * ROW_H + GROUP_GAP + 36
    X = _lin_map(0, 10, BAR_A, BAR_B)
    badge_color = {"badge-green": _C_GREEN, "badge-orange": _C_ORANGE, "badge-red": _C_RED}

    parts = ['<span class="section-tag">评分分布</span>',
             _svg_open(W, H, "九维评分分布")]
    _vgrid_ticks(parts, X, _ticks(0, 10, 6), T - 8, H - 30, H - 14)
    gx7 = X(7.0)
    parts.append(f'<line x1="{gx7:.1f}" y1="{T - 8}" x2="{gx7:.1f}" y2="{H - 30}" stroke="{_C_GOOD_LINE}" stroke-width="1.2" stroke-dasharray="5 4"/>')
    parts.append(f'<text x="{gx7:.1f}" y="{T - 14}" text-anchor="middle" font-size="10.5" fill="{_C_LABEL}">良好线 7.0</text>')
    y = T
    for layer in ("L1", "L3"):
        dims = [d for d in DIMS if d[1] == layer]
        parts.append(f'<text x="0" y="{y - 8}" font-size="11" font-weight="600" fill="{_C_LABEL}">'
                     f'{LAYER_NAMES[layer]} · 占质量分 {ls[layer]:.0f}%</text>')
        for key, _l, name, _dw in dims:
            s = float(adj.get(key, 0))
            w = float(weights.get(key, 0))
            cy = y + 2
            color = badge_color[badge_class(s)]
            parts.append(f'<rect x="{BAR_A}" y="{cy}" width="{BAR_B - BAR_A}" height="{BAR_H}" rx="5" fill="{_C_TRACK}"/>')
            parts.append(f'<rect x="{BAR_A}" y="{cy}" width="{max((BAR_B - BAR_A) * s / 10.0, 3):.1f}" '
                         f'height="{BAR_H}" rx="5" fill="{color}"/>')
            parts.append(f'<text x="{NL - 10}" y="{cy + BAR_H / 2 + 4.5:.1f}" text-anchor="end" font-size="12" '
                         f'fill="{_C_INK}">{_esc(name)}</text>')
            parts.append(f'<text x="{BAR_A + max((BAR_B - BAR_A) * s / 10.0, 3) + 8:.1f}" y="{cy + BAR_H / 2 + 4.5:.1f}" '
                         f'font-size="12" font-weight="700" fill="{color}">{s:.1f} {_dim_verdict(s)}</text>')
            parts.append(f'<text x="{WT_X}" y="{cy + BAR_H / 2 + 4.5:.1f}" text-anchor="end" font-size="11" '
                         f'fill="{_C_LABEL}">{w:g}% · {s * w / 100:.2f}</text>')
            y += ROW_H
        y += GROUP_GAP
    parts.append(_svg_close())
    parts.append('<span class="source">评分分布（脚本按 scores/weights 生成）：条长=维度得分（0-10 定域），'
                 '条色=徽章档（≥7 绿 / 4-6.9 橙 / &lt;4 红），条端=得分与判词，右列=层内权重 · 加权得分，'
                 '虚线=7.0 良好线</span>')
    return "".join(parts)


def build_sensitivity_tornado(fill: dict) -> str:
    """02 关键利润驱动·敏感性龙卷风（fill["sensitivity"] 可选字段）：变量 ±10% 变动对归母净利
    影响幅度（%）的双向条，红=不利方向、绿=有利方向，排序=弹性大小（首行=第一变量）。
    sensitivity: [{"name":"矿产金售价（金价）","impact":20,"delta":"±10%","amount":"约±9-10亿元"}, ...]
    （impact 取绝对值；delta/amount 可选——填了即在变量名下展示「变动幅度 → 金额影响」，
    信息覆盖旧敏感性表，填了本字段 P0 就不必再手写敏感性表）。字段缺失 → 返回空串。"""
    items = []
    for s in fill.get("sensitivity") or []:
        imp = _num(s.get("impact"))
        name = str(s.get("name") or "").strip()
        if imp is None or not name:
            continue
        items.append({"name": name, "impact": abs(imp),
                      "delta": str(s.get("delta") or "").strip(),
                      "amount": str(s.get("amount") or "").strip()})
    if not items:
        return ""
    items.sort(key=lambda r: -r["impact"])
    has_detail = any(it["delta"] or it["amount"] for it in items)
    W = 1000
    # v4.8.2：变量名列宽度自适应——先组文本行并用 _text_w 量宽，超 388px 的长名折两行；
    # NL/X0/HALF 随最长行宽动态取值，长变量名不再越出画布左缘被裁
    rows = [[[it["name"] + ("（第一变量）" if i == 0 else "")],
             " → ".join(x for x in (it["delta"], it["amount"]) if x)] for i, it in enumerate(items)]
    max_w = max([_text_w(r[0][0], 13.0) for r in rows]
                + [_text_w(r[1], 11.0) for r in rows if r[1]])
    if max_w > 388:
        rows = [[_wrap_label(nm, 388, 13.0), det] for [nm], det in rows]
        max_w = max([_text_w(t, 13.0) for r in rows for t in r[0]]
                    + [_text_w(r[1], 11.0) for r in rows if r[1]])
    NL = min(max(max_w + 12, 230), 400)      # 变量名列右缘
    if NL <= 230:
        X0, HALF = 600, 300                  # 短名布局与 v4.8.1 一致（W 与全站图表统一 1000）
    else:
        X0 = min(NL + 370, 700)              # 中轴右移给名称让位
        HALF = min(300, X0 - NL - 63, 950 - X0)  # 条幅收缩，两侧 ±xx% 标签不出界
    any_wrap = any(len(r[0]) > 1 for r in rows)
    T, BAR_H = 30, 17
    ROW_H = (58 if any_wrap else 44) if has_detail else (48 if any_wrap else 36)
    H = T + len(items) * ROW_H + 38
    imax = items[0]["impact"]
    k = HALF / imax if imax else 1.0
    parts = ['<span class="section-tag">敏感性排序</span>',
             _svg_open(W, H, "敏感性龙卷风")]
    axis_y = T + len(items) * ROW_H + 4
    for v in _ticks(0, imax, 4):
        for sign in (-1, 1):
            gx = X0 + sign * v * k
            parts.append(f'<line x1="{gx:.1f}" y1="{T - 6}" x2="{gx:.1f}" y2="{axis_y}" stroke="{_C_GRID}" stroke-width="1"/>')
            lbl = f'{"+" if sign > 0 else "−"}{_fmt(v)}%' if v > 0 else "0"
            if v > 0 or sign > 0:
                parts.append(f'<text x="{gx:.1f}" y="{axis_y + 16}" text-anchor="middle" font-size="11" fill="{_C_LABEL}">{lbl}</text>')
    parts.append(f'<line x1="{X0}" y1="{T - 6}" x2="{X0}" y2="{axis_y}" stroke="{_C_SAND}" stroke-width="1.2"/>')
    for i, it in enumerate(items):
        cy = T + i * ROW_H + (ROW_H - BAR_H) / 2
        w = it["impact"] * k
        first = (i == 0)
        nm_lines, detail = rows[i]
        # 名称/detail 行组：相对条心垂直居中堆叠（行距 15），长名折行后同样居中
        lines = [(t, "13", 700 if first else 400, _C_BLACK if first else _C_INK) for t in nm_lines]
        if detail:
            lines.append((detail, "11", 400, _C_LABEL))
        y0 = cy + BAR_H / 2 + 4.5 - (len(lines) - 1) * 15 / 2
        for li, (t, fs, fw, fc) in enumerate(lines):
            parts.append(f'<text x="{NL:.1f}" y="{y0 + li * 15:.1f}" text-anchor="end" font-size="{fs}" '
                         f'font-weight="{fw}" fill="{fc}">{_esc(t)}</text>')
        parts.append(f'<rect x="{X0 - w:.1f}" y="{cy:.1f}" width="{w:.1f}" height="{BAR_H}" fill="{_C_RED}"/>')
        parts.append(f'<rect x="{X0:.1f}" y="{cy:.1f}" width="{w:.1f}" height="{BAR_H}" fill="{_C_GREEN}"/>')
        parts.append(f'<text x="{X0 - w - 8:.1f}" y="{cy + BAR_H / 2 + 4.5:.1f}" text-anchor="end" font-size="12" '
                     f'font-weight="700" fill="{_C_RED}">−{_fmt(it["impact"])}%</text>')
        parts.append(f'<text x="{X0 + w + 8:.1f}" y="{cy + BAR_H / 2 + 4.5:.1f}" font-size="12" '
                     f'font-weight="700" fill="{_C_GREEN}">+{_fmt(it["impact"])}%</text>')
    parts.append(_svg_close())
    parts.append('<span class="source">敏感性龙卷风（脚本按 sensitivity 字段生成）：条长=变量变动对归母净利的'
                 '影响幅度（估算绝对值），红=不利方向、绿=有利方向，左列=变动幅度与金额影响，'
                 '排序=弹性大小（首行=第一变量）；填了本字段，P0 不必再写敏感性表</span>')
    return "".join(parts)


def build_pe_band(fill: dict) -> str:
    """07→10 估值·PE 历史带（fill["pe_history"] 可选字段 + valuation_inputs 的 pe_band/pe_ttm）：
    横向子弹图——浅带=历史 PE 区间，钢蓝段=合理带，黑刻=当前值，灰虚刻=关键时点。
    v4.8.1：显示域自适应截断（hist_hi 远超决策值集合×1.5 时截到该倍数，右缘「峰值→」标注），
    关键时点标签双层交错排布。
    v4.7.1 起图挪至 10 周期规律章（手写时段拆解前，概览→明细）。
    pe_history: {"hist_lo":13.7, "hist_hi":83.2, "label":"近5年",
                 "milestones":[{"label":"2021H1","pe":46.9}, …]}（label 可选；milestones 可选，
                 建议 3-6 个关键时点：峰值/谷值/典型时段，与时段拆解表同源取数）；
    字段缺失或与 valuation_inputs 不齐 → 返回空串（可选增强，静默跳过）。"""
    ph = fill.get("pe_history") or {}
    vi = fill.get("valuation_inputs") or {}
    hist_lo, hist_hi = _num(ph.get("hist_lo")), _num(ph.get("hist_hi"))
    cur = _num(vi.get("pe_ttm"))
    band = vi.get("pe_band") or []
    band_lo = _num(band[0]) if len(band) >= 1 else None
    band_hi = _num(band[1]) if len(band) >= 2 else None
    if None in (hist_lo, hist_hi, cur, band_lo, band_hi) or hist_hi <= hist_lo or band_hi < band_lo:
        return ""
    # 分位区（v4.8，可选 pe_history.p25/p75，em_fetch E1 分位带直接回填）：带内深沙段
    p25, p75 = _num(ph.get("p25")), _num(ph.get("p75"))
    iq_ok = p25 is not None and p75 is not None and hist_lo <= p25 < p75 <= hist_hi
    # 关键时点先解析（v4.8.1：显示域自适应要用其上限）
    ms_items = []
    for ms in ph.get("milestones") or []:
        mv = _num(ms.get("pe"))
        mlbl = str(ms.get("label") or "").strip()
        if mv is None or not mlbl:
            continue
        ms_items.append((mv, mlbl))
    # 显示域自适应截断（v4.8.1）：hist_hi 远超决策值集合（合理带/当前值/关键时点）×1.5 时，
    # 线性全域会把决策区挤进左侧角落——显示域截到决策值集合×1.5，溢出峰值在右缘截断标注，
    # 全量区间仍在带上方标签文本里给出（数据不丢）
    ess_hi = max([band_hi, cur] + [mv for mv, _ in ms_items])
    spike = hist_hi > ess_hi * 1.5
    disp_hi = ess_hi * 1.5 if spike else hist_hi
    lo_d, hi_d = _pad_domain(min(hist_lo, band_lo, cur), max(disp_hi, band_hi, cur), 0.04, floor=0.0)
    W, H, L, R = 1000, 196, 64, 64
    X = _lin_map(lo_d, hi_d, L, W - R)
    cy, BH = 100, 30
    mlabel = str(vi.get("metric_label") or "PE(TTM)")
    plabel = str(ph.get("label") or "历史")
    parts = [f'<span class="section-tag">{_esc(mlabel)} 历史带</span>',
             _svg_open(W, H, f"{_esc(mlabel)}历史带")]
    _vgrid_ticks(parts, X, _ticks(lo_d, hi_d, 6), 38, cy + BH + 10, cy + BH + 26, "x")
    parts.append(f'<line x1="{L}" y1="{cy + BH + 10}" x2="{W - R}" y2="{cy + BH + 10}" stroke="{_C_AXIS}" stroke-width="1.2"/>')
    # 历史区间浅带 + 带标签（v4.8.1：spike 时右端为截断面，虚线封口 + 峰值标注）
    xh_lo, xh_hi = X(hist_lo), X(min(hist_hi, hi_d))
    parts.append(f'<rect x="{xh_lo:.1f}" y="{cy}" width="{xh_hi - xh_lo:.1f}" height="{BH}" rx="8" '
                 f'fill="{_C_TRACK}" stroke="{_C_AXIS}"/>')
    # P25–P75 分位区（深沙段，v4.8；v4.8.1 起随显示域截断，截断深度超过 p25 时宽度归零不画）
    if iq_ok:
        iq_w = max(min(X(p75), xh_hi) - X(p25), 0)
        if iq_w >= 2:
            parts.append(f'<rect x="{X(p25):.1f}" y="{cy}" width="{iq_w:.1f}" height="{BH}" '
                         f'fill="{_C_SAND_LT}"/>')
    if spike:
        parts.append(f'<line x1="{xh_hi:.1f}" y1="{cy}" x2="{xh_hi:.1f}" y2="{cy + BH}" '
                     f'stroke="{_C_SAND}" stroke-width="1.2" stroke-dasharray="3 3"/>')
        parts.append(f'<text x="{xh_hi - 8:.1f}" y="{cy + BH / 2 + 4:.1f}" text-anchor="end" '
                     f'font-size="11" font-weight="700" fill="{_C_LABEL}">峰值 {_fmt(hist_hi)}x →</text>')
    iq_note = f'（一半时间落在 {_fmt(p25)}–{_fmt(p75)}x）' if iq_ok else ''
    parts.append(f'<text x="{xh_lo:.1f}" y="{cy - 40}" font-size="11" fill="{_C_LABEL}">'
                 f'{_esc(plabel)} {_esc(mlabel)} 区间 {_fmt(hist_lo)}–{_fmt(hist_hi)}x{iq_note}</text>')
    # 合理带（钢蓝实心段；标签放得下就带内白字，否则带下灰字）
    xb_lo, xb_hi = X(band_lo), X(band_hi)
    band_label = f'合理带 {_fmt(band_lo)}–{_fmt(band_hi)}x'
    parts.append(f'<rect x="{xb_lo:.1f}" y="{cy}" width="{max(xb_hi - xb_lo, 2):.1f}" height="{BH}" rx="8" fill="{_C_BLUE}"/>')
    if _text_w(band_label, 11) + 14 <= xb_hi - xb_lo:
        parts.append(f'<text x="{(xb_lo + xb_hi) / 2:.1f}" y="{cy + BH / 2 + 4:.1f}" text-anchor="middle" '
                     f'font-size="11" font-weight="700" fill="{_C_PAPER}">{band_label}</text>')
    else:
        parts.append(f'<text x="{(xb_lo + xb_hi) / 2:.1f}" y="{cy + BH + 40}" text-anchor="middle" '
                     f'font-size="11" fill="{_C_BLUE}">{band_label}</text>')
    # 当前值黑刻 + 标签（近边缘改对齐）
    cxp = X(cur)
    parts.append(f'<line x1="{cxp:.1f}" y1="{cy - 12}" x2="{cxp:.1f}" y2="{cy + BH + 12}" stroke="{_C_BLACK}" stroke-width="3"/>')
    parts.append(f'<circle cx="{cxp:.1f}" cy="{cy + BH / 2}" r="5" fill="{_C_BLACK}"/>')
    cur_label = f'当前 {_fmt(cur)}x'
    anchor, tx = _anchor_fit(cxp, _text_w(cur_label, 12), L, W - R, 4)
    parts.append(f'<text x="{tx:.1f}" y="{cy - 20}" text-anchor="{anchor}" font-size="12" '
                 f'font-weight="700" fill="{_C_BLACK}">{cur_label}</text>')
    # 关键时点标注（v4.7.1 milestones 可选）：灰虚刻 + 带上方标签
    # v4.8.1：标签改双层交错排布（按 pe 升序奇偶分层），pe 过近时不再互叠
    for li, (mv, mlbl) in enumerate([m for m in sorted(ms_items) if lo_d <= m[0] <= hi_d]):
        mx = X(mv)
        parts.append(f'<line x1="{mx:.1f}" y1="{cy - 6:.1f}" x2="{mx:.1f}" y2="{cy + BH + 6:.1f}" '
                     f'stroke="{_C_LABEL}" stroke-width="1.2" stroke-dasharray="3 3"/>')
        mtext = f'{mlbl} {_fmt(mv)}x'
        mw = _text_w(mtext, 10.5)
        ma, mtx = _anchor_clamp(mx, mw, 4, W - 4)
        ly = cy - 58 if li % 2 == 0 else cy - 76
        parts.append(f'<text x="{mtx:.1f}" y="{ly}" text-anchor="{ma}" font-size="10.5" '
                     f'fill="{_C_STONE}">{_esc(mtext)}</text>')
    parts.append(_svg_close())
    parts.append(f'<span class="source">{_esc(mlabel)} 历史带（脚本按 pe_history + valuation_inputs 生成）：'
                 f'浅带={_esc(plabel)}区间，钢蓝段=合理带，黑刻=当前值，灰虚刻=关键时点 PE；三者同一口径'
                 + ('；深沙段=P25–P75 分位区（历史上一半时间的 PE 落点，em_fetch E1 分位带回填）' if iq_ok else '')
                 + ('；右缘「峰值→」=区间上沿超出显示域的截断标注（全量见带上方文字）' if spike else '') + '</span>')
    return "".join(parts)


def build_segments_plot(fill: dict) -> str:
    """03 公司本质·业务构成横条图（fill["segments"] 可选字段，锚点 <!--SEGMENTS--> 挂 3.1）：
    v4.8.2 改版——横条=收入占比（0-100% 定域，首行钢蓝=第一大业务、其余暖灰），
    钢蓝圆点=毛利率（与占比同一 % 轴，无需副轴），右列=毛利率数值；
    左列分部名（宽度自适应、超长折两行），条下=收入/毛利额小字，条端=占比；
    画布高度随行数自适应（取代 v4.8.1 竖柱版固定 H=360 与柱下单行名称——长名挤压与空旷问题）。
    分部净利润无公开披露（tushare/东财/妙想均只到毛利）——利润口径一律为毛利，图注明示。
    segments: {"period":"2025年报","by":"按产品",
               "items":[{"name":"烯烃产品","revenue":156.2,"rev_pct":48.1,
                         "gross_margin":36.4,"gross_profit":56.8,"gp_pct":62.0}, ...]}
    （金额单位=亿元；rev_pct/gross_margin/gp_pct 为百分数；name+rev_pct 必填，其余可省。
    有效条目 <2 → 返回空串，静默跳过）"""
    seg = fill.get("segments") or {}
    items = []
    for it in seg.get("items") or []:
        name = str(it.get("name") or "").strip()
        rp = _num(it.get("rev_pct"))
        if not name or rp is None:
            continue
        items.append({"name": name, "rev_pct": rp,
                      "revenue": _num(it.get("revenue")),
                      "gross_margin": _num(it.get("gross_margin")),
                      "gross_profit": _num(it.get("gross_profit")),
                      "gp_pct": _num(it.get("gp_pct"))})
    if len(items) < 2:
        return ""
    items.sort(key=lambda r: -r["rev_pct"])  # 第一大业务居上

    W = 1000
    name_lines = [_wrap_label(it["name"], 200, 12.0) for it in items]
    NL = min(max(_text_w(t, 12.0) for ls in name_lines for t in ls) + 10, 220)   # 名称列宽
    ML = 16                           # 名称列左缘
    X0 = ML + NL + 12                 # 横条区左缘（% 轴零点）
    XR = W - 16 - 56                  # % 轴右缘（100% 处）；右侧留 56px 毛利率数值列
    X = _lin_map(0, 100, X0, XR)
    has_gm = any(it["gross_margin"] is not None for it in items)
    period = str(seg.get("period") or "").strip()
    by = str(seg.get("by") or "").strip()
    tag = "业务构成" + (f'（{_esc(period)}{"·" + _esc(by) if by else ""}）' if period or by else "")
    BAR_H, T = 16, 58                 # 条高 / 首行顶（图例行 18 + 刻度行 40）
    row_hs = [60 if len(ls) > 1 else 46 for ls in name_lines]
    H = T + sum(row_hs) + 30
    parts = [f'<span class="section-tag">{tag}</span>',
             _svg_open(W, H, "业务构成")]
    # 图例（左上）
    parts.append(f'<rect x="{ML}" y="8" width="14" height="10" rx="3" fill="{_C_SAND}"/>')
    parts.append(f'<text x="{ML + 20}" y="17" font-size="11" fill="{_C_STONE}">收入占比</text>')
    if has_gm:
        lx2 = ML + 20 + _text_w("收入占比", 11) + 24
        parts.append(f'<circle cx="{lx2 + 5:.0f}" cy="13" r="4.5" fill="{_C_BLUE}"/>')
        parts.append(f'<text x="{lx2 + 14:.0f}" y="17" font-size="11" fill="{_C_BLUE}">毛利率（同一 % 轴）</text>')
    # % 轴网格（0-100 定域）+ 顶部刻度 + 右列「毛利率」列头
    _vgrid_ticks(parts, X, _ticks(0, 100, 5), T - 14, H - 24, T - 22, "%")
    if has_gm:
        parts.append(f'<text x="{W - 16}" y="{T - 22}" text-anchor="end" font-size="11" '
                     f'font-weight="600" fill="{_C_BLUE}">毛利率</text>')
    parts.append(f'<line x1="{X0:.1f}" y1="{H - 24}" x2="{XR:.1f}" y2="{H - 24}" stroke="{_C_AXIS}" stroke-width="1.2"/>')
    # 逐行：名称 / 占比条 / 条端或条内占比 / 条下收入·毛利小字 / 毛利率圆点 + 右列数值
    ry = T
    for i, it in enumerate(items):
        rh = row_hs[i]
        bc_y, bc_c = ry + 4, ry + 4 + BAR_H / 2    # 条顶 / 条心 y
        nls = name_lines[i]
        ny0 = bc_c + 4.5 - (len(nls) - 1) * 14 / 2
        for li, t in enumerate(nls):
            parts.append(f'<text x="{ML + NL:.1f}" y="{ny0 + li * 14:.1f}" text-anchor="end" font-size="12" '
                         f'font-weight="{700 if i == 0 else 400}" fill="{_C_BLACK if i == 0 else _C_INK}">'
                         f'{_esc(t)}</text>')
        bw = max(X(it["rev_pct"]) - X0, 2)
        color = _C_BLUE if i == 0 else _C_SAND
        parts.append(f'<rect x="{X0:.1f}" y="{bc_y:.1f}" width="{bw:.1f}" height="{BAR_H}" rx="5" fill="{color}"/>')
        pct_label = f'{_fmt(it["rev_pct"])}%'
        if bw >= _text_w(pct_label, 12) + 16:    # 条够长 → 条内右端
            parts.append(f'<text x="{X0 + bw - 8:.1f}" y="{bc_c + 4.5:.1f}" text-anchor="end" font-size="12" '
                         f'font-weight="700" fill="{_C_PAPER if i == 0 else _C_INK}">{pct_label}</text>')
        else:
            parts.append(f'<text x="{X0 + bw + 8:.1f}" y="{bc_c + 4.5:.1f}" font-size="12" '
                         f'font-weight="700" fill="{color}">{pct_label}</text>')
        subs = []
        if it["revenue"] is not None:
            subs.append(f'收入 {_fmt_amt(it["revenue"])}亿')
        if it["gross_profit"] is not None:
            g = f'毛利 {_fmt_amt(it["gross_profit"])}亿'
            if it["gp_pct"] is not None:
                g += f'（占 {_fmt(it["gp_pct"])}%）'
            subs.append(g)
        if subs:
            parts.append(f'<text x="{X0:.1f}" y="{ry + rh - 10:.1f}" font-size="10.5" '
                         f'fill="{_C_LABEL}">{_esc(" ｜ ".join(subs))}</text>')
        # 毛利率圆点（同一 % 轴；负值按 0 截底绘制，右列数值仍示真实值）
        if it["gross_margin"] is not None:
            parts.append(f'<circle cx="{X(max(it["gross_margin"], 0)):.1f}" cy="{bc_c:.1f}" r="4.5" '
                         f'fill="{_C_BLUE}" stroke="{_C_PAPER}" stroke-width="1.5"/>')
            parts.append(f'<text x="{W - 16}" y="{bc_c + 4.5:.1f}" text-anchor="end" font-size="12" '
                         f'font-weight="700" fill="{_C_BLUE}">{_fmt(it["gross_margin"])}%</text>')
        ry += rh
    parts.append(_svg_close())
    parts.append('<span class="source">业务构成（脚本按 segments 字段生成，数据来自 em_fetch E6/年报）：'
                 '横条=收入占比（0-100% 定域），首行=第一大业务，钢蓝圆点=毛利率（同一 % 轴），右列=毛利率数值；'
                 '条下=收入/毛利额；<strong>利润口径为毛利——分部净利润无公开披露</strong></span>')
    return "".join(parts)


def build_chain_plot(fill: dict) -> str:
    """03 公司本质·产业链位置图（fill["industry_chain"] 可选字段，锚点 <!--CHAIN--> 挂 3.2）：
    三栏流向——左=上游行业（供给端），中=本公司（钢蓝卡），右=下游行业（需求端），
    贝塞尔曲线=供需关系（v4.8.1 起直线改曲线）；self_note 移到公司卡正下方居中展示，
    不再塞进卡内（长注不再溢出）。只列行业不列企业（上下游玩家众多，列企业反而以偏概全）。
    industry_chain: {"upstream":["煤炭开采","电力"], "self_note":"煤制烯烃一体化",
                     "downstream":["聚烯烃加工","包装","家电"]}
    （上游/下游各 1-6 个、各至少 1 个，否则返回空串静默跳过；单个名称建议 ≤10 字）"""
    ch = fill.get("industry_chain") or {}
    ups = [str(x).strip() for x in ch.get("upstream") or [] if str(x).strip()][:6]
    downs = [str(x).strip() for x in ch.get("downstream") or [] if str(x).strip()][:6]
    if not ups or not downs:
        return ""
    company = str(fill.get("company") or "本公司")
    note = str(ch.get("self_note") or "").strip()

    W = 1000
    COL_W = 250                      # 上下游栏宽
    LX, RX = 30, W - 30 - COL_W      # 左栏 x / 右栏 x
    MX0, MX1 = 390, 610              # 本公司卡横向范围
    BOX_H, GAP, TOP = 34, 14, 46
    rows = max(len(ups), len(downs))
    cy_mid = TOP + rows * (BOX_H + GAP) / 2   # 公司卡纵向中心
    CARD_H = 64
    H = TOP + rows * (BOX_H + GAP) + 16
    if note:   # 卡在纵向中段，note 移到卡下方，行数少时画布需要加高
        H = max(H, int(cy_mid + CARD_H / 2 + 34))

    parts = ['<span class="section-tag">产业链位置</span>',
             _svg_open(W, H, "产业链位置")]
    # 栏目标题
    parts.append(f'<text x="{LX + COL_W / 2:.0f}" y="26" text-anchor="middle" font-size="12" '
                 f'font-weight="600" fill="{_C_LABEL}">上游 · 供给端</text>')
    parts.append(f'<text x="{(MX0 + MX1) / 2:.0f}" y="26" text-anchor="middle" font-size="12" '
                 f'font-weight="600" fill="{_C_LABEL}">本公司</text>')
    parts.append(f'<text x="{RX + COL_W / 2:.0f}" y="26" text-anchor="middle" font-size="12" '
                 f'font-weight="600" fill="{_C_LABEL}">下游 · 需求端</text>')

    def _col(items, x, links_to_left):
        for i, name in enumerate(items):
            by = TOP + i * (BOX_H + GAP)
            parts.append(f'<rect x="{x}" y="{by}" width="{COL_W}" height="{BOX_H}" rx="8" '
                         f'fill="{_C_TRACK}" stroke="{_C_AXIS}"/>')
            parts.append(f'<text x="{x + COL_W / 2:.0f}" y="{by + BOX_H / 2 + 4.5:.0f}" '
                         f'text-anchor="middle" font-size="12" fill="{_C_INK}">{_esc(name)}</text>')
            # 供需连线（贝塞尔曲线，水平进出）：上游 → 公司卡左缘；公司卡右缘 → 下游
            sy = by + BOX_H / 2
            if links_to_left:
                bend = (MX0 - (x + COL_W)) / 2
                parts.append(f'<path d="M{x + COL_W},{sy} C{x + COL_W + bend:.1f},{sy} '
                             f'{MX0 - bend:.1f},{cy_mid:.1f} {MX0},{cy_mid:.1f}" '
                             f'stroke="{_C_SAND}" stroke-width="1.2" fill="none"/>')
            else:
                bend = (x - MX1) / 2
                parts.append(f'<path d="M{MX1},{cy_mid:.1f} C{MX1 + bend:.1f},{cy_mid:.1f} '
                             f'{x - bend:.1f},{sy} {x},{sy}" '
                             f'stroke="{_C_SAND}" stroke-width="1.2" fill="none"/>')

    _col(ups, LX, True)
    _col(downs, RX, False)
    # 本公司卡（钢蓝实心，单行公司名；定位注移到卡正下方）
    parts.append(f'<rect x="{MX0}" y="{cy_mid - CARD_H / 2:.1f}" width="{MX1 - MX0}" height="{CARD_H}" '
                 f'rx="10" fill="{_C_BLUE}"/>')
    parts.append(f'<text x="{(MX0 + MX1) / 2:.0f}" y="{cy_mid + 4.5:.1f}" '
                 f'text-anchor="middle" font-size="13" font-weight="700" fill="{_C_PAPER}">'
                 f'{_esc(company)}</text>')
    if note:
        parts.append(f'<text x="{(MX0 + MX1) / 2:.0f}" y="{cy_mid + CARD_H / 2 + 18:.1f}" text-anchor="middle" '
                     f'font-size="11" fill="{_C_LABEL}">{_esc(note)}</text>')
    parts.append(_svg_close())
    parts.append('<span class="source">产业链位置（脚本按 industry_chain 字段生成，内容来自年报/定性检索）：'
                 '左=上游行业，右=下游行业，曲线=供需关系，卡下=本公司定位注；只列行业不列企业，不代表全部玩家</span>')
    return "".join(parts)


def _inject_l1_charts(l1_html: str, fill: dict) -> str:
    """3.1/3.2 图锚点注入（v4.8）：l1_html 里的 <!--SEGMENTS--> / <!--CHAIN--> 注释替换为
    对应脚本图；锚点缺失但字段已填 → 图追加第 3 章末尾 + 告警；字段未填 → 锚点静默清除。
    （与第 10 章 {{PE_BAND_HTML}} 裸占位符同款思路：避开模板条件块不支持嵌套的限制，
    又让模型保留图在维度块内的位置控制权。）"""
    for anchor, html, field in (("<!--SEGMENTS-->", build_segments_plot(fill), "segments"),
                                ("<!--CHAIN-->", build_chain_plot(fill), "industry_chain")):
        if anchor in l1_html:
            l1_html = l1_html.replace(anchor, html)
        elif html:
            l1_html += "\n" + html
            print(f"⚠️ l1_html 缺 {anchor} 锚点：{field} 图已追加到第 3 章末尾"
                  f"（建议把锚点放到对应维度块内，3.1=业务构成 / 3.2=产业链位置）", file=sys.stderr)
    return l1_html


def build_price_history(fill: dict) -> str:
    """10 周期规律·股价/PE 历史发丝图（fill["price_history"] 可选字段，与 PE 历史带同源 E2 月线）：
    左轴=月收盘价（深灰发丝 + 浅沙色面积填充），右轴=PE(TTM)（钢蓝发丝，过半点缺 PE 则只画股价），
    横轴按年 tick（带竖向浅网格线），末端最新值标注带药丸底色。概览→明细：垫在历史带之后、手写时段拆解之前。
    price_history: {"label":"近5年", "series":[{"m":"2021-09","close":12.3,"pe":15.2}, ...]}
    （旧→新，月频；有效点 <12 → 返回空串，数据太短画不出形态，静默跳过）"""
    ph = fill.get("price_history") or {}
    pts = []
    for p in ph.get("series") or []:
        m = str(p.get("m") or "").strip()
        c = _num(p.get("close"))
        if not m or c is None:
            continue
        pts.append({"m": m, "close": c, "pe": _num(p.get("pe"))})
    if len(pts) < 12:
        return ""
    n = len(pts)
    has_pe = sum(1 for p in pts if p["pe"] is not None) >= max(12, n // 2)

    W, H, L, R, T, B = 1000, 240, 56, 64, 34, 36
    X = lambda i: L + i / (n - 1) * (W - L - R)
    closes = [p["close"] for p in pts]
    lo_c, hi_c = _pad_domain(min(closes), max(closes), 0.08, floor=0.0)
    Yc = _lin_map(lo_c, hi_c, H - B, T)
    if has_pe:
        pes = [p["pe"] for p in pts if p["pe"] is not None]
        lo_p, hi_p = _pad_domain(min(pes), max(pes), 0.08, floor=0.0)
        Yp = _lin_map(lo_p, hi_p, H - B, T)

    label = str(ph.get("label") or "").strip()
    cur = str(fill.get("currency") or "元")
    # PE 序列同源 E2 月线（价格×股本÷TTM净利），恒为 PE(TTM) 口径，不随 metric_label 换标签
    parts = [f'<span class="section-tag">股价与 PE(TTM) 历史{("（" + _esc(label) + "）") if label else ""}</span>',
             _svg_open(W, H, "股价与PE历史走势")]
    # 图例（左上）
    parts.append(f'<line x1="{L}" y1="{T - 12}" x2="{L + 26}" y2="{T - 12}" stroke="{_C_INK}" stroke-width="1.6"/>')
    parts.append(f'<text x="{L + 32}" y="{T - 8}" font-size="11" fill="{_C_INK}">股价（左轴，{_esc(cur)}）</text>')
    if has_pe:
        lx2 = L + 32 + _text_w(f"股价（左轴，{cur}）", 11) + 24
        parts.append(f'<line x1="{lx2:.0f}" y1="{T - 12}" x2="{lx2 + 26:.0f}" y2="{T - 12}" stroke="{_C_BLUE}" stroke-width="1.6"/>')
        parts.append(f'<text x="{lx2 + 32:.0f}" y="{T - 8}" font-size="11" fill="{_C_BLUE}">PE(TTM)（右轴）</text>')
    # 左轴（股价）网格与刻度
    for v in _ticks(lo_c, hi_c, 5):
        gy = Yc(v)
        parts.append(f'<line x1="{L}" y1="{gy:.1f}" x2="{W - R}" y2="{gy:.1f}" stroke="{_C_GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{L - 8}" y="{gy + 4:.1f}" text-anchor="end" font-size="11" fill="{_C_LABEL}">{_fmt(v)}</text>')
    # 右轴（PE）刻度
    if has_pe:
        for v in _ticks(lo_p, hi_p, 5):
            gy = Yp(v)
            parts.append(f'<text x="{W - R + 8}" y="{gy + 4:.1f}" font-size="11" fill="{_C_BLUE}">{_fmt(v)}</text>')
    # 横轴：按年 tick（每年首个点；v4.8.2 加竖向浅网格线）
    seen_years = set()
    for i, p in enumerate(pts):
        y = p["m"][:4]
        if y.isdigit() and y not in seen_years:
            seen_years.add(y)
            parts.append(f'<line x1="{X(i):.1f}" y1="{T}" x2="{X(i):.1f}" y2="{H - B}" stroke="{_C_YEAR_GRID}" stroke-width="1"/>')
            parts.append(f'<text x="{X(i):.1f}" y="{H - 10}" text-anchor="middle" font-size="11" '
                         f'fill="{_C_LABEL}">{y}</text>')
    parts.append(f'<line x1="{L}" y1="{H - B}" x2="{W - R}" y2="{H - B}" stroke="{_C_AXIS}" stroke-width="1.2"/>')
    # 股价发丝线（v4.8.2：线下浅沙色面积填充，发丝 1.3→1.8）
    path = "M" + " L".join(f"{X(i):.1f},{Yc(p['close']):.1f}" for i, p in enumerate(pts))
    parts.append(f'<path d="{path} L{X(n - 1):.1f},{H - B} L{L},{H - B} Z" fill="{_C_TRACK}" stroke="none"/>')
    parts.append(f'<path d="{path}" fill="none" stroke="{_C_INK}" stroke-width="1.8"/>')
    # PE 发丝线（允许中间缺值：缺值处分段）
    if has_pe:
        run = []
        for i, p in enumerate(pts + [{"pe": None}]):  # 哨兵收尾
            if p["pe"] is not None:
                run.append(i)
            elif run:
                d = "M" + " L".join(f"{X(j):.1f},{Yp(pts[j]['pe']):.1f}" for j in run)
                parts.append(f'<path d="{d}" fill="none" stroke="{_C_BLUE}" stroke-width="1.8"/>')
                run = []
    # 末端点与最新值标注（v4.8.2：药丸底色，避免压线难读）
    def _pill(tx, ty, txt, fc):
        tw = _text_w(txt, 11)
        parts.append(f'<rect x="{tx - tw - 10:.1f}" y="{ty - 12:.1f}" width="{tw + 14:.1f}" height="16" '
                     f'rx="8" fill="{_C_PAPER}" stroke="{_C_AXIS}"/>')
        parts.append(f'<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="end" font-size="11" '
                     f'font-weight="700" fill="{fc}">{txt}</text>')
    parts.append(f'<circle cx="{X(n - 1):.1f}" cy="{Yc(closes[-1]):.1f}" r="3" fill="{_C_INK}"/>')
    _pill(X(n - 1) - 6, Yc(closes[-1]) - 8, _fmt(closes[-1]), _C_INK)
    if has_pe:
        last_pe = next((p["pe"] for p in reversed(pts) if p["pe"] is not None), None)
        if last_pe is not None:
            _pill(X(n - 1) - 6, Yp(last_pe) + 16, f'{_fmt(last_pe)}x', _C_BLUE)
    parts.append(_svg_close())
    parts.append('<span class="source">股价/PE 历史走势（脚本按 price_history 字段生成，与上方历史带同源 E2 月线）：'
                 '深灰=月收盘价（左轴），钢蓝=PE(TTM)（右轴）；双轴各自定标，读交叉不读绝对高度；'
                 '判读：价涨 PE 平=业绩驱动，价平 PE 跳=估值重定价（财报日 TTM 净利跳变所致）</span>')
    return "".join(parts)


def build_holders_plot(fill: dict) -> str:
    """11 仓位与时机决策·股东户数趋势（fill["holders"] 可选字段，E4 数据回填）：
    柱状图，暖灰柱=历史期、钢蓝柱=最新期；柱上=户数（千位符），柱下=截止日与环比——
    环比按筹码语义着色：户数增=筹码分散=红，户数减=集中=绿。
    holders: [{"date":"2025-03-31","num":188153,"chg":5.2}, ...]（旧→新，chg 为环比%，可省；
    有效点 <3 → 返回空串，静默跳过）"""
    pts = []
    for p in fill.get("holders") or []:
        d = str(p.get("date") or "").strip()
        num = _num(p.get("num"))
        if not d or num is None:
            continue
        pts.append({"date": d, "num": num, "chg": _num(p.get("chg"))})
    if len(pts) < 3:
        return ""
    pts.sort(key=lambda r: r["date"])  # 旧→新

    W, H, L, R, T, B = 1000, 260, 60, 20, 40, 44
    n = len(pts)
    slot = (W - L - R) / n
    bar_w = min(slot * 0.56, 72)
    hi = max(p["num"] for p in pts) * 1.18  # 不断轴（柱=真实数值契约），顶部留给数值标签
    Y = _lin_map(0, hi, H - B, T)

    parts = ['<span class="section-tag">股东户数趋势</span>',
             _svg_open(W, H, "股东户数趋势")]
    parts.append(f'<line x1="{L}" y1="{H - B}" x2="{W - R}" y2="{H - B}" stroke="{_C_AXIS}" stroke-width="1.2"/>')
    for i, p in enumerate(pts):
        x = L + i * slot + (slot - bar_w) / 2
        y = Y(p["num"])
        color = _C_BLUE if i == n - 1 else _C_SAND
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{H - B - y:.1f}" '
                     f'rx="4" fill="{color}"/>')
        parts.append(f'<text x="{x + bar_w / 2:.1f}" y="{y - 6:.1f}" text-anchor="middle" '
                     f'font-size="11" font-weight="{700 if i == n - 1 else 400}" '
                     f'fill="{_C_BLUE if i == n - 1 else _C_STONE}">{p["num"]:,.0f}</text>')
        parts.append(f'<text x="{x + bar_w / 2:.1f}" y="{H - B + 16}" text-anchor="middle" '
                     f'font-size="10.5" fill="{_C_LABEL}">{_esc(p["date"][2:7])}</text>')
        if p["chg"] is not None:
            chg_color = _C_RED if p["chg"] > 0 else _C_GREEN  # 户数增=分散=红；减=集中=绿
            parts.append(f'<text x="{x + bar_w / 2:.1f}" y="{H - B + 31}" text-anchor="middle" '
                         f'font-size="10.5" fill="{chg_color}">{p["chg"]:+.1f}%</text>')
    parts.append(_svg_close())
    parts.append('<span class="source">股东户数趋势（脚本按 holders 字段生成，数据来自 em_fetch E4）：'
                 '柱=期末股东户数，柱下=截止日与环比；<strong>户数增=筹码分散（红），户数减=集中（绿）</strong>，'
                 '钢蓝柱=最新一期</span>')
    return "".join(parts)


def build_review_dumbbell(prev: dict, quality: float, valuation: float, timing) -> str:
    """12 回测复盘·三轨分新旧对比哑铃图（0-10 定域）：灰点=上版、蓝点=本版，
    连线带箭头（方向=上版→本版），绿=上调、红=下调，右列=分差。prev 为空 → 返回空串。"""
    if not prev:
        return ""
    rows = []
    for label, old, new in (("质量分", _num(prev.get("quality", prev.get("research"))), quality),
                            ("估值分", _num(prev.get("valuation")), valuation),
                            ("时机分", _num(prev.get("timing")), timing)):
        if old is None or new is None:
            continue
        rows.append({"label": label, "old": old, "new": float(new)})
    if not rows:
        return ""
    W, NL, BAR_A, BAR_B = 1000, 110, 140, 890
    T, ROW_H = 30, 50
    H = T + len(rows) * ROW_H + 36
    X = _lin_map(0, 10, BAR_A, BAR_B)
    parts = ['<span class="section-tag">三轨分新旧对比</span>',
             _svg_open(W, H, "三轨分新旧对比")]
    _vgrid_ticks(parts, X, _ticks(0, 10, 6), T - 6, H - 30, H - 14)
    for i, r in enumerate(rows):
        cy = T + i * ROW_H + ROW_H / 2 - 6
        xo, xn = X(r["old"]), X(r["new"])
        d = r["new"] - r["old"]
        dcolor = _C_GREEN if d >= 0 else _C_RED
        # v4.8.1：连线末端加箭头（方向=上版→本版，直观看出分数升/降）；两点过近时不画
        s = 1 if xn >= xo else -1
        far = abs(xn - xo) >= 26
        parts.append(f'<line x1="{xo:.1f}" y1="{cy:.1f}" x2="{(xn - 19 * s) if far else xn:.1f}" y2="{cy:.1f}" '
                     f'stroke="{dcolor}" stroke-width="3"/>')
        if far:
            tip = xn - 10 * s   # 箭头尖贴到新点圆缘（r=7.5 + 描边 2）
            parts.append(f'<polygon points="{tip:.1f},{cy:.1f} {tip - 9 * s:.1f},{cy - 5.5:.1f} '
                         f'{tip - 9 * s:.1f},{cy + 5.5:.1f}" fill="{dcolor}"/>')
        parts.append(f'<circle cx="{xo:.1f}" cy="{cy:.1f}" r="6" fill="{_C_SAND}"/>')
        parts.append(f'<circle cx="{xn:.1f}" cy="{cy:.1f}" r="7.5" fill="{_C_BLUE}" stroke="{_C_PAPER}" stroke-width="2"/>')
        parts.append(f'<text x="{NL}" y="{cy + 4.5:.1f}" text-anchor="end" font-size="12.5" fill="{_C_INK}">{r["label"]}</text>')
        # 新旧点过近时旧值改放下方，避免两个数值标签重叠
        old_y = cy + 24 if abs(xn - xo) < 70 else cy - 14
        parts.append(f'<text x="{xo:.1f}" y="{old_y:.1f}" text-anchor="middle" font-size="11" fill="{_C_LABEL}">{_fmt(r["old"])}</text>')
        parts.append(f'<text x="{xn:.1f}" y="{cy - 14:.1f}" text-anchor="middle" font-size="12" '
                     f'font-weight="700" fill="{_C_BLUE}">{_fmt(r["new"])}</text>')
        parts.append(f'<text x="{BAR_B + 10}" y="{cy + 4.5:.1f}" font-size="12" font-weight="700" '
                     f'fill="{dcolor}">{d:+.2f}</text>')
    parts.append(_svg_close())
    parts.append(f'<span class="source">三轨分新旧对比（脚本按 prev 字段生成）：灰点={_esc(str(prev.get("date", "上版")))} 上版，'
                 f'蓝点=本版；连线箭头指向上版→本版方向（绿=上调、红=下调）；右列=分差；0-10 定域</span>')
    return "".join(parts)

