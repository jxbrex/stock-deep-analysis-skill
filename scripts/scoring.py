#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scoring.py — 评分与卡片公共基座（render_report 拆分模块，v4.8.2 重构）

内容：维度元数据/权重常量、判词与徽章函数、通用文本工具（_num/_fmt/_esc）、
compute_scores（三轨评分）、6/7/11 章卡片族（质量分汇总、估值过程卡、仓位判定卡）。
依赖方向：最底层共享层，被 charts/validate/render_report 导入；自身仅依赖标准库。
"""
import re


# 维度元数据：key -> (层, 显示名, 层内默认权重)
# v4.0 质量层：L1 本质六维（1A-1F 层内权重和=100）+ L3 预期三维（3A-3C 层内权重和=100）。
# 估值（原 2A）独立成估值分（valuation_score），不进质量分。
DIMS = [
    ("1A", "L1", "3.1 赛道与宏观", 12),
    ("1B", "L1", "3.2 产业链位置", 12),
    ("1C", "L1", "3.3 商业模式与护城河", 20),
    ("1D", "L1", "3.4 财务健康", 16),
    ("1E", "L1", "3.5 治理与资本配置", 20),
    ("1F", "L1", "3.6 资本回报质量", 20),
    ("3A", "L3", "4.1 利润增长", 40),
    ("3B", "L3", "4.2 项目确定性", 35),
    ("3C", "L3", "4.3 催化剂", 25),
]
# 层占比（质量分内 L1:L3，分型可通过 layer_share 覆盖）
DEFAULT_LAYER_SHARE = {"L1": 70, "L3": 30}
# 时机层（不入质量分）：筹码面 67% / 技术面 33%
TIMING_DIMS = [
    ("筹码面", "筹码面", 67),
    ("技术面", "技术面", 33),
]


def _dim_verdict(s: float) -> str:
    """单维得分判词（第 6 章汇总表用）：≥8 优秀 / ≥7 良好 / ≥6 中上 / ≥5 中等 / ≥4 偏弱 / <4 警示。"""
    if s >= 8.0:
        return "优秀"
    if s >= 7.0:
        return "良好"
    if s >= 6.0:
        return "中上"
    if s >= 5.0:
        return "中等"
    if s >= 4.0:
        return "偏弱"
    return "警示"


LAYER_NAMES = {"L1": "公司本质", "L3": "未来预期"}
REQUIRED_SCALAR = ["company", "code", "date"]


def badge_class(score: float) -> str:
    if score >= 7.0:
        return "badge-green"
    if score >= 4.0:
        return "badge-orange"
    return "badge-red"


def valuation_badge_class(score: float) -> str:
    """估值分徽章四档配色：≥8 绿 / 6-7.9 蓝 / 4-5.9 橙 / <4 红。"""
    if score >= 8.0:
        return "badge-green"
    if score >= 6.0:
        return "badge-blue"
    if score >= 4.0:
        return "badge-orange"
    return "badge-red"


def _quality_verdict(q: float) -> str:
    """质量分判词：≥7 好公司 / 5.5-6.9 中上 / 4-5.4 一般 / <4 回避。"""
    if q >= 7.0:
        return "好公司"
    if q >= 5.5:
        return "中上"
    if q >= 4.0:
        return "一般"
    return "回避"


def _valuation_verdict(v: float) -> str:
    """估值分判词（唯一口径）：≥8 深度安全边际 / 6-7.9 合理偏便宜 / 4-5.9 合理无安全边际 / <4 贵。"""
    if v >= 8.0:
        return "深度安全边际"
    if v >= 6.0:
        return "合理偏便宜"
    if v >= 4.0:
        return "合理无安全边际"
    return "贵"


def _timing_verdict(t: float) -> str:
    """时机分判词：≥6 好时机 / 4-5.9 中性 / <4 差时机。"""
    if t >= 6.0:
        return "好时机"
    if t >= 4.0:
        return "中性"
    return "差时机"


def _num(v):
    """"390.40" / "18,062.5" / 390.4 → float；取首个数字串，失败返回 None"""
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d[\d,]*\.?\d*", str(v))
    return float(m.group(0).replace(",", "")) if m else None


def _fmt(v):
    """390.4 → "390.4"；294.0 → "294" """
    return f"{v:g}"


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))



def compute_scores(fill: dict):
    """v4.0 三轨：质量分（L1 六维 + L3 三维，不含估值）+ 估值分（独立）+ 时机分（微调）。
    返回 dict：rows_html（质量层明细）/ layer_scores / layer_share / pre_risk_quality /
    yellow_total / quality（质量分）/ valuation（估值分）/ timing（时机分）/ red_flag。
    校验：L1 六维层内权重和=100；L3 三维层内权重和=100；layer_share 两值和=100；
    时机层权重和=100。"""
    scores = fill.get("scores") or {}
    w_override = fill.get("weights") or {}
    missing = [d[0] for d in DIMS if d[0] not in scores]
    if missing:
        raise ValueError(f"scores 缺维度: {missing}")

    # 1D 红旗扣分（结构化字段 red_deductions：[{item, points}]，单项上限 1 分）
    red_deductions = fill.get("red_deductions") or []
    for r in red_deductions:
        rp = float(r.get("points", 0))
        if rp < 0:
            raise ValueError(f"red_deductions 单项扣分 {rp} < 0（{r.get('item', '?')}）："
                             f"负扣分等于变相加分、绕过扣分上限，拒渲染")
        if rp > 1:
            raise ValueError(f"red_deductions 单项扣分 {rp} > 1（{r.get('item', '?')}）："
                             f"1D 红旗每项扣分上限 1 分")
    red_total = round(sum(float(r.get("points", 0)) for r in red_deductions), 2)
    if red_total:
        scores = dict(scores)
        scores["1D"] = max(0.0, float(scores["1D"]) - red_total)  # 下限 0

    # 层内权重（分型可通过 weights 覆盖；默认值即各分型的基础权重，见 scoring.md）
    weights = {}
    for key, _layer, _name, default_w in DIMS:
        weights[key] = float(w_override.get(key, default_w))
    for layer in ("L1", "L3"):
        layer_w = sum(weights[d[0]] for d in DIMS if d[1] == layer)
        if abs(layer_w - 100.0) > 0.01:
            raise ValueError(f"{layer} 层内权重总和 = {layer_w}，必须为 100（分型调整时各层内权重之和仍须等于100）")

    # 层占比（质量分内 L1:L3，分型可通过 layer_share 覆盖）
    ls_raw = fill.get("layer_share") or {}
    ls = {k: float(ls_raw.get(k, DEFAULT_LAYER_SHARE[k])) for k in ("L1", "L3")}
    if abs(sum(ls.values()) - 100.0) > 0.01:
        raise ValueError(f"layer_share 之和 = {sum(ls.values())}，必须为 100")

    layer_scores = {}
    rows = []
    for layer in ("L1", "L3"):
        dims = [d for d in DIMS if d[1] == layer]
        layer_s = sum(float(scores[d[0]]) * weights[d[0]] for d in dims) / 100.0
        layer_scores[layer] = layer_s
        for j, (key, _l, name, _dw) in enumerate(dims):
            s = float(scores[key])
            w = weights[key]
            wtd = s * w / 100.0
            badge = badge_class(s)
            # 1D 红旗注解：红旗已先行扣入 1D 得分，单元格显示「原始分 − 红旗扣分 = 扣后分」
            # （footer 算式不再列红旗项，避免与已扣分的 layer_scores 重复计算）
            score_txt = (f"{s + red_total:.1f} − {red_total:.1f} 红旗 = {s:.1f}"
                         if key == "1D" and red_total else f"{s:.1f}")
            first = (f'<td rowspan="{len(dims)}"><strong>{LAYER_NAMES[layer]}</strong>'
                     f'（占质量分 {ls[layer]:.0f}%）</td>') if j == 0 else ""
            rows.append(
                f'<tr>{first}<td>{name}</td>'
                f'<td class="center score-cell"><span class="badge {badge}">{score_txt}</span></td>'
                f'<td class="center">{_dim_verdict(s)}</td>'
                f'<td class="num">{w:g}%</td><td class="num">{wtd:.2f}</td></tr>'
            )

    # 不考虑风险质量分 = L1 层分×L1占比 + L3 层分×L3占比
    pre_risk = sum(layer_scores[l] * ls[l] for l in ("L1", "L3")) / 100.0

    # 黄灯扣分（模型填 yellow_deductions 明细：[{label, points}]）
    # 硬校验：单项 >1 或累计 >2 → 拒渲染（按规则应升红灯）
    # 黄灯扣分明细为必填键（fill-schema 标 ✓）：缺失即拒渲染，无扣分必须显式填 []
    if "yellow_deductions" not in fill:
        raise ValueError("yellow_deductions 键缺失：黄灯扣分明细必须显式给出，无扣分请填 []")
    yellow = fill.get("yellow_deductions") or []
    for y in yellow:
        yp = float(y.get("points", 0))
        if yp < 0:
            raise ValueError(f"黄灯单项扣分 {yp} < 0（{y.get('label', '?')}）："
                             f"负扣分等于变相加分、绕过扣分上限，拒渲染")
        if yp > 1:
            raise ValueError(f"黄灯单项扣分 {yp} > 1（{y.get('label', '?')}）："
                             f"累计扣分>2 或单项>1，应按规则升红灯")
    yellow_total = round(sum(float(y.get("points", 0)) for y in yellow), 2)
    if yellow_total > 2:
        raise ValueError(f"黄灯累计扣分 {yellow_total} > 2：累计扣分>2 或单项>1，应按规则升红灯")
    quality = max(0.0, round(pre_risk - yellow_total, 2))  # 最终质量分（下限 0）

    # 估值分（独立价格轨；fill 里的 valuation_score 只做范围校验，
    # 最终值由 render 用四件套计算结果覆盖，见 compute_valuation_score）
    valuation = None
    v_raw = fill.get("valuation_score")
    if v_raw is not None:
        try:
            valuation = float(v_raw)
        except (TypeError, ValueError):
            raise ValueError("valuation_score 必须是 0-10 数字")
        if not (0 <= valuation <= 10):
            raise ValueError(f"valuation_score = {valuation} 超出 0-10 范围")

    # 时机分（筹码面 67% + 技术面 33%；只算分值，时机轨表在 11 由模型呈现，09 只给小结）
    # timing_scores 为必填键：缺失或缺维度即拒渲染（不允许静默按 0 计入，消除 get(k,0) 兜底）
    t_scores = fill.get("timing_scores")
    if not isinstance(t_scores, dict) or not t_scores:
        raise ValueError("timing_scores 为必填字段：时机层得分对象（筹码面/技术面），缺失即拒渲染")
    miss_t = [k for k, _n, _w in TIMING_DIMS if k not in t_scores]
    if miss_t:
        raise ValueError(f"timing_scores 缺维度: {miss_t}（筹码面/技术面缺一不可，不接受缺维按 0 计）")
    bad_t = [k for k in t_scores if k not in {d[0] for d in TIMING_DIMS}]
    if bad_t:
        raise ValueError(f"timing_scores 含非法键名 {bad_t}：只接受 筹码面/技术面（2B/2C 旧键名兼容已移除）")
    t_weights = {k: float((fill.get("timing_weights") or {}).get(k, dw)) for k, _n, dw in TIMING_DIMS}
    tw_sum = sum(t_weights.values())
    if abs(tw_sum - 100.0) > 0.01:
        raise ValueError(f"时机层权重总和 = {tw_sum}，必须为 100")
    timing = sum(float(t_scores[k]) * t_weights[k] for k, _n, _w in TIMING_DIMS) / 100.0

    red_flag = (fill.get("red_flag") or "").strip()
    return {
        "rows_html": "\n".join(rows), "layer_scores": layer_scores,
        "layer_share": ls, "pre_risk_quality": pre_risk,
        "yellow_total": yellow_total, "quality": quality,
        "red_total": red_total, "red_deductions": red_deductions,
        "valuation": valuation, "timing": timing,
        "red_flag": red_flag,
        # 供评分横条图使用（与汇总表同一份口径：1D 已含红旗扣减，权重为实际生效值）
        "weights": weights,
        "adj_scores": {k: float(scores[k]) for k, _l, _n, _w in DIMS},
    }


# ---------- 脚本生成区块（6 质量分汇总 / 7 估值过程卡 / 11 三轨判定与仓位结论卡） ----------

def _valuation_four_rows(calc: dict, vc: dict, inputs: dict):
    """估值四件套明细行（项目/输入值/映射得分/权重），7 估值过程卡用。"""
    pe_ttm = _num(inputs.get("pe_ttm"))
    band = inputs.get("pe_band") or [None, None]
    band_lo, band_hi = _num(band[0]), _num(band[1])
    div_yield = _num(inputs.get("div_yield"))
    risk_free = _num(inputs.get("risk_free"))
    odds_txt = "∞（悲观下限高于现价）" if calc["odds"] is None else f"{calc['odds']:.2f}"
    div_txt = (f"股息率 {div_yield:g}% − 无风险 {risk_free:g}% = {div_yield - risk_free:+.1f}pct"
               if div_yield is not None and risk_free is not None else "缺股息输入（按中性 5 分）")
    # 行业口径标签（P/NAV、P/rNPV、P/EV、经调整PE 等），缺省 PE(TTM)
    mlabel = str(inputs.get("metric_label") or "PE(TTM)")
    return [
        ("中枢分", f"年化中枢 {calc['central'] * 100:+.1f}%（{calc['horizon']}）", vc["central_s"], 40),
        ("赔率分", f"赔率 {odds_txt}", vc["odds_s"], 25),
        ("合理倍数分", f"{mlabel} {pe_ttm:g}x vs 合理带 {band_lo:g}-{band_hi:g}x", vc["warranted_s"], 25),
        ("股息分", div_txt, vc["div_s"], 10),
    ]


def build_score_summary(sc: dict) -> str:
    """6 质量分汇总章尾公式条（脚本生成）：层分×占比 ± 黄灯 → 最终质量分。
    9 行维度明细表已并入上方的评分分布横条图（得分/判词/权重/加权全部由图承载，见
    build_score_bars），本章不再重复表格——footer 只保留算式与最终分。"""
    layer_scores, ls = sc["layer_scores"], sc["layer_share"]
    quality, yellow_total = sc["quality"], sc["yellow_total"]
    red_total = sc["red_total"]

    terms = " + ".join(
        f"{LAYER_NAMES[layer]} {layer_scores[layer]:.2f} × {ls[layer]:.0f}%"
        for layer in ("L1", "L3"))
    parts = [terms]
    if yellow_total:
        parts.append(f"− 黄灯 {yellow_total:.1f}")
    formula = " ".join(parts)
    # 红旗扣分已在 1D 维度分内先行扣减（图上 3.4 条为扣后分），算式不重复列入
    red_note = ""
    if red_total:
        red_items = "；".join(str(r.get("item", "")) for r in sc["red_deductions"])
        red_note = (f' <span class="muted">（3.4 财务健康得分已含红旗扣分 {red_total:.1f}'
                    + (f'：{_esc(red_items)}' if red_items else "") + '）</span>')
    return (f'<div class="layer-summary">质量分 = {formula} = '
            f'<span class="badge {badge_class(quality)} badge-lg">{quality:.2f}</span>'
            f' <strong>{_quality_verdict(quality)}</strong>{red_note}</div>')


def build_valuation_process_card(calc: dict, vc: dict, inputs: dict) -> str:
    """7 估值与安全边际章末尾汇总卡（脚本生成，作为本节结论列在最后）：四件套 输入值→映射得分→权重→加权，
    总分行并入表格末行（加权和明细 + 最终估值分徽章 + 判词），档位图例留在表下小字。"""
    four = _valuation_four_rows(calc, vc, inputs)
    rows = []
    for name, inp, s, w in four:
        rows.append(
            f'<tr><td>{name}</td><td>{_esc(inp)}</td>'
            f'<td class="center score-cell"><span class="badge {badge_class(s)}">{s:.1f}</span></td>'
            f'<td class="num">×{w}%</td><td class="num">{s * w / 100:.2f}</td></tr>')
    score = vc["score"]
    # 总分行：加权和明细 + 最终分徽章 + 判词（不再单列 decision-bar）
    wsum = " + ".join(f"{s * w / 100:.2f}" for _n, _i, s, w in four)
    rows.append(
        f'<tr><td colspan="2"><strong>估值分 = {wsum} = {score:.1f}</strong></td>'
        f'<td class="center score-cell"><span class="badge {valuation_badge_class(score)} badge-lg">'
        f'{score:.1f}</span></td>'
        f'<td colspan="2"><strong>{_valuation_verdict(score)}</strong></td></tr>')
    table = ('<div class="table-scroll"><table><thead><tr><th>套件</th><th>输入值</th>'
             '<th class="center">映射得分</th><th class="num">权重</th><th class="num">加权</th></tr></thead>'
             '<tbody>' + "".join(rows) + '</tbody></table></div>')
    legend = ('<span class="source">估值分档位：≥8 深度安全边际 / 6-7.9 合理偏便宜 / '
              '4-5.9 合理无安全边际 / &lt;4 贵</span>')
    return ('<span class="section-tag">估值分计算</span>' + table + legend)


# 仓位档位序列（上浮 20% 硬顶、下调 0 兜底；规则正文唯一权威在 references/scoring.md 决策主轴节，改动须同步）
_POS_LADDER = [0, 5, 10, 20]
_POS_LABEL = {0: "不建议参与", 5: "轻仓 ≤5%", 10: "标准仓 ≤10%", 20: "重仓 ≤20%"}


def _matrix_slot(q: float, v: float):
    """决策矩阵落位（唯一口径）：返回 (档位描述, 档位值或'观察池', 命中行号)。"""
    if q >= 7.0:
        if v >= 8.0:
            return ("好公司·好价格", 20, 0)
        if v >= 6.0:
            return ("好公司·合理偏便宜", 10, 1)
        if v >= 4.0:
            return ("好公司·合理无安全边际", 5, 2)
        return ("好公司·差价格", "观察池", 3)
    if q >= 5.5:
        if v >= 8.0:
            return ("中上·好价格", 10, 4)
        if v >= 6.0:
            return ("中上·合理偏便宜", 5, 5)
        return ("中上·差价格", "观察池", 6)
    if q >= 4.0:
        return ("质地一般", 5, 7)
    # 注意：必须返回整数 0（_POS_LADDER 档位），返回字符串会被 build_position_card
    # 落入「观察池」分支——质量 <4 的正确结论是「不建议参与」
    return ("质量<4", 0, 8)


def build_position_card(fill: dict, quality: float, valuation: float, timing,
                        calc: dict, red_flag: str) -> str:
    """11 仓位与时机决策章末尾三轨判定卡（脚本生成，置于 position_html 之后）：
    ① 三轨判定行（质量/估值/时机各带落档判词）→ ② 调节轨迹（只列实际触发条目）
    → ③ 最终仓位结论徽章行。完整决策矩阵规则见 references/scoring.md，报告不展开。"""
    parts = ['<span class="section-tag">三轨判定与仓位结论</span>']

    # ① 三轨判定行
    t_txt = f"{timing:.2f}" if timing is not None else "—"
    t_verdict = _timing_verdict(timing) if timing is not None else "—"
    parts.append(
        '<div class="metric-row">'
        f'<div class="metric-card"><div class="label">质量分</div>'
        f'<div class="value">{quality:.2f}</div><div class="sub">{_quality_verdict(quality)}'
        f'（≥7 好公司 / 5.5-6.9 中上 / 4-5.4 一般 / &lt;4 回避）</div></div>'
        f'<div class="metric-card"><div class="label">估值分</div>'
        f'<div class="value">{valuation:.1f}</div><div class="sub">{_valuation_verdict(valuation)}'
        f'（≥8 深度安全边际 / 6-7.9 合理偏便宜 / 4-5.9 合理 / &lt;4 贵）</div></div>'
        f'<div class="metric-card"><div class="label">时机分</div>'
        f'<div class="value">{t_txt}</div><div class="sub">{t_verdict}'
        f'（≥6 好时机 / 4-5.9 中性 / &lt;4 差时机）</div></div>'
        '</div>')

    # ② 调节轨迹（固定优先级：红灯熔断 > 中枢为负拦截器 > 矩阵落位
    #    > 时机分调节 > 离散度调节 > 赔率 ∞ 上浮；只列实际触发条目，未触发不列。
    #    上浮类合计净效应 ≤ +1 档且不进 20 档，被拦项以「上浮封顶」条目说明）
    steps = []
    slot_txt = None
    if red_flag:
        final_label = "不建议参与"
        steps.append(f"红灯熔断：命中「{_esc(red_flag)}」→ 不建议参与（后续调节不再适用）")
    elif calc and calc["central_raw"] < 0:
        final_label = "回避（中枢为负，等价格）"
        steps.append(f"中枢为负拦截器：年化中枢 {calc['central'] * 100:+.1f}% < 0 → 直接回避"
                     f"（后续调节不再适用）")
    else:
        slot_desc, pos, _hit = _matrix_slot(quality, valuation)
        pos_txt = _POS_LABEL.get(pos, pos) if isinstance(pos, int) else pos
        slot_txt = f"矩阵落位：质量 {quality:.2f} × 估值 {valuation:.1f} → {slot_desc} → {pos_txt}"
        if isinstance(pos, int) and pos > 0:
            idx = _POS_LADDER.index(pos)
            # 上浮封顶（规则见 references/scoring.md 决策主轴节）：上浮类调节合计净效应
            # ≤ +1 档，且任何调节不得进入 20 档——重仓唯一入口是矩阵直接落位（≥7×≥8）。
            # 防两类历史缺陷：①轻仓被时机+离散+赔率三连浮推成重仓；②下调缺 0 兜底时
            # 负索引回卷到重仓。被拦项统一记入 blocked_by_cap，在轨迹中说明未生效原因。
            up_used = 0
            blocked_by_cap = []
            # 时机分调节（≥6 上浮一档 / <4 下调一档；0 兜底）
            if timing is not None and timing >= 6:
                if (up_used == 0 and idx + 1 < len(_POS_LADDER)
                        and _POS_LADDER[idx + 1] < 20):
                    steps.append(f"时机分调节：时机分 {timing:.2f} ≥ 6 → 上浮一档"
                                 f"（{_POS_LABEL[_POS_LADDER[idx]]}→{_POS_LABEL[_POS_LADDER[idx + 1]]}）")
                    idx += 1
                    up_used = 1
                elif idx + 1 < len(_POS_LADDER):  # 落位已在顶格时不重复解释
                    blocked_by_cap.append(f"时机分 {timing:.2f} ≥ 6")
            elif timing is not None and timing < 4:
                new_idx = max(idx - 1, 0)
                steps.append(f"时机分调节：时机分 {timing:.2f} < 4 → 下调一档"
                             f"（{_POS_LABEL[_POS_LADDER[idx]]}→{_POS_LABEL[_POS_LADDER[new_idx]]}）")
                idx = new_idx
            # 离散度调节（>90% 下调一档 / <40% 上浮一档；60% 旧阈值在 20 份报告中触发率 70%，
            # 形同普遍降档，已按经验分布收紧到极端档）
            if calc and calc["dispersion"] > 0.90:
                new_idx = max(idx - 1, 0)
                steps.append(f"离散度调节：离散度 {calc['dispersion'] * 100:.1f}% > 90% → 下调一档"
                             f"（{_POS_LABEL[_POS_LADDER[idx]]}→{_POS_LABEL[_POS_LADDER[new_idx]]}）")
                idx = new_idx
            elif calc and calc["dispersion"] < 0.40:
                if (up_used == 0 and idx + 1 < len(_POS_LADDER)
                        and _POS_LADDER[idx + 1] < 20):
                    steps.append(f"离散度调节：离散度 {calc['dispersion'] * 100:.1f}% < 40% → 上浮一档"
                                 f"（{_POS_LABEL[_POS_LADDER[idx]]}→{_POS_LABEL[_POS_LADDER[idx + 1]]}）")
                    idx += 1
                    up_used = 1
                elif idx + 1 < len(_POS_LADDER):
                    blocked_by_cap.append(f"离散度 {calc['dispersion'] * 100:.1f}% < 40%")
            # 赔率 ∞ 上浮一档（受封顶约束）
            if calc and calc["odds"] is None:
                if (up_used == 0 and idx + 1 < len(_POS_LADDER)
                        and _POS_LADDER[idx + 1] < 20):
                    steps.append(f"赔率调节：赔率 ∞（悲观仍正收益）→ 上浮一档"
                                 f"（{_POS_LABEL[_POS_LADDER[idx]]}→{_POS_LABEL[_POS_LADDER[idx + 1]]}）")
                    idx += 1
                    up_used = 1
                elif idx + 1 < len(_POS_LADDER):
                    blocked_by_cap.append("赔率 ∞")
            if blocked_by_cap:
                steps.append("上浮封顶：" + "、".join(blocked_by_cap)
                             + " 同样满足上浮条件，受「上浮合计 ≤1 档且不进 20 档」限制未生效")
            final_label = _POS_LABEL[_POS_LADDER[idx]]
        elif pos == 0:
            final_label = "不建议参与"
        else:
            # 观察池：不因时机/赔率上浮；时机 <4 或离散度 >90% 下调为不建议参与
            down = []
            if timing is not None and timing < 4:
                down.append(f"时机分 {timing:.2f} < 4")
            if calc and calc["dispersion"] > 0.90:
                down.append(f"离散度 {calc['dispersion'] * 100:.1f}% > 90%")
            if down:
                steps.append(f"{'；'.join(down)} → 观察池下调为不建议参与")
                final_label = "不建议参与"
            else:
                final_label = "观察池"
        if not steps:
            steps.append("矩阵落位直接生效，无调节项触发")

    parts.append('<div class="track-summary">' + "".join(
        f'<div class="ts-row"><span class="ts-formula">{s}</span></div>' for s in steps) + '</div>')

    # ③ 最终仓位结论徽章行（落位信息并入，报告只显示落位与结论）
    final_badge = ("badge-red" if final_label in ("不建议参与",) or final_label.startswith("回避")
                   else "badge-orange" if final_label in ("观察池", "轻仓 ≤5%")
                   else "badge-blue" if final_label.startswith("标准仓") else "badge-green")
    slot_html = f'<span class="muted">{slot_txt} ｜ </span>' if slot_txt else ""
    parts.append(f'<div class="decision-bar"><strong>最终仓位结论：</strong>{slot_html}'
                 f'<span class="badge {final_badge} badge-lg">{final_label}</span></div>')
    return "".join(parts)
