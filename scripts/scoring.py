#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scoring.py — 评分与卡片公共基座（render_report 拆分模块，v4.8.2 重构）

内容：维度元数据/权重常量、判词与徽章函数、通用文本工具（_num/_fmt/_esc）、
compute_scores（三轨评分）、7/8/12 章卡片族（质量分汇总、估值过程卡、仓位判定卡）。
依赖方向：最底层共享层，被 charts/validate/render_report 导入；自身仅依赖标准库。
"""
import re
import sys


# 维度元数据：key -> (层, 显示名, 层内默认权重)
# v4.0 质量层：L1 本质六维（1A-1F 层内权重和=100）+ L3 预期三维（3A-3C 层内权重和=100）。
# 估值（原 2A）独立成估值分（valuation_score），不进质量分。
DIMS = [
    ("1A", "L1", "4.1 赛道与宏观", 12),
    ("1B", "L1", "4.2 产业链位置", 12),
    ("1C", "L1", "4.3 商业模式与护城河", 20),
    ("1D", "L1", "4.4 财务健康", 16),
    ("1E", "L1", "4.5 治理与资本配置", 20),
    ("1F", "L1", "4.6 资本回报质量", 20),
    ("3A", "L3", "5.1 利润增长", 40),
    ("3B", "L3", "5.2 项目确定性", 35),
    ("3C", "L3", "5.3 催化剂", 25),
]
# 层占比（质量分内 L1:L3，分型可通过 layer_share 覆盖）
DEFAULT_LAYER_SHARE = {"L1": 70, "L3": 30}
# 时机层（不入质量分）：筹码面 67% / 技术面 33%
TIMING_DIMS = [
    ("筹码面", "筹码面", 67),
    ("技术面", "技术面", 33),
]


def _dim_verdict(s: float) -> str:
    """单维得分判词（第 7 章汇总表用）：≥8 优秀 / ≥7 良好 / ≥6 中上 / ≥5 中等 / ≥4 偏弱 / <4 警示。"""
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


def _plain_text(frag: str) -> str:
    """剥掉 HTML 标签后的纯文本（内容地板字数校验与对齐机的共用口径）。"""
    return re.sub(r"<[^>]+>", "", frag or "").strip()


def _scenario_numbers(s: dict):
    """单情景 profit/pe/mcap 三组数值的机械解析（compute_valuation 与内容校验共用同一口径）：
    返回 (profit, pe_lo, pe_hi, mc_lo, mc_hi)，缺失/不可解析/列表不足时为 None。
    只做「能取出多少数」，不做口径冲突与区间合法性判断（倒挂/非正/双填由调用方
    按各自语义处理——校验层拒渲染、计算层按现行优先级取数）。"""
    profit = _num(s.get("profit"))
    pe = s.get("pe") or []
    pe_lo = _num(pe[0]) if len(pe) >= 1 else None
    pe_hi = _num(pe[1]) if len(pe) >= 2 else None
    mc = s.get("mcap") or []
    mc_lo = _num(mc[0]) if len(mc) >= 1 else None
    mc_hi = _num(mc[1]) if len(mc) >= 2 else None
    return profit, pe_lo, pe_hi, mc_lo, mc_hi


# 情景语义名（评分/估值层固有映射；可视化配色在 charts_base._SCENARIO_COLORS，按 key 查）
_SCENARIO_NAMES = {"pess": "悲观", "base": "基础", "opt": "乐观"}


def compute_valuation(fill: dict):
    """valuation 字段（结构化三情景假设）→ 全部估值数字由脚本计算。
    输入：{"shares": 46.27（亿股）, "horizon": "12个月",
           "scenarios": [{"key":"pess","label":"悲观","trigger":"…","profit":850（归母净利,亿）,"pe":[16,18]}, …]}
    情景口径二选一：profit+pe（利润口径）或 "mcap":[低,高]（目标总市值亿元，
    NAV/rNPV/SOTP 行业附录用；目标价 = mcap ÷ shares，无利润/EPS/PE 口径）。
    返回 None（字段缺失/数据不足）或 dict：
    rows（含每情景 eps/low/high/mid/upside）、central（年化中枢）、
    odds（赔率）、dispersion（离散度）、base_lo/base_hi、horizon、mode（pe/mcap）。
    rows 只填语义字段（label）；配色由 charts 层按 key 查 _SCENARIO_COLORS。"""
    v = fill.get("valuation")
    if not v:
        return None
    price = _num(fill.get("price"))
    shares = _num(v.get("shares"))
    if not price or not shares:
        print("⚠️ valuation 已填但缺 price/shares，情景表与三指标卡未生成", file=sys.stderr)
        return None
    order = {"pess": 0, "base": 1, "opt": 2}
    rows = []
    for s in v.get("scenarios") or []:
        profit, pe_lo, pe_hi, mc_lo, mc_hi = _scenario_numbers(s)
        key = str(s.get("key") or "").lower()
        if mc_lo is not None and mc_hi is not None:
            lo, hi = mc_lo / shares, mc_hi / shares
            profit = pe_lo = pe_hi = eps = None
        elif profit is not None and pe_lo is not None and pe_hi is not None:
            lo, hi = profit * pe_lo / shares, profit * pe_hi / shares
            eps = profit / shares
            mc_lo = mc_hi = None
        else:
            continue
        mid = (lo + hi) / 2
        rows.append({"key": key, "label": s.get("label") or _SCENARIO_NAMES.get(key, "情景"),
                     "trigger": str(s.get("trigger") or ""), "horizon": str(s.get("horizon") or v.get("horizon") or "12个月"),
                     "profit": profit, "pe_lo": pe_lo, "pe_hi": pe_hi,
                     "mcap_lo": mc_lo, "mcap_hi": mc_hi,
                     "eps": eps, "low": lo, "high": hi, "mid": mid,
                     "upside": mid / price - 1})
    if not rows:
        return None
    rows.sort(key=lambda r: order.get(r["key"], 1))
    # 按 key 建字典取三情景：scenarios 含多余 key 或顺序混乱时，按排序位置取行会取错
    by_key = {r["key"]: r for r in rows}
    pess = by_key.get("pess", rows[0])
    base = by_key.get("base", rows[1] if len(rows) > 1 else rows[0])
    opt = by_key.get("opt", rows[-1])
    # 年化中枢的时间维度用 base 情景的 horizon（rows 里已按情景级优先、valuation 级兜底解析）
    horizon = base["horizon"]
    m = re.search(r"(\d+\.?\d*)", horizon)
    if m:
        hv = float(m.group(1))
        months = hv * 12 if "年" in horizon else hv  # 含"年"→×12；含"月"或纯数字 → 按月
    else:
        print(f"⚠️ horizon「{horizon}」无法解析出时长，按 12 个月处理", file=sys.stderr)
        months = 12.0
    central_raw = base["mid"] / price - 1
    # v4.11.1（审核 D1）：负中枢（亏损股 profit<0 → base.mid<0 → central_raw<-1）不做年化——
    # 负底数非整数幂在 Python3 返回 complex，下游 _map_central 的 >= 比较会 TypeError 裸崩；
    # 且年化对负中枢本无意义（「中枢为负拦截器」按 central_raw<0 判定，与年化值无关）
    central = (1 + central_raw) ** (12 / months) - 1 if (months > 0 and central_raw > -1) else central_raw
    down = price - pess["low"]
    odds = None if down <= 0 else (base["mid"] - price) / down  # down<=0 → 悲观仍正收益 → ∞
    dispersion = (opt["mid"] - pess["mid"]) / price
    if rows[0]["mid"] > rows[-1]["mid"]:
        print("⚠️ valuation 三情景目标价顺序异常（悲观中枢 > 乐观中枢），请检查 profit/pe 假设"
              "——跨情景倒挂将被 validate 拒渲染（v4.11.1 起）", file=sys.stderr)
    # v5.0 机制三：悲观情景可选 floor 地板证据对象（{"type":"net_cash"/"dividend",
    # "value":元/股,"evidence":"推导"}）透传给估值分上浮分级与调节链；合法性由
    # validate._check_odds_floor 门禁（悲观下限 ≥ 现价时必须有地板且托得住）
    pess_src = next((s for s in v.get("scenarios") or []
                     if str((s or {}).get("key") or "").lower() == "pess"), None)
    pess_floor = (pess_src or {}).get("floor")
    # F14：floor.type 归一（strip+小写）——validate/scoring 过程卡/_position_steps 三处口径同源一致
    if isinstance(pess_floor, dict):
        pess_floor = {**pess_floor, "type": str(pess_floor.get("type") or "").strip().lower()}
    return {"rows": rows, "central": central, "central_raw": central_raw, "months": months,
            "odds": odds, "dispersion": dispersion, "base_lo": base["low"], "base_hi": base["high"],
            "horizon": horizon, "price": price, "pess_floor": pess_floor,
            "mode": "mcap" if rows[0]["mcap_lo"] is not None else "pe"}


def _lookup(val, pairs, default):
    """阈值表查找：pairs 为 [(阈值, 分值)] 降序，返回首个 val >= 阈值 的分值。"""
    for t, s in pairs:
        if val >= t:
            return s
    return default


def _lookup_lt(val, pairs, default):
    """严格小于阈值表查找（合理倍数等「越低越好」口径用；pairs 升序）。"""
    for t, s in pairs:
        if val < t:
            return s
    return default


# 估值分四件套阈值表（规则正文唯一权威在 scoring.md，改动须同步）
_CENTRAL_TABLE = [(20, 9.0), (15, 8.0), (10, 7.0), (5, 6.0), (0, 5.0), (-5, 4.0), (-10, 3.0)]
_ODDS_TABLE = [(2, 8.5), (1.5, 7.5), (1.0, 6.0), (0.5, 5.0), (0, 3.5)]
_DIV_TABLE = [(3, 9.0), (2, 8.0), (1, 7.0), (0, 6.0), (-1, 5.0)]
# 合理倍数：ratio = 现价 PE ÷ 带中枢，越低越便宜；1e-9 偏移保留原 ≤ 边界语义（≤1.1→5.0 / ≤1.2→3.5）
_WARRANTED_TABLE = [(0.8, 9.0), (0.9, 8.0), (1.0, 7.0), (1.1 + 1e-9, 5.0), (1.2 + 1e-9, 3.5)]


def _map_central(central: float) -> float:
    return _lookup(central * 100, _CENTRAL_TABLE, 2.0)


def _map_odds(odds) -> float:
    if odds is None:
        return 10.0  # ∞（悲观仍正收益）
    return _lookup(odds, _ODDS_TABLE, 2.0)


def _map_warranted(pe_ttm: float, band: list) -> float:
    ratio = pe_ttm / ((band[0] + band[1]) / 2)
    return _lookup_lt(ratio, _WARRANTED_TABLE, 2.0)


def _map_div(div_yield: float, risk_free: float) -> float:
    return _lookup(div_yield - risk_free, _DIV_TABLE, 4.0)


def compute_valuation_score(calc: dict, inputs: dict, gap_tier=None):
    """估值分四件套量化 = 中枢×0.4 + 赔率×0.25 + 合理倍数×0.25 + 股息×0.1。
    inputs: {"pe_ttm": 13.5, "pe_band": [14.5, 15.5], "div_yield": 1.6, "risk_free": 1.7,
             "consensus_np": 100（v5.0 机制二：当年卖方一致预期归母净利均值，亿元，可选）}
    可选 metric_label：行业口径（P/NAV、P/rNPV、P/EV、经调整PE 等）替换过程卡默认 PE(TTM) 标签。
    v5.0 机制二（乐观税门禁）：base 情景净利 ÷ consensus_np > 1.15 且 gap_tier
    （去空格大写）≠ "A" → 中枢分封顶 6 后重算总分；A 档解封不封顶；缺 consensus_np
    或 mcap 口径（base 无 profit）→ 无法校验，tax=None。
    v5.0 机制三（赔率 ∞ 地板分级上浮）：calc["odds"] is None 时读 calc["pess_floor"]——
    net_cash 硬地板 score=max(score,8.0)；dividend 软地板 score=max(score, min(round(score+1,1), 7.5))
    （保送不减分：已 ≥7.5 时不动）；floor 缺失不上浮（防御兜底，validate._check_odds_floor 已硬拒）。
    返回 dict（score + 四件套各分 + formula 文字 + tax + floor_uplift）或 None（缺 calc/inputs/字段）。"""
    if not calc or not inputs:
        return None
    pe_ttm = _num(inputs.get("pe_ttm"))
    band = inputs.get("pe_band") or []
    if pe_ttm is None or len(band) < 2:
        return None
    band = [_num(band[0]), _num(band[1])]
    if band[0] is None or band[1] is None or band[1] <= band[0]:
        return None
    central_s = _map_central(calc["central"])
    # 乐观税门禁：base 净利 vs 卖方一致预期（mcap 口径无净利可比，跳过）
    tax = None
    base_row = next((r for r in calc.get("rows") or [] if r.get("key") == "base"), None)
    base_profit = (base_row or {}).get("profit")
    consensus_np = _num(inputs.get("consensus_np"))
    if base_profit is not None and consensus_np is not None and consensus_np > 0:
        ratio = base_profit / consensus_np
        exempt = str(gap_tier or "").strip().upper() == "A"
        capped = ratio > 1.15 and not exempt
        if capped:
            central_s = min(central_s, 6)
        tax = {"ratio": ratio, "capped": capped, "exempt": exempt}
    odds_s = _map_odds(calc["odds"])
    warranted_s = _map_warranted(pe_ttm, band)
    div_yield = _num(inputs.get("div_yield"))
    risk_free = _num(inputs.get("risk_free"))
    div_s = _map_div(div_yield, risk_free) if (div_yield is not None and risk_free is not None) else 5.0
    total = round(central_s * 0.4 + odds_s * 0.25 + warranted_s * 0.25 + div_s * 0.1, 1)
    # 赔率 ∞ 地板分级上浮（总分层面；调节链一侧在 _position_steps）
    floor_uplift = None
    if calc.get("odds") is None:
        floor_type = ((calc.get("pess_floor") or {}).get("type") or "").strip()
        if floor_type == "net_cash":
            uplifted = max(total, 8.0)
        elif floor_type == "dividend":
            uplifted = max(total, min(round(total + 1, 1), 7.5))  # 保送不减分：已 ≥7.5 时不动
        else:
            uplifted = total
        if uplifted != total:
            floor_uplift = {"type": floor_type, "before": total, "after": uplifted}
        total = uplifted
    return {
        "score": total,
        "central_s": central_s, "odds_s": odds_s,
        "warranted_s": warranted_s, "div_s": div_s,
        "tax": tax, "floor_uplift": floor_uplift,
        "formula": (f"中枢 {central_s:g}×0.4 + 赔率 {odds_s:g}×0.25 + "
                    f"合理倍数 {warranted_s:g}×0.25 + 股息 {div_s:g}×0.1"),
    }


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
    """估值四件套明细行（项目/输入值/映射得分/权重），7 估值过程卡用。
    v5.0：中枢分行按 vc["tax"] 追加乐观税标注；赔率分行在 ∞ 且有地板时按
    calc["pess_floor"] 追加地板证据。"""
    pe_ttm = _num(inputs.get("pe_ttm"))
    band = inputs.get("pe_band") or [None, None]
    band_lo, band_hi = _num(band[0]), _num(band[1])
    div_yield = _num(inputs.get("div_yield"))
    risk_free = _num(inputs.get("risk_free"))
    odds_txt = "∞（悲观下限高于现价）" if calc["odds"] is None else f"{calc['odds']:.2f}"
    if calc["odds"] is None:
        fl = calc.get("pess_floor") or {}
        ftype, fvalue = str(fl.get("type") or "").strip(), _num(fl.get("value"))
        fevidence = str(fl.get("evidence") or "").strip()
        pess_low = next((r["low"] for r in calc.get("rows") or [] if r.get("key") == "pess"), None)
        if ftype in ("net_cash", "dividend") and fvalue is not None and pess_low is not None:
            ftag = "硬地板=净现金/股" if ftype == "net_cash" else "软地板=保底分红折现/股"
            odds_txt = (f"∞（悲观下限 {pess_low:g} ≥ 现价；{ftag} {fvalue:g}"
                        + (f"：{_esc(fevidence)}" if fevidence else "") + "）")
    div_txt = (f"股息率 {div_yield:g}% − 无风险 {risk_free:g}% = {div_yield - risk_free:+.1f}pct"
               if div_yield is not None and risk_free is not None else "缺股息输入（按中性 5 分）")
    # 行业口径标签（P/NAV、P/rNPV、P/EV、经调整PE 等），缺省 PE(TTM)
    # F15：用户可控文本（metric_label/horizon/floor.evidence）在拼接入行处逐段 _esc
    # （对齐 scenario label/trigger 惯例），卡内不再整串转义（防双重转义）
    mlabel = _esc(str(inputs.get("metric_label") or "PE(TTM)"))
    central_inp = f"年化中枢 {calc['central'] * 100:+.1f}%（{_esc(calc['horizon'])}）"
    tax = vc.get("tax")
    if tax and tax.get("capped"):
        central_inp += (f"（乐观税封顶 6：base 净利 ÷ 一致预期 = {tax['ratio']:.2f} > 1.15；"
                        f"解封需 9 章预期差 A 档）")
    elif tax and tax.get("exempt") and tax.get("ratio", 0) > 1.15:
        central_inp += f"（乐观税已检：比值 {tax['ratio']:.2f} > 1.15，9 章预期差 A 档解封）"
    return [
        ("中枢分", central_inp, vc["central_s"], 40),
        ("赔率分", f"赔率 {odds_txt}", vc["odds_s"], 25),
        ("合理倍数分", f"{mlabel} {pe_ttm:g}x vs 合理带 {band_lo:g}-{band_hi:g}x", vc["warranted_s"], 25),
        ("股息分", div_txt, vc["div_s"], 10),
    ]


def build_score_summary(sc: dict) -> str:
    """7 质量分汇总章尾公式条（脚本生成）：层分×占比 ± 黄灯 → 最终质量分。
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
    # 红旗扣分已在 1D 维度分内先行扣减（图上 4.4 条为扣后分），算式不重复列入
    red_note = ""
    if red_total:
        red_items = "；".join(str(r.get("item", "")) for r in sc["red_deductions"])
        red_note = (f' <span class="muted">（4.4 财务健康得分已含红旗扣分 {red_total:.1f}'
                    + (f'：{_esc(red_items)}' if red_items else "") + '）</span>')
    return (f'<div class="layer-summary">质量分 = {formula} = '
            f'<span class="badge {badge_class(quality)} badge-lg">{quality:.2f}</span>'
            f' <strong>{_quality_verdict(quality)}</strong>{red_note}</div>')


def build_valuation_process_card(calc: dict, vc: dict, inputs: dict) -> str:
    """8 估值与安全边际章末尾汇总卡（脚本生成，作为本节结论列在最后）：四件套 输入值→映射得分→权重→加权，
    总分行并入表格末行（加权和明细 + 最终估值分徽章 + 判词），档位图例留在表下小字。"""
    four = _valuation_four_rows(calc, vc, inputs)
    rows = []
    for name, inp, s, w in four:
        rows.append(
            f'<tr><td>{name}</td><td>{inp}</td>'   # inp 用户文本段已在 _valuation_four_rows 逐段 _esc
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
    legend_txt = ('估值分档位：≥8 深度安全边际 / 6-7.9 合理偏便宜 / '
                  '4-5.9 合理无安全边际 / &lt;4 贵')
    # v5.0 机制二：乐观税未检说明（tax=None：缺一致预期 / 一致预期 ≤0 / mcap 口径无净利可比）
    if not vc.get("tax"):
        cons_np = _num(inputs.get("consensus_np"))
        if calc.get("mode") == "mcap":
            legend_txt += '；乐观税未检：市值口径无净利可比'
        elif cons_np is not None and cons_np <= 0:
            # F16：键存在但 ≤0（亏损预期）与「无卖方覆盖」区分列示
            legend_txt += '；乐观税未检：一致预期为负/零，乐观税不适用'
        else:
            legend_txt += '；乐观税未检：无卖方覆盖'
    # v5.0 机制三：赔率 ∞ 地板分级上浮说明（软地板注明调节链不上浮）
    fu = vc.get("floor_uplift")
    if fu:
        if fu["type"] == "net_cash":
            legend_txt += f'；赔率 ∞ 硬地板（净现金/股）：估值分 {fu["before"]:g} → 上浮至 {fu["after"]:g}'
        else:
            legend_txt += (f'；赔率 ∞ 软地板（保底分红折现）：估值分 {fu["before"]:g} +1 '
                           f'封顶 7.5 → {fu["after"]:g}（调节链不上浮）')
    legend = f'<span class="source">{legend_txt}</span>'
    return ('<span class="section-tag">估值分计算</span>' + table + legend)


def build_dcf_cards(fill: dict) -> str:
    """8 估值章·DCF 双卡（fill["dcf"]，v4.11.3）：DCF 强制三行从 valuation_html 手写表格
    改为字段承载——卡 1=保守参数 DCF 每股值（参数口径进 sub），卡 2=现价隐含永续增速
    （反推口径进 sub），判词 info-card 收尾；「较现价高/低 X%」脚本算
    （value ÷ _num(fill.price) − 1，防伪链同源的现价比价，模型不手算）。
    dcf: {"value":422.8,"fcf0":"908.8亿（2025 OCF 1,332.2−资本开支 423.4）","growth_5y":"5%",
          "g_perp":"2.5%","wacc":"8.5%","net_cash":"2,263亿","implied_g":"0.1",
          "implied_note":"g=WACC−FCF₁/EV=…；EV=…","verdict":"隐含 g≈0 vs …（判词，不含现价比价）"}
    （value/implied_g/verdict 缺一 → 返回空串；implied_g 填数值文本不带 %，% 脚本加）"""
    d = fill.get("dcf") or {}
    value = _num(d.get("value"))
    implied_g = str(d.get("implied_g") or "").strip().rstrip("%").strip()
    verdict = str(d.get("verdict") or "").strip()
    if value is None or not implied_g or not verdict:
        return ""

    fcf0 = str(d.get("fcf0") or "").strip()
    params = "、".join(p for p in (
        f"5年增速 {str(d.get('growth_5y') or '').strip()}" if str(d.get("growth_5y") or "").strip() else "",
        f"永续 g={str(d.get('g_perp') or '').strip()}" if str(d.get("g_perp") or "").strip() else "",
        f"WACC={str(d.get('wacc') or '').strip()}" if str(d.get("wacc") or "").strip() else "") if p)
    net_cash = str(d.get("net_cash") or "").strip()
    sub1 = "；".join(p for p in (f"FCF₀={_esc(fcf0)}" if fcf0 else "",
                                 _esc(params) if params else "",
                                 f"含净现金 {_esc(net_cash)}" if net_cash else "") if p)
    card1 = ('<div class="metric-card"><div class="label">保守参数 DCF 每股值</div>'
             f'<div class="value">{_esc(_fmt(value))}<span class="unit">元</span></div>'
             + (f'<div class="sub">{sub1}</div>' if sub1 else "") + '</div>')

    implied_note = str(d.get("implied_note") or "").strip()
    card2 = ('<div class="metric-card"><div class="label">现价隐含永续增速</div>'
             f'<div class="value">{_esc(implied_g)}<span class="unit">%</span></div>'
             + (f'<div class="sub">{_esc(implied_note)}</div>' if implied_note else "") + '</div>')

    price = _num(fill.get("price"))
    pct_txt = ""
    if price and price > 0:
        pct = (value / price - 1) * 100
        pct_txt = f" 保守 DCF 每股值较现价{'高' if pct >= 0 else '低'} {abs(pct):.1f}%（脚本算）。"
    verdict_html = (f'<div class="info-card"><strong>判词：</strong>{_esc(verdict)}{pct_txt}</div>')
    return '<div class="metric-row">' + card1 + card2 + '</div>' + verdict_html


# 仓位档位序列（上浮 20% 硬顶、下调 0 兜底；规则正文唯一权威在 references/scoring.md 决策主轴节，改动须同步）
_POS_LADDER = [0, 5, 10, 20]
# 仓位结论保守度排序（孰低比较用）：不建议参与 < 观察池 < 轻仓 < 标准仓 < 重仓
_POS_RANK = {0: 0, "观察池": 1, 5: 2, 10: 3, 20: 4}
# 兜底档位文案常量：validate 红灯校验按此字面消费，改文案只许改这里（否则校验静默失效）
_LABEL_REFUSE = "不建议参与"
_POS_LABEL = {0: _LABEL_REFUSE, 5: "轻仓 ≤5%", 10: "标准仓 ≤10%", 20: "重仓 ≤20%"}


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


# v5.0 机制一（临界档透明化）：边界常量与 _matrix_slot 字面阈值同源绑定——
# 质量 7.0/5.5/4.0、估值 8.0/6.0/4.0 即矩阵分档线；改 _matrix_slot 阈值必须同步这里。
_Q_BOUNDS = (7.0, 5.5, 4.0)
_V_BOUNDS = (8.0, 6.0, 4.0)
# 临界带半宽：距最近边界 ≤0.3 判定临界（初始值，按 archive 漂移实测校准）
_CRIT_TOL = 0.3


def _edge_info(quality: float, valuation: float, floor_uplift: dict = None):
    """临界档判定（v5.0 机制一）：每轨找距离最近的档位边界，距离 ≤_CRIT_TOL 即临界。
    返回 (crit_list, q_eff, v_eff)：crit_list 记 {"track","score","bound","dist"}；
    临界轨有效分 = bound − 1e-6（压到边界下侧，作为 _position_steps 孰低比较的
    降档候选——矩阵个别行非单调，孰低须两侧实算，不能只看本侧），非临界轨原值。
    边界间距 ≥1.5 > 2×0.3，临界带内最近边界唯一，不存在两边界等距歧义。
    v5.0.0 热核修复（F3）：floor_uplift 非空且 type=="net_cash" 且估值分恰落 8.0
    （容差 1e-9）时，估值轨剔除 8.0 边界项——净现金硬地板 max(total,8.0) 的落点是
    机制产物（必恰落 8.0）而非测量噪声，不判临界（否则上浮冻结、仓位被没收降档，
    机制三承诺全落空）。乐观税封顶方向向下，不豁免。"""
    crit = []
    q_eff, v_eff = quality, valuation
    for track, score, bounds in (("质量", quality, _Q_BOUNDS), ("估值", valuation, _V_BOUNDS)):
        if (track == "估值" and floor_uplift
                and str(floor_uplift.get("type") or "") == "net_cash"
                and abs(score - 8.0) <= 1e-9):
            bounds = tuple(b for b in bounds if b != 8.0)   # 净现金硬地板上浮落点豁免临界
        bound = min(bounds, key=lambda b: abs(score - b))
        dist = abs(score - bound)
        if dist <= _CRIT_TOL:
            crit.append({"track": track, "score": score, "bound": bound, "dist": dist})
            if track == "质量":
                q_eff = bound - 1e-6
            else:
                v_eff = bound - 1e-6
    return crit, q_eff, v_eff


def build_edge_upgrade_rows(crit: list) -> str:
    """14 章档位临界升档路径行（v5.0 机制一，脚本生成）：每条临界轨一行 pending 灰态
    trig，写明升档路径（复核期该轨分越过边界 +0.3 带外）与复核证据——「错过」变
    「推迟+验证路径」。crit 为空返回空串。结构沿用模板 .trig-strip/.trig 类族。"""
    if not crit:
        return ""
    rows = []
    for c in crit:
        rows.append(
            '<div class="trig"><span class="trig-dot pending"></span>'
            f'<span class="trig-cond">档位临界升档复核：{c["track"]}分 {c["score"]:.2f}'
            f'（距 {c["bound"]} 边界 {c["dist"]:.2f}）</span>'
            f'<span class="trig-mt">升档路径：复核期{c["track"]}分 ≥{c["bound"] + _CRIT_TOL + 0.01:.2f}'
            f'（距边界 >0.3）且其余轨不恶化，恢复相邻高档位评估；'
            f'复核证据：下期财报关键指标与跟踪信号核对</span>'
            '<span class="trig-status pending">待验证</span></div>')
    return ('<span class="section-tag">档位临界升档路径（脚本生成）</span>'
            '<div class="trig-strip">' + "".join(rows) + '</div>')


def _position_steps(quality: float, valuation: float, timing, calc: dict, red_flag: str,
                    floor_uplift: dict = None):
    """仓位决策链纯函数（12 卡逻辑体，v4.9 从 build_position_card 抽出便于直接单测；
    HTML 渲染留在卡片函数）。输入 质量/估值/时机分、估值 calc、红灯 → 返回
    (final_label, steps, slot_txt, crit)：steps 为轨迹文案列表（只列实际触发条目），
    slot_txt 为矩阵落位说明（非矩阵路径为 None），crit 为档位临界列表
    （v5.0 机制一；非矩阵路径——红灯熔断/中枢为负拦截——为空列表，仓位未走矩阵不挂临界）。
    floor_uplift（v5.0.0 F3）：传估值过程卡的 vc["floor_uplift"]——net_cash 硬地板上浮
    恰落 8.0 时估值轨豁免临界判定（落点是机制产物非测量噪声），票面 8.0 不挂临界徽章、
    矩阵按 8.0 落 ≥8 列、上浮不冻结；与 render 层 14 章升档行同口径（同传一份）。
    决策优先级固定：红灯熔断 > 中枢为负拦截器 > 矩阵落位 > 时机分调节 > 离散度调节
    > 赔率 ∞ 上浮。上浮类合计净效应 ≤ +1 档且不进 20 档（重仓唯一入口是矩阵直落）。
    v5.0 机制一：矩阵落位对原分与 _edge_info 有效分两侧各落一次、取保守度孰低
    （_POS_RANK；临界轨压到边界下侧只是候选之一——质量 5.5 行非单调，v<6 时下侧
    反而更高，只算一侧会抬档），
    crit 非空时上浮类调节（时机≥6/离散度<40%/赔率∞）一律冻结，下调照常——
    防「降一档再浮一档」自我抵消。
    v5.0 机制三：赔率 ∞ 上浮一档仅当 calc["pess_floor"]["type"]=="net_cash"（硬地板）；
    dividend 软地板只保送估值分（+1 封顶 7.5），调节链不上浮；floor 缺失不上浮
    （防御兜底——validate._check_odds_floor 已硬拒无地板的赔率 ∞）。
    规则正文唯一权威在 references/scoring.md 决策主轴节，改动须同步。"""
    steps = []
    slot_txt = None
    crit = []
    if red_flag:
        final_label = _LABEL_REFUSE
        steps.append(f"红灯熔断：命中「{_esc(red_flag)}」→ 不建议参与（后续调节不再适用）")
    elif calc and calc["central_raw"] < 0:
        final_label = "回避（中枢为负，等价格）"
        steps.append(f"中枢为负拦截器：年化中枢 {calc['central'] * 100:+.1f}% < 0 → 直接回避"
                     f"（后续调节不再适用）")
    else:
        crit, q_eff, v_eff = _edge_info(quality, valuation, floor_uplift)
        # 孰低要真比较两侧落位而非只算压边界一侧：矩阵在质量 5.5 行非单调
        # （v<6 时上侧=观察池、下侧=质地一般 5）——单侧压边界会把观察池抬成轻仓 5
        # （热核审计实证：5.6×5.0 被抬档，违反「降档不抬档」）
        slot_desc, pos, _hit = min((_matrix_slot(quality, valuation),
                                    _matrix_slot(q_eff, v_eff)),
                                   key=lambda s: _POS_RANK[s[1]])
        pos_txt = _POS_LABEL.get(pos, pos) if isinstance(pos, int) else pos
        slot_txt = f"矩阵落位：质量 {quality:.2f} × 估值 {valuation:.1f} → {slot_desc} → {pos_txt}"
        for c in crit:
            slot_txt += (f"；档位临界：{c['track']}分 {c['score']:.2f} 距 {c['bound']} 边界 "
                         f"{c['dist']:.2f}，按相邻两档孰低降档执行")
        if isinstance(pos, int) and pos > 0:
            idx = _POS_LADDER.index(pos)
            # 上浮封顶（规则见 references/scoring.md 决策主轴节）：上浮类调节合计净效应
            # ≤ +1 档，且任何调节不得进入 20 档——重仓唯一入口是矩阵直接落位（≥7×≥8）。
            # 防两类历史缺陷：①轻仓被时机+离散+赔率三连浮推成重仓；②下调缺 0 兜底时
            # 负索引回卷到重仓。被拦项统一记入 blocked_by_cap，在轨迹中说明未生效原因。
            up_used = 0
            blocked_by_cap = []

            def try_up(name: str, detail: str, cap_tag: str = None) -> None:
                """上浮一档（受封顶约束）：合计净效应 ≤+1 档且不进 20 档；
                被拦项记 blocked_by_cap（cap_tag 缺省取 detail），在轨迹中说明未生效原因。
                v5.0 机制一：档位临界（crit 非空）时上浮类调节一律冻结，记轨迹不生效。"""
                nonlocal idx, up_used
                if crit:
                    steps.append(f"上浮冻结：{detail}（档位临界，上浮类调节冻结，下调照常）")
                    return
                if up_used == 0 and idx + 1 < len(_POS_LADDER) and _POS_LADDER[idx + 1] < 20:
                    steps.append(f"{name}调节：{detail} → 上浮一档"
                                 f"（{_POS_LABEL[_POS_LADDER[idx]]}→{_POS_LABEL[_POS_LADDER[idx + 1]]}）")
                    idx += 1
                    up_used = 1
                elif idx + 1 < len(_POS_LADDER):  # 落位已在顶格时不重复解释
                    blocked_by_cap.append(cap_tag if cap_tag is not None else detail)

            # 时机分调节（≥6 上浮一档 / <4 下调一档；0 兜底）
            if timing is not None and timing >= 6:
                try_up("时机分", f"时机分 {timing:.2f} ≥ 6")
            elif timing is not None and timing < 4:
                new_idx = max(idx - 1, 0)
                steps.append(f"时机分调节：时机分 {timing:.2f} < 4 → 下调一档"
                             f"（{_POS_LABEL[_POS_LADDER[idx]]}→{_POS_LABEL[_POS_LADDER[new_idx]]}）")
                idx = new_idx
            # 离散度调节（>90% 下调一档 / <40% 上浮一档；60% 旧阈值在 20 份报告中触发率 70%，
            # 形同普遍降档，已按经验分布收紧到极端档）
            # v4.11.1（审核 D2）：dispersion < 0 = 三情景倒挂的衍生假信号（校验层漏网时的
            # 第二道防线），不得判为「低不确定性」上浮——加 0 下限守卫
            if calc and calc["dispersion"] > 0.90:
                new_idx = max(idx - 1, 0)
                steps.append(f"离散度调节：离散度 {calc['dispersion'] * 100:.1f}% > 90% → 下调一档"
                             f"（{_POS_LABEL[_POS_LADDER[idx]]}→{_POS_LABEL[_POS_LADDER[new_idx]]}）")
                idx = new_idx
            elif calc and 0 <= calc["dispersion"] < 0.40:
                try_up("离散度", f"离散度 {calc['dispersion'] * 100:.1f}% < 40%")
            # 赔率 ∞ 上浮一档（受封顶约束；v5.0 机制三收紧：仅硬地板=净现金享受，
            # 软地板=保底分红折现只保送估值分、调节链不上浮；floor 缺失为校验漏网防御）
            if calc and calc["odds"] is None:
                floor_type = (calc.get("pess_floor") or {}).get("type")
                if floor_type == "net_cash":
                    try_up("赔率", "赔率 ∞（悲观仍正收益）", "赔率 ∞")
                elif floor_type == "dividend":
                    steps.append("赔率 ∞（软地板=保底分红折现）：估值分 +1 封顶 7.5，调节链不上浮")
            if blocked_by_cap:
                steps.append("上浮封顶：" + "、".join(blocked_by_cap)
                             + " 同样满足上浮条件，受「上浮合计 ≤1 档且不进 20 档」限制未生效")
            final_label = _POS_LABEL[_POS_LADDER[idx]]
        elif pos == 0:
            final_label = _LABEL_REFUSE
        else:
            # 观察池：不因时机/赔率上浮；时机 <4 或离散度 >90% 下调为不建议参与
            down = []
            if timing is not None and timing < 4:
                down.append(f"时机分 {timing:.2f} < 4")
            if calc and calc["dispersion"] > 0.90:
                down.append(f"离散度 {calc['dispersion'] * 100:.1f}% > 90%")
            if down:
                steps.append(f"{'；'.join(down)} → 观察池下调为不建议参与")
                final_label = _LABEL_REFUSE
            else:
                final_label = "观察池"
        if not steps:
            steps.append("矩阵落位直接生效，无调节项触发")
    return final_label, steps, slot_txt, crit


def build_position_card(fill: dict, quality: float, valuation: float, timing,
                        calc: dict, red_flag: str, floor_uplift: dict = None) -> str:
    """12 仓位与时机决策章末尾三轨判定卡（脚本生成，置于 position_html 之后）：
    ① 三轨判定行（质量/估值/时机各带落档判词）→ ② 调节轨迹（只列实际触发条目）
    → ③ 最终仓位结论徽章行。决策链逻辑在 _position_steps（纯函数），本函数只做
    HTML 渲染。完整决策矩阵规则见 references/scoring.md，报告不展开。
    v5.0 机制一：临界轨的质量/估值卡 sub 追加「档位临界」橙徽章 + 距离说明。
    v5.0.0（F3）：floor_uplift 透传决策链——net_cash 硬地板上浮恰落 8.0 豁免临界
    （调用方 render 层与 14 章升档行同传 vc["floor_uplift"]，徽章与升档行同生共灭）。"""
    parts = ['<span class="section-tag">三轨判定与仓位结论</span>']

    # 决策链先行（① 的临界徽章依赖 crit）：逻辑在 _position_steps（纯函数，规则注释见其 docstring）
    final_label, steps, slot_txt, crit = _position_steps(quality, valuation, timing, calc, red_flag,
                                                         floor_uplift)

    # ① 三轨判定行
    q_sub = (f'{_quality_verdict(quality)}'
             f'（≥7 好公司 / 5.5-6.9 中上 / 4-5.4 一般 / &lt;4 回避）')
    v_sub = (f'{_valuation_verdict(valuation)}'
             f'（≥8 深度安全边际 / 6-7.9 合理偏便宜 / 4-5.9 合理 / &lt;4 贵）')
    for c in crit:
        note = (f' <span class="badge badge-orange">档位临界</span>'
                f' 距 {c["bound"]} 边界 {c["dist"]:.2f}，按降档执行')
        if c["track"] == "质量":
            q_sub += note
        else:
            v_sub += note
    t_txt = f"{timing:.2f}" if timing is not None else "—"
    t_verdict = _timing_verdict(timing) if timing is not None else "—"
    parts.append(
        '<div class="metric-row">'
        f'<div class="metric-card"><div class="label">质量分</div>'
        f'<div class="value">{quality:.2f}</div><div class="sub">{q_sub}</div></div>'
        f'<div class="metric-card"><div class="label">估值分</div>'
        f'<div class="value">{valuation:.1f}</div><div class="sub">{v_sub}</div></div>'
        f'<div class="metric-card"><div class="label">时机分</div>'
        f'<div class="value">{t_txt}</div><div class="sub">{t_verdict}'
        f'（≥6 好时机 / 4-5.9 中性 / &lt;4 差时机）</div></div>'
        '</div>')

    # ② 调节轨迹
    parts.append('<div class="track-summary">' + "".join(
        f'<div class="ts-row"><span class="ts-formula">{s}</span></div>' for s in steps) + '</div>')

    # ③ 最终仓位结论徽章行（落位信息并入，报告只显示落位与结论）
    final_badge = ("badge-red" if final_label in (_LABEL_REFUSE,) or final_label.startswith("回避")
                   else "badge-orange" if final_label in ("观察池", "轻仓 ≤5%")
                   else "badge-blue" if final_label.startswith("标准仓") else "badge-green")
    slot_html = f'<span class="muted">{slot_txt} ｜ </span>' if slot_txt else ""
    parts.append(f'<div class="decision-bar"><strong>最终仓位结论：</strong>{slot_html}'
                 f'<span class="badge {final_badge} badge-lg">{final_label}</span></div>')
    return "".join(parts)
