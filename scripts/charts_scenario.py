#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""charts_scenario.py — 情景类图族（v4.10 从 charts.py 拆出）：05 目标价走廊（build_scenario_spectrum）/ 三情景表+三指标卡（build_scenario_block）/ 07 估值-质量散点图（build_peers_plot）。依赖 charts_base 与 scoring。"""

import math

from scoring import _num, _fmt, _esc
from charts_base import *

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
    # v4.9 颜色语义拆分：中枢期望收益是方向量（随 .up/.down 红涨绿跌）；
    # 赔率/离散度是好坏评价，走 .good/.bad（绿好红坏，不随涨跌色翻转）
    if odds is None:
        o_val, o_cls, o_sub = "∞", "good", "悲观下限高于现价——最强不对称信号，仓位可上浮一档"
    else:
        o_val, o_cls = f"{odds:.2f}", "good" if odds >= 1.5 else "bad"
        o_sub = "(基础中值−现价)÷(现价−悲观下限)；>1.5 为良好不对称"
    if disp < 0.40:
        d_cls, d_note = "good", "可预测"
    elif disp <= 0.90:
        d_cls, d_note = "mid", "中不确定"
    else:
        d_cls, d_note = "bad", "高发散，仓位降一档"
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
