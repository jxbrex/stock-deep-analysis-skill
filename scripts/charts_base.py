#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""charts_base.py — SVG 图表基座（v4.9 从 charts.py 拆出）

内容：全站图表共用色板常量（_C_*，含模板 .mini-cell 底色 _C_PAPER_CELL 与徽章深色字典
_C_BADGE_DEEP）、数值/格式/几何工具（_fmt_px/_fmt_amt/_pad_domain/_lin_map/_text_w/_wrap_label/_ticks）、
情景字典（_SCENARIO_COLORS）、SVG 骨架 helper（_SVG_STYLE/_svg_open/_svg_close/
_vgrid_ticks/_hgrid_ticks/_legend_row/_anchor_fit/_anchor_clamp/_inject_chart_anchors）与回测新旧
对比共享行（_prev_track_rows）。
只依赖 scoring，被各图族模块与 validate.py 导入。"""

import math
import sys

from scoring import _esc, _fmt, _num

# SVG 色板（全站图表共用暖灰/钢蓝色系，唯一权威处；改色只动这里）
_C_LABEL = "#6f695e"       # 轴刻度/灰字说明/虚线时点刻（v4.9 自 #8a8375 压深，小字对比度达标）
_C_GRID = "#ece7db"        # 细网格线
_C_AXIS = "#e0d7c3"        # 轴主线/细描边
_C_BLUE = "#4a6fa5"        # 钢蓝：目标公司/合理带/最新值/PE 发丝
_C_PAPER = "#fffdf9"       # 近白：白刻/描边/带内白字
_C_INK = "#3a362e"         # 深墨：名称文字/发丝线/图例
_C_BLACK = "#2b2620"       # 最重色：首变量名/当前值刻
_C_STONE = "#57524a"       # 中灰：散点同业标签/图例小字
_C_OLIVE = "#66604f"       # 散点图非目标点
_C_SAND = "#b3ab93"        # 暖沙：历史柱/连线曲线/中轴/图例块
_C_SAND_LT = "#ddd3bd"     # 浅沙：分带虚线/分位段
_C_TRACK = "#efe9db"       # 条底轨道/历史带底/面积填充
_C_PAPER_CELL = "#f7f2e7"  # 米纸格底：与模板 .mini-cell 底色一致（文字光晕描边 paint-order 防叠字）
_C_GOOD_LINE = "#c9bfa8"   # 7.0 良好线虚线
_C_YEAR_GRID = "#f0ebdf"   # 发丝图年份竖网格
# 评价色（好坏语义，绿好红坏不变）；股价涨跌方向色走模板 .up/.down（v4.9 起红涨绿跌）
_C_GREEN = "#6ba86b"       # 绿（评价）：有利/上调/乐观/质量好
_C_RED = "#c75b5b"         # 红（评价）：不利/下调/悲观/质量差
_C_ORANGE = "#c08a2e"      # 橙：中档/基础情景
# 徽章深色字典（跟随模板 .badge-* 加深系：白字/小字 AA 对比度；评分条色用，与 pastel 评价色区分）
_C_BADGE_DEEP = {"badge-green": "#4d804d", "badge-orange": "#96691a", "badge-red": "#b84a4a"}


def _fmt_px(v):
    """目标价/区间展示价（v4.10）：低价股两位小数（<10 元，如 5.88-6.47），其余整数。
    缘起：工行报告 7 元价位被 :.0f 压成 6-6/8-8/9-9 假无区间。统一用于三情景表/
    Hero 目标价区间卡/走廊图标签，同一份报告只此一种精度。"""
    return f"{v:.2f}" if abs(v) < 10 else f"{v:.0f}"


def _fmt_amt(v) -> str:
    """亿元金额标签：≥1000 带千位符，去尾零（1,156.0 → 1,156；56.8 → 56.8）。v4.8 业务构成图用。"""
    if v is None:
        return "—"
    s = f"{float(v):,.1f}"
    return s[:-2] if s.endswith(".0") else s



_SCENARIO_COLORS = {"pess": _C_RED, "base": _C_ORANGE, "opt": _C_GREEN}


def _prev_track_rows(prev: dict, quality, valuation, timing) -> list:
    """回测三轨分新旧对比共享行（build_prev_strip 与 build_review_dumbbell 同一口径）：
    旧版 prev 键 research 自动映射 quality（兼容旧回测数据）；_num 解析、新旧均有效才入行；
    d=新−旧（≥0 上调=好/绿，<0 下调=坏/红）——呈现映射（CSS 类 good/bad 与 SVG 色）由调用方各自完成。"""
    rows = []
    for label, old, new in (("质量分", _num(prev.get("quality", prev.get("research"))), quality),
                            ("估值分", _num(prev.get("valuation")), valuation),
                            ("时机分", _num(prev.get("timing")), timing)):
        if old is None or new is None:
            continue
        rows.append({"label": label, "old": old, "new": float(new), "d": float(new) - old})
    return rows


def _pad_domain(lo: float, hi: float, ratio: float, floor=None):
    """值域向两端各扩 ratio 比例（防贴边）；floor 给下限（如 ROE 不为负）。"""
    pad = (hi - lo) * ratio or 1
    lo -= pad
    hi += pad
    if floor is not None:
        lo = max(floor, lo)
    return lo, hi


def _lin_map(a: float, b: float, A: float, B: float):
    """线性映射：数值域 [a,b] → 像素域 [A,B]（a→A，b→B）。"""
    return lambda v: A + (v - a) / (b - a) * (B - A)


def _text_w(s: str, font_size: float) -> float:
    """粗估 SVG 文本像素宽（中文/全角≈1em、ASCII≈0.56em），用于标签避让与碰撞检测。"""
    return sum(1.0 if ord(ch) > 0x2E7F else 0.56 for ch in str(s)) * font_size


def _wrap_label(s: str, max_w: float, fs: float) -> list:
    """文本超宽时按视觉宽度对半折两行（断点取两侧宽度最均衡处）；未超宽原样返回 [s]。"""
    if _text_w(s, fs) <= max_w:
        return [s]
    best, best_diff = len(s) // 2, float("inf")
    for i in range(2, len(s) - 1):
        d = abs(_text_w(s[:i], fs) - _text_w(s[i:], fs))
        if d < best_diff:
            best, best_diff = i, d
    return [s[:best], s[best:]]


def _ticks(lo: float, hi: float, n: int = 5) -> list:
    """nice-number 刻度：步长取 1/2/2.5/5×10^k，返回落在 [lo,hi] 内的步长整数倍刻度。
    取代旧版「等距后取整」（会产出 19/32/44/57/69 这类间隔观感不齐的读数）。"""
    span = hi - lo
    if not span > 0:
        return [lo]
    raw = span / (n - 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = mag
    for m in (1, 2, 2.5, 5, 10):
        if m * mag >= raw:
            step = m * mag
            break
    t = math.ceil(lo / step - 1e-9) * step
    out = []
    while t <= hi + 1e-9:
        out.append(round(t, 9))
        t += step
    return out





_SVG_STYLE = "width:100%;min-width:760px;height:auto;display:block;font-family:inherit;"


def _svg_open(w, h, label: str) -> str:
    """图表骨架开头：plot-wrap 容器 + viewBox + aria-label + 全站统一 style。"""
    return (f'<div class="plot-wrap"><svg viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="{label}" style="{_SVG_STYLE}">')


def _svg_close() -> str:
    return '</svg></div>'


def _vgrid_ticks(parts: list, X, vals: list, y1, y2, ty, suffix: str = "") -> None:
    """竖向网格线 + 居中刻度文字（走廊/评分/PE带/业务构成/哑铃五图共用）。
    y1/y2 为网格线纵坐标、ty 为刻度文字纵坐标，数值由调用方按各图布局给出；
    suffix 为刻度数字后的单位（如 x / %）。"""
    for v in vals:
        gx = X(v)
        parts.append(f'<line x1="{gx:.1f}" y1="{y1}" x2="{gx:.1f}" y2="{y2}" stroke="{_C_GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{gx:.1f}" y="{ty}" text-anchor="middle" font-size="11" fill="{_C_LABEL}">{_fmt(v)}{suffix}</text>')


def _hgrid_ticks(parts: list, Y, vals: list, x1, x2, tx, suffix: str = "", fs: int = 11,
                 dy: int = 4, labels: bool = True) -> None:
    """横向网格线 + 右对齐刻度文字（股价发丝图/利润增长图/财务趋势面板三图共用）。
    x1/x2 为网格线横向范围、tx 为刻度文字右缘 x，数值由调用方按各图布局给出；
    suffix 为刻度数字后的单位（% 等）；labels=False 只画线不出字（财务趋势纯线面板网格随线域）。"""
    for v in vals:
        gy = Y(v)
        parts.append(f'<line x1="{x1}" y1="{gy:.1f}" x2="{x2}" y2="{gy:.1f}" stroke="{_C_GRID}" stroke-width="1"/>')
        if labels:
            parts.append(f'<text x="{tx}" y="{gy + dy:.1f}" text-anchor="end" font-size="{fs}" fill="{_C_LABEL}">{_fmt(v)}{suffix}</text>')


def _legend_row(parts: list, items: list, x, y: int = 8, fs: int = 11, sw: int = 13, sh: int = 9,
                rx: float = 2.5, dx: int = 18, gap: int = 22, tcolor: str = _C_LABEL):
    """图例横排单行：逐项画「矩形色块 + 标签文字」并水平推进，返回行末 x（下一项起点）。
    items: [(标签, 色块 fill)] 或 [(标签, 色块 fill, 色块额外属性)]；标签由本函数转义、推进宽度按
    未转义文本量取；文字基线取色块下缘（y + sh - 1）。色块尺寸/字号/间距随各图版式由参数给定。"""
    for it in items:
        txt, fill = it[0], it[1]
        extra = f' {it[2]}' if len(it) > 2 and it[2] else ""
        parts.append(f'<rect x="{x}" y="{y}" width="{sw}" height="{sh}" rx="{rx}" fill="{fill}"{extra}/>')
        parts.append(f'<text x="{x + dx}" y="{y + sh - 1}" font-size="{fs}" fill="{tcolor}">{_esc(txt)}</text>')
        x += dx + _text_w(txt, fs) + gap
    return x


def _anchor_fit(x: float, w: float, lo: float, hi: float, inset: float):
    """居中标签近边缘改对齐：左缘先查，越界改 start/end 且锚点内缩 inset
    （走廊现价标签 / PE 带当前值标签）。返回 (text-anchor, x)。"""
    if x - w / 2 < lo:
        return "start", max(x - inset, lo)
    if x + w / 2 > hi:
        return "end", min(x + inset, hi)
    return "middle", x


def _anchor_clamp(x: float, w: float, lo: float, hi: float):
    """居中标签近边缘改对齐：右缘先查，越界直接夹到 hi/lo 边界
    （走廊中枢标签 / 卖方一致带标签 / PE 带关键时点标签）。返回 (text-anchor, x)。"""
    if x + w / 2 > hi:
        return "end", hi
    if x - w / 2 < lo:
        return "start", lo
    return "middle", x


def _inject_chart_anchors(html: str, items: tuple, owner: str, tail: str, hint: str) -> str:
    """图表锚点注入（第 3 章 / 第 4 章共用）：items 为 (锚点注释, 图 HTML, 字段名) 序列，
    锚点在 → 原位替换；锚点缺失但字段已填 → 图追加到章末尾 + stderr 告警；字段未填 → 锚点静默
    清除（图返回空串）。owner=正文变量名、tail=追加位置描述、hint=锚点摆放建议，只用于告警文案。"""
    for anchor, chart_html, field in items:
        if anchor in html:
            html = html.replace(anchor, chart_html)
        elif chart_html:
            html += "\n" + chart_html
            print(f"⚠️ {owner} 缺 {anchor} 锚点：{field} 图已追加到{tail}（{hint}）", file=sys.stderr)
    return html


# 供图族模块 `from charts_base import *` 拉取全部基座符号（含下划线名，
# 免逐名漏列——v4.9 拆分初版曾漏 _C_INK 致 NameError）
__all__ = [
    "_C_LABEL", "_C_GRID", "_C_AXIS", "_C_BLUE", "_C_PAPER", "_C_INK", "_C_BLACK",
    "_C_STONE", "_C_OLIVE", "_C_SAND", "_C_SAND_LT", "_C_TRACK", "_C_PAPER_CELL",
    "_C_GOOD_LINE", "_C_YEAR_GRID", "_C_GREEN", "_C_RED", "_C_ORANGE", "_C_BADGE_DEEP",
    "_fmt_px", "_fmt_amt", "_SCENARIO_COLORS", "_prev_track_rows",
    "_pad_domain", "_lin_map", "_text_w", "_wrap_label", "_ticks",
    "_SVG_STYLE", "_svg_open", "_svg_close", "_vgrid_ticks", "_hgrid_ticks", "_legend_row",
    "_inject_chart_anchors", "_anchor_fit", "_anchor_clamp",
]
