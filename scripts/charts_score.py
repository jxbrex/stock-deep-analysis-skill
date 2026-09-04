#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""charts_score.py — 评分类图族（v4.10 从 charts.py 拆出）：06 九维评分分布横条（build_score_bars）/ 02 敏感性龙卷风（build_sensitivity_tornado）。依赖 charts_base 与 scoring。"""

from scoring import DIMS, LAYER_NAMES, badge_class, _dim_verdict, _num, _fmt, _esc
from charts_base import *

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
    # v4.9：评分条色跟随模板徽章加深系（白字/小字 AA 对比度），与 pastel 评价色（大面积填充）区分
    badge_color = {"badge-green": "#4d804d", "badge-orange": "#96691a", "badge-red": "#b84a4a"}

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
