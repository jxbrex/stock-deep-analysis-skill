#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""charts_cycle.py — 第 10 章（周期规律）图族（v4.10 从 charts.py 拆出）：PE 历史带（build_pe_band）/ 股价与 PE 历史发丝图（build_price_history）。依赖 charts_base 与 scoring。"""

from scoring import _num, _fmt, _esc
from charts_base import *

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
