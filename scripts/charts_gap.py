#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""charts_gap.py — 9 市场预期差拆解图族（v5.1.5 自 charts_misc 拆出）：逐机构分布图（A 档）
与 B 档零轴偏离哑铃（build_gap_plot + _gap_plot_a/_gap_plot_b）、gap-notes 附注
（_gap_notes_html）与锚点注入（_inject_gap_chart）；自有轴线件 _gap_axis/_gap_ticks/
_gap_fmt/_px。依赖 charts_base 与 scoring。"""

import math
import re

from scoring import _num, _fmt, _esc
from charts_base import *

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
        if not _gap_dim_ok(d):   # 行有效性唯一定义（charts_base，v5.1.2 起附注/校验同源）
            continue
        name = str(d.get("name") or "").strip()
        ours, cons = _num(d.get("ours")), _num(d.get("consensus"))
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
    clamped_any = False
    for i, d in enumerate(dims):
        cy = 71 + 62 * i
        pt = d["pt"]
        pct = (d["ours"] / d["cons"] - 1) * 100
        # 审计 P2-1：偏离超出定域（-10%~+15%）时点位被夹在边界——虚线棒+空心点作截断记号，
        # 数值仍以右列为准（点位视觉不得撒谎）
        clamped = pct < -10 or pct > 15
        if clamped:
            clamped_any = True
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
        dx = X(max(-10, min(15, round(pct, 1))))   # 定位与右列显示同值（所见即所量）
        dash = ' stroke-dasharray="4 3"' if clamped else ""
        parts.append(_arrow_dumbbell(zx, dx, cy, _C_BLUE, _px, dash=dash, hollow=clamped))
        parts.append(f'<text x="872" y="{_px(cy + 4.5)}" font-size="13" font-weight="700" '
                     f'fill="{_C_INK}">{pct:+.1f}%</text>')
    parts.append(_svg_close())
    src = ('<span class="source">预期差哑铃图（脚本按 gap_plot 字段生成，B 档）：灰点=卖方一致预期（固定零轴），'
           '蓝点=本文；横轴=本文相对卖方偏离 %；比率型维度按相对偏离定位，原生差值（+1.5pct）写进行注')
    rev_nums = "".join(_GAP_CIRCLED[i] for i, d in enumerate(dims) if d["rev"])
    if rev_nums:
        src += f'；{rev_nums} 为反推口径——卖方未披露该维度假设，由一致净利/目标价反推'
    if clamped_any:
        src += '；虚线棒+空心蓝点=偏离超出 -10%~+15% 定域，按右列数值为准'
    parts.append(src + '</span>')
    return "".join(parts)


def _renumber_note(note: str, circled: str) -> str:
    """把附注文首（可隔 <b> 开标签）的圈号前缀改写为指定行号；无圈号前缀原样返回。
    v5.1.2：note 圈号本是填写方手写，行被剔除后手写编号失效——脚本按过滤后行序统一改写。"""
    # v5.1.2：前缀形态放宽为「任意标签/实体/空白」（热核 P2-1：<i>/<b style>/&nbsp; 开头
    # 的 note 此前不改写，剔除行后手写圈号与图行再次错位）
    return re.sub(r"^((?:\s|&nbsp;|<[^>]+>)*)[①-⑥]", rf"\g<1>{circled}", note, count=1)


def _gap_notes_html(gp: dict) -> str:
    """gap-notes 附注（图下编号注）：dims[].note 按图行序（①②… 与图行一一对应）+ text_dims 续编号
    文本项。v5.1.2：行过滤与图同源（_gap_dim_ok，cons≤0 行剔除、取前 6、有效行 <2 随图不生成），
    附注编号由脚本按过滤后行序改写（此前按原始数组取行前 6 且编号手写——剔除行后图①与注①
    错位，读者把 A 行的注读成 B 行的）。内容为填写方直写 HTML，脚本只包 <li>；
    无任何附注 → 空串。"""
    dims = [d for d in (gp.get("dims") or []) if _gap_dim_ok(d)][:6]
    if len(dims) < 2:
        return ""
    items = []
    for i, d in enumerate(dims):
        note = str(d.get("note") or "").strip()
        if note:
            items.append(f"<li>{_renumber_note(note, _GAP_CIRCLED[i])}</li>")
    for j, t in enumerate(gp.get("text_dims") or []):
        t = str(t or "").strip()
        if not t:
            continue
        if len(dims) + j < len(_GAP_CIRCLED):
            t = _renumber_note(t, _GAP_CIRCLED[len(dims) + j])
        else:
            # 无圈号可用（图行已占满 ①-⑥）：剥掉手写文首圈号，避免与图行撞号（热核 P2-3）
            t = re.sub(r"^((?:\s|&nbsp;|<[^>]+>)*)[①-⑥]", r"\g<1>", t, count=1)
        items.append(f"<li>{t}</li>")
    return '<ol class="gap-notes">' + "".join(items) + "</ol>" if items else ""


def _inject_gap_chart(gap_html: str, fill: dict) -> str:
    """9 预期差图锚点注入（与 _inject_l3_charts 同一注入机）：gap_html 里的 <!--GAP--> 注释
    原位替换为「图 + <ol class="gap-notes"> 附注」整体；锚点缺失但字段已填 → 垫第 9 章章首 +
    告警（prepend——图是本章主体）；字段未填 → 锚点静默清除；有效维度 <2 → 图与附注同不生成
    （v5.1.2 起附注与图行同源，text_dims 一并丢弃）。"""
    block = build_gap_plot(fill) + _gap_notes_html(fill.get("gap_plot") or {})
    return _inject_chart_anchors(
        gap_html,
        (("<!--GAP-->", block, "gap_plot"),),
        "gap_html", "第 9 章章首", "建议把锚点放到档位说明段之后", prepend=True)

