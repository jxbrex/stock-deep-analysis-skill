#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""charts_misc.py — 杂货图族（v4.9 从 charts.py 拆出；v5.1.5 拆出 gap 族 → charts_gap.py、
报告期族 → charts_period.py）：5.1 利润增长图（build_growth_plot，含 5 章锚点注入
_inject_l3_charts）/ 12 股东户数趋势（build_holders_plot）/ 13 回测锚移动台账与三轨哑铃
（build_anchor_ledger / build_review_dumbbell）/ 14 触发条件状态条（build_triggers_strip）
/ 2 驱动卡与 11 阶段卡（build_driver_cards / build_cycle_stages）。依赖 charts_base 与 scoring。"""

from scoring import _num, _fmt, _esc, _parse_prev_scenarios
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
    hi = max(p["num"] for p in pts) * 1.18 or 1.0  # 不断轴（柱=真实数值契约），顶部留给数值标签；
    # 全零户数（停牌脏数据）时 max×1.18=0 会除零——or 1.0 兜底（同 charts_period 单季图口径）
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


def build_anchor_ledger(fill: dict, calc: dict) -> str:
    """13 章回测复盘·估值锚移动台账（v5.1.0 锚纪律三，恒瑞复盘实证：悲观价月内 41.8→38.5
    由 PE 带下修驱动而两版间无新增基本面证据——锚移动必须上账接受审判，不许默默重置）：
    三情景的上版锚 vs 本版锚对照（利润×PE→中枢）+ pe_band_evidence 增量证据清单
    （与 validate._check_anchor_discipline 门禁同源字段）。上版照抄 prev.scenarios
    （extract_review 对上版报告 scenario-table 的解析，禁手改），本版取 compute_valuation
    计算值——两侧均禁手估；中枢列=目标价区间中点（上版为报告显示口径中点，与本版真值
    中枢比对存显示精度内误差）。非回测（prev.scenarios 缺）/ calc 缺失 → 空串；
    上版某情景解析不出（旧版格式差异/市值口径无利润PE行）→ 该行降级标注，不炸链。"""
    prev = fill.get("prev") or {}
    prev_scen = prev.get("scenarios")
    if not prev_scen or not calc or not calc.get("rows"):
        return ""
    parsed = _parse_prev_scenarios(prev_scen)
    rows_by_key = {r["key"]: r for r in calc["rows"]}
    trs = []
    degraded = 0
    for key, label in (("pess", "悲观"), ("base", "基础"), ("opt", "乐观")):
        p = parsed.get(key) or {}
        cur = rows_by_key.get(key)
        if cur is None:
            continue
        if p.get("pe") and p.get("mid"):
            profit_txt = f"{p['profit']:g} 亿" if p.get("profit") is not None else "—"
            prev_txt = f"{profit_txt} × {p['pe'][0]:g}-{p['pe'][1]:g}x → {_fmt_px(p['mid'])} 元"
        elif p.get("mid"):
            prev_txt = f"目标价中点 {_fmt_px(p['mid'])} 元（上版无利润/PE 行，市值口径）"
            degraded += 1
        else:
            prev_txt = "解析失败（以原文对照为准）"
            degraded += 1
        if cur.get("profit") is not None and cur.get("pe_lo") is not None:
            cur_txt = (f"{cur['profit']:g} 亿 × {cur['pe_lo']:g}-{cur['pe_hi']:g}x "
                       f"→ {_fmt_px(cur['mid'])} 元")
        else:
            cur_txt = f"目标市值区间 → {_fmt_px(cur['mid'])} 元"
        if p.get("mid"):
            d_txt = f"{(cur['mid'] / p['mid'] - 1) * 100:+.1f}%"
        else:
            d_txt = "—"
        trs.append(f'<tr><td>{label}</td><td>{_esc(prev_txt)}</td><td>{_esc(cur_txt)}</td>'
                   f'<td class="num">{d_txt}</td></tr>')
    if not trs:
        return ""
    ev = (fill.get("valuation") or {}).get("pe_band_evidence") or []
    ev_html = ""
    if ev:
        lis = "".join(
            f'<li><strong>{_esc(str(e.get("type") or "?"))}</strong>｜'
            f'{_esc(str(e.get("note") or ""))}</li>'
            for e in ev if isinstance(e, dict))
        ev_html = ('<div class="info-card"><strong>锚移动增量证据</strong>（两版报告间的新增信息；'
                   '无新增基本面证据时 PE 带不得移动——估值锚纪律一，价格与卖方观点不构成理由）：'
                   f'<ul>{lis}</ul></div>')
    src = ('锚移动台账（脚本生成）：上版照抄 prev.scenarios（extract_review 对上版报告的解析），'
           '本版为脚本计算值；中枢=目标价区间中点（上版为报告显示口径中点），Δ=本版中枢÷'
           '上版中枢−1；锚的每次移动必须归因到上方增量证据清单，写不出基本面增量的移动不合法'
           + ('；上版含解析降级行（旧版格式或市值口径），以原文对照为准' if degraded else ''))
    return (f'<span class="section-tag">估值锚移动台账（较上版 '
            f'{_esc(str(prev.get("date") or "—"))}）</span>'
            '<div class="table-scroll"><table><thead><tr><th>情景</th>'
            '<th>上版锚（利润×PE→中枢）</th><th>本版锚（利润×PE→中枢）</th>'
            '<th class="num">Δ中枢</th></tr></thead><tbody>'
            + "".join(trs) + '</tbody></table></div>' + ev_html
            + f'<span class="source">{src}</span>')


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
        parts.append(_arrow_dumbbell(xo, xn, cy, dcolor, lambda v: f"{v:.1f}"))
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


# ════════════════════ 2 关键利润驱动 · 驱动卡 / 11 周期规律 · 阶段卡（v4.11.3） ════════════════════

def build_driver_cards(fill: dict) -> str:
    """2 关键利润驱动·驱动卡（fill["drivers"] + fill["driver_verdict"]，v4.11.3）：
    1-2 个关键利润驱动各一张卡——弹性值（大字号）+ 备注（当前值/撕扯力量）+ 三情景锚标签；
    第一变量带 drv-badge 角标；卡下判词横条（.layer-summary）承载「为什么 X 是第一变量」
    （v4.11.3 起替代 p0_html 手写 info-card）。
    v5.1.1：第一变量改由脚本按 sensitivity |impact| 降序加冕（charts_base._first_var_name，
    与龙卷风图/校验同源——影石创新驱动卡手标与排序图各执一词实证）；sensitivity 缺失时
    才回退手标 first_var。
    drivers: [{"name":"单Wh净利（单位盈利）","first_var":true,
               "elastic":"±0.01元/Wh → 净利 ±100亿","elastic_sub":"±10.6%，1,000GWh 基数",
               "note":"当前约 0.10元/Wh。……",
               "chips":[{"label":"悲观","value":"0.085"},{"label":"基础","value":"0.095–0.10"},
                        {"label":"乐观","value":"0.105"},{"label":"元/Wh","unit":true}]}, ...]
    （chips 恰 3 情景档 + 可选 1 个 unit 标签；字段缺失/空 → 返回空串）"""
    drivers = [d for d in fill.get("drivers") or [] if isinstance(d, dict)]
    first_var = _first_var_name(fill)
    first_key = _var_key(first_var)
    cards = []
    for d in drivers:
        name = str(d.get("name") or "").strip()
        elastic = str(d.get("elastic") or "").strip()
        if not name or not elastic:
            continue
        badge = ('<span class="drv-badge">第一变量</span>'
                 if first_key and _var_key(name) == first_key else "")
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
        first = next((d for d in drivers
                      if first_key and _var_key(d.get("name")) == first_key), None)
        first_name = str((first or {}).get("name") or "").strip() or first_var
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
    v5.4.0：calib:true 的校准时段再叠「校准锚」角标（弱化沙色系，不与「本轮」撞色；
    两角标同卡时并排于同一 `.stage-tags` 容器内 flex 自动让位）。
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
        calib = bool(s.get("calib"))
        cls = "stage current" if cur else "stage"
        # v5.4.0：角标容器化（flex + gap 自动并排，取代「current 时右移 52px」的魔法数）
        tags = "".join(('<span class="stage-cur-tag">本轮</span>' if cur else "",
                        '<span class="stage-calib-tag">校准锚</span>' if calib else ""))
        tags = f'<span class="stage-tags">{tags}</span>' if tags else ""
        pe = str(s.get("pe") or "").strip()
        price = str(s.get("price") or "").strip()
        meta = " ｜ ".join(p for p in (_esc(period),
                                      f"PE {_esc(pe)}" if pe else "",
                                      f"股价 {_esc(price)}" if price else "") if p)
        driver = str(s.get("driver") or "").strip()
        driver_html = f'<div class="stage-driver">{_esc(driver)}</div>' if driver else ""
        cards.append(
            f'<div class="{cls}">{tags}<div class="stage-top"><span class="stage-num">{len(cards) + 1:02d}</span>'
            f'<span class="stage-name">{_esc(name)}</span></div>'
            f'<div class="stage-meta">{meta}</div>{driver_html}</div>')
    if not cards:
        return ""
    return '<div class="stage-strip">' + "".join(cards) + '</div>'


def build_cycle_position(fill: dict) -> str:
    """11 周期规律·当前位置刻度条（fill["cycle_position"]，v5.2.0）：「上行期」类无刻度标签
    的云铝半年报实证立项——当前位置必须带刻度：阶段名 + 三件套（商品价格历史分位 /
    产能投放轨迹 / 库存或价差分位）+ 位置含义句（距顶/底哪边更近 → 对应估值纪律）。
    cycle_position: {"stage":"上行期后段","price_pctile":"铝价历史分位 ~70%（2015 至今）",
                     "capacity":"产能天花板下投放低峰","stock_spread":"氧化铝价差处历史 90% 分位",
                     "implication":"利润距顶比距底更近——PE 按周期股铁律给折价"}
    （字段缺失/空 → 返回空串：首版软约束，周期股缺填由 validate 层告警；复用 layer-summary
    判词横条视觉，垫在阶段卡与手写 cycle_html 之间）"""
    cp = fill.get("cycle_position")
    if not isinstance(cp, dict) or not cp:
        return ""
    parts = []
    stage = str(cp.get("stage") or "").strip()
    if stage:
        parts.append(f"<strong>当前位置：{_esc(stage)}</strong>")
    for v in (cp.get("price_pctile"), cp.get("capacity"), cp.get("stock_spread")):
        t = str(v or "").strip()
        if t:
            parts.append(_esc(t))
    impl = str(cp.get("implication") or "").strip()
    if impl:
        parts.append(f"→ {_esc(impl)}")
    if len(parts) < 2:
        return ""
    return '<div class="layer-summary">' + " ｜ ".join(parts) + "</div>"


