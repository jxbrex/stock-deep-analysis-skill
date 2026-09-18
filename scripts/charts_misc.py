#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""charts_misc.py — 其余图族（v4.9 从 charts.py 拆出）：5.1 利润增长图（build_growth_plot，含 5 章锚点注入 _inject_l3_charts）/ 9 市场预期差逐机构分布图与 B 档哑铃（build_gap_plot + _inject_gap_chart）/ 12 股东户数趋势（build_holders_plot）/ 13 回测哑铃（build_review_dumbbell）/ 3 最新报告期透视四件套（build_period_summary/build_period_kpi/build_period_bullets/build_period_sqplot，v5.0 起、v5.0.1 重构——绝对额表删除，信息并入一览卡与子弹图刻度）。依赖 charts_base 与 scoring。"""


import math

from scoring import _num, _fmt, _esc
from charts_base import *

def build_growth_plot(fill: dict) -> str:
    """05 未来预期·5.1 利润增长图（fill["growth_plot"] 必填字段，锚点 <!--GROWTH-->，v4.9）：
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
    lx = _legend_row(parts, [("收入增速（实际）", _C_SAND), ("净利增速（实际）", _C_BLUE)], L)
    lx = _legend_row(parts, [("本文净利预测区间", _C_BLUE,
                              f'fill-opacity="0.3" stroke="{_C_BLUE}" stroke-width="1"')], lx)
    parts.append(f'<polygon points="{lx + 6},8 {lx + 12},13 {lx + 6},18 {lx},13" fill="{_C_BLACK}"/>')
    parts.append(f'<text x="{lx + 18}" y="16" font-size="11" fill="{_C_LABEL}">卖方一致预期</text>')
    # 横网格 + y 轴刻度 + 零基线
    _hgrid_ticks(parts, Y, _ticks(lo_d, hi_d, 5), L, W - R, L - 8, "%")
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
                         f'stroke="{_C_PAPER_CELL}" stroke-width="3" paint-order="stroke" '
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
    """12 仓位与时机决策·股东户数趋势（fill["holders"] 可选字段，E4 数据回填）：
    柱状图，暖灰柱=历史期、钢蓝柱=最新期；柱上=户数（千位符），柱下=截止日与环比——
    环比按筹码语义着色：户数增=筹码分散=红，户数减=集中=绿。
    holders: [{"date":"2025-03-31","num":188153,"chg":5.2}, ...]（旧→新，chg 为环比%，可省；
    v4.11.0 起照抄 E4「季度序列」行——季末口径近 12 期 + 最新点，间隔均匀；不定期披露点
    不再上图。有效点 <3 → 返回空串，静默跳过）"""
    pts = []
    for p in fill.get("holders") or []:
        d = str(p.get("date") or "").strip()
        num = _num(p.get("num"))
        if not d or num is None:
            continue
        pts.append({"date": d, "num": num, "chg": _num(p.get("chg"))})
    pts.sort(key=lambda r: r["date"])  # 旧→新
    # v4.11.0：同一截止日多行（E4 上游偶发重复，天齐 20260710 双行且变动值不一致实证）
    # → 去重保留后写行（先于 <3 门禁，去重后不足 3 期同样不生成；审计 P2：去重键按数字序列归一，
    # "20260710" 与 "2026-07-10" 视为同日）；横标重复（月内多期披露，天齐 2026-07 四期实证）→
    # 降精度到日，同年用 MM-DD、跨年用 YY-MM-DD，避免一排「26-07」
    dk = lambda ds: "".join(ch for ch in ds if ch.isdigit())
    pts = [p for i, p in enumerate(pts) if i == len(pts) - 1 or dk(pts[i + 1]["date"]) != dk(p["date"])]
    if len(pts) < 3:
        return ""

    def _hl(ds):
        digs = "".join(ch for ch in ds if ch.isdigit())
        if len(digs) >= 8:
            return digs[2:4], digs[4:6], digs[6:8]
        if len(digs) == 6:
            return digs[2:4], digs[4:6], None
        return None

    parsed = [_hl(p["date"]) for p in pts]
    labels = [f"{t[0]}-{t[1]}" if t else p["date"][:7] for t, p in zip(parsed, pts)]
    if len(set(labels)) < len(labels):
        same_year = len({t[0] for t in parsed if t}) <= 1
        labels = [(f"{t[1]}-{t[2]}" if t and t[2] and same_year else
                   f"{t[0]}-{t[1]}-{t[2]}" if t and t[2] else labels[i])
                  for i, t in enumerate(parsed)]

    W, H, L, R, T, B = 1000, 260, 60, 20, 40, 44
    n = len(pts)
    slot = (W - L - R) / n
    bar_w = min(slot * 0.5, 44)   # v4.11.0：季度序列柱数上探 12+，柱宽封顶下调（72→44）
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
                     f'font-size="10.5" fill="{_C_LABEL}">{_esc(labels[i])}</text>')
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
    """13 回测复盘·三轨分新旧对比哑铃图（0-10 定域）：灰点=上版、蓝点=本版，
    连线带箭头（方向=上版→本版），绿=上调、红=下调，右列=分差。prev 为空 → 返回空串。"""
    if not prev:
        return ""
    rows = _prev_track_rows(prev, quality, valuation, timing)
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
        d = r["d"]
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
    """5.1 利润增长图锚点注入（v4.9；v4.10.2 收编进 charts_base _inject_chart_anchors，与第 4 章
    _inject_l1_charts 同一注入机）：l3_html 里的 <!--GROWTH--> 注释替换为脚本图；
    锚点缺失但字段已填 → 图追加第 5 章末尾 + 告警；字段未填（如未盈利分型豁免）→ 锚点静默清除。"""
    return _inject_chart_anchors(
        l3_html,
        (("<!--GROWTH-->", build_growth_plot(fill), "growth_plot"),),
        "l3_html", "第 5 章末尾", "建议把锚点放到 5.1 利润增长维度块首")


_TRIG_STATUS = {"hit": ("已兑现", "hit"), "miss": ("未兑现", "miss"), "pending": ("待验证", "pending")}


def build_triggers_strip(fill: dict) -> str:
    """14 跟踪仪表盘·触发条件状态条（fill["triggers"] 可选字段，v4.9）：
    把 dash 触发条件结构化为状态条，垫在手写 dash_html 前。评价语义色：hit=绿 / miss=红 / pending=灰。
    triggers: [{"cond":"提价兑现","metric":"26H2 毛利率","target":"≥46%","status":"hit"}, ...]
    （status 三值：hit 已兑现 / miss 未兑现 / pending 待验证——首版报告全部 pending，
    回测模式填旧触发条件的核对结果；cond 必填，metric/target 可省。字段缺失/空 → 返回空串；
    v4.10.3：全 pending（首版报告）同样返回空串不渲染——无核对结果的状态条只是噪音）"""
    rows = []
    verdict = False
    for t in fill.get("triggers") or []:
        if not isinstance(t, dict):
            continue
        cond = str(t.get("cond") or "").strip()
        if not cond:
            continue
        status = str(t.get("status") or "pending").strip().lower()
        label, cls = _TRIG_STATUS.get(status, _TRIG_STATUS["pending"])
        if cls != "pending":
            verdict = True
        metric = str(t.get("metric") or "").strip()
        target = str(t.get("target") or "").strip()
        mt = ""
        if metric or target:
            mt = (f'<span class="trig-mt">{_esc(metric)}'
                  + (f' {_esc(target)}' if target else "") + '</span>')
        rows.append(f'<div class="trig"><span class="trig-dot {cls}"></span>'
                    f'<span class="trig-cond">{_esc(cond)}</span>{mt}'
                    f'<span class="trig-status {cls}">{label}</span></div>')
    if not rows or not verdict:
        return ""
    return ('<span class="section-tag">触发条件状态</span>'
            '<div class="trig-strip">' + "".join(rows) + '</div>'
            '<span class="source">触发条件状态（脚本按 triggers 字段生成）：绿=已兑现、红=未兑现、'
            '灰=待验证（评价色，与涨跌红绿无关）；status 由填写方按最新数据核对后标注</span>')


# ════════════════════ 8 市场预期差拆解 · 逐机构分布图 / B 档哑铃 ════════════════════

_GAP_CIRCLED = "①②③④⑤⑥"   # 行号（图行 / gap-notes 附注 / 图例共用一套编号）


def _px(v) -> str:
    """坐标格式化：保留 1 位小数、整数去尾（386.7 / 520），与 demo 定稿的写法一致。"""
    s = f"{float(v):.1f}"
    return s[:-2] if s.endswith(".0") else s


def _gap_fmt(v, pt: bool = False) -> str:
    """gap 图数值标签：比率型维度（pct_pt）保底一位小数（24 → 24.0），其余 %g 去尾零；
    非比率大数值（|v| ≥ 10000，如出货量原生单位）改千分位整数，防 %g 科学计数法上轴
    （审计 P2-3：_fmt(1234567)='1.23457e+06'）。"""
    s = f"{v:,.0f}" if not pt and abs(v) >= 10000 else _fmt(v)
    return s + ".0" if pt and "." not in s else s


def _gap_axis(lo0: float, hi0: float):
    """A 档行轴定域：数据 ±10% 垫域；步长取 {1,2,3,5}×10^k 中域内刻度 ≤5 个的最小档；
    域边就近吸到 step/4 量级网格（step 为 3/5×10^k 时网格取 10^k），随后保证数据点不贴边。
    返回 (lo, hi, step)。"""
    span = hi0 - lo0
    pad = span * 0.1 if span > 0 else max(abs(hi0) * 0.1, 1)
    lo_p, hi_p = lo0 - pad, hi0 + pad
    k0 = int(math.floor(math.log10(hi_p - lo_p))) - 1
    step, mag = None, 1
    for k in range(k0, k0 + 8):
        for m in (1, 2, 3, 5):
            st = m * 10.0 ** k
            cnt = math.ceil(hi_p / st - 1e-9) - (math.floor(lo_p / st + 1e-9) + 1)
            if cnt <= 5:
                step, mag = st, {1: 0.25, 2: 0.5, 3: 1.0, 5: 1.0}[m] * 10.0 ** k
                break
        if step is not None:
            break
    if step is None:
        step, mag = hi_p - lo_p, (hi_p - lo_p) / 4
    lo = math.floor(lo_p / mag + 0.5 + 1e-9) * mag
    hi = math.floor(hi_p / mag + 0.5 + 1e-9) * mag
    while lo >= lo0:   # 就近吸网格后仍须包住数据（点不落域边）
        lo -= mag
    while hi <= hi0:
        hi += mag
    return round(lo, 9), round(hi, 9), step


def _gap_ticks(lo: float, hi: float, step: float) -> list:
    """严格落在开区间 (lo, hi) 内的 step 整数倍刻度。"""
    out, k = [], math.floor(lo / step + 1e-9) + 1
    while k * step < hi - 1e-9:
        out.append(round(k * step, 9))
        k += 1
    return out


def build_gap_plot(fill: dict) -> str:
    """09 市场预期差拆解图（fill["gap_plot"] 可选字段，缺失/有效维度 <2 → 返回空串不告警，同 holders 惯例）。

    A 档（dims 带 street 逐机构明细）= 横向分布定位：一个点=一家机构近 180 天最新预测
    （灰=其他机构不标名 / 橙=major 头部外资标名 / 蓝=本文白描边压轴 / 黑◆=一致预期均值），
    右列=本文相对一致偏离 %（脚本算 ours/consensus−1）；street 整体缺失 → B 档偏离哑铃
    （灰点=卖方一致固定零轴，蓝点=本文，棒长∝相对偏离，定域 -10%~+15%）；部分行缺 street →
    仍按 A 档渲染，该行只画 本文/◆ 两点（行级退化）。
    dims: [{"name","ours","consensus","cover"?,"pct_pt"?,"reverse"?,"note"?,
            "street"?=[{"org"?,"v","major"?}]}]，name/ours/consensus 必填，consensus ≤0 的行剔除；
    cover 可省（默认按 street 家数「N 家覆盖」，无明细行「未见逐机构明细」）；pct_pt=比率型维度
    （数值保底一位小数，B 档行注追加原生 pct 点差）；reverse=反推口径维度（B 档行注/图源标注）。
    行数 2–6（超出取前 6）。
    防叠三层：① 与本文过近（<12px）的灰点钉轴，本文点白描边压轴压盖；② 灰点间距 <12px →
    一上一下对称泳道错位（±9px，簇起始向按值哈希，确定性）；③ 同值灰点合并为大点。
    ◆ 标签落位阶梯：轴下左 → 轴下右 → 省略与 ◆ 过近（≤30px）的刻度（等值刻度由 ◆ 标签承载）。"""
    gp = fill.get("gap_plot") or {}
    dims = []
    for d in gp.get("dims") or []:
        if not isinstance(d, dict):
            continue
        name = str(d.get("name") or "").strip()
        ours, cons = _num(d.get("ours")), _num(d.get("consensus"))
        if not name or ours is None or cons is None or cons <= 0:
            continue
        street = []
        for s in d.get("street") or []:
            if not isinstance(s, dict):
                continue
            v = _num(s.get("v"))
            if v is None:
                continue
            org = str(s.get("org") or "").strip()
            street.append({"v": v, "org": org, "major": bool(s.get("major")) and bool(org)})
        dims.append({"name": name, "ours": ours, "cons": cons, "street": street,
                     "cover": str(d.get("cover") or "").strip(),
                     "pt": bool(d.get("pct_pt")), "rev": bool(d.get("reverse"))})
    if len(dims) < 2:
        return ""
    dims = dims[:6]
    if any(d["street"] for d in dims):
        return _gap_plot_a(dims)
    return _gap_plot_b(dims)


def _gap_plot_a(dims: list) -> str:
    """A 档主形态：逐机构横向分布定位（demo v3 定稿版式：轴 x∈[280,840]、行距 70、右列 x=880）。"""
    n = len(dims)
    parts = ['<span class="section-tag">卖方分布 vs 本文假设 · 逐机构定位</span>',
             _svg_open(1000, 30 + 70 * n, "市场预期差机构分布图")]
    # 图例行（位置为定稿固定值）
    parts.append(f'<circle cx="62" cy="12" r="5" fill="{_C_SAND}"/>'
                 f'<text x="73" y="16" font-size="11" fill="{_C_LABEL}">其他机构预测</text>')
    parts.append(f'<circle cx="180" cy="12" r="5.5" fill="{_C_ORANGE}"/>'
                 f'<text x="192" y="16" font-size="11" fill="{_C_LABEL}">头部/外资机构（标名称）</text>')
    parts.append(f'<circle cx="352" cy="12" r="7" fill="{_C_BLUE}" stroke="{_C_PAPER}" stroke-width="2"/>'
                 f'<text x="365" y="16" font-size="11" fill="{_C_LABEL}">本文假设</text>')
    parts.append(f'<polygon points="470,6 476,12 470,18 464,12" fill="{_C_BLACK}"/>'
                 f'<text x="483" y="16" font-size="11" fill="{_C_LABEL}">一致预期（E5 均值）</text>')
    nums = "".join(_GAP_CIRCLED[i] for i in range(n))
    parts.append(f'<text x="600" y="16" font-size="11" fill="{_C_LABEL}">行号 {nums} 对应图下附注 · '
                 f'右列=本文相对一致偏离</text>')
    parts.append(f'<text x="880" y="32" font-size="11" fill="{_C_LABEL}">本文 vs 一致</text>')
    for i, d in enumerate(dims):
        ay = 70 + 70 * i
        pt = d["pt"]
        vals = [s["v"] for s in d["street"]] + [d["ours"], d["cons"]]
        lo, hi, step = _gap_axis(min(vals), max(vals))
        X = _lin_map(lo, hi, 280, 840)
        xc, x_ours = X(d["cons"]), X(d["ours"])
        parts.append(f'<text x="240" y="{ay - 26}" text-anchor="end" font-size="12.5" font-weight="600" '
                     f'fill="{_C_INK}">{_GAP_CIRCLED[i]} {_esc(d["name"])}</text>')
        cover = d["cover"] or (f'{len(d["street"])} 家覆盖' if d["street"] else "未见逐机构明细")
        if i == 0:
            cover += " · 近 180 天研报"
        parts.append(f'<text x="240" y="{ay - 12}" text-anchor="end" font-size="10.5" '
                     f'fill="{_C_LABEL}">{_esc(cover)}</text>')
        parts.append(f'<line x1="280" y1="{ay}" x2="840" y2="{ay}" stroke="{_C_AXIS}" stroke-width="1.2"/>')
        # 刻度：先省略与 ◆ 过近（≤30px）者（等值刻度由 ◆ 标签承载）
        ticks = [t for t in _gap_ticks(lo, hi, step) if abs(X(t) - xc) > 30]

        def _tick_rect(t):
            tw = _text_w(_gap_fmt(t, pt), 10.5)
            return X(t) - tw / 2, X(t) + tw / 2

        def _hit(rect):
            return any(rect[0] < tr[1] and tr[0] < rect[1] for tr in map(_tick_rect, ticks))

        # ◆ 标签落位阶梯：轴下左 → 轴下右 → 两侧皆撞则省略冲突刻度回轴下左
        cons_label = f"一致 {_gap_fmt(d['cons'], pt)}"
        lw = _text_w(cons_label, 10.5)
        left_rect = (xc - 12 - lw, xc - 12)
        if not _hit(left_rect):
            cons_anchor, cons_x = "end", xc - 12
        elif not _hit((xc + 10, xc + 10 + lw)):
            cons_anchor, cons_x = "start", xc + 10
        else:
            ticks = [t for t in ticks
                     if not (left_rect[0] < _tick_rect(t)[1] and _tick_rect(t)[0] < left_rect[1])]
            cons_anchor, cons_x = "end", xc - 12
        for t in ticks:
            parts.append(f'<text x="{_px(X(t))}" y="{ay + 16}" text-anchor="middle" font-size="10.5" '
                         f'fill="{_C_LABEL}">{_gap_fmt(t, pt)}</text>')
        # 灰点：同值合并大点 → 防叠①钉轴 / ②泳道错位
        groups = []
        for v in sorted(s["v"] for s in d["street"] if not s["major"]):
            if groups and v == groups[-1][0]:
                groups[-1][1] += 1
            else:
                groups.append([v, 1])
        lanes = [0.0] * len(groups)
        j = 0
        while j < len(groups):   # 相邻间距 <12px 的点连成簇；簇内非钉轴点 ≥2 才一上一下错位
            k = j + 1
            while k < len(groups) and X(groups[k][0]) - X(groups[k - 1][0]) < 12:
                k += 1
            free = [m for m in range(j, k) if abs(X(groups[m][0]) - x_ours) >= 12]
            if len(free) >= 2:
                dir0 = 1 if int(round(abs(groups[free[0]][0]) * 1000)) % 2 == 0 else -1
                for idx, m in enumerate(free):
                    lanes[m] = dir0 * (9 if idx % 2 == 0 else -9)
            j = k
        for (v, cnt), lane in zip(groups, lanes):
            r = 4.5 if cnt == 1 else min(4.5 + 1.5 * (cnt - 1), 7.5)
            parts.append(f'<circle cx="{_px(X(v))}" cy="{_px(ay + lane)}" r="{_px(r)}" fill="{_C_SAND}"/>')
        # 橙点（major 头部/外资）+ 具名标签；标签同行碰撞时移高一档（-16 → -24）；
        # 审计 P1-1/P1-2：lvl1 标签同样入册，且 lvl1（ay-24）与本文标签（ay-30）纵向带相交、
        # 跨带查 x 交叠；两档皆撞 → 标签降级为仅机构名（点永不删，定稿纪律）
        ours_label = f"本文 {_gap_fmt(d['ours'], pt)}"
        ours_rect = (x_ours - _text_w(ours_label, 11.5) / 2, x_ours + _text_w(ours_label, 11.5) / 2)
        bands = {0: [], 1: []}

        def _free(rect, lvl):
            pool = bands[lvl] + ([ours_rect] if lvl == 1 else [])
            return not any(rect[0] < b1 and b0 < rect[1] for b0, b1 in pool)

        for s in sorted((s for s in d["street"] if s["major"]), key=lambda s: s["v"]):
            x = X(s["v"])
            label = f'{s["org"]} {_gap_fmt(s["v"], pt)}'
            w = _text_w(label, 10.5)
            rect = (x - w / 2, x + w / 2)
            lvl = 0 if _free(rect, 0) else 1
            if lvl == 1 and not _free(rect, 1):
                label = s["org"]   # 降级仅机构名
                w = _text_w(label, 10.5)
                rect = (x - w / 2, x + w / 2)
                if not _free(rect, 1) and _free(rect, 0):
                    lvl = 0
            bands[lvl].append(rect)
            parts.append(f'<circle cx="{_px(x)}" cy="{ay}" r="5.5" fill="{_C_ORANGE}"/>'
                         f'<text x="{_px(x)}" y="{ay - (24 if lvl else 16)}" text-anchor="middle" '
                         f'font-size="10.5" font-weight="600" fill="{_C_BADGE_DEEP["badge-orange"]}">'
                         f'{_esc(label)}</text>')
        # 本文点压轴绘制（白描边压盖近点）+ ◆ 一致预期
        parts.append(f'<circle cx="{_px(x_ours)}" cy="{ay}" r="7.5" fill="{_C_BLUE}" '
                     f'stroke="{_C_PAPER}" stroke-width="2"/>'
                     f'<text x="{_px(x_ours)}" y="{ay - 30}" text-anchor="middle" font-size="11.5" '
                     f'font-weight="700" fill="{_C_BLUE}">本文 {_gap_fmt(d["ours"], pt)}</text>')
        parts.append(f'<polygon points="{_px(xc)},{_px(ay - 6.5)} {_px(xc + 6)},{ay} '
                     f'{_px(xc)},{_px(ay + 6.5)} {_px(xc - 6)},{ay}" fill="{_C_BLACK}"/>')
        anchor_attr = f' text-anchor="{cons_anchor}"' if cons_anchor == "end" else ""
        parts.append(f'<text x="{_px(cons_x)}" y="{ay + 22}"{anchor_attr} font-size="10.5" '
                     f'fill="{_C_STONE}">{_esc(cons_label)}</text>')
        pct = (d["ours"] / d["cons"] - 1) * 100
        parts.append(f'<text x="880" y="{_px(ay + 4.5)}" font-size="13" font-weight="700" '
                     f'fill="{_C_INK}">{pct:+.1f}%</text>')
    parts.append(_svg_close())
    parts.append('<span class="source">机构分布定位图（脚本按 gap_plot 字段生成）：一个点=一家机构近 180 天研报预测'
                 '（E5 逐研报明细回填，同机构多份取最新）；沙=其他机构、橙=头部/外资（标名称）、蓝=本文、'
                 '◆=一致预期均值；各维度独立原生单位轴，行内比较有效、跨行比偏离看右列；'
                 '近点处理=本文点白描边压轴压盖（值接近时灰点露月牙）、灰点间对称泳道错位，'
                 '◆ 标签与刻度冲突时右移或省略等值刻度</span>')
    return "".join(parts)


def _gap_plot_b(dims: list) -> str:
    """B 档兜底形态：零轴偏离哑铃（street 整体缺失时）——灰点=卖方一致预期（固定零轴），蓝点=本文，
    棒长∝相对偏离 %（定域 -10%~+15%，跨行可比）；reverse 维度行注/图源标「反推」口径。"""
    n = len(dims)
    y2 = 62 * n + 38
    X = _lin_map(-10, 15, 290, 850)
    zx = X(0)
    has_rev = any(d["rev"] for d in dims)
    # 审计 P1-3：tag 的「（反推口径）」只在确有 reverse 行时输出（纯 B 档不误标）
    tag = "卖方一致预期 vs 本文假设 · 偏离拆解（反推口径）" if has_rev \
        else "卖方一致预期 vs 本文假设 · 偏离拆解"
    parts = [f'<span class="section-tag">{tag}</span>',
             _svg_open(1000, y2 + 26, "市场预期差哑铃图（B 档）")]
    parts.append(f'<circle cx="62" cy="12" r="6" fill="{_C_SAND}"/>'
                 f'<text x="74" y="16" font-size="11" fill="{_C_LABEL}">卖方一致预期（零轴）</text>')
    parts.append(f'<circle cx="222" cy="12" r="7" fill="{_C_BLUE}" stroke="{_C_PAPER}" stroke-width="2"/>'
                 f'<text x="235" y="16" font-size="11" fill="{_C_LABEL}">本文假设</text>')
    parts.append(f'<text x="330" y="16" font-size="11" fill="{_C_LABEL}">蓝点偏右=本文高于卖方，偏左=低于；'
                 f'棒长 ∝ 相对偏离幅度，跨行可比</text>')
    for v, txt in ((-10, "-10%"), (-5, "-5%"), (5, "+5%"), (10, "+10%"), (15, "+15%")):
        parts.append(f'<line x1="{_px(X(v))}" y1="30" x2="{_px(X(v))}" y2="{y2}" stroke="{_C_GRID}" '
                     f'stroke-width="1"/>'
                     f'<text x="{_px(X(v))}" y="{y2 + 16}" text-anchor="middle" font-size="11" '
                     f'fill="{_C_LABEL}">{txt}</text>')
    parts.append(f'<line x1="{_px(zx)}" y1="30" x2="{_px(zx)}" y2="{y2}" stroke="{_C_AXIS}" stroke-width="1.6"/>'
                 f'<text x="{_px(zx)}" y="{y2 + 16}" text-anchor="middle" font-size="11" font-weight="700" '
                 f'fill="{_C_STONE}">0</text>')
    parts.append(f'<text x="872" y="34" font-size="11" fill="{_C_LABEL}">相对偏离</text>')
    any_clamped = []
    for i, d in enumerate(dims):
        cy = 71 + 62 * i
        pt = d["pt"]
        pct = (d["ours"] / d["cons"] - 1) * 100
        # 审计 P2-1：偏离超出定域（-10%~+15%）时点位被夹在边界——虚线棒+空心点作截断记号，
        # 数值仍以右列为准（点位视觉不得撒谎）
        clamped = pct < -10 or pct > 15
        if clamped:
            any_clamped.append(True)
        suffix = "%" if pt else ""
        parts.append(f'<text x="255" y="{cy - 8}" text-anchor="end" font-size="12.5" font-weight="600" '
                     f'fill="{_C_INK}">{_GAP_CIRCLED[i]} {_esc(d["name"])}</text>')
        extra = []
        if pt:
            extra.append(f'{d["ours"] - d["cons"]:+g}pct')
        if d["rev"]:
            extra.append("反推")
        note = (f'卖方 {_gap_fmt(d["cons"], pt)}{suffix} → 本文 {_gap_fmt(d["ours"], pt)}{suffix}'
                + (f'（{"，".join(extra)}）' if extra else ""))
        parts.append(f'<text x="255" y="{cy + 8}" text-anchor="end" font-size="10.5" '
                     f'fill="{_C_LABEL}">{_esc(note)}</text>')
        dx = X(max(-10, min(15, float(f"{pct:.1f}"))))   # 定位与右列显示同值（所见即所量）
        s = 1 if pct >= 0 else -1
        far = abs(dx - zx) >= 26   # 偏离过近时不画箭头（同 13 章回测哑铃惯例）
        dash = ' stroke-dasharray="4 3"' if clamped else ""
        parts.append(f'<line x1="{_px(zx)}" y1="{cy}" x2="{_px(dx - 19 * s) if far else _px(dx)}" '
                     f'y2="{cy}" stroke="{_C_BLUE}" stroke-width="3"{dash}/>')
        if far:
            tip = dx - 10 * s   # 箭头尖贴到蓝点圆缘（r=7.5 + 描边 2）
            parts.append(f'<polygon points="{_px(tip)},{cy} {_px(tip - 9 * s)},{cy - 5.5} '
                         f'{_px(tip - 9 * s)},{cy + 5.5}" fill="{_C_BLUE}"/>')
        parts.append(f'<circle cx="{_px(zx)}" cy="{cy}" r="6" fill="{_C_SAND}"/>')
        if clamped:
            parts.append(f'<circle cx="{_px(dx)}" cy="{cy}" r="7.5" fill="{_C_PAPER}" '
                         f'stroke="{_C_BLUE}" stroke-width="2"/>')
        else:
            parts.append(f'<circle cx="{_px(dx)}" cy="{cy}" r="7.5" fill="{_C_BLUE}" '
                         f'stroke="{_C_PAPER}" stroke-width="2"/>')
        parts.append(f'<text x="872" y="{_px(cy + 4.5)}" font-size="13" font-weight="700" '
                     f'fill="{_C_INK}">{pct:+.1f}%</text>')
    parts.append(_svg_close())
    src = ('<span class="source">预期差哑铃图（脚本按 gap_plot 字段生成，B 档）：灰点=卖方一致预期（固定零轴），'
           '蓝点=本文；横轴=本文相对卖方偏离 %；比率型维度按相对偏离定位，原生差值（+1.5pct）写进行注')
    rev_nums = "".join(_GAP_CIRCLED[i] for i, d in enumerate(dims) if d["rev"])
    if rev_nums:
        src += f'；{rev_nums} 为反推口径——卖方未披露该维度假设，由一致净利/目标价反推'
    if any_clamped:
        src += '；虚线棒+空心蓝点=偏离超出 -10%~+15% 定域，按右列数值为准'
    parts.append(src + '</span>')
    return "".join(parts)


def _gap_notes_html(gp: dict) -> str:
    """gap-notes 附注（图下编号注）：dims[].note 按行序（①②… 与图行一一对应）+ text_dims 续编号
    文本项。内容为填写方直写 HTML（含 <b>① 短名：</b> 前缀，图已有数值不复述），脚本只包 <li>；
    无任何附注 → 空串。"""
    items = []
    for d in (gp.get("dims") or [])[:6]:   # 与图行截断同口径（审计 P2-2：附注不得指向未画的行）
        if not isinstance(d, dict):
            continue
        note = str(d.get("note") or "").strip()
        if note:
            items.append(f"<li>{note}</li>")
    for t in gp.get("text_dims") or []:
        t = str(t or "").strip()
        if t:
            items.append(f"<li>{t}</li>")
    return '<ol class="gap-notes">' + "".join(items) + "</ol>" if items else ""


def _inject_gap_chart(gap_html: str, fill: dict) -> str:
    """9 预期差图锚点注入（与 _inject_l3_charts 同一注入机）：gap_html 里的 <!--GAP--> 注释
    原位替换为「图 + <ol class="gap-notes"> 附注」整体；锚点缺失但字段已填 → 垫第 9 章章首 +
    告警（prepend——图是本章主体）；字段未填 → 锚点静默清除；维度不足但有附注 →
    锚点替换为纯附注（C 档信息不丢，图不生成）。"""
    block = build_gap_plot(fill) + _gap_notes_html(fill.get("gap_plot") or {})
    return _inject_chart_anchors(
        gap_html,
        (("<!--GAP-->", block, "gap_plot"),),
        "gap_html", "第 9 章章首", "建议把锚点放到档位说明段之后", prepend=True)


# ════════════════════ 2 关键利润驱动 · 驱动卡 / 11 周期规律 · 阶段卡（v4.11.3） ════════════════════

def build_driver_cards(fill: dict) -> str:
    """2 关键利润驱动·驱动卡（fill["drivers"] + fill["driver_verdict"]，v4.11.3）：
    1-2 个关键利润驱动各一张卡——弹性值（大字号）+ 备注（当前值/撕扯力量）+ 三情景锚标签；
    第一变量带 drv-badge 角标；卡下判词横条（.layer-summary）承载「为什么 X 是第一变量」
    （v4.11.3 起替代 p0_html 手写 info-card）。
    drivers: [{"name":"单Wh净利（单位盈利）","first_var":true,
               "elastic":"±0.01元/Wh → 净利 ±100亿","elastic_sub":"±10.6%，1,000GWh 基数",
               "note":"当前约 0.10元/Wh。……",
               "chips":[{"label":"悲观","value":"0.085"},{"label":"基础","value":"0.095–0.10"},
                        {"label":"乐观","value":"0.105"},{"label":"元/Wh","unit":true}]}, ...]
    （chips 恰 3 情景档 + 可选 1 个 unit 标签；字段缺失/空 → 返回空串）"""
    drivers = [d for d in fill.get("drivers") or [] if isinstance(d, dict)]
    cards = []
    for d in drivers:
        name = str(d.get("name") or "").strip()
        elastic = str(d.get("elastic") or "").strip()
        if not name or not elastic:
            continue
        badge = '<span class="drv-badge">第一变量</span>' if d.get("first_var") else ""
        sub = str(d.get("elastic_sub") or "").strip()
        sub_html = f'<span class="unit">（{_esc(sub)}）</span>' if sub else ""
        note = str(d.get("note") or "").strip()
        note_html = f'<div class="drv-note">{_esc(note)}</div>' if note else ""
        chips = []
        for c in d.get("chips") or []:
            if not isinstance(c, dict):
                continue
            label = str(c.get("label") or "").strip()
            if not label:
                continue
            if c.get("unit"):
                chips.append(f'<span>{_esc(label)}</span>')
            else:
                value = str(c.get("value") or "").strip()
                chips.append(f'<span>{_esc(label)} <b>{_esc(value)}</b></span>')
        chips_html = f'<div class="drv-chips">{"".join(chips)}</div>' if chips else ""
        cards.append(
            f'<div class="drv"><div class="drv-head"><span class="drv-name">{_esc(name)}</span>{badge}</div>'
            f'<div class="drv-elastic">{_esc(elastic)}{sub_html}</div>'
            f'{note_html}{chips_html}</div>')
    if not cards:
        return ""
    verdict = str(fill.get("driver_verdict") or "").strip()
    verdict_html = ""
    if verdict:
        first = next((d for d in drivers if d.get("first_var")), None)
        first_name = str((first or {}).get("name") or "").strip()
        lead = f"为什么{_esc(first_name)}是第一变量：" if first_name else "第一变量判词："
        verdict_html = f'<div class="layer-summary"><strong>{lead}</strong>{_esc(verdict)}</div>'
    return '<div class="drv-strip">' + "".join(cards) + '</div>' + verdict_html


def build_cycle_stages(fill: dict) -> str:
    """11 周期规律·阶段卡（fill["cycle_stages"]，v4.11.3）：阶段拆解从手写表格改为步骤卡网格
    ——大序号 + 阶段名 + 加粗日期/PE/股价行 + 一句驱动（显示宽 ≤48，灭孤字），本轮高亮 + 「本轮」角标。
    顺序由序号与 Z 字阅读承载，网格去箭头（03→04 跨行箭头会误指 06 的 demo 实证）。
    cycle_stages: [{"name":"赛道泡沫期","period":"2021/01–2022/04","pe":"60–216x",
                    "price":"162–355","driver":"新能源爆发初期赛道溢价；碳酸锂 5万→50万/吨",
                    "current":false}, ...]
    （3-6 项、恰 1 个 current；字段缺失/空 → 返回空串，cycle_html 手写阶段表旧形态不受影响）"""
    cards = []
    for s in fill.get("cycle_stages") or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "").strip()
        period = str(s.get("period") or "").strip()
        if not name or not period:
            continue
        cur = bool(s.get("current"))
        cls = "stage current" if cur else "stage"
        tag = '<span class="stage-cur-tag">本轮</span>' if cur else ""
        pe = str(s.get("pe") or "").strip()
        price = str(s.get("price") or "").strip()
        meta = " ｜ ".join(p for p in (_esc(period),
                                      f"PE {_esc(pe)}" if pe else "",
                                      f"股价 {_esc(price)}" if price else "") if p)
        driver = str(s.get("driver") or "").strip()
        driver_html = f'<div class="stage-driver">{_esc(driver)}</div>' if driver else ""
        cards.append(
            f'<div class="{cls}">{tag}<div class="stage-top"><span class="stage-num">{len(cards) + 1:02d}</span>'
            f'<span class="stage-name">{_esc(name)}</span></div>'
            f'<div class="stage-meta">{meta}</div>{driver_html}</div>')
    if not cards:
        return ""
    return '<div class="stage-strip">' + "".join(cards) + '</div>'



# ════════════════════ 3 最新报告期透视（v5.0.1）：进度小结条 / 累计一览卡 / 进度子弹图 / 单季双联图 ════════════════════

_PERIOD_VERDICTS = ("超前", "正常", "滞后", "无法判定")
# 判词徽章色（SVG 内联 fill，与模板 badge 色系同源）：超前=绿 / 滞后=红（复用 _C_BADGE_DEEP），
# 正常=灰 / 无法判定=浅灰（浅沙底+深灰字）
_PERIOD_VERDICT_FILL = {"超前": _C_BADGE_DEEP["badge-green"], "正常": _C_LABEL,
                        "滞后": _C_BADGE_DEEP["badge-red"], "无法判定": _C_SAND_LT}
_PERIOD_VERDICT_BADGE = {"超前": "badge-green", "正常": "badge-gray",
                         "滞后": "badge-red", "无法判定": "badge-gray"}
# 子弹图行配置（标签, 累计键, 同比键, 判词键, 经营目标键, 一致预期键, 节奏带键）。
# v5.0.1 起仅「有金额化全年参照」（经营目标/一致预期任一非 None）的行才画——无分母时轨道右端
# 退化为累计值×1.08，空段是零信息绘图留白（旧版被误读为「全年任务未完成」）；扣非天然无
# 分母口径（经营目标/一致预期均为营收或归母净利口径），不再入图。无参照行的累计值由一览卡承接
_PERIOD_ROWS = (("营业收入", "rev", "rev_yoy", "verdict_rev", "goal_rev", None, "band_rev"),
                ("归母净利", "np", "np_yoy", "verdict_np", "goal_np", "consensus_np", "band_np"))
# 累计一览卡行配置（标签, 累计键, 同比键）：四行全出，无分母口径要求
_PERIOD_KPI_ROWS = (("营业收入", "rev", "rev_yoy"), ("归母净利", "np", "np_yoy"),
                    ("扣非净利", "np_dedt", "np_dedt_yoy"), ("经营现金流", "ocf", "ocf_yoy"))
# 小结条徽章行配置（标签, 累计键, 判词键；经营现金流不设判词——波动受回款节奏支配，判词易误导）
_PERIOD_SUMMARY_ROWS = (("营业收入", "rev", "verdict_rev"), ("归母净利", "np", "verdict_np"),
                        ("扣非净利", "np_dedt", "verdict_dedt"))
# 单季双联图组配置（联标题, ((标签, 上年同季键, 最新单季键, 单季同比键), ...)）：
# 左联=收入与经营现金流（规模与收现含金量），右联=归母与扣非（利润口径，两柱差额≈非经常项）
_PERIOD_SQ_PANELS = (
    ("收入与经营现金流", (("营业收入", "sq_prev_rev", "sq_rev", "sq_rev_yoy"),
                        ("经营现金流", "sq_prev_ocf", "sq_ocf", "sq_ocf_yoy"))),
    ("归母与扣非", (("归母净利", "sq_prev_np", "sq_np", "sq_np_yoy"),
                    ("扣非净利", "sq_prev_dedt", "sq_dedt", "sq_dedt_yoy"))))


def _pamt(v) -> str:
    """第 3 章图内金额标签（亿元）：≥100 整数带千位符；<100 两位小数去尾零（92.10→92.1、60.67→60.67）。"""
    if v is None:
        return "—"
    if abs(v) >= 100:
        return f"{v:,.0f}"
    s = f"{v:.2f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _pyoy_txt(v) -> str:
    """同比标注文本：数值 → +32.3%（一位小数带符号）；文字（扭亏/转亏/减亏/增亏）原样；None → ""。"""
    if isinstance(v, (int, float)):
        return f"{v:+.1f}%"
    return str(v or "").strip()


def _period_verdict(pt: dict, key: str) -> str:
    """判词读取：缺失/非法值兜底「无法判定」（非法值在 validate 已被拒渲染，此处仅渲染兜底）。"""
    v = str(pt.get(key) or "").strip()
    return v if v in _PERIOD_VERDICTS else "无法判定"


def build_period_summary(pt: dict) -> str:
    """3 章·进度小结条（period_track，v5.0.1）：章首总览——判词徽章行（脚本按 verdict_* 合成，
    缺判词按「无法判定」渲染，与子弹图徽章同口径）+ 无全年参照指标点名 + 模型手填一句
    （summary_html ≤2 句，只许陈述进度事实与完成度，论证归 4.4/5.1/9 章；可空）。
    三个判词指标金额全 None 且 summary_html 空 → 返回空串。"""
    if not isinstance(pt, dict):
        return ""
    badges = []
    no_ref = []
    for label, amt_k, verdict_k in _PERIOD_SUMMARY_ROWS:
        if _num(pt.get(amt_k)) is None:
            continue
        word = _period_verdict(pt, verdict_k)
        badges.append(f'{label} <span class="badge {_PERIOD_VERDICT_BADGE[word]}">{word}</span>')
        # 金额化全年参照口径：营收=goal_rev；归母=goal_np/consensus_np；扣非天然无该口径
        has_ref = ((pt.get("goal_rev") is not None) if amt_k == "rev"
                   else (pt.get("goal_np") is not None or pt.get("consensus_np") is not None)
                   if amt_k == "np" else False)
        if not has_ref:
            no_ref.append(label)
    summary = str(pt.get("summary_html") or "").strip()
    if not badges and not summary:
        return ""
    notes = []
    if no_ref:
        notes.append(f'{"、".join(no_ref)}无金额化全年参照，不画进度条')
    if _num(pt.get("ocf")) is not None:
        notes.append("经营现金流不设判词")
    parts = ['<div class="period-summary"><div class="ps-line"><b>进度小结：</b>',
             " · ".join(badges)]
    if notes:
        parts.append(f'<span class="ps-note">（{"；".join(notes)}）</span>')
    parts.append('</div>')
    if summary:
        parts.append(f'<div class="ps-text">{summary}</div>')
    parts.append('</div>')
    return "".join(parts)


def build_period_kpi(pt: dict) -> str:
    """3 章·本期累计一览卡（period_track，v5.0.1）：收入/归母/扣非/经营现金流四卡——
    本期累计（亿元，两位小数）+ 同比（数值红涨绿跌，扭亏/转亏等文字原样；缺值标—）。
    本章锚件：四项金额全 None → 返回空串（render 层以此判定整章存亡——TOC 与章节块
    同生共灭硬约束的承载者；v5.0.1 起子弹图/单季图任一缺席不再影响章节存在）。"""
    if not isinstance(pt, dict):
        return ""
    cards = []
    for label, amt_k, yoy_k in _PERIOD_KPI_ROWS:
        v = _num(pt.get(amt_k))
        yoy = pt.get(yoy_k)
        if isinstance(yoy, (int, float)):
            yoy_html = f'<span class="{"up" if yoy >= 0 else "down"}">{yoy:+.1f}%</span>'
        else:
            yoy_s = _pyoy_txt(yoy)
            yoy_html = _esc(yoy_s) if yoy_s else "—"
        cards.append(f'<div class="metric-card"><div class="label">{label}</div>'
                     f'<div class="value">{f"{v:,.2f}" if v is not None else "—"}'
                     + ('<span class="unit"> 亿</span>' if v is not None else "")
                     + f'</div><div class="sub">同比 {yoy_html}</div></div>')
    if all(_num(pt.get(k)) is None for _, k, _ in _PERIOD_KPI_ROWS):
        return ""
    return ('<span class="section-tag">本期累计一览（亿元）</span>'
            '<div class="metric-row">' + "".join(cards) + '</div>')


def build_period_bullets(pt: dict) -> str:
    """3 最新报告期透视·进度子弹图（period_track 字段，v5.0.1）：仅画「有金额化全年参照」的行
    （经营目标/一致预期任一非 None——节奏带换算本就依赖该分母），横向子弹图竖排共用一个
    figure 与一行图例——钢蓝条=本期累计（条端标累计值与同比，同比为文字时原样），琥珀粗刻=
    经营目标、深墨粗刻=卖方一致预期（分母缺则不画，图注标「未披露/未获取」；刻度标签附完成度
    =累计÷分母，脚本算，累计或分母 ≤0 时完成度无意义不标），浅沙底带=近三年同期节奏带
    （同期累计占全年比例带 × 分母换算金额区间；分母=一致预期优先、缺则经营目标，双缺不画带），
    右侧判词徽章（绿=超前/灰=正常/红=滞后/浅灰=无法判定，缺判词按无法判定渲染）。
    轨道右端=全年参照锚（累计/目标/预期/带上限取大）外扩 8% 留白，空段=距全年参照的差额；
    各行金额域独立：[min(0, 累计, 分母, 带下限), max(0, 累计, 目标, 预期, 带上限)×1.08]，
    域退化兜底 lo+1.0（负值/零值不崩）——负值条自零轴向左伸、标签放条左端外侧；
    分母 ≤0 不换算节奏带（图注标不适用），带换算后负占比截零。无参照行在图注点名
    （累计值见上方一览卡）。有参照行数=0 → 返回空串（章存亡由一览卡判定，与本图解耦）。"""
    if not isinstance(pt, dict):
        return ""
    rows = []
    miss_notes = []
    skipped = []
    for label, amt_k, yoy_k, verdict_k, goal_k, cons_k, band_k in _PERIOD_ROWS:
        v = _num(pt.get(amt_k))
        if v is None:
            continue
        goal = _num(pt.get(goal_k)) if goal_k else None
        cons = _num(pt.get(cons_k)) if cons_k else None
        if goal is None and cons is None:
            skipped.append(label)   # 无金额化全年参照：不画（空轨道零信息，见模块配置注释）
            continue
        band = None
        if band_k:
            bl = pt.get(band_k) or []
            blo = _num(bl[0]) if len(bl) >= 1 else None
            bhi = _num(bl[1]) if len(bl) >= 2 else None
            d = cons if cons is not None else goal   # 换算分母：一致预期优先，缺则经营目标
            if blo is not None and bhi is not None and bhi > blo:
                if d is not None and d > 0:
                    # 带换算后下限钳 ≥0（节奏带语义=正常进度参照，负占比截零；仅渲染层截断）
                    lo_c, hi_c = max(0.0, blo / 100 * d), bhi / 100 * d
                    if hi_c > lo_c:
                        band = (lo_c, hi_c, "一致预期" if cons is not None else "经营目标", d)
                elif d is not None:
                    # 分母 ≤0（负一致预期）不换算节奏带；分母未披露由下行「未披露」注覆盖
                    miss_notes.append(f"{label}节奏带换算分母为负，节奏带不适用")
        if goal_k and goal is None:
            miss_notes.append(f"{label}经营目标：未披露")
        if cons_k and cons is None:
            miss_notes.append(f"{label}一致预期：未获取")
        rows.append({"label": label, "v": v, "yoy": pt.get(yoy_k), "goal": goal, "cons": cons,
                     "band": band, "verdict": _period_verdict(pt, verdict_k)})
    if not rows:
        return ""

    W, L, R, BH, TOP, ROW_H = 1000, 96, 168, 26, 64, 88
    H = TOP + ROW_H * (len(rows) - 1) + 50
    parts = ['<span class="section-tag">报告期累计进度：仅列有全年参照的指标</span>',
             _svg_open(W, H, "报告期进度子弹图")]
    # 共用图例行（缺席形态不出图例项——与「无线不出图例」同纪律）
    lx = L
    parts.append(f'<rect x="{lx}" y="6" width="13" height="9" rx="2.5" fill="{_C_BLUE}"/>')
    parts.append(f'<text x="{lx + 18}" y="14" font-size="11" fill="{_C_LABEL}">本期累计</text>')
    lx += 18 + _text_w("本期累计", 11) + 26
    if any(r["goal"] is not None for r in rows):
        parts.append(f'<line x1="{lx + 5}" y1="3" x2="{lx + 5}" y2="16" stroke="{_C_ORANGE}" stroke-width="3"/>')
        parts.append(f'<text x="{lx + 14}" y="14" font-size="11" fill="{_C_LABEL}">经营目标</text>')
        lx += 14 + _text_w("经营目标", 11) + 26
    if any(r["cons"] is not None for r in rows):
        parts.append(f'<line x1="{lx + 5}" y1="3" x2="{lx + 5}" y2="16" stroke="{_C_BLACK}" stroke-width="3"/>')
        parts.append(f'<text x="{lx + 14}" y="14" font-size="11" fill="{_C_LABEL}">一致预期</text>')
        lx += 14 + _text_w("一致预期", 11) + 26
    if any(r["band"] for r in rows):
        parts.append(f'<rect x="{lx}" y="6" width="13" height="9" rx="2.5" fill="{_C_SAND_LT}"/>')
        parts.append(f'<text x="{lx + 18}" y="14" font-size="11" fill="{_C_LABEL}">'
                     f'历史节奏带（近三年同期占比×分母）</text>')
    for i, r in enumerate(rows):
        cy = TOP + i * ROW_H
        # 金额域放开负值（亏损期累计为负是合法输入）：下限含 0/累计/双分母/带下限，
        # 上限含 0/各正值 ×1.08；域退化（全零/上下限相等）兜底 lo+1.0 防 _lin_map 除零
        lo_d = min(0.0, r["v"], r["goal"] or 0.0, r["cons"] or 0.0,
                   r["band"][0] if r["band"] else 0.0)
        hi_d = max(0.0, r["v"], r["goal"] or 0.0, r["cons"] or 0.0,
                   r["band"][1] if r["band"] else 0.0) * 1.08
        if hi_d <= lo_d:
            hi_d = lo_d + 1.0
        X = _lin_map(lo_d, hi_d, L, W - R)
        parts.append(f'<text x="{L - 10}" y="{cy + 4.5:.1f}" text-anchor="end" font-size="12.5" '
                     f'font-weight="600" fill="{_C_INK}">{r["label"]}</text>')
        parts.append(f'<rect x="{L}" y="{cy - BH / 2:.1f}" width="{W - R - L}" height="{BH}" rx="8" '
                     f'fill="{_C_TRACK}" stroke="{_C_AXIS}"/>')
        if r["band"]:
            blo, bhi, dname, dv = r["band"]
            xb1, xb2 = X(blo), X(bhi)
            parts.append(f'<rect x="{xb1:.1f}" y="{cy - BH / 2:.1f}" width="{max(xb2 - xb1, 2):.1f}" '
                         f'height="{BH}" fill="{_C_SAND_LT}"/>')
            bnote = f"近三年同期节奏带（按{dname} {_pamt(dv)} 亿换算）"
            ba, bx = _anchor_clamp((xb1 + xb2) / 2, _text_w(bnote, 10), L + 2, W - R - 2)
            parts.append(f'<text x="{bx:.1f}" y="{cy + BH / 2 + 17:.1f}" text-anchor="{ba}" '
                         f'font-size="10" fill="{_C_LABEL}">{bnote}</text>')
        x0, xv = X(0), X(r["v"])
        if lo_d < 0:
            # 负域（亏损期）：零轴标线 + 条自零轴画到 X(v)（负值向左伸，同单季双柱负域口径）
            parts.append(f'<line x1="{x0:.1f}" y1="{cy - BH / 2:.1f}" x2="{x0:.1f}" '
                         f'y2="{cy + BH / 2:.1f}" stroke="{_C_AXIS}" stroke-width="1.2"/>')
            parts.append(f'<rect x="{min(x0, xv):.1f}" y="{cy - BH / 2:.1f}" '
                         f'width="{max(abs(xv - x0), 2):.1f}" height="{BH}" rx="8" fill="{_C_BLUE}"/>')
        else:
            parts.append(f'<rect x="{L}" y="{cy - BH / 2:.1f}" width="{max(xv - L, 2):.1f}" height="{BH}" '
                         f'rx="8" fill="{_C_BLUE}"/>')
        yoy_s = _pyoy_txt(r["yoy"])
        bl_txt = f"{_pamt(r['v'])} 亿" + (f" · 同比 {_esc(yoy_s)}" if yoy_s else "")
        bl_w = _text_w(bl_txt, 11.5)
        if r["v"] < 0:
            # 负值条标签放条左端外侧（深墨）；左端逼近行标签区 → 条内右端白字；
            # 条太窄（零轴贴左缘）→ 零轴右侧深墨
            if xv - 8 - bl_w >= L + 2:
                parts.append(f'<text x="{xv - 8:.1f}" y="{cy + 4:.1f}" text-anchor="end" '
                             f'font-size="11.5" font-weight="700" fill="{_C_INK}">{bl_txt}</text>')
            elif abs(xv - x0) >= bl_w + 8:
                parts.append(f'<text x="{x0 - 8:.1f}" y="{cy + 4:.1f}" text-anchor="end" '
                             f'font-size="11.5" font-weight="700" fill="{_C_PAPER}">{bl_txt}</text>')
            else:
                parts.append(f'<text x="{x0 + 8:.1f}" y="{cy + 4:.1f}" font-size="11.5" '
                             f'font-weight="700" fill="{_C_INK}">{bl_txt}</text>')
        elif xv + 8 + bl_w <= W - R - 4:   # 条外右侧放得下 → 深墨；放不下 → 条内白字
            parts.append(f'<text x="{xv + 8:.1f}" y="{cy + 4:.1f}" font-size="11.5" font-weight="700" '
                         f'fill="{_C_INK}">{bl_txt}</text>')
        else:
            parts.append(f'<text x="{xv - 8:.1f}" y="{cy + 4:.1f}" text-anchor="end" font-size="11.5" '
                         f'font-weight="700" fill="{_C_PAPER}">{bl_txt}</text>')
        # 双分母刻度（标签附完成度=累计÷分母；累计/分母 ≤0 时完成度无意义不标；
        # 标签防叠：两条过近时经营目标标签抬一层）
        drawn = []
        for tv, tc, tn in ((r["goal"], _C_ORANGE, "经营目标"), (r["cons"], _C_BLACK, "一致预期")):
            if tv is None:
                continue
            tx = X(tv)
            tl = f"{tn} {_pamt(tv)} 亿"
            if tv > 0 and r["v"] > 0:
                tl += f" · 已完成 {r['v'] / tv * 100:.1f}%"
            ta, tx2 = _anchor_fit(tx, _text_w(tl, 10.5), L + 2, W - R - 2, 4)
            drawn.append([tx, tc, tl, ta, tx2, cy - 27])
        if len(drawn) == 2:
            rects = []
            for _tx, _tc, tl, ta, tx2, _ly in drawn:
                w2 = _text_w(tl, 10.5)
                rects.append((tx2 - w2, tx2) if ta == "end" else
                             ((tx2, tx2 + w2) if ta == "start" else (tx2 - w2 / 2, tx2 + w2 / 2)))
            if rects[0][0] < rects[1][1] and rects[1][0] < rects[0][1]:
                drawn[0][5] = cy - 43   # 经营目标标签抬一层
        for tx, tc, tl, ta, tx2, ly in drawn:
            parts.append(f'<line x1="{tx:.1f}" y1="{cy - BH / 2 - 8:.1f}" x2="{tx:.1f}" '
                         f'y2="{cy + BH / 2 + 8:.1f}" stroke="{tc}" stroke-width="3"/>')
            parts.append(f'<text x="{tx2:.1f}" y="{ly}" text-anchor="{ta}" font-size="10.5" '
                         f'font-weight="700" fill="{tc}">{tl}</text>')
        word = r["verdict"]
        vf = _PERIOD_VERDICT_FILL[word]
        vt = _C_STONE if word == "无法判定" else _C_PAPER
        pw = _text_w(word, 11) + 20
        parts.append(f'<rect x="{W - 12 - pw:.1f}" y="{cy - 9}" width="{pw:.1f}" height="18" rx="9" fill="{vf}"/>')
        parts.append(f'<text x="{W - 12 - pw / 2:.1f}" y="{cy + 3.5:.1f}" text-anchor="middle" '
                     f'font-size="11" font-weight="700" fill="{vt}">{word}</text>')
    parts.append(_svg_close())
    src = ('报告期进度子弹图（脚本按 period_track 字段生成，数据照抄 em_fetch period_track 照抄行）：'
           '钢蓝条=本期累计（条端标累计值与同比，同比为扭亏/转亏等文字时原样），琥珀刻=经营目标'
           '（年报经营计划披露），深墨刻=卖方一致预期（E5 当年净利均值），刻度附完成度=累计÷分母'
           '（脚本计算）；浅沙带=近三年同期累计占全年比例带×分母换算的节奏带；轨道右端=全年参照锚'
           '（累计/经营目标/一致预期/带上限取大）外扩 8% 留白，空段=距全年参照的差额；'
           '各行金额域独立定标（看行内比例，不跨行比长度）；判词徽章 绿=超前/灰=正常/红=滞后/浅灰=无法判定')
    if skipped:
        src += f'；{"、".join(skipped)}无金额化全年参照，不画进度条（累计值见上方一览卡）'
    if miss_notes:
        src += '；' + '；'.join(miss_notes)
    parts.append(f'<span class="source">{src}</span>')
    return "".join(parts)


def build_period_sqplot(pt: dict) -> str:
    """3 章·单季并肩双柱双联图（period_track 的 sq_* 字段，v5.0.1）：一张 figure 左右两联——
    左联 营业收入/经营现金流（规模与收现含金量）、右联 归母净利/扣非净利（利润口径，
    两柱差额≈非经常损益影响）；两联独立定标（旧版四指标共轴，收入 90 亿级把利润 10 亿级
    压成矮桩），联内共享零轴与网格，柱高只在联内可比。每组两根（沙柱=上年同季、钢蓝柱=
    最新单季），柱顶标数值，最新柱上方标同比%（文字同比原样）；组下标季度名与指标名，
    联标题置底居中。Q1 期（sq_label 以 Q1 结尾，或 sq 值与累计口径相等）各组退化单柱；
    某组上年同季缺数同样单柱；某组最新值缺 → 整组缺席，整联缺 → 整联缺席（另一联占满幅宽）。
    无 sq_label 或四组最新值全 None → 返回空串。"""
    if not isinstance(pt, dict):
        return ""
    sq_label = str(pt.get("sq_label") or "").strip()
    if not sq_label:
        return ""
    same_as_cum = []
    for ck, ak in (("sq_rev", "rev"), ("sq_np", "np")):
        a, b = _num(pt.get(ck)), _num(pt.get(ak))
        if a is not None and b is not None:
            same_as_cum.append(a == b)
    q1 = sq_label.endswith("Q1") or (bool(same_as_cum) and all(same_as_cum))
    prev_label = str(pt.get("sq_prev_label") or "").strip()
    panels = []
    for ptitle, groups_cfg in _PERIOD_SQ_PANELS:
        groups = []
        for name, pk, ck, yk in groups_cfg:
            cur = _num(pt.get(ck))
            if cur is None:
                continue
            prev = _num(pt.get(pk))
            groups.append({"name": name, "prev": (prev if not q1 else None), "cur": cur,
                           "yoy": pt.get(yk)})
        if groups:
            panels.append((ptitle, groups))
    if not panels:
        return ""
    W, H, T, B = 1000, 268, 44, 86
    paired = any(g["prev"] is not None for _, gs in panels for g in gs)
    tag = (f"单季对比：{_esc(prev_label)} → {_esc(sq_label)}" if paired
           else f"单季：{_esc(sq_label)}" + ("（累计即单季）" if q1 else ""))
    parts = [f'<span class="section-tag">{tag}</span>', _svg_open(W, H, "单季同比对比图")]
    lx = 56
    if paired:
        lx = _legend_row(parts, [("上年同季", _C_SAND)], lx)
    _legend_row(parts, [("最新单季", _C_BLUE)], lx)
    spans = [(56, 480), (560, 980)] if len(panels) == 2 else [(56, 980)]
    for (ptitle, groups), (PL, PR) in zip(panels, spans):
        vals = [g["cur"] for g in groups] + [g["prev"] for g in groups if g["prev"] is not None]
        lo_d = min(0.0, min(vals))
        lo_d = lo_d * 1.15 if lo_d < 0 else 0.0   # 负值（亏损季）向下扩域
        hi_d = max(0.0, max(vals)) * 1.18 or 1.0   # 域顶含 0（全负域崩坏修复：负 max×1.18 是负
                                                   # truthy，「or 1.0」不兜底 → 域不含 0）；不断轴
        Y = _lin_map(lo_d, hi_d, H - B, T)
        y0 = Y(0)
        _hgrid_ticks(parts, Y, _ticks(lo_d, hi_d, 5), PL, PR, PL - 8)
        parts.append(f'<line x1="{PL}" y1="{y0:.1f}" x2="{PR}" y2="{y0:.1f}" '
                     f'stroke="{_C_AXIS}" stroke-width="1.2"/>')
        n = len(groups)
        slot = (PR - PL) / n
        bw = min(slot * 0.3, 84)
        for i, g in enumerate(groups):
            gx = PL + slot * (i + 0.5)
            seq = ([(g["prev"], _C_SAND, gx - bw - 8, prev_label)] if g["prev"] is not None else []) \
                + [(g["cur"], _C_BLUE, gx + 8 if g["prev"] is not None else gx - bw / 2, sq_label)]
            for bi, (v, col, x, qlbl) in enumerate(seq):
                cur_bar = bi == len(seq) - 1
                top, h = min(Y(v), y0), max(abs(y0 - Y(v)), 1)
                parts.append(f'<rect x="{x:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="3" fill="{col}"/>')
                vy = top - 6 if v >= 0 else top + h + 14
                parts.append(f'<text x="{x + bw / 2:.1f}" y="{vy:.1f}" text-anchor="middle" font-size="11" '
                             f'font-weight="{700 if cur_bar else 400}" '
                             f'fill="{_C_BLUE if cur_bar else _C_STONE}">{_pamt(v)}</text>')
                parts.append(f'<text x="{x + bw / 2:.1f}" y="{H - B + 16}" text-anchor="middle" '
                             f'font-size="10.5" fill="{_C_INK if cur_bar else _C_LABEL}">{_esc(qlbl)}</text>')
            yoy_s = _pyoy_txt(g["yoy"])
            if yoy_s:
                cx = seq[-1][2] + bw / 2
                # 负值柱（最新季亏损）：同比标签上移到零轴上方（柱顶外侧）避让底部标签堆
                yy = (min(Y(g["cur"]), y0) - 20) if g["cur"] >= 0 else (y0 - 8)
                parts.append(f'<text x="{cx:.1f}" y="{max(yy, 12):.1f}" text-anchor="middle" '
                             f'font-size="11" font-weight="700" fill="{_C_BLUE}">{_esc(yoy_s)}</text>')
            parts.append(f'<text x="{gx:.1f}" y="{H - B + 34}" text-anchor="middle" font-size="11.5" '
                         f'font-weight="600" fill="{_C_INK}">{g["name"]}（亿元）</text>')
        parts.append(f'<text x="{(PL + PR) / 2:.1f}" y="{H - B + 56}" text-anchor="middle" '
                     f'font-size="12" font-weight="700" fill="{_C_LABEL}">{ptitle}</text>')
    parts.append(_svg_close())
    parts.append('<span class="source">单季并肩双柱双联图（脚本按 period_track 单季拆分字段生成，数据照抄 '
                 'em_fetch 照抄行）：左联=收入与经营现金流（规模与收现含金量）、右联=归母与扣非'
                 '（柱差≈非经常损益影响）；两联独立定标、联内共享零轴，柱高只在联内可比；'
                 '沙柱=上年同季、钢蓝柱=最新单季，柱顶=单季金额（亿元），最新柱上方=单季同比'
                 '（扭亏/转亏等文字原样）；扣非与经营现金流单季=累计差分（Q2=中报−Q1，Q3=前三季−中报）；'
                 'Q1 期累计即单季，退化为单柱；经营现金流单季受回款节奏影响波动大，仅作方向参考</span>')
    return "".join(parts)
