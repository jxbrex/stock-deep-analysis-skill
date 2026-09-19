#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""charts_cycle.py — 第 11 章（周期规律）图族（v4.9 从 charts.py 拆出）：PE 历史带（build_pe_band）/ 股价与 PE 历史发丝图（build_price_history）。依赖 charts_base 与 scoring。"""

from scoring import _num, _fmt, _esc
from charts_base import *

def build_pe_band(fill: dict) -> str:
    """08→11 估值·PE 历史带（fill["pe_history"] 可选字段 + valuation_inputs 的 pe_band/pe_ttm）：
    横向子弹图——浅带=历史 PE 区间，钢蓝段=合理带，黑刻=当前值，灰虚刻=关键时点。
    v4.8.1：显示域自适应截断（hist_hi 远超决策值集合×1.5 时截到该倍数，右缘「峰值→」标注），
    关键时点标签双层交错排布。
    v4.7.1 起图挪至 11 周期规律章（手写时段拆解前，概览→明细）。
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


def build_price_history(fill: dict) -> str:
    """11 周期规律·股价/PE 历史图（fill["price_history"] 可选字段，与 PE 历史带同源 E2 月线）：
    v4.11.0 起主形态=季K蜡烛（series 带 open/high/low/close 时——照抄 E2「全序列」行；按日历季度聚合：
    季首月开/季内高低/季末月收，红涨绿跌仅股价方向），无 OHLC 的旧 fill 回退月收发丝线（原形态）。
    v4.11.1 起叠加趋势均线（海油反馈：季K 单看蜡烛不易读趋势）——季K=季度收盘 MA4、
    发丝=月收盘 MA12，暖灰细线 + 图例；均线值域含于价格域内，不影响定标。
    右轴=PE(TTM)（钢蓝折线：v5.0 起季K 分支按季聚合——取季末月值，与蜡烛/4 季均线同频同口径；
    非季K 退化路径仍月频。有效 pe <12 点则只画股价；亏损期 PE 无定义自然断线分段，
    连续缺值段加浅灰底纹并命名「亏损期 · PE(TTM) 无定义」——缺口是诚实区间不是断数，
    天齐实证 2020 亏损尾巴+2024-2025 亏损期两段）；**PE 右轴自适应截断**（max > p75×3 时域顶=p75×3、
    超限段平贴域顶、右缘标注「峰值 Nx →」，套 v4.8.1 pe_history 规则——扭亏初期净利极薄会冲出
    200x+ 把正常段压成平线，天齐 2026-03 204.6x 实证）。横轴按年 tick（带竖向浅网格线），
    末端最新值标注带药丸底色。概览→明细：垫在历史带之后、手写时段拆解之前。
    price_history: {"label":"近5年", "series":[{"m":"2021-09","open":..,"high":..,"low":..,"close":12.3,"pe":15.2}, ...]}
    （旧→新，月频；open/high/low 可省（回退发丝线）；有效点 <12 → 返回空串，静默跳过）"""
    ph = fill.get("price_history") or {}
    pts = []
    for p in ph.get("series") or []:
        m = str(p.get("m") or "").strip()
        c = _num(p.get("close"))
        if not m or c is None:
            continue
        pts.append({"m": m, "close": c, "pe": _num(p.get("pe")),
                    "o": _num(p.get("open")), "h": _num(p.get("high")), "l": _num(p.get("low"))})
    if len(pts) < 12:
        return ""
    pts.sort(key=lambda p: p["m"])   # v4.11.0 审计：逆序 fill 会画成时间轴镜像（m=YYYY-MM 可字典序排）
    n = len(pts)
    # v4.11.0：门槛自「过半」放宽为 ≥12 点——亏损期 PE(TTM) 无定义天然缺值，分段断线
    # 才是诚实形态（天齐实证：照抄全序列后 29/68 点有效，过半规则会误杀 2022-2024 段）
    has_pe = sum(1 for p in pts if p["pe"] is not None) >= 12
    has_ohlc = sum(1 for p in pts if None not in (p["o"], p["h"], p["l"])) >= max(12, n // 2)
    if has_ohlc:
        # 审计 P0-1：缺 OHLC 的月退化为收盘价一字线（o=h=l=close），聚合不再遇 None（不炸链路）
        for p in pts:
            if None in (p["o"], p["h"], p["l"]):
                p["o"] = p["h"] = p["l"] = p["close"]

    W, H, L, R, T, B = 1000, 240, 56, 64, 34, 36
    closes = [p["close"] for p in pts]

    # 季度聚合（日历季度；开=季首月开、高/低=季内极值、收=季末月收）
    def _mi(m):   # "YYYY-MM" → (年, 月)；非法返回 None（该点自成一组，不崩链）
        return (int(m[:4]), int(m[5:7])) if len(m) >= 7 and m[:4].isdigit() and m[5:7].isdigit() else None
    quarters = []
    if has_ohlc:
        i = 0
        while i < n:
            q0 = _mi(pts[i]["m"])
            j = i
            while j + 1 < n and q0 is not None:
                q1 = _mi(pts[j + 1]["m"])
                if q1 is None or q1[0] != q0[0] or (q1[1] - 1) // 3 != (q0[1] - 1) // 3:
                    break
                j += 1
            g = pts[i:j + 1]
            quarters.append({"i0": i, "i1": j, "o": g[0]["o"], "h": max(x["h"] for x in g),
                             "l": min(x["l"] for x in g), "c": g[-1]["close"]})
            i = j + 1

    # X 映射：发丝模式端点对齐（原契约）；季K 模式月槽中心（蜡烛占槽）
    if has_ohlc:
        slot = (W - L - R) / n
        X = lambda i: L + (i + 0.5) * slot
        step = slot
    else:
        X = lambda i: L + i / (n - 1) * (W - L - R)
        step = (W - L - R) / (n - 1)

    # v5.0（F 频率统一）：季K 分支 PE(TTM) 按季聚合——取每季末月值（与季度收盘口径一致），
    # 点过季度槽中心（与蜡烛/4 季均线同位），缺 PE 的季记 None（断线分段沿用）；
    # (x, pe, 月槽起, 月槽止) 四元组，右轴定标/截断/亏损期底纹/折线/末端标注同消费。
    # 非季K 退化路径（月K 发丝）保持月频不动
    if has_ohlc:
        pe_line = [(X((q["i0"] + q["i1"]) / 2), pts[q["i1"]]["pe"], q["i0"], q["i1"])
                   for q in quarters]
    else:
        pe_line = [(X(i), p["pe"], i, i) for i, p in enumerate(pts)]

    if has_ohlc:
        lo_c, hi_c = _pad_domain(min(q["l"] for q in quarters), max(q["h"] for q in quarters),
                                 0.08, floor=0.0)
    else:
        lo_c, hi_c = _pad_domain(min(closes), max(closes), 0.08, floor=0.0)
    Yc = _lin_map(lo_c, hi_c, H - B, T)
    pe_cap = None
    pes = sorted(v for _, v, _, _ in pe_line if v is not None)
    if has_pe and not pes:
        # 季K 极端情形：月末有值但季末月全缺 → 季频序列空，等同无 PE（防下方 pes[-1] 炸链）
        has_pe = False
    if has_pe:
        hi_raw = pes[-1]
        p75 = pes[int((len(pes) - 1) * 0.75)]
        if p75 > 0 and hi_raw > p75 * 3:
            pe_cap = p75 * 3   # 扭亏初期 PE 冲出 200x+ 压扁正常段 → 截断（右缘标注峰值）
        if pe_cap:
            lo_p = max(0.0, pes[0] - (pe_cap - pes[0]) * 0.08)
            hi_p = pe_cap      # 截断模式域顶即 cap，不再二次垫高（与文档「域顶=p75×3」承诺一致）
        else:
            lo_p, hi_p = _pad_domain(pes[0], hi_raw, 0.08, floor=0.0)
        _Yp = _lin_map(lo_p, hi_p, H - B, T)
        Yp = lambda v: max(_Yp(min(v, hi_p)), T)   # 超限段平贴域顶

    label = str(ph.get("label") or "").strip()
    cur = str(fill.get("currency") or "元")
    # 趋势均线预计算（v4.11.1，海油反馈）：季K=季度收盘 MA4 过季度槽中心、发丝=月收盘 MA12。
    # 热核审计 P2-2：图例/source/折线同一门槛——≥2 点才成线（quarters≥5 / n≥13），
    # 否则图例说了谎却没有线（单点 moveto-only path 不可见）
    if has_ohlc:
        ma_pts = [(X((quarters[i]["i0"] + quarters[i]["i1"]) / 2),
                   Yc(sum(quarters[k]["c"] for k in range(i - 3, i + 1)) / 4))
                  for i in range(3, len(quarters))] if len(quarters) >= 5 else []
    else:
        ma_pts = [(X(i), Yc(sum(closes[i - 11:i + 1]) / 12))
                  for i in range(11, n)] if n >= 13 else []
    # PE 序列同源 E2 月线（价格×股本÷TTM净利），恒为 PE(TTM) 口径，不随 metric_label 换标签
    tag = f'股价季K 与 PE(TTM) 历史{("（" + _esc(label) + "）") if label else ""}' if has_ohlc \
        else f'股价与 PE(TTM) 历史{("（" + _esc(label) + "）") if label else ""}'
    parts = [f'<span class="section-tag">{tag}</span>',
             _svg_open(W, H, "股价季K与PE历史走势" if has_ohlc else "股价与PE历史走势")]
    # 亏损期底纹（连续缺 pe 段；先画在最底层）。审计 P0-2：尾部段（延伸到序列末，
    # 即当前仍亏损——困境反转标的恰恰如此）旧哨兵逻辑永不收尾 → 显式收 run_start 到末尾。
    # v5.0（F）：季K 分支随 PE 季频序列按季判缺（连续缺点的季成段，1 季 ≈ 旧月频 ≥3 个月口径）；
    # 退化路径仍逐月（≥3 个月成段）。runs 存月槽索引区间，下方渲染口径不变
    runs, run_start = [], None
    if has_pe:
        min_run = 1 if has_ohlc else 3
        for i, (_x, v, _s0, _s1) in enumerate(pe_line):
            if v is None and run_start is None:
                run_start = i
            elif v is not None and run_start is not None:
                if i - run_start >= min_run:
                    runs.append((pe_line[run_start][2], pe_line[i - 1][3]))
                run_start = None
        if run_start is not None and len(pe_line) - run_start >= min_run:
            runs.append((pe_line[run_start][2], pe_line[-1][3]))
    _shade_label = "亏损期 · PE(TTM) 无定义"
    for a, b in runs:
        x1 = max(X(a) - step / 2, L)          # 夹到绘图区（回退模式首段左溢实证）
        x2 = min(X(b) + step / 2, W - R)
        parts.append(f'<rect x="{x1:.1f}" y="{T}" width="{x2 - x1:.1f}" height="{H - B - T}" '
                     f'fill="{_C_STONE}" fill-opacity="0.07"/>')
        if x2 - x1 >= _text_w(_shade_label, 11) + 16:
            parts.append(f'<text x="{(x1 + x2) / 2:.1f}" y="{T + 16}" text-anchor="middle" font-size="11" '
                         f'fill="{_C_STONE}" stroke="{_C_PAPER_CELL}" stroke-width="3" '
                         f'paint-order="stroke">{_shade_label}</text>')
    # 图例（左上）
    if has_ohlc:
        parts.append(f'<rect x="{L}" y="{T - 17}" width="12" height="9" rx="2" fill="{_C_RED}"/>')
        parts.append(f'<rect x="{L + 14}" y="{T - 17}" width="12" height="9" rx="2" fill="{_C_GREEN}"/>')
        parts.append(f'<text x="{L + 32}" y="{T - 8}" font-size="11" fill="{_C_INK}">股价季K（左轴，{_esc(cur)}；红涨绿跌）</text>')
    else:
        parts.append(f'<line x1="{L}" y1="{T - 12}" x2="{L + 26}" y2="{T - 12}" stroke="{_C_INK}" stroke-width="1.6"/>')
        parts.append(f'<text x="{L + 32}" y="{T - 8}" font-size="11" fill="{_C_INK}">股价（左轴，{_esc(cur)}）</text>')
    _leg1 = f"股价季K（左轴，{cur}；红涨绿跌）" if has_ohlc else f"股价（左轴，{cur}）"
    # v4.11.1（海油反馈）：叠加趋势均线——季K 模式=季度收盘 MA4，发丝模式=月收盘 MA12；
    # 中性暖灰细线，不抢蜡烛/PE 线视觉层级
    _ma_leg = "4 季均线" if has_ohlc else "12 月均线"
    _pe_freq = "季度" if has_ohlc else "月频"   # v5.0（F）：季K 分支 PE 已季频聚合
    lx2 = L + 32 + _text_w(_leg1, 11) + 24
    if ma_pts:   # 图例与折线同门槛（无线不出图例）
        parts.append(f'<line x1="{lx2:.0f}" y1="{T - 12}" x2="{lx2 + 26:.0f}" y2="{T - 12}" '
                     f'stroke="{_C_STONE}" stroke-width="1.6"/>')
        parts.append(f'<text x="{lx2 + 32:.0f}" y="{T - 8}" font-size="11" fill="{_C_STONE}">{_ma_leg}</text>')
        lx2 += 32 + _text_w(_ma_leg, 11) + 24
    if has_pe:
        parts.append(f'<line x1="{lx2:.0f}" y1="{T - 12}" x2="{lx2 + 26:.0f}" y2="{T - 12}" stroke="{_C_BLUE}" stroke-width="1.6"/>')
        parts.append(f'<text x="{lx2 + 32:.0f}" y="{T - 8}" font-size="11" fill="{_C_BLUE}">PE(TTM)（右轴，{_pe_freq}）</text>')
    # 左轴（股价）网格与刻度
    _hgrid_ticks(parts, Yc, _ticks(lo_c, hi_c, 5), L, W - R, L - 8)
    # 右轴（PE）刻度 + 截断标注
    if has_pe:
        for v in _ticks(lo_p, hi_p, 5):
            gy = Yp(v)
            parts.append(f'<text x="{W - R + 8}" y="{gy + 4:.1f}" font-size="11" fill="{_C_BLUE}">{_fmt(v)}</text>')
        if pe_cap:
            # 虚线封口（自首个超限点起）+ 峰值标签贴截断段起点（避开右缘最新值药丸区，P1-1 实证：
            # 天齐峰值恰在末点，右缘标注被药丸遮掉）
            f0 = next(s0 for _x, v, s0, _s1 in pe_line if v is not None and v >= hi_p)
            parts.append(f'<line x1="{X(f0) - step / 2:.1f}" y1="{Yp(hi_p):.1f}" x2="{W - R}" y2="{Yp(hi_p):.1f}" '
                         f'stroke="{_C_SAND}" stroke-width="1.2" stroke-dasharray="4 3"/>')
            _cap_txt = f"峰值 {_fmt(hi_raw)}x →"
            _canc, _cx = _anchor_clamp(X(f0) - 6, _text_w(_cap_txt, 10.5), L + 4, W - R - 4)
            parts.append(f'<text x="{_cx:.1f}" y="{T + 14}" text-anchor="{_canc}" font-size="10.5" '
                         f'font-weight="700" fill="{_C_BLUE}" stroke="{_C_PAPER_CELL}" stroke-width="3" '
                         f'paint-order="stroke">{_cap_txt}</text>')
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
    if has_ohlc:
        # 季K蜡烛：红涨绿跌（仅股价方向用色，v4.9 方向色约定）
        for q in quarters:
            cx = X((q["i0"] + q["i1"]) / 2)
            bw = min(step * (q["i1"] - q["i0"] + 1) * 0.55, max(26, step * 2))
            col = _C_RED if q["c"] > q["o"] else (_C_GREEN if q["c"] < q["o"] else _C_LABEL)
            parts.append(f'<line x1="{cx:.1f}" y1="{Yc(q["h"]):.1f}" x2="{cx:.1f}" y2="{Yc(q["l"]):.1f}" '
                         f'stroke="{col}" stroke-width="1.2"/>')
            y1, y2 = Yc(max(q["o"], q["c"])), Yc(min(q["o"], q["c"]))
            parts.append(f'<rect x="{cx - bw / 2:.1f}" y="{y1:.1f}" width="{bw:.1f}" '
                         f'height="{max(y2 - y1, 1):.1f}" fill="{col}"/>')
    else:
        # 股价发丝线（v4.8.2：线下浅沙色面积填充，发丝 1.3→1.8）
        path = "M" + " L".join(f"{X(i):.1f},{Yc(p['close']):.1f}" for i, p in enumerate(pts))
        parts.append(f'<path d="{path} L{X(n - 1):.1f},{H - B} L{L},{H - B} Z" fill="{_C_TRACK}" stroke="none"/>')
        parts.append(f'<path d="{path}" fill="none" stroke="{_C_INK}" stroke-width="1.8"/>')
    # 趋势均线（v4.11.1）：折线/图例/source 同门槛（≥2 点），预计算见 legend 区上方
    if ma_pts:
        parts.append('<path d="M' + " L".join(f"{x:.1f},{y:.1f}" for x, y in ma_pts)
                     + f'" fill="none" stroke="{_C_STONE}" stroke-width="1.6"/>')
    # PE 折线（允许中间缺值：缺值处分段——v5.0 起季K 分支=季末月值过季度槽中心，退化路径仍逐月）
    if has_pe:
        run = []
        for x, v, _s0, _s1 in pe_line + [(0, None, 0, 0)]:  # 哨兵收尾
            if v is not None:
                run.append((x, v))
            elif run:
                d = "M" + " L".join(f"{px:.1f},{Yp(pv):.1f}" for px, pv in run)
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
        last = next((t for t in reversed(pe_line) if t[1] is not None), None)
        if last is not None:
            # 末端药丸 x 锚 PE 折线实际末点（F18）：季K 末季不完整（序列止于季中）时 X(n-1)
            # 与折线末点（季度槽中心）错位一个月槽；末季完整时 X(n-1) 即季末月槽，
            # 与股价药丸同列对齐。发丝路径逐月，末点 x 即折线末端（亏损尾巴不再漂到序列末）
            tail_incomplete = has_ohlc and quarters[-1]["i1"] - quarters[-1]["i0"] < 2
            px = last[0] if (not has_ohlc or tail_incomplete) else X(n - 1)
            _pill(px - 6, Yp(last[1]) + 16, f'{_fmt(last[1])}x', _C_BLUE)
    parts.append(_svg_close())
    # 判词（v5.1.0，恒瑞反馈：图注只教方法「读交叉」却不给当前结论）：季K 分支追加
    # 「当前交叉状态」——①最新月收 vs 4 季均线（偏离%+连续方位季数）；②近 4 季价与 PE(TTM)
    # 方向四象限（E=价÷PE 的 TTM 业绩方向：价涨E涨=业绩驱动 / 价涨E跌=估值扩张 /
    # 价跌E涨=估值消化 / 价跌E跌=业绩估值双杀）。全部取自本图已渲染序列，确定性可复算；
    # 部件数据不足（无均线/当季 PE 缺/窗口不足 4 季）自动缺席，不硬凑整句。
    verdict = ""
    if has_ohlc and ma_pts:
        ma_vals = [sum(quarters[k]["c"] for k in range(i - 3, i + 1)) / 4
                   for i in range(3, len(quarters))]
        if ma_vals[-1] > 0:
            dev = (quarters[-1]["c"] / ma_vals[-1] - 1) * 100
            sides = [1 if quarters[i]["c"] >= mv else -1
                     for i, mv in zip(range(3, len(quarters)), ma_vals)]
            run = 1
            for s in reversed(sides[:-1]):
                if s == sides[-1]:
                    run += 1
                else:
                    break
            if abs(dev) < 3:
                pos = f"最新月收贴近 4 季均线，偏离 {dev:+.1f}%"
            else:
                pos = f"最新月收{'低' if dev < 0 else '高'}于 4 季均线 {abs(dev):.1f}%"
            side_s = "下" if sides[-1] < 0 else "上"
            stint = (f"本季刚转入均线{side_s}方"
                     if run == 1 and len(sides) > 1 else f"连续 {run} 季收于均线{side_s}方")
            verdict = f"；当前：{pos}，{stint}"
            k = 4 if len(quarters) >= 9 else 0
            pe_now = pe_line[-1][1] if pe_line else None
            pe_old = pe_line[-1 - k][1] if k and len(pe_line) > k else None
            if k and pe_now and pe_old and pe_old > 0:
                pc = (quarters[-1]["c"] / quarters[-1 - k]["c"] - 1) * 100
                ppe = (pe_now / pe_old - 1) * 100
                de = ((1 + pc / 100) / (1 + ppe / 100) - 1) * 100   # E=价÷PE 的 TTM 业绩方向
                if pc >= 3:
                    quad = ("业绩驱动上涨段" if de >= 3 else
                            "估值扩张段（价涨而 TTM 业绩降）" if de <= -3 else "价与业绩同步上行")
                elif pc <= -3:
                    quad = ("估值消化段（TTM 业绩仍增）" if de >= 3 else
                            "业绩与估值双杀段" if de <= -3 else "价与业绩同步回落")
                else:
                    quad = "价格横盘段"
                verdict += f"；近 {k} 季价 {pc:+.0f}%、PE(TTM) {ppe:+.0f}%——{quad}"
    if has_ohlc:
        src = ('股价季K/PE 历史走势（脚本按 price_history 字段生成，同源 E2 月线全序列）：'
               '蜡烛=季度 K 线（季首月开/季内高低/季末月收；红涨绿跌仅股价方向）'
               + ('，暖灰=4 季均线（每季一点，取近 4 季收盘均值——与 PE 同为季度频率，'
                  '「4 季」是平滑窗口非频率）' if ma_pts else '')
               + '，钢蓝=PE(TTM)（右轴，季度）；'
               '灰底纹段=亏损期（TTM 净利 ≤0，PE 无定义——诚实区间非断数）；双轴各自定标，读交叉不读绝对高度')
        if pe_cap:
            src += f'；右缘「峰值 {_fmt(hi_raw)}x →」=PE 右轴截断标注（正常段可读性优先）'
        src += verdict
    else:
        src = ('股价/PE 历史走势（脚本按 price_history 字段生成，与上方历史带同源 E2 月线）：'
               '深灰=月收盘价（左轴）'
               + ('，暖灰=12 月均线' if ma_pts else '')
               + '，钢蓝=PE(TTM)（右轴）'
               + ('；灰底纹段=亏损期（TTM 净利 ≤0，PE 无定义）' if runs else '')
               + (f'；右缘「峰值 {_fmt(hi_raw)}x →」=PE 右轴截断标注' if has_pe and pe_cap else '')
               + '；双轴各自定标，读交叉不读绝对高度；'
               '判读：价涨 PE 平=业绩驱动，价平 PE 跳=估值重定价（财报日 TTM 净利跳变所致）')
    parts.append(f'<span class="source">{src}</span>')
    return "".join(parts)
