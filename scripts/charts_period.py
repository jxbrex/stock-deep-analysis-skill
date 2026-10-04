#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""charts_period.py — 3 最新报告期透视图族（v5.1.5 自 charts_misc 拆出；v5.0 起、v5.0.1
重构——绝对额表删除，信息并入一览卡与子弹图刻度）：进度小结条 / 累计一览卡 / 进度子弹图 /
单季双联图（build_period_summary/_kpi/_bullets/_sqplot）与配套 _PERIOD_* 行配置、
_pamt/_pyoy_txt/_period_verdict。判词四元组 _PERIOD_VERDICTS 在 charts_base（与 validate
单源）。依赖 charts_base 与 scoring。"""

from scoring import _num, _esc
from charts_base import *

# ════════════════════ 3 最新报告期透视（v5.0.1）：进度小结条 / 累计一览卡 / 进度子弹图 / 单季双联图 ════════════════════

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
