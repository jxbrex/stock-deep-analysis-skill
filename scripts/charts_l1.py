#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""charts_l1.py — 第 3 章（公司本质）图族（v4.10 从 charts.py 拆出）：3.1 业务构成（build_segments_plot）/ 3.2 产业链位置（build_chain_plot）/ 3.4 财务五年趋势图墙（build_fin_trend）+ 3 章锚点注入（_inject_l1_charts）。依赖 charts_base 与 scoring。"""

import sys

from scoring import _num, _fmt, _esc
from charts_base import *

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
    # v4.9：口径/清洗说明走 note 字段（渲染进 source 小字），period 只放短时段标签（≤8字，校验器告警）
    note = str(seg.get("note") or "").strip()
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
            # 条外标签：v4.9 改用深墨色（原随条色 _C_SAND #b3ab93 浅底上对比度不足）
            parts.append(f'<text x="{X0 + bw + 8:.1f}" y="{bc_c + 4.5:.1f}" font-size="12" '
                         f'font-weight="700" fill="{_C_INK}">{pct_label}</text>')
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
                 '条下=收入/毛利额；<strong>利润口径为毛利——分部净利润无公开披露</strong>'
                 + (f'；<strong>口径备注：</strong>{_esc(note)}' if note else '') + '</span>')
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

    # v4.9：每栏在同一总高内按自身条数均分间距——短栏自动拉开、两栏上下对齐，
    # 不再共用 TOP+固定行距导致少的一侧顶部对齐、下方留白（青啤 4上游 vs 5下游 实证）
    col_h = rows * (BOX_H + GAP) - GAP       # 长栏实际总高（首盒顶→末盒底）

    def _col(items, x, links_to_left):
        n = len(items)
        pitch = (col_h - BOX_H) / (n - 1) if n > 1 else 0
        for i, name in enumerate(items):
            by = TOP + (i * pitch if n > 1 else (col_h - BOX_H) / 2)
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
                 '左=上游行业，右=下游行业，两栏各自在总高内均分（条数不同则间距不同），'
                 '曲线=供需关系，卡下=本公司定位注；只列行业不列企业，不代表全部玩家</span>')
    return "".join(parts)


def build_fin_trend(fill: dict) -> str:
    """03 公司本质·3.4 财务健康五年组合图墙（fill["fin_trend"] 必填字段，锚点 <!--FIN_TREND-->，v4.9）：
    双轴组合图面板（柱=金额·左轴·亿，线=比率·右轴·%/倍），.mini-grid 两列网格，取代手写 5 年年表。
    fin_trend: {"years":["2021",...,"2025"], "panels":[
      {"title":"营收 × 毛利率",
       "bars":[{"name":"营收","unit":"亿","values":[301.7,...]}],
       "lines":[{"name":"毛利率","pct":true,"values":[36.7,...]}]}, ...]}
    （bars/lines[].values 与 years 等长、全为数字；bars 每面板 1-2 条（双柱并排：第一条沙色、
    第二条钢蓝，如 经营现金流+自由现金流）；lines 每面板 1-2 条（第 2 条渲染为灰虚线）；
    pct=true 按 % 展示；lines[].threshold 可选红虚线阈值（如现金含量 0.7）。
    标准 4 面板：营收×毛利率 / 归母净利×净利率×ROE / 经营现金流+自由现金流×现金含量（阈值0.7) / 货币资金×短债覆盖率。
    数据照抄 em_fetch E3 年表，禁手估。有效面板 <3 或年数 <3 → 返回空串；必填硬校验在 validate 层）"""
    ft = fill.get("fin_trend") or {}
    years = [str(y) for y in ft.get("years") or []]

    def _series_ok(vals):
        return len(vals) == len(years) and all(_num(v) is not None for v in vals)

    panels = []
    for p in ft.get("panels") or []:
        if not isinstance(p, dict):
            continue
        bars = []
        for b in p.get("bars") or []:
            bname = str(b.get("name") or "").strip()
            if bname and _series_ok(b.get("values") or []):
                bars.append({"name": bname, "unit": str(b.get("unit") or "亿").strip(),
                             "values": [_num(v) for v in b["values"]]})
        lines = []
        for ln in p.get("lines") or []:
            lname = str(ln.get("name") or "").strip()
            if lname and _series_ok(ln.get("values") or []):
                lines.append({"name": lname, "values": [_num(v) for v in ln["values"]],
                              "pct": bool(ln.get("pct")), "threshold": _num(ln.get("threshold"))})
        if bars and lines:
            panels.append({"title": str(p.get("title") or bars[0]["name"]).strip(),
                           "bars": bars[:2], "lines": lines[:2]})
    if len(years) < 3 or len(panels) < 3:
        return ""

    cells = []
    for p in panels:
        n = len(years)
        W, H, T, B, L, R = 480, 158, 26, 18, 38, 38
        slot = (W - L - R) / n
        # 左轴=柱（柱不断轴：值域含 0 基线）；右轴=线（按数据垫边，含阈值）
        bv_all = [v for b in p["bars"] for v in b["values"]]
        if min(bv_all) >= 0:
            blo, bhi = _pad_domain(0.0, max(bv_all), 0.15, floor=0.0)
        else:
            blo, bhi = _pad_domain(min(bv_all), max(bv_all), 0.15)
        lv_all = [v for ln in p["lines"] for v in ln["values"]]
        th_all = [ln["threshold"] for ln in p["lines"] if ln["threshold"] is not None]
        llo, lhi = _pad_domain(min(lv_all + th_all), max(lv_all + th_all), 0.25)
        YB = _lin_map(blo, bhi, H - B, T)
        YL = _lin_map(llo, lhi, H - B, T)
        y0 = YB(0)
        line_colors = [_C_BLUE, _C_STONE]
        HALO = '#f7f2e7'   # 与 .mini-cell 底色一致：文字光晕防柱线叠字（lieflat paint-order 语法）
        halo = f' stroke="{HALO}" stroke-width="3" paint-order="stroke"'
        svg = [f'<svg viewBox="0 0 {W} {H}">']
        # 轴刻度：左（柱）带浅网格，右（线）只出刻度字
        for t in _ticks(blo, bhi, 3):
            gy = YB(t)
            svg.append(f'<line x1="{L}" y1="{gy:.1f}" x2="{W - R}" y2="{gy:.1f}" stroke="{_C_GRID}" stroke-width="1"/>')
            svg.append(f'<text x="{L - 4}" y="{gy + 3:.1f}" text-anchor="end" font-size="8" fill="{_C_LABEL}">{_fmt(t)}</text>')
        for t in _ticks(llo, lhi, 3):
            svg.append(f'<text x="{W - R + 4}" y="{YL(t) + 3:.1f}" font-size="8" fill="{_C_LABEL}">{_fmt(t)}</text>')
        svg.append(f'<line x1="{L}" y1="{y0:.1f}" x2="{W - R}" y2="{y0:.1f}" stroke="{_C_AXIS}" stroke-width="1.2"/>')
        # 图例（顶部单行）
        lx = L
        bar_colors = [_C_SAND, _C_BLUE]   # 双柱：第一条沙、第二条钢蓝
        for bi, b in enumerate(p["bars"]):
            blab = f'{b["name"]}（{b["unit"]}，左轴）'
            svg.append(f'<rect x="{lx}" y="6" width="11" height="8" rx="2" fill="{bar_colors[bi]}"/>')
            svg.append(f'<text x="{lx + 15}" y="13" font-size="9" fill="{_C_LABEL}">{_esc(blab)}</text>')
            lx += 15 + _text_w(blab, 9) + 14
        for li, ln in enumerate(p["lines"]):
            c = line_colors[li]
            dash = ' stroke-dasharray="3 2"' if li == 1 else ""
            lab = ln["name"] + ("（%，右轴）" if ln["pct"] else "（右轴）")
            svg.append(f'<line x1="{lx}" y1="10" x2="{lx + 14}" y2="10" stroke="{c}" stroke-width="2"{dash}/>')
            svg.append(f'<text x="{lx + 18}" y="13" font-size="9" fill="{_C_LABEL}">{_esc(lab)}</text>')
            lx += 18 + _text_w(lab, 9) + 14
        # 阈值红虚线
        for ln in p["lines"]:
            if ln["threshold"] is not None:
                ty = YL(ln["threshold"])
                svg.append(f'<line x1="{L}" y1="{ty:.1f}" x2="{W - R}" y2="{ty:.1f}" stroke="{_C_RED}" '
                           f'stroke-width="1" stroke-dasharray="3 3"/>')
                svg.append(f'<text x="{W - R + 4}" y="{ty - 3:.1f}" font-size="8"{halo} fill="{_C_RED}">'
                           f'{_fmt(ln["threshold"])}</text>')
        # 柱：单柱=沙色历史+钢蓝最新年；双柱=并排（第一条沙、第二条钢蓝，不做逐年变色）
        nb = len(p["bars"])
        bw = min(slot * (0.5 if nb == 1 else 0.32), 30)
        for bi, b in enumerate(p["bars"]):
            for i, v in enumerate(b["values"]):
                if nb == 1:
                    x = L + i * slot + (slot - bw) / 2
                    c = _C_BLUE if i == n - 1 else _C_SAND
                else:
                    x = L + i * slot + slot / 2 + (bi - (nb - 1) / 2) * (bw + 3) - bw / 2
                    c = bar_colors[bi]
                y = YB(v)
                svg.append(f'<rect x="{x:.1f}" y="{min(y, y0):.1f}" width="{bw:.1f}" '
                           f'height="{max(abs(y0 - y), 1):.1f}" rx="2.5" fill="{c}"/>')
                svg.append(f'<text x="{x + bw / 2:.1f}" y="{min(y, y0) - 3:.1f}" text-anchor="middle" '
                           f'font-size="{8.5 if nb == 1 else 8}"{halo} '
                           f'fill="{_C_BLUE if c == _C_BLUE else _C_LABEL}">{_fmt(v)}</text>')
        # 线（首条钢蓝实线、次条灰虚线；首末点标值）
        for li, ln in enumerate(p["lines"]):
            c = line_colors[li]
            dash = ' stroke-dasharray="4 3"' if li == 1 else ""
            pts = [(L + i * slot + slot / 2, YL(v)) for i, v in enumerate(ln["values"])]
            svg.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" fill="none" '
                       f'stroke="{c}" stroke-width="1.8"{dash}/>')
            for i, (x, y) in enumerate(pts):
                svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{2.5 if i == n - 1 else 1.8}" fill="{c}"/>')
                if i in (0, n - 1):
                    lab = f"{_fmt(ln['values'][i])}%" if ln["pct"] else _fmt(ln["values"][i])
                    svg.append(f'<text x="{x:.1f}" y="{y - 5:.1f}" text-anchor="middle" font-size="8.5"'
                               f'{halo} fill="{c}">{lab}</text>')
        # 年份底标
        for i, yr in enumerate(years):
            svg.append(f'<text x="{L + i * slot + slot / 2:.1f}" y="{H - 4:.1f}" text-anchor="middle" '
                       f'font-size="8" fill="{_C_LABEL}">{_esc(yr[2:])}</text>')
        svg.append('</svg>')
        # 头行：标题 + 最新值（首柱带同比，双柱列各自末值，各线列末值）
        b0 = p["bars"][0]
        b_last = f'{_fmt(b0["values"][-1])}{b0["unit"]}'
        yoy = ""
        if n >= 2 and b0["values"][-2] != 0:
            yoy = f' <span class="m-yoy">{(b0["values"][-1] / b0["values"][-2] - 1) * 100:+.1f}%</span>'
        if len(p["bars"]) > 1:
            b1 = p["bars"][1]
            b_last += f' / {_fmt(b1["values"][-1])}{b1["unit"]}'
        line_lasts = " / ".join((f'{_fmt(ln["values"][-1])}%' if ln["pct"] else _fmt(ln["values"][-1]))
                                for ln in p["lines"])
        cells.append(f'<div class="mini-cell"><div class="m-head"><span class="m-name">{_esc(p["title"])}</span>'
                     f'<span class="m-val">{b_last}{yoy} ｜ {line_lasts}</span></div>{"".join(svg)}</div>')

    return (f'<span class="section-tag">财务五年趋势（{_esc(years[0])}–{_esc(years[-1])}）</span>'
            '<div class="mini-grid">' + "".join(cells) + '</div>'
            '<span class="source">财务五年趋势（脚本按 fin_trend 字段生成，数据照抄 em_fetch E3 年表）：'
            '组合图双轴——柱=金额（左轴 亿；单柱时沙=历史/钢蓝=最新年，双柱并排时沙=第一条/钢蓝=第二条），'
            '线=比率（右轴 %/倍，钢蓝实线=第一条、灰虚线=第二条），红虚线=阈值（如现金含量 0.7 盈利质量线）；'
            '图为概览，异常年份归因见本块正文与红旗四项卡</span>')


def _inject_l1_charts(l1_html: str, fill: dict) -> str:
    """3.1/3.2/3.4 图锚点注入（v4.8 起，v4.9 加 FIN_TREND）：l1_html 里的 <!--SEGMENTS--> / <!--CHAIN--> /
    <!--FIN_TREND--> 注释替换为对应脚本图；锚点缺失但字段已填 → 图追加第 3 章末尾 + 告警；
    字段未填 → 锚点静默清除。（与第 10 章 {{PE_BAND_HTML}} 裸占位符同款思路：避开模板条件块
    不支持嵌套的限制，又让模型保留图在维度块内的位置控制权。）"""
    for anchor, html, field in (("<!--SEGMENTS-->", build_segments_plot(fill), "segments"),
                                ("<!--CHAIN-->", build_chain_plot(fill), "industry_chain"),
                                ("<!--FIN_TREND-->", build_fin_trend(fill), "fin_trend")):
        if anchor in l1_html:
            l1_html = l1_html.replace(anchor, html)
        elif html:
            l1_html += "\n" + html
            print(f"⚠️ l1_html 缺 {anchor} 锚点：{field} 图已追加到第 3 章末尾"
                  f"（建议把锚点放到对应维度块内，3.1=业务构成 / 3.2=产业链位置 / 3.4=财务趋势图墙）",
                  file=sys.stderr)
    return l1_html
