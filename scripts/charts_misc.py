#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""charts_misc.py — 其余图族（v4.10 从 charts.py 拆出）：4.1 利润增长图（build_growth_plot，含 4 章锚点注入 _inject_l3_charts）/ 11 股东户数趋势（build_holders_plot）/ 12 回测哑铃（build_review_dumbbell）。依赖 charts_base 与 scoring。"""

import sys

from scoring import _num, _fmt, _esc
from charts_base import *

def build_growth_plot(fill: dict) -> str:
    """04 未来预期·4.1 利润增长图（fill["growth_plot"] 必填字段，锚点 <!--GROWTH-->，v4.9）：
    历史段=收入增速（沙柱）+归母净利增速（钢蓝柱）并列；预测段=本文净利增速区间（钢蓝区间竖条）
    +卖方一致预期（黑◆），组下标预期差（本文中枢−一致预期）。全图中性色，不含涨跌红绿。
    growth_plot: {"hist":[{"y":"2023","rev":5.3,"np":15.0}, ...],
                  "fcst":[{"y":"2026E","np_lo":2,"np_hi":6,"np_consensus":4.7,"rev":3.0}, ...]}
    （增速均为百分数；hist 近 3-5 年取 E3 年表同比，np_lo/np_hi=本文情景区间、np_consensus=卖方一致
    预期（E5，必填——图的核心是预期差）、fcst.rev 可省。hist 有效年 <3 或 fcst 空 → 返回空串）"""
    gp = fill.get("growth_plot") or {}
    hist = []
    for h in gp.get("hist") or []:
        y, npv = str(h.get("y") or "").strip(), _num(h.get("np"))
        if not y or npv is None:
            continue
        hist.append({"y": y, "rev": _num(h.get("rev")), "np": npv})
    fcst = []
    for f in gp.get("fcst") or []:
        y = str(f.get("y") or "").strip()
        lo, hi, cons = _num(f.get("np_lo")), _num(f.get("np_hi")), _num(f.get("np_consensus"))
        if not y or lo is None or hi is None or hi < lo or cons is None:
            continue
        fcst.append({"y": y, "lo": lo, "hi": hi, "cons": cons, "rev": _num(f.get("rev"))})
    if len(hist) < 3 or not fcst:
        return ""

    W, H, L, R, T, B = 1000, 288, 56, 20, 30, 48   # v4.9 二轮：高度 340→288（用户反馈再压低）
    n = len(hist) + len(fcst)
    slot = (W - L - R) / n
    all_v = [h["np"] for h in hist] + [h["rev"] for h in hist if h["rev"] is not None] \
        + [v for f in fcst for v in (f["lo"], f["hi"], f["cons"])] \
        + [f["rev"] for f in fcst if f["rev"] is not None]
    lo_d, hi_d = _pad_domain(min(all_v + [0]), max(all_v + [0]), 0.15)
    Y = _lin_map(lo_d, hi_d, H - B, T)
    y0 = Y(0)

    parts = ['<span class="section-tag">利润增长：历史 → 本文预测 vs 卖方一致</span>',
             _svg_open(W, H, "利润增长")]
    # 图例（左上，单行）
    lx = L
    for glyph, txt, c in ("rect", "收入增速（实际）", _C_SAND), ("rect", "净利增速（实际）", _C_BLUE):
        parts.append(f'<rect x="{lx}" y="8" width="13" height="9" rx="2.5" fill="{c}"/>')
        parts.append(f'<text x="{lx + 18}" y="16" font-size="11" fill="{_C_LABEL}">{txt}</text>')
        lx += 18 + _text_w(txt, 11) + 22
    parts.append(f'<rect x="{lx}" y="8" width="13" height="9" rx="2.5" fill="{_C_BLUE}" fill-opacity="0.3" '
                 f'stroke="{_C_BLUE}" stroke-width="1"/>')
    parts.append(f'<text x="{lx + 18}" y="16" font-size="11" fill="{_C_LABEL}">本文净利预测区间</text>')
    lx += 18 + _text_w("本文净利预测区间", 11) + 22
    parts.append(f'<polygon points="{lx + 6},8 {lx + 12},13 {lx + 6},18 {lx},13" fill="{_C_BLACK}"/>')
    parts.append(f'<text x="{lx + 18}" y="16" font-size="11" fill="{_C_LABEL}">卖方一致预期</text>')
    # 横网格 + y 轴刻度 + 零基线
    for t in _ticks(lo_d, hi_d, 5):
        gy = Y(t)
        parts.append(f'<line x1="{L}" y1="{gy:.1f}" x2="{W - R}" y2="{gy:.1f}" stroke="{_C_GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{L - 8}" y="{gy + 4:.1f}" text-anchor="end" font-size="11" '
                     f'fill="{_C_LABEL}">{_fmt(t)}%</text>')
    parts.append(f'<line x1="{L}" y1="{y0:.1f}" x2="{W - R}" y2="{y0:.1f}" stroke="{_C_AXIS}" stroke-width="1.4"/>')
    # 实际/预测分区虚线 + 区标签
    sep_x = L + len(hist) * slot
    parts.append(f'<line x1="{sep_x:.1f}" y1="{T}" x2="{sep_x:.1f}" y2="{H - B}" stroke="{_C_SAND_LT}" '
                 f'stroke-width="1" stroke-dasharray="5 4"/>')
    parts.append(f'<text x="{sep_x - 8:.1f}" y="{T + 12}" text-anchor="end" font-size="10.5" '
                 f'fill="{_C_LABEL}">实际</text>')
    parts.append(f'<text x="{sep_x + 8:.1f}" y="{T + 12}" font-size="10.5" fill="{_C_LABEL}">预测</text>')

    def _s(v):
        return f'{"+" if v > 0 else ""}{_fmt(v)}%'

    diffs = []
    for i, g in enumerate(hist + fcst):
        cx = L + i * slot + slot / 2
        if i < len(hist):   # 历史组：收入（沙）+净利（钢蓝）并列柱
            bw = min(slot * 0.3, 34)
            for k, (v, c) in enumerate(((g["rev"], _C_SAND), (g["np"], _C_BLUE))):
                if v is None:
                    continue
                x = cx - bw - 2 + k * (bw + 4)
                top, h = min(Y(v), y0), max(abs(y0 - Y(v)), 1)
                parts.append(f'<rect x="{x:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="3" fill="{c}"/>')
                parts.append(f'<text x="{x + bw / 2:.1f}" y="{top - 4:.1f}" text-anchor="middle" font-size="10" '
                             f'fill="{_C_INK if v == g["np"] else _C_LABEL}">{_s(v)}</text>')
            parts.append(f'<text x="{cx:.1f}" y="{H - B + 16}" text-anchor="middle" font-size="11" '
                         f'fill="{_C_LABEL}">{_esc(g["y"])}</text>')
        else:               # 预测组：本文区间竖条 + 一致预期◆ + 组下预期差
            bw = min(slot * 0.34, 38)
            x = cx - bw / 2
            parts.append(f'<rect x="{x:.1f}" y="{Y(g["hi"]):.1f}" width="{bw:.1f}" '
                         f'height="{max(Y(g["lo"]) - Y(g["hi"]), 2):.1f}" rx="4" fill="{_C_BLUE}" '
                         f'fill-opacity="0.3" stroke="{_C_BLUE}" stroke-width="1.2"/>')
            parts.append(f'<text x="{cx:.1f}" y="{Y(g["hi"]) - 5:.1f}" text-anchor="middle" font-size="10" '
                         f'fill="{_C_BLUE}">{_s(g["hi"])}</text>')
            parts.append(f'<text x="{cx:.1f}" y="{Y(g["lo"]) + 12:.1f}" text-anchor="middle" font-size="10" '
                         f'fill="{_C_BLUE}">{_s(g["lo"])}</text>')
            gy = Y(g["cons"])
            parts.append(f'<polygon points="{cx:.1f},{gy - 7:.1f} {cx + 7:.1f},{gy:.1f} {cx:.1f},{gy + 7:.1f} '
                         f'{cx - 7:.1f},{gy:.1f}" fill="{_C_BLACK}"/>')
            parts.append(f'<text x="{cx + 10:.1f}" y="{gy - 9:.1f}" font-size="10" '
                         f'stroke="#f7f2e7" stroke-width="3" paint-order="stroke" '
                         f'fill="{_C_BLACK}">一致 {_s(g["cons"])}</text>')
            d = (g["lo"] + g["hi"]) / 2 - g["cons"]
            diffs.append(f'{_esc(g["y"])} {d:+.1f}pct')
            parts.append(f'<text x="{cx:.1f}" y="{H - B + 16}" text-anchor="middle" font-size="11" '
                         f'font-weight="600" fill="{_C_INK}">{_esc(g["y"])}</text>')
            parts.append(f'<text x="{cx:.1f}" y="{H - B + 31}" text-anchor="middle" font-size="10" '
                         f'fill="{_C_STONE}">差 {d:+.1f}pct</text>')
    parts.append(_svg_close())
    parts.append('<span class="source">利润增长（脚本按 growth_plot 字段生成）：柱=历史增速（沙=收入、钢蓝=归母净利，'
                 '取 E3 年表同比），区间竖条=本文净利增速预测区间，◆=卖方一致预期（E5 研报汇总）；'
                 f'预期差（本文中枢−一致预期）：{"；".join(diffs)}；全图为中性色，红涨绿跌仅用于股价方向</span>')
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


def _inject_l3_charts(l3_html: str, fill: dict) -> str:
    """4.1 利润增长图锚点注入（v4.9）：l3_html 里的 <!--GROWTH--> 注释替换为脚本图；
    锚点缺失但字段已填 → 图追加第 4 章末尾 + 告警；字段未填（如未盈利分型豁免）→ 锚点静默清除。"""
    for anchor, html, field in (("<!--GROWTH-->", build_growth_plot(fill), "growth_plot"),):
        if anchor in l3_html:
            l3_html = l3_html.replace(anchor, html)
        elif html:
            l3_html += "\n" + html
            print(f"⚠️ l3_html 缺 {anchor} 锚点：{field} 图已追加到第 4 章末尾"
                  f"（建议把锚点放到 4.1 利润增长维度块首）", file=sys.stderr)
    return l3_html


_TRIG_STATUS = {"hit": ("已兑现", "hit"), "miss": ("未兑现", "miss"), "pending": ("待验证", "pending")}


def build_triggers_strip(fill: dict) -> str:
    """13 跟踪仪表盘·触发条件状态条（fill["triggers"] 可选字段，v4.10）：
    把 dash 触发条件结构化为状态条，垫在手写 dash_html 前。评价语义色：hit=绿 / miss=红 / pending=灰。
    triggers: [{"cond":"提价兑现","metric":"26H2 毛利率","target":"≥46%","status":"hit"}, ...]
    （status 三值：hit 已兑现 / miss 未兑现 / pending 待验证——首版报告全部 pending，
    回测模式填旧触发条件的核对结果；cond 必填，metric/target 可省。字段缺失/空 → 返回空串）"""
    rows = []
    for t in fill.get("triggers") or []:
        if not isinstance(t, dict):
            continue
        cond = str(t.get("cond") or "").strip()
        if not cond:
            continue
        status = str(t.get("status") or "pending").strip().lower()
        label, cls = _TRIG_STATUS.get(status, _TRIG_STATUS["pending"])
        metric = str(t.get("metric") or "").strip()
        target = str(t.get("target") or "").strip()
        mt = ""
        if metric or target:
            mt = (f'<span class="trig-mt">{_esc(metric)}'
                  + (f' {_esc(target)}' if target else "") + '</span>')
        rows.append(f'<div class="trig"><span class="trig-dot {cls}"></span>'
                    f'<span class="trig-cond">{_esc(cond)}</span>{mt}'
                    f'<span class="trig-status {cls}">{label}</span></div>')
    if not rows:
        return ""
    return ('<span class="section-tag">触发条件状态</span>'
            '<div class="trig-strip">' + "".join(rows) + '</div>'
            '<span class="source">触发条件状态（脚本按 triggers 字段生成）：绿=已兑现、红=未兑现、'
            '灰=待验证（评价色，与涨跌红绿无关）；status 由填写方按最新数据核对后标注</span>')
