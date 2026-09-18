#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate.py — fill 内容校验（render_report 拆分模块，v4.8.2 重构）

内容：全部 _check_* 硬校验与告警项、validate_content 总开关。
只依赖 scoring/charts_base 的常量与工具，不依赖主模块运行时状态；
告警直接打印 stderr（与拆分前行为一致）。
v4.10.2 归位出清：_tag_timing_table → align_fix.py；_check_l4_order/build_prev_strip
→ render_report.py（前者被 render 单点调用，后者为 Hero 片段构建，均非本模块校验职责）。
"""
import json
import re
import sys

from scoring import (DIMS, _num, _fmt, _scenario_numbers, _plain_text, _LABEL_REFUSE,
                     _SCENARIO_NAMES)
from charts_base import _C_BLUE


# 正文 HTML 字段全集（写作纪律/代号泄漏/.rev 高亮检查用）
_HTML_FIELDS = ("thesis_html", "conclusion_html", "p0_html", "l1_html", "l3_html", "l4_html",
                "valuation_html", "gap_html", "peers_html", "dash_html", "position_html", "review_html")
# 可含数据表的章节字段（source 来源标注检查用；thesis 不含表，剔除）
_HTML_TABLE_FIELDS = _HTML_FIELDS[1:]

# v4.11.1（审核 D8）：dim-block 切块正则容忍附加类（class="dim-block extra"），
# 三处消费方（内容地板/维度块校验/治理条）收敛同一 helper，口径唯一
_DIM_BLOCK_RE = r'<div class="dim-block(?:\s[^"]*)?">'


def _split_dim_blocks(frag: str) -> list:
    """切出全部 dim-block 片段（不含首段前导部分）。附加类形态（dim-block xxx）一并识别。"""
    return re.split(_DIM_BLOCK_RE, frag or "")[1:]


def _check_price_date(fill: dict) -> None:
    """price/date 校验：缺失/非法即拒渲染。"""
    # price 缺失/非数字、date 格式非法在此拦截（友好报错先于估值计算结果的所有使用方）
    if _num(fill.get("price")) is None:
        raise ValueError(f"price 缺失或无法解析为数字: {fill.get('price')!r}"
                         f"（Hero 指标卡与估值三情景计算都依赖现价）")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(fill.get("date") or "")):
        raise ValueError(f"date 格式非法: {fill.get('date')!r}（必须严格 YYYY-MM-DD）")


def _strict_num(v):
    """防伪比对专用严格解析：仅接受 int/float 或纯数字字符串，
    夹带任何文字（如「18.6（H股口径）」）返回 None——防伪强度不应由解析层宽松度决定。"""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "").strip()
    return float(s) if re.fullmatch(r"-?\d+(\.\d+)?", s) else None


def _req_strict(owner: str, key: str, raw):
    """防伪字段存在即须为纯数字：有值但严格解析失败 → 拒渲染（夹带文字即防伪链疑点）。"""
    v = _strict_num(raw)
    if raw is not None and str(raw).strip() and v is None:
        raise ValueError(f"{owner}.{key} 不是纯数字: {raw!r}——防伪比对字段禁止夹带文字"
                         f"（如「18.6（H股口径）」），口径注请写进 .source 说明后重渲")
    return v


def _check_quote_consistency(fill: dict) -> None:
    """quote 防伪（神华 601088 现价造假事故修复）：fill 声明 quote.source_file 时，
    读 em_fetch --out 落盘 JSON，比对 price/pe_ttm，偏差 >1% 拒渲染（与估值分四件套同级）。
    fill 侧一律严格解析（_strict_num），夹带文字即拒；quote 字段缺失不拒（存量 fill 兼容），
    由 _check_quote_present 走告警。"""
    q = fill.get("quote")
    if q is None:
        return
    if not isinstance(q, dict) or not q.get("source_file"):
        raise ValueError('quote 字段需为 {"source_file": "em_fetch --out 落盘路径", "date": "YYYY-MM-DD"}')
    src = q["source_file"]
    try:
        with open(src, encoding="utf-8") as f:
            ref = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"quote.source_file 读取失败: {src}（{e}）——防伪链断裂不能静默放行，"
                         f"请重跑 em_fetch --out 落盘后再渲染")
    for fill_key, ref_key in (("price", "price"), ("pe_ttm", "pe_ttm")):
        fv, rv = _req_strict("fill", fill_key, fill.get(fill_key)), _num(ref.get(ref_key))
        if fv is None or rv is None or rv == 0:
            continue
        if abs(fv - rv) / abs(rv) > 0.01:
            raise ValueError(f"{fill_key} 与 E1 落盘值不一致: fill={fv:g} vs {src}={rv:g}"
                             f"（偏差 {abs(fv - rv) / abs(rv) * 100:.1f}% > 1%）——现价类数字禁止手填，"
                             f"以 em_fetch --out 落盘值为准修正后重渲")
    # v4.8 四件套扩展比对（方向一防伪链闭环：神华是「真碎片+假框架」整套自洽，
    # 只比 price/pe_ttm 两个点不够，估值分输入必须同源）
    vi = fill.get("valuation_inputs") or {}
    if not vi.get("metric_label"):  # 行业口径（P/NAV、P/rNPV 等）下 pe 语义非 PE(TTM)，跳过
        vpe, rpe = _req_strict("valuation_inputs", "pe_ttm", vi.get("pe_ttm")), _num(ref.get("pe_ttm"))
        if vpe is not None and rpe:
            if abs(vpe - rpe) / abs(rpe) > 0.01:
                raise ValueError(f"valuation_inputs.pe_ttm 与 E1 落盘值不一致: fill={vpe:g} vs "
                                 f"{src}={rpe:g}（偏差 {abs(vpe - rpe) / abs(rpe) * 100:.1f}% > 1%）"
                                 f"——估值分输入与现价同级防伪，以落盘值为准修正后重渲")
        # 合理带完全落在历史极值带之外 = 校准逻辑或取数必有一假（完全无交集才拦，部分重叠正常）
        band, hb = vi.get("pe_band") or [], ref.get("pe_band") or []
        if len(band) >= 2 and len(hb) >= 2:
            blo = _req_strict("valuation_inputs", "pe_band[0]", band[0])
            bhi = _req_strict("valuation_inputs", "pe_band[1]", band[1])
            hlo, hhi = _num(hb[0]), _num(hb[1])
            if None not in (blo, bhi, hlo, hhi) and (bhi < hlo or blo > hhi):
                raise ValueError(f"valuation_inputs.pe_band [{_fmt(blo)},{_fmt(bhi)}] 与 E1 落盘历史带 "
                                 f"[{_fmt(hlo)},{_fmt(hhi)}] 完全无交集——合理带须来自历史时段匹配校准，"
                                 f"越界即防伪链疑点，请核对 pe_band 取数与校准逻辑后重渲")
    # risk_free / div_yield 偏差 >0.3pct 告警不拒（允许手工估算/税后折算，但必须可见）
    for k in ("risk_free", "div_yield"):
        fv, rv = _req_strict("valuation_inputs", k, vi.get(k)), _num(ref.get(k))
        if fv is None or rv is None:
            continue
        if k == "div_yield" and ref.get("market") != "A股":
            continue  # 港股通/红筹税后折算差异天然 >0.3pct，不做机械比对
        if abs(fv - rv) > 0.3:
            print(f"⚠️ 内容校验: valuation_inputs.{k}（{fv:g}）与 E1 落盘值（{rv:g}）偏差 >0.3pct"
                  f"——若为手工估算或税后折算口径，请在 .source 注明", file=sys.stderr)


def _check_score_ranges(fill: dict) -> None:
    """分数范围（0-10）越界是硬错误。"""
    for field in ("scores", "timing_scores"):
        for k, v in (fill.get(field) or {}).items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{field}.{k} 不是数字: {v!r}")
            if not (0 <= fv <= 10):
                raise ValueError(f"{field}.{k} = {fv} 超出 0-10 范围")


def _check_valuation_inputs(fill: dict) -> None:
    """valuation_inputs 必填（估值分强制脚本化，四键缺一不可）。"""
    vi = fill.get("valuation_inputs")
    if not isinstance(vi, dict):
        raise ValueError('valuation_inputs 为必填字段：{"pe_ttm":…, "pe_band":[低,高], '
                         '"div_yield":…, "risk_free":…}（估值分由脚本四件套计算，不再接受手填）')
    miss_vi = [k for k in ("pe_ttm", "pe_band", "div_yield", "risk_free") if k not in vi]
    if miss_vi:
        raise ValueError(f"valuation_inputs 缺键: {miss_vi}（四键必填：pe_ttm / pe_band / div_yield / risk_free）")


def _check_valuation_scenarios(fill: dict, warns: list = None) -> None:
    """valuation 结构化三情景必填且完整（每情景：profit+PE 区间 或 mcap 市值区间 + horizon）。
    v4.11.1（审核 D2）：增跨情景顺序硬校验（pess.mid ≤ base.mid ≤ opt.mid，倒挂拒渲染）——
    旧版只校验单情景内部区间，跨档倒挂只告警不拒，负离散度还会被决策链误判为
    「低不确定性」上浮一档；docstring 承诺的「校验层拒渲染」此前未覆盖跨情景路径。
    v4.11.1（审核 D1）：profit+pe 口径负 profit 告警不拒（困境反转/未盈利应走正常化利润
    或 mcap 口径，提示模型确认口径）。"""
    v = fill.get("valuation")
    if not isinstance(v, dict) or not v.get("scenarios"):
        raise ValueError("valuation 为必填字段：结构化三情景假设（shares / horizon / scenarios），"
                         "目标价与估值分全部由脚本计算")
    shares_n = _num(v.get("shares"))
    if shares_n is None or shares_n <= 0:
        raise ValueError("valuation.shares 缺失、非法或 ≤0（总股本，亿股，必须为正数）")
    skeys = set()
    modes = set()
    mids = {}
    for s in v.get("scenarios") or []:
        skey = str(s.get("key") or "").lower()
        if skey in skeys:
            # F6：重复 key 拒渲染——双 pess 曾使地板门禁（next() 首个）与计算层（by_key 末个）
            # 口径分裂，重复键没有合法语义
            raise ValueError(f"valuation.scenarios key 重复: {skey!r}——同一情景只许一条，"
                             f"重复键会让地板门禁与估值计算取到不同情景（口径分裂），请去重后重渲")
        skeys.add(skey)
        slab = s.get("label") or s.get("key") or "?"
        # 三组数值机械解析与 compute_valuation 共用（_scenario_numbers），口径唯一
        profit, pe_lo, pe_hi, mc_lo, mc_hi = _scenario_numbers(s)
        has_mc = mc_lo is not None and mc_hi is not None
        has_profit = profit is not None
        if has_mc and has_profit:
            raise ValueError(f"valuation.scenarios[{slab}] 口径冲突：profit+pe 与 mcap 同情景只能二选一")
        if has_mc:
            # 市值口径（NAV/rNPV/SOTP 行业附录）：mcap = [低, 高] 目标总市值（亿元）
            if mc_lo <= 0 or mc_hi < mc_lo:
                raise ValueError(f"valuation.scenarios[{slab}] mcap 区间非法（mcap: [低, 高]，亿元，需 0<低≤高）")
            modes.add("mcap")
            mids[str(s.get("key") or "").lower()] = (mc_lo + mc_hi) / 2 / shares_n
        else:
            if not has_profit:
                raise ValueError(f"valuation.scenarios[{slab}] 缺净利假设（profit，归母净利亿元）"
                                 f"或目标市值区间（mcap: [低, 高]，亿元）")
            if pe_lo is None or pe_hi is None:
                raise ValueError(f"valuation.scenarios[{slab}] 缺 PE 区间（pe: [低, 高]）")
            # 与 mcap 侧对称的区间校验：倒挂（高<低）或非正值一律拒渲染
            if pe_lo <= 0 or pe_hi < pe_lo:
                raise ValueError(f"valuation.scenarios[{slab}] PE 区间非法（pe: [低, 高]，需 0<低≤高）")
            if profit < 0 and warns is not None:
                warns.append(f"valuation.scenarios[{slab}] profit={profit:g} 为负：困境反转/未盈利标的"
                             f"请确认口径——profit+pe 口径应用正常化利润，原始亏损口径请改 mcap 市值区间")
            modes.add("pe")
            mids[str(s.get("key") or "").lower()] = profit * (pe_lo + pe_hi) / 2 / shares_n
        if not str(s.get("horizon") or v.get("horizon") or "").strip():
            raise ValueError(f"valuation.scenarios[{slab}] 缺时间维度（horizon，可放情景级或 valuation 级）")
    if len(modes) > 1:
        raise ValueError("valuation.scenarios 口径混用：profit+pe 与 mcap 三情景必须统一口径")
    if not {"pess", "base", "opt"} <= skeys:
        raise ValueError(f"valuation.scenarios 必须含 pess/base/opt 三情景，当前只有: {sorted(skeys)}")
    # 跨情景顺序：悲观中枢 ≤ 基础中枢 ≤ 乐观中枢（相等允许——三情景同值是合法的极端保守写法）
    if {"pess", "base", "opt"} <= set(mids):
        if mids["pess"] > mids["base"] or mids["base"] > mids["opt"]:
            raise ValueError(f"valuation 三情景中枢跨档倒挂：悲观 {mids['pess']:.2f} / 基础 {mids['base']:.2f} / "
                             f"乐观 {mids['opt']:.2f}（目标价口径，需 悲观≤基础≤乐观）——请检查各情景 "
                             f"profit/pe/mcap 假设是否填反（倒挂会产生负离散度假信号，污染仓位决策链）")


def _check_gap_plot(fill: dict, calc: dict, warns: list) -> None:
    """gap_plot 分布图字段校验（v4.11.1 落地时补设计；字段可选，缺失不查）。
    硬拒：dim 缺 name/ours/consensus 或不可解析（非法字段值不放行）。
    告警：consensus ≤0 行被图剔除、有效维度 <2（图不生成）、dims >6、street 同机构多点、
    「目标价」维度 ours 与脚本中枢价失配（镜像 thesis 一致性 2%/0.1 口径）。
    org 名真实性无法机械校验——由 fill-schema「照抄 E5 明细行、禁编造」条款 + 附注来源兜底。"""
    gp = fill.get("gap_plot")
    if gp is None:
        return
    if not isinstance(gp, dict):
        raise ValueError(f"gap_plot 字段需为对象（{{\"dims\": [...]}}），实际: {type(gp).__name__}")
    dims = gp.get("dims") or []
    if not dims:
        warns.append("gap_plot.dims 为空：分布图不会生成——无数据请整字段删除（同 holders 惯例）")
        return
    effective = 0
    cmap = {r["key"]: r["mid"] for r in (calc or {}).get("rows", [])}
    base_mid = cmap.get("base")
    for i, d in enumerate(dims):
        if not isinstance(d, dict):
            raise ValueError(f"gap_plot.dims[{i}] 不是对象：每行需 {{name, ours, consensus, ...}}")
        name = str(d.get("name") or "").strip()
        ours, cons = _num(d.get("ours")), _num(d.get("consensus"))
        if not name or ours is None or cons is None:
            raise ValueError(f"gap_plot.dims[{i}] 缺 name/ours/consensus 或不可解析：{d!r}")
        if cons <= 0:
            warns.append(f"gap_plot.dims[{i}]「{name}」consensus={cons:g} ≤0：该行图内剔除")
            continue
        effective += 1
        seen_orgs = []
        for s in (d.get("street") or []):
            if not isinstance(s, dict):
                # 热核审计 P1-1：street 元素非对象与 dims 非法行同标准——不放行
                raise ValueError(f"gap_plot.dims[{i}]「{name}」street 元素需为对象 "
                                 f'（{{"org","v","major"?}}），实际: {s!r}')
            if s.get("org"):
                seen_orgs.append(str(s["org"]))
        dup = sorted({o for o in seen_orgs if seen_orgs.count(o) > 1})
        if dup:
            warns.append(f"gap_plot.dims[{i}]「{name}」street 同机构多点: {dup}"
                         f"——一家机构 180 天内只取最新一份研报，请去重")
        if "目标价" in name and base_mid is not None and base_mid > 0:
            if abs(ours - base_mid) > 0.1 and abs(ours - base_mid) / base_mid > 0.02:
                warns.append(f"gap_plot「{name}」本文值 {ours:g} 与 valuation 基础情景中枢 "
                             f"{base_mid:.2f} 偏差 >2%：本文假设点与三情景口径须一致")
    if dims and effective < 2:
        warns.append(f"gap_plot 有效数值维度仅 {effective} 个 <2：分布图不会生成（准入规则）")
    if len(dims) > 6:
        warns.append(f"gap_plot.dims 共 {len(dims)} 行 >6：图内只画前 6 行，其余请挪 text_dims 附注")


def _check_chart_fields(fill: dict) -> None:
    """v4.9 必填图字段硬校验：fin_trend（4.4 小图墙，替手写年表）/ growth_plot（5.1 增长图）。
    两字段数据均来自标准采集（E3 年表 / E5 一致预期），缺失=空心趋势章节 → 拒渲染。
    growth_plot 豁免：stock_type 含「未盈利/管线」（净利无意义）。"""
    ft = fill.get("fin_trend")
    if not isinstance(ft, dict):
        raise ValueError('fin_trend 为必填字段（v4.9 起 4.4 财务健康年表由脚本图墙替代）：'
                         '{"years":["2021",...,"2025"], "panels":[{"title":"营收 × 毛利率",'
                         '"bars":[{"name":"营收","unit":"亿","values":[...]}], '
                         '"lines":[{"name":"毛利率","pct":true,"values":[...]}]}, ...]}'
                         '——数据照抄 em_fetch E3 年表，禁手估')
    years = ft.get("years") or []
    if len(years) < 3:
        raise ValueError(f"fin_trend.years 仅 {len(years)} 年 < 3：趋势图墙至少 3 个年度点（建议 5 年）")
    ok = []
    for p in ft.get("panels") or []:
        if not isinstance(p, dict):
            continue
        bars_ok = [b for b in p.get("bars") or []
                   if b.get("name") and len(b.get("values") or []) == len(years)
                   and all(_num(v) is not None for v in b.get("values") or [])]
        lines_ok = [ln for ln in p.get("lines") or []
                    if ln.get("name") and len(ln.get("values") or []) == len(years)
                    and all(_num(v) is not None for v in ln.get("values") or [])]
        if bars_ok or lines_ok:
            ok.append(p)
    if len(ok) < 3:
        raise ValueError(f"fin_trend.panels 有效面板 {len(ok)} < 3（标准 4 面板（v4.9.1）：营收×毛利率 / "
                         f"归母净利+扣非净利×净利率×ROE / 经营现金流+自由现金流×现金含量（阈值0.7) / "
                         f"应收+存货周转天数（纯双线）；每面板 1-2 柱或 1-2 线、柱线至少其一，"
                         f"values 与 years 等长且全为数字）")
    st = str(fill.get("stock_type") or "")
    if "未盈利" not in st and "管线" not in st:
        gp = fill.get("growth_plot")
        if not isinstance(gp, dict):
            raise ValueError('growth_plot 为必填字段（v4.9 起 5.1 利润增长配历史+预测图）：'
                             '{"hist":[{"y":"2023","rev":…,"np":…}, ...≥3年], '
                             '"fcst":[{"y":"2026E","np_lo":…,"np_hi":…,"np_consensus":…}, ...]}'
                             '——历史取 E3 同比，一致预期取 E5；未盈利/管线分型豁免')
        hist_ok = [h for h in gp.get("hist") or [] if h.get("y") and _num(h.get("np")) is not None]
        fcst_ok = [f for f in gp.get("fcst") or []
                   if f.get("y") and _num(f.get("np_lo")) is not None and _num(f.get("np_hi")) is not None
                   and _num(f.get("np_hi")) >= _num(f.get("np_lo")) and _num(f.get("np_consensus")) is not None]
        if len(hist_ok) < 3:
            raise ValueError(f"growth_plot.hist 有效年 {len(hist_ok)} < 3（需 y + np 增速；rev 可省）")
        if not fcst_ok:
            raise ValueError("growth_plot.fcst 无有效年（需 y + np_lo ≤ np_hi + np_consensus）")


def _check_red_flag_breaker(fill: dict) -> None:
    """红灯熔断：red_flag 非空 → position_html 必须包含「不建议参与」。"""
    red_flag = (fill.get("red_flag") or "").strip()
    pos_html = fill.get("position_html") or ""
    if red_flag and _LABEL_REFUSE not in _plain_text(pos_html):
        raise ValueError(f"红灯熔断：red_flag「{red_flag}」非空，position_html 必须包含「{_LABEL_REFUSE}」结论")


def _check_odds_floor(fill: dict, warns: list) -> None:
    """v5.0 机制三（赔率 ∞ 收紧·地板分级）：悲观下限 ≥ 现价（即 compute_valuation 赔率 ∞
    条件，down = price − pess_low ≤ 0）时，pess 情景必须带 floor 证据对象且托得住下限——
    floor 存在、type ∈ {net_cash, dividend}、evidence 非空、value ≥ 悲观下限×0.99
    （「悲观下限 ≤ 证据地板值」容差 1%）；任一不满足 → 拒渲染。
    floor 存在但赔率有限（下限 < 现价）→ 软告警（此时 floor 无作用）。
    挂载在 _check_valuation_scenarios 之后：shares/scenarios 合法性已由前者硬拒，
    这里取不到数时静默跳过（不重复报错）。"""
    v = fill.get("valuation")
    if not isinstance(v, dict):
        return
    # F17：floor 是悲观情景（pess）子键——写在 base/opt 不生效，软告警提示挪位
    for s in v.get("scenarios") or []:
        k = str((s or {}).get("key") or "").lower()
        if k != "pess" and isinstance((s or {}).get("floor"), dict):
            warns.append(f"valuation.scenarios[{k or '?'}] 含 floor 子键：floor 是悲观情景子键，"
                         f"写错位置不生效——请移到 pess 情景或删除")
    price = _num(fill.get("price"))
    shares = _num(v.get("shares"))
    if price is None or shares is None or shares <= 0:
        return
    pess = next((s for s in v.get("scenarios") or []
                 if str((s or {}).get("key") or "").lower() == "pess"), None)
    if not pess:
        return
    # 与 compute_valuation 同口径复算悲观下限：profit×pe_lo÷shares 或 mcap_lo÷shares
    profit, pe_lo, _pe_hi, mc_lo, _mc_hi = _scenario_numbers(pess)
    if mc_lo is not None:
        low = mc_lo / shares
    elif profit is not None and pe_lo is not None:
        low = profit * pe_lo / shares
    else:
        return
    floor = pess.get("floor")
    if low < price:
        if floor:
            warns.append(f"valuation.scenarios[悲观].floor 在赔率有限时无作用"
                         f"（悲观下限 {low:g} < 现价 {price:g}），可删——"
                         f"floor 只在悲观下限 ≥ 现价（赔率 ∞）时生效")
        return
    why = None
    if not isinstance(floor, dict):
        why = "floor 字段缺失"
    else:
        ftype = str(floor.get("type") or "").strip()
        fvalue = _num(floor.get("value"))
        fevidence = str(floor.get("evidence") or "").strip()
        if ftype not in ("net_cash", "dividend"):
            why = f"floor.type 非法: {floor.get('type')!r}（只接受 net_cash 净现金 / dividend 保底分红折现）"
        elif not fevidence:
            why = "floor.evidence 为空（须写明地板值推导，如「净现金123亿÷总股本10亿」）"
        elif fvalue is None or fvalue < low * 0.99:
            why = f"floor.value {floor.get('value')!r} 托不住悲观下限 {low:g}（须 ≥ 下限×0.99，容差 1%）"
    if why:
        raise ValueError(f"悲观下限 {low:g} 不低于现价 {price:g}（≥，含相等边界）但地板证据缺失/不足（{why}），"
                         f"赔率 ∞ 不予认定；请下修悲观情景或补 floor 字段"
                         f'（pess 情景加 "floor": {{"type":"net_cash"/"dividend",'
                         f'"value":元/股,"evidence":"地板值推导"}}）')


def _check_consensus_np(fill: dict, warns: list) -> None:
    """v5.0 机制二（乐观税门禁）交叉校验：valuation_inputs.consensus_np（当年卖方一致预期
    归母净利均值，亿元）必须照抄 em_fetch --out 落盘 JSON 的 consensus_np.np_avg——
    偏差 >1% 拒渲染；fill 有值落盘无键 → 拒渲染（手估嫌疑）；落盘有 fill 无 → 软告警
    （漏抄，乐观税未检）；双向皆缺 → 通过。读取套路复用 _check_period_track 同款
    （quote.source_file 落盘 JSON；落盘读不到时降级跳过比对——主键门禁已管）。"""
    vi = fill.get("valuation_inputs") or {}
    raw = vi.get("consensus_np")
    fc = _strict_num(raw)
    if raw is not None and str(raw).strip() and fc is None:
        raise ValueError(f"valuation_inputs.consensus_np 不是纯数字: {raw!r}——照抄字段禁止夹带文字"
                         f"（亿元；口径注请写进 .source 说明后重渲）")
    q = fill.get("quote") or {}
    src = q.get("source_file") if isinstance(q, dict) else None
    ref = None
    if src:
        try:
            with open(src, encoding="utf-8") as f:
                ref = json.load(f)
        except (OSError, json.JSONDecodeError):
            ref = None   # 落盘读不到：_check_quote_consistency 已硬拒，这里降级跳过比对
    rc = _num(((ref or {}).get("consensus_np") or {}).get("np_avg")) if ref is not None else None
    if fc is None and rc is None:
        return
    if fc is None:
        warns.append(f"valuation_inputs.consensus_np 漏抄（落盘 consensus_np.np_avg={rc:g}）："
                     f"乐观税未检——照抄 em_fetch --out 落盘值回填后重渲"
                     f"（无卖方覆盖标的落盘无此键，不在此列）")
        return
    if rc is None:
        if ref is None:
            warns.append("valuation_inputs.consensus_np 已填但 quote.source_file 缺失或读不到："
                         "无法交叉校验（quote 门禁已管主键，本条不重复硬拒）")
            return
        raise ValueError(f"valuation_inputs.consensus_np 落盘无值而 fill 填了 {fc:g}："
                         f"E5 未覆盖标的禁止手估一致预期——以 em_fetch --out 落盘为准修正后重渲")
    dev = abs(fc - rc)
    bad = abs(fc) > 0.005 if rc == 0 else dev / abs(rc) > 0.01
    if bad:
        pct = f"（偏差 {dev / abs(rc) * 100:.1f}% > 1%）" if rc else ""
        raise ValueError(f"valuation_inputs.consensus_np 与 em_fetch 落盘值不一致: fill={fc:g} vs "
                         f"落盘 consensus_np.np_avg={rc:g}{pct}——一致预期照抄落盘禁手改，"
                         f"以落盘值为准修正后重渲")


def _check_thesis_consistency(fill: dict, calc: dict) -> None:
    """thesis 三情景价一致性：手写 span 价 vs 脚本按 valuation 算出的中枢价。"""
    th = fill.get("thesis_html", "")
    span_prices = {}
    for cls, key in (("scenario-pess", "pess"), ("scenario-base", "base"), ("scenario-opt", "opt")):
        m = re.search(r'<span\b[^>]*class="[^"]*\b' + cls + r'\b[^"]*"[^>]*>(.*?)</span>', th, re.I | re.S)
        if m:
            span_prices[key] = _num(re.sub(r"<[^>]+>", "", m.group(1)))
    if len(span_prices) == 3 and calc:
        cmap = {r["key"]: r["mid"] for r in calc["rows"]}
        bad = []
        for k in ("pess", "base", "opt"):
            c, f = cmap.get(k), span_prices[k]
            if c is None or f is None:
                continue
            if c > 0:
                mismatch = abs(f - c) > 0.1 and abs(f - c) / c > 0.02
            else:
                # c≤0（极端负中枢）时相对偏差无意义，只按绝对差 >0.1 判定
                mismatch = abs(f - c) > 0.1
            if mismatch:
                bad.append(f"{_SCENARIO_NAMES[k]} 手写 {f:g} vs 脚本 {c:.2f}")
        if bad:
            # v4.11.1（审核 D7）：推导式抽成局部变量，不再 f-string 内嵌双层花括号
            hand = {k: span_prices[k] for k in ("pess", "base", "opt")}
            calc_m = {k: round(cmap.get(k, 0), 2) for k in ("pess", "base", "opt")}
            raise ValueError("thesis_html 三情景手写价与 valuation 计算值不一致（相对偏差>2% 且绝对差>0.1）："
                             + "；".join(bad)
                             + f"。手写={hand}，脚本={calc_m}")


def _check_content_floor(fill: dict) -> None:
    """内容地板（空心章节一律拒渲染）+ 表格来源标注数必须 ≥ 表格数。"""
    concl_len = len(_plain_text(fill.get("conclusion_html")))
    if concl_len < 120:
        raise ValueError(f"conclusion_html 纯文本仅 {concl_len} 字 < 120：核心结论四卡不能为空洞"
                         f"（v4.9.1 补充修订四：四卡 ul 短列表化，地板由 200 下调）")
    for name, need in (("l1_html", 6), ("l3_html", 3)):
        # 与下方字数地板同口径（_split_dim_blocks），避免 class="dim-block x" 之类写法两口径打架
        n = len(_split_dim_blocks(fill.get(name) or ""))
        if n < need:
            raise ValueError(f"{name} 仅 {n} 个 dim-block < {need}：每个评分维度必须各有一个维度块")
    if "<table" not in (fill.get("peers_html") or ""):
        raise ValueError("peers_html 不含 <table>：同业对比必须有数据表")
    pos_html = fill.get("position_html") or ""
    pos_len = len(_plain_text(pos_html))
    if pos_len < 100:
        raise ValueError(f"position_html 纯文本仅 {pos_len} 字 < 100：仓位决策四步不能为空洞")
    # 含表格的章节字段：source 来源标注数必须 ≥ 表格数
    for name in _HTML_TABLE_FIELDS:
        frag = fill.get(name) or ""
        n_tbl, n_src = frag.count("<table"), frag.count('class="source"')
        if n_tbl and n_src < n_tbl:
            raise ValueError(f"{name} 含 {n_tbl} 张数据表但只有 {n_src} 个 `.source` 来源标注："
                             f"每张表下方必须有来源标注——在缺口表格下方补 "
                             f'<span class="source">数据来源：…</span> 后重新渲染'
                             f"（报错后禁止绕过脚本手写全文 HTML，只能修 fill 重渲）")


def _check_missing_required_warns(fill: dict, warns: list) -> None:
    """必填字段缺失告警（fill-schema 标 ✓ 但渲染器原零校验，静默缺失会让分数算错或结构残缺）。"""
    if not fill.get("timing_scores"):
        warns.append("timing_scores 缺失或为空：时机分将显示 —，请补筹码面/技术面得分")
    if "yellow_deductions" not in fill:
        warns.append("yellow_deductions 键缺失：黄灯扣分按 0 处理，质量分可能虚高；无扣分请显式填 []")
    th = fill.get("thesis_html", "")
    if not th.strip():
        warns.append("thesis_html 缺失：Hero 一句话结论为空")


def _check_stock_type_weights(fill: dict, warns: list) -> None:
    """分型权重交叉校验：非默认分型必须显式填 weights/layer_share，否则静默用默认值算错分。"""
    st = str(fill.get("stock_type") or "")
    if any(t in st for t in ("稳定价值", "金融", "银行", "保险", "券商", "快速成长", "未盈利", "困境反转")):
        if not fill.get("layer_share"):
            warns.append(f"stock_type={st} 层占比非默认，但未填 layer_share——脚本将用默认 70:30 计算，分数可能错误")
        if not fill.get("weights"):
            warns.append(f"stock_type={st} L1 权重非默认，但未填 weights——脚本将用基础权重计算，分数可能错误")


def _check_thesis_price_tags(fill: dict, warns: list) -> None:
    """thesis 三情景价格标注完整性。"""
    th = fill.get("thesis_html", "")
    if th and not all(c in th for c in ("scenario-pess", "scenario-base", "scenario-opt")):
        warns.append("thesis_html 缺三情景价格标注（scenario-pess/base/opt span 未齐）")


def _check_thesis_info_floor(fill: dict, warns: list) -> None:
    """thesis 信息量地板：Hero 一句话是全文提纲挈领，不能只塞三个价格。"""
    # thesis 信息量地板：Hero 一句话是全文提纲挈领，不能只塞三个价格
    # （中兴 2026-08-24 实证：thesis 只有"12个月目标价：悲观/基础/乐观"）
    th = fill.get("thesis_html", "")
    th_txt_len = len(_plain_text(th))
    if th_txt_len:
        th_no_price = re.sub(r'<span\b[^>]*class="[^"]*\bscenario-(?:pess|base|opt)\b[^"]*"[^>]*>.*?</span>',
                             "", th, flags=re.I | re.S)
        th_rest = len(_plain_text(th_no_price))
        if th_txt_len < 60 or th_rest < 20:
            warns.append(f"thesis_html 信息量不足（纯文本 {th_txt_len} 字，剥掉三情景价后仅 {th_rest} 字）："
                         f"一句话结论 = 论点 + 关键证据 + 三情景价 + 操作结论，不能只塞目标价")


def _check_peers_plot_target(fill: dict, warns: list) -> None:
    """peers_plot 目标公司标记 + 目标点 PE/ROE 与数据口径一致性告警（不拒渲染）。"""
    pp = fill.get("peers_plot")
    pts = (pp.get("points") if isinstance(pp, dict) else pp) or []
    if pts:
        tg = [p for p in pts if p.get("target")]
        if not tg:
            warns.append("peers_plot 没有 target=true 的目标公司点")
        elif fill.get("company") and str(fill["company"]) not in str(tg[0].get("name", "")):
            warns.append(f"peers_plot 目标点名称「{tg[0].get('name')}」与公司名「{fill['company']}」不一致")
        # 口径一致性（赤峰 2026-09-02 实证：图中目标点用 A 股 PE 23.58x，正文用 H 股 18.6x）
        if tg:
            tpe = _num(tg[0].get("pe"))
            vpe = _num((fill.get("valuation_inputs") or {}).get("pe_ttm"))
            if tpe and vpe and abs(tpe - vpe) / abs(vpe) > 0.3:
                warns.append(f"peers_plot 目标公司 PE（{tpe:g}）与 valuation_inputs.pe_ttm（{vpe:g}）偏差 >30%："
                             f"请确认口径一致（A/H 股、IFRS/经调整、TTM/预测），确需混排在 peers_meta 注明")
            # ROE 量级倒挂（v4.9）：fill 无独立 ROE 参照源可比对（E1 落盘无 roe、正文为文字），
            # 只对「目标点 ROE 明显脱离同业量级」这类机械异常告警——目标比最弱同业还低一半、
            # 或比最强同业高一倍，几乎必是口径不一（年报 vs TTM/加权、不同年份）或取数错误
            troe = _num(tg[0].get("roe"))
            peers_roe = [_num(p.get("roe")) for p in pts
                         if not p.get("target") and _num(p.get("roe")) is not None and _num(p.get("roe")) > 0]
            if troe is not None and troe > 0 and len(peers_roe) >= 2:
                p_lo, p_hi = min(peers_roe), max(peers_roe)
                if troe < p_lo / 2 or troe > p_hi * 2:
                    warns.append(f"peers_plot 目标公司 ROE（{troe:g}%）脱离同业量级（同业 {p_lo:g}-{p_hi:g}%）"
                                 f"——ROE 口径疑似不一（年报/加权/TTM、不同年份）或取数错误，请核对")


def _check_timing_table_cells(fill: dict, warns: list) -> None:
    """时机判定小表单元格超长告警（长句塞格会溢出横向滚动；长解释应挪到表下 .source 行）。"""
    pos_html = fill.get("position_html") or ""
    for tm in re.finditer(r"<table\b[^>]*>.*?</table>", pos_html, re.I | re.S):
        tbl = tm.group(0)
        if "技术面" not in tbl or "筹码面" not in tbl:
            continue
        for cell in re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", tbl, re.I | re.S):
            if len(_plain_text(cell)) > 40:
                warns.append("时机判定小表存在 >40 字单元格：只写短语（≤15 字/条），"
                             "长解释与降级说明挪到表下 .source 行（fill-schema 固定 4 行 3 列格式）")
                break


def _check_dim_blocks(fill: dict, warns: list) -> None:
    """dim-block 内容地板（纯文本 <40 字拒渲染 / <80 字告警）与极端分证据校验。"""
    # dim-block 内容地板（deepseek 中兴/豪威"每块一句话凑数"缩水实证）：
    # 纯文本 <40 字 → 拒渲染（连一条论据都写不出）；<80 字 → 告警。
    # 同循环保留极端分证据校验：≥8 或 ≤3 的维度，dim-block 纯文本 <50 字 → 告警（极端分须配量化依据）
    # v4.11.1（审核 D3）：维度识别废位置 zip——乱序块会被错配（极端分门槛被静默绕过）；
    # 改与 _check_governance_strip 同口径，从 dim-name 提取 `\d\.\d` 编号映射 DIMS；
    # 提取不到编号 → 按位置兜底并告警（写法漂移可见，不静默）
    thin_reject, thin_warn = [], []
    for field, layer in (("l1_html", "L1"), ("l3_html", "L3")):
        blocks = _split_dim_blocks(fill.get(field) or "")
        dims = [d for d in DIMS if d[1] == layer]
        by_num = {d[2].split()[0]: d for d in dims}   # "4.1 赛道与宏观" → "4.1"
        fallback = 0
        for pos, blk in enumerate(blocks):
            m = re.search(r'dim-name[^>]*>\s*(\d\.\d)', blk)
            if m and m.group(1) in by_num:
                key, name = by_num[m.group(1)][0], by_num[m.group(1)][2]
            elif pos < len(dims):
                key, name = dims[pos][0], dims[pos][2]
                fallback += 1
            else:
                key, name = None, f"第 {pos + 1} 块"
            blen = len(_plain_text(blk))
            if blen < 40:
                thin_reject.append(f"{name} 仅 {blen} 字")
            elif blen < 80:
                thin_warn.append(f"{name} 仅 {blen} 字")
            if key is None:
                continue
            sv = (fill.get("scores") or {}).get(key)
            if sv is None:
                continue
            sv = float(sv)
            if (sv >= 8 or sv <= 3) and blen < 50:
                warns.append(f"{name} 得分 {sv:g}（极端分）但 dim-block 纯文本仅 {blen} 字 < 50："
                             f"≥8 或 ≤3 必须配具体量化依据")
        if fallback:
            warns.append(f"{field} 有 {fallback} 个 dim-block 未从 dim-name 提取到有效编号，"
                         f"已按位置兜底匹配——dim-name 请写「编号+名称」规范形态（如 4.1 赛道与宏观），"
                         f"乱序块的极端分证据校验依赖编号识别")
    if thin_reject:
        raise ValueError("dim-block 内容地板：" + "；".join(thin_reject)
                         + "（纯文本 <40 字）：每个维度块至少写出论据+数据，不能只写一句判语")
    if thin_warn:
        warns.append("dim-block 内容偏薄（纯文本 <80 字）：" + "；".join(thin_warn)
                     + "——每个维度块应有论据、数据与判词，薄块请补写后重渲")


def _check_internal_codes(fill: dict, warns: list) -> None:
    """框架内部代号泄漏检查：正文引用只准用章节编号/名称（L1/L3/L4/1D 代号禁入正文）。"""
    # "L1:L3" 占比记法是分型声明的合法写法，先剥离再检查
    for name in _HTML_FIELDS:
        txt = _plain_text(fill.get(name) or "").replace("L1:L3", "")
        hits = sorted(set(re.findall(r"(?<![A-Za-z0-9])(?:L[134]|1D)(?![A-Za-z0-9])", txt)))
        if hits:
            warns.append(f"{name} 正文出现框架内部代号 {'/'.join(hits)}："
                         f"请改用章节编号/名称（第 4 章 / 4.4 / 第 6 章风险评估）")


def _check_writing_discipline(fill: dict, warns: list) -> None:
    """v4.7.1 写作纪律告警（东方电气反馈）：四拍挤段 / 3 年趋势三年并排 / pe_history 无第 11 章承载。"""
    # 四拍各自成段（fill-schema dim-block 四拍结构）：判词/论据/对比/评分挤进同一个 <p> → 提示拆段
    beats = ("判词：", "论据：", "对比：", "评分：")
    for name in ("l1_html", "l3_html"):
        for pm in re.finditer(r"<p[^>]*>(.*?)</p>", fill.get(name) or "", flags=re.S):
            hits = sum(1 for b in beats if b in pm.group(1))
            if hits >= 2:
                warns.append(f"{name} 存在四拍挤段（单段含 {hits} 个拍名）："
                             f"判词/论据/对比/评分应各自成段（fill-schema dim-block 四拍结构）")
                break  # 每字段报一次即可
    # 3 年趋势表只写 起→终（方向词）：三年数字并排反而看不出趋势
    peers = fill.get("peers_html") or ""
    if "<table" in peers:
        yseq = []
        for tm in re.finditer(r"<th[^>]*>(.*?)</th>", peers, flags=re.S):
            t = re.sub(r"<[^>]+>", "", tm.group(1)).strip()
            yseq.append(bool(re.fullmatch(r"20\d{2}年?", t)))
        stacked = any(len(re.findall(r"20\d{2}\s*[：:]", cdm.group(1))) >= 2
                      for cdm in re.finditer(r"<td[^>]*>(.*?)</td>", peers, flags=re.S))
        if any(yseq[i] and yseq[i + 1] and yseq[i + 2] for i in range(len(yseq) - 2)) or stacked:
            warns.append("3 年趋势表疑似三年数字并排：应写「起→终（方向词）」"
                         "（如 8.0→30.8（大升），方向词按指标语义着色），见 fill-schema 趋势表规则")
    # pe_history 图已挂第 11 章（v4.7.1）：cycle_html 缺失 → 整章删除，图无处显示
    if (fill.get("pe_history") or {}).get("hist_lo") is not None and not (fill.get("cycle_html") or "").strip():
        warns.append("pe_history 已填但 cycle_html 缺失：PE 历史带图挂第 11 章，整章被删后图不显示"
                     "——v4.7.1 起四类分型（周期/稳健成长/稳定价值/困境反转）应写第 11 章，或删除 pe_history")


def _check_prev_fields(fill: dict, warns: list) -> None:
    """prev 内部字段校验（回测模式锚点缺项会静默显示 "?"/"—"）。"""
    if fill.get("prev"):
        pv = fill["prev"]
        for k in ("date", "quality", "valuation", "timing", "target_range"):
            if not pv.get(k):
                warns.append(f"prev.{k} 缺失：回测对比条该行将显示缺省值，请补全上版锚点")
        # 复盘高亮校验：评分变化/被证伪假设/新增变量应挂 .rev（全文 <3 处说明漏标）
        rev_n = sum((fill.get(name) or "").count('class="rev"')
                    for name in _HTML_FIELDS)
        if rev_n < 3:
            warns.append(f"回测模式下 .rev 高亮过少（全文仅 {rev_n} 处 < 3）："
                         f"评分变化/被证伪假设/新增变量应标注（fill-schema 的 .rev 规则）")
        # 关键假设变更表（防评分漂移，backtest.md 6.6 硬性要求）
        rv = fill.get("review_html") or ""
        if rv and ("<table" not in rv or "假设" not in rv):
            warns.append("review_html 缺关键假设变更表：R 章节必须含相邻两版三情景假设对比表"
                         "（假设未变也要显式写明），见 backtest.md 6.6")


def _check_misc_required(fill: dict, warns: list) -> None:
    """其余 fill-schema 标 ✓ 但渲染器零校验的必填字段。"""
    for name in ("valuation_method", "stock_type", "gap_tier", "peers_meta", "next_review"):
        if not str(fill.get(name) or "").strip() or fill.get(name) == "—":
            warns.append(f"{name} 缺失或为占位符：对应章节标题/meta 将为空白")
    if not (fill.get("subtitle") or "").strip():
        warns.append("subtitle 缺失：Hero 副标题为空")
    elif "报告日期" in fill["subtitle"]:
        warns.append("subtitle 含「报告日期」：模板 Hero 会自动追加报告日期，subtitle 请勿再写日期")


def _check_quote_present(fill: dict, warns: list) -> None:
    """quote 缺失门禁（v4.11.1 升级，审核 D5）：fill date ≥ 2026-09-02（v4.8 引入 quote 之日）
    缺 quote → 拒渲染（不填 quote 即可绕过现价防伪的静默口被关上）；此前日期的存量 fill
    → 维持告警豁免。quote 存在但不一致已在 _check_quote_consistency 拒渲染。"""
    if fill.get("quote"):
        return
    if str(fill.get("date") or "") >= "2026-09-02":
        raise ValueError("quote 字段缺失：现价/PE(TTM) 无 em_fetch --out 落盘防伪"
                         "（神华 601088 现价造假事故修复项）——v4.8 起的新报告必须在 em_fetch 时加 "
                         "--out 落盘，并在 fill 回填 quote.source_file 后重渲"
                         "（2026-09-02 前的存量 fill 仅告警豁免）")
    warns.append("quote 字段缺失：现价/PE(TTM) 无 em_fetch --out 落盘防伪（神华 601088 事故修复项）"
                 "——新报告应在 em_fetch 时加 --out 落盘，并在 fill 回填 quote.source_file")


def _check_optional_charts(fill: dict, warns: list) -> None:
    """v4.8 可选图字段纪律：业务构成占比和 / 产业链两端 / 发丝图与第 11 章绑定 / 户数期数。"""
    seg = fill.get("segments") or {}
    items = seg.get("items") or []
    if items:
        s = sum(_num(it.get("rev_pct")) or 0 for it in items)
        if abs(s - 100) > 5:
            warns.append(f"segments 收入占比合计 {s:.1f}% 偏离 100%：请核对是否漏列分部"
                         f"（E6 各分部占比之和应≈100%，若有「其他」项请补列）；"
                         f"若 E6 含按产品/地区双维数据，占比减半多为未剔合计行所致，请回 E6 原文核对")
    # v4.9：period 只放短时段标签（青啤实证把整段口径清洗说明塞进 period，图标题变 70 字怪物）
    period = str(seg.get("period") or "")
    if len(period) > 8:
        warns.append(f"segments.period「{period[:12]}…」共 {len(period)} 字 > 8：period 只放时段标签"
                     f"（如 2026中报），口径/清洗说明请挪到 segments.note（渲染为图注小字）")
    if any(k in period for k in ("口径", "源为", "合计行", "剔除", "重算")):
        warns.append("segments.period 含口径/来源字样：请挪到 segments.note 字段，period 只放时段标签")
    ch = fill.get("industry_chain") or {}
    if ch and (not ch.get("upstream") or not ch.get("downstream")):
        warns.append("industry_chain 上游/下游缺一：链条图需两端各至少 1 个行业，缺端图不生成")
    if (fill.get("price_history") or {}).get("series") and not (fill.get("cycle_html") or "").strip():
        warns.append("price_history 已填但 cycle_html 缺失：股价/PE 发丝图挂第 11 章，整章被删后图不显示"
                     "——与 pe_history 同规则（v4.7.1 绑定关系）")
    holders = fill.get("holders") or []
    if holders and len(holders) < 3:
        warns.append("holders 有效点 <3：户数趋势图不生成（E4 默认返回近 8 期，请回填 ≥3 期）")
    # v4.11.0：同一截止日多行告警（E4 上游偶发重复，天齐 20260710 双行且变动值不一致实证；
    # 图内已去重保留后写行，此处提示模型核对哪一行为准）。审计修订：去重键按数字序列归一
    #（"20260710" 与 "2026-07-10" 同日）；去重后 <3 期时图不生成，与图门槛同口径告警
    hdates = ["".join(ch for ch in str((p or {}).get("date") or "") if ch.isdigit()) for p in holders]
    dup = sorted({d for d in hdates if d and hdates.count(d) > 1})
    if dup:
        warns.append(f"holders 存在重复截止日：{'、'.join(dup)}——图内已去重（保留后写行），"
                     f"请核对 E4 原始输出哪一行的变动值为准")
    if len(holders) >= 3 and len({d for d in hdates if d}) < 3:
        warns.append("holders 去重后有效期数 <3：户数趋势图不生成（与图内去重门槛同口径）")
    # v4.9：触发条件状态条字段纪律
    trg = fill.get("triggers") or []
    if trg:
        bad = [t for t in trg
               if str((t or {}).get("status") or "pending").strip().lower() not in ("hit", "miss", "pending")]
        if bad:
            warns.append(f"triggers 含非法 status（{len(bad)} 条）：只接受 hit/miss/pending，非法值按 pending 渲染")
        if len(trg) > 8:
            warns.append(f"triggers 共 {len(trg)} 条 > 8：状态条宜 3-6 条，过多稀释跟踪焦点")


def _check_hero_band_claims(fill: dict, warns: list) -> None:
    """Hero 文案引用「分位/历史带」概念时的数据支撑核对（v4.9）：
    概念必须在 pe_history（第 11 章同源数据，与 E1 落盘 pe_p25/pe_p75、历史带同口径）有对应字段
    可佐证——「分位」→ p25/p75，「历史带/历史区间」→ hist_lo/hist_hi；有分位字段时再做
    现价 PE 相对位置的极性核对（称「低分位」而现价高于 P75、称「高分位」而现价低于 P25 即矛盾）。
    缺支撑字段 → 告警提示补数据或改文案（数据侧不存在该口径即不可信）。"""
    ph = fill.get("pe_history") or {}
    p25, p75 = _num(ph.get("p25")), _num(ph.get("p75"))
    has_iq = p25 is not None and p75 is not None
    has_extreme = _num(ph.get("hist_lo")) is not None and _num(ph.get("hist_hi")) is not None
    pe_ttm = _num((fill.get("valuation_inputs") or {}).get("pe_ttm"))
    for name in ("pe_sub", "price_sub_html", "target_sub_html"):
        txt = _plain_text(fill.get(name) or "")
        if not txt:
            continue
        # 只盯明确引用概念的字样；无概念字面的 sub（「PE」「现价」）不打扰
        if "分位" not in txt and not re.search(r"历史带|历史区间", txt):
            continue
        if "分位" in txt:
            if not has_iq:
                warns.append(f"{name} 引用「分位」但 pe_history 未填 p25/p75（E1 落盘 pe_p25/pe_p75 "
                             f"回填该字段）：Hero 分位说法在报告内无数据佐证，请补数据或改文案")
            elif pe_ttm is not None and (("低分位" in txt or "低位" in txt) and pe_ttm > p75):
                warns.append(f"{name} 称「低分位/低位」但现价 PE(TTM) {pe_ttm:g}x > P75 {p75:g}x——"
                             f"分位说法与 pe_history 数据矛盾，请核对口径")
            elif pe_ttm is not None and (("高分位" in txt or "高位" in txt) and pe_ttm < p25):
                warns.append(f"{name} 称「高分位/高位」但现价 PE(TTM) {pe_ttm:g}x < P25 {p25:g}x——"
                             f"分位说法与 pe_history 数据矛盾，请核对口径")
        if re.search(r"历史带|历史区间", txt) and not has_extreme:
            warns.append(f"{name} 引用「历史带/历史区间」但 pe_history 未填 hist_lo/hist_hi"
                         f"（E1 落盘历史带回填该字段）：该说法在报告内无数据佐证，请补数据或改文案")


def _check_conclusion_structure(fill: dict, warns: list) -> None:
    """conclusion_html 四卡结构（fill-schema 1 核心结论；v4.9.1 补充修订二起 .concl-grid
    2×2 卡网格，顺序固定）：①关键优势→②关键弱点→③当前市场认知→④核心投资逻辑。
    缺卡或乱序 → 告警不拒（纯文本关键词校验，对容器形式不敏感；
    评分数字在 Hero/section-meta 已呈现，正文不重复）。"""
    txt = _plain_text(fill.get("conclusion_html") or "")
    if len(txt) < 20:
        return  # 内容地板已在 _check_content_floor 拒渲染，这里防空
    keys = ("关键优势", "关键弱点", "当前市场认知", "核心投资逻辑")
    pos = [txt.find(k) for k in keys]
    missing = [k for k, p in zip(keys, pos) if p < 0]
    if missing:
        warns.append(f"conclusion_html 缺卡：{'/'.join(missing)}——四卡固定（.concl-grid 内四张 "
                     f".concl-card，.concl-head 卡头）：①关键优势→②关键弱点→③当前市场认知→④核心投资逻辑"
                     f"（见 fill-schema「核心结论四卡骨架」）")
    elif pos != sorted(pos):
        warns.append("conclusion_html 四卡顺序错误：应为 ①关键优势→②关键弱点→"
                     "③当前市场认知→④核心投资逻辑")


def _check_governance_strip(fill: dict, warns: list) -> None:
    """v4.9.1 补充修订二：4.5 治理与资本配置分块单行化——整块 <p> 恰为 2 个
    （判词段 + 评分末拍段）；trig 行后另起 <p> 正文 → 告警（论据应内联进 .trig-mt）。
    未用 trig-strip 的旧存量 fill 不打扰。
    补充修订四：同款清单推广到 4.3 护城河 / 5.3 催化剂（5.2 为可选形态不强制），
    <p> 恰为 2 规则同步覆盖（5.3 评分段可省，校验只看 >2）。"""
    for field, tags in (("l1_html", ("4.3", "4.5")), ("l3_html", ("5.3",))):
        for blk in _split_dim_blocks(fill.get(field) or ""):
            # 审计 P1-3：tag 从 dim-name 提取（旧「子串命中」会被块内正文提及的 4.3 截胡，
            # 导致 4.5 块被当成 4.3、扣分校验整段跳过）
            _m = re.search(r'dim-name[^>]*>\s*(\d\.\d)', blk)
            tag = _m.group(1) if _m and _m.group(1) in tags else None
            if tag is None or "trig-strip" not in blk:
                continue
            np = len(re.findall(r"<p[ >]", blk))
            if np > 2:
                warns.append(f"{tag} 维度块含 {np} 个 <p>（应恰为 2：判词段+评分末拍段）："
                             f"trig 行后不要另起 <p> 正文，论据压进 .trig-mt 一句内联（fill-schema 条款）")
            # v4.11.0（天齐 09-13 实证）：评分末拍写了扣分项但 trig 行无一「扣分」状态——
            # 方块只剩正面/中性，扣分结论断层。审计修订：扣分项识别容忍写法漂移
            #（嵌套括号/全角减号 − – －/无「扣分项（」前缀的裸负分），扣分行识别容忍 class 顺序
            # 与「已扣分/减分」文案；「不扣分」句整体豁免
            if (tag == "4.5"
                    and re.search(r"扣分[\s\S]{0,24}?[−\-–－]\s*\.?\d", blk)
                    and not re.search(r"不扣分", blk)
                    and not re.search(r'<span class="[^"]*\bmiss\b[^"]*"[^>]*>\s*(已)?[扣减]分', blk)):
                warns.append("4.5 治理块评分段含扣分项，但 trig 行无「扣分」状态："
                             "扣分结论也要写进方块——miss 红行状态文案写「扣分」（「关注」=不扣分仅跟踪，两者不得混用）")


def _check_peers_orientation(fill: dict, warns: list) -> None:
    """v4.9.1 补充修订二：同业两表公司强制行标题——目标公司蓝色加粗应标在行首格；
    蓝 style 落在 <th> 表头 = 误写成「公司=列」旧方向 → 告警。"""
    peers = fill.get("peers_html") or ""
    if re.search(r"<th[^>]*style\s*=\s*[\"'][^\"']*color\s*:\s*" + re.escape(_C_BLUE), peers, flags=re.I):
        warns.append("peers_html 目标公司蓝色加粗落在 <th> 表头（写成了公司=列旧方向）："
                     "当前指标表与趋势表应公司=行标题，目标公司蓝色加粗标在行首格（fill-schema peers 规则）")


def _check_peers_bestworst(fill: dict, warns: list) -> None:
    """v4.10：同业当前指标表每列最优/最差标注（cell-best/cell-worst）缺失告警——
    工行 09-11 报告两表零标注实证（软规则无门禁就不会被遵守）。matrix-table 兜底形态不适用。
    v4.11.0 升级为逐列检查（天齐 09-13 实证：全表 7 列只标了 4 列，市值/PE最佳/26H1 同比
    整列裸奔但零标注告警不触发）——当前指标表每个数值列至少一个 best/worst 标注，
    缺列按列名告警（方向性确实无意义的列如市值，在 peers_meta 说明后可忽略本告警）。"""
    peers = fill.get("peers_html") or ""
    if "<table" not in peers:
        return
    if "cell-best" not in peers and "cell-worst" not in peers:
        warns.append("peers_html 当前指标表无 cell-best/cell-worst 最优/最差标注："
                     "每列按指标方向性各标一格（低为优：PE/PB/负债率；高为优：ROE/增速等），"
                     "规则见 fill-schema「表格」节")
        return
    # 审计 P1-6：matrix-table 兜底只跳过它自己那张表（旧逻辑「peers 含 matrix-table 即整段跳过」
    # 会让当前指标表的逐列检查失效——多表并存实证）
    tbl = next((t for t in re.finditer(r"(<table\b[^>]*>.*?</table>)", peers, flags=re.I | re.S)
                if "matrix-table" not in t.group(0)), None)
    if not tbl:
        return
    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", tbl.group(1), flags=re.I | re.S)
    if len(rows) < 2:
        return
    cells_of = [re.findall(r"<t[hd]\b([^>]*)>(.*?)</t[hd]>", r, flags=re.I | re.S) for r in rows]
    headers = [re.sub(r"<[^>]+>", "", c).strip() for _, c in cells_of[0]]
    marked, numeric = set(), set()
    for cells in cells_of[1:]:
        for ci, (attrs, content) in enumerate(cells):
            if "cell-best" in attrs or "cell-worst" in attrs:
                marked.add(ci)
            if re.search(r"\d", re.sub(r"<[^>]+>", "", content)):
                numeric.add(ci)
    missing = [headers[ci] if ci < len(headers) else f"第{ci + 1}列"
               for ci in sorted(numeric - marked) if ci > 0]
    # 审计 P1-9：方向性无意义列（如市值）在 peers_meta 注明后抑制对应列告警
    #（fill-schema 承诺「注明即可」的实现侧——此前文档写了、实现没做，每份规范报告会稳定误报市值列）
    meta = fill.get("peers_meta") or ""
    missing = [c for c in missing if c and c not in meta]
    if missing:
        warns.append(f"peers_html 当前指标表数值列缺最优/最差标注：{'、'.join(missing)}"
                     f"——每列按方向性至少标一格（低为优：PE/PB/负债率；高为优：ROE/增速等）；"
                     f"方向性无意义的列（如市值）在 peers_meta 注明后可忽略")


def _check_peers_column_support(fill: dict, warns: list) -> None:
    """v4.10.3：peers 趋势表「无对比支撑」列告警——承接 fill-schema「无引用=删列」硬规则
    （长久只写在文档里、无校验执行）：某列超半数单元格为「—」（或空）且该列名未在同业结论框
    （.conclusion-box）中被提及 → 该列撑不起对比，应补 peers 数据或在结论框引用，否则删列。
    字符串级实现（正则切表/切格，不引解析库）；无 <table> 或该表不足 2 行时跳过。"""
    peers = fill.get("peers_html") or ""
    if "<table" not in peers:
        return
    boxes = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", " ".join(
        re.findall(r'<div class="conclusion-box".*?</div>', peers, flags=re.I | re.S)))
    for ti, tbl in enumerate(re.findall(r'<table\b[^>]*>.*?</table>', peers, flags=re.I | re.S), 1):
        trs = re.findall(r'<tr\b[^>]*>(.*?)</tr>', tbl, flags=re.I | re.S)
        if len(trs) < 2:
            continue
        heads = [_plain_text(h).strip() for h in
                 re.findall(r'<t[hd]\b[^>]*>(.*?)</t[hd]>', trs[0], flags=re.I | re.S)]
        if len(heads) < 2:
            continue
        rows = [re.findall(r'<t[hd]\b[^>]*>(.*?)</t[hd]>', tr, flags=re.I | re.S) for tr in trs[1:]]
        for j in range(1, len(heads)):   # 首列=公司名，不查
            vals = [(_plain_text(r[j]).strip() if j < len(r) else "") for r in rows]
            if not vals:
                continue
            miss = sum(1 for v in vals if not v or v.startswith("—"))
            if miss * 2 <= len(vals):
                continue   # 可得数据 ≥ 半数，正常列
            key = _peers_col_key(heads[j])
            if key and key in boxes:
                continue   # 已在结论框引用
            warns.append(f"peers_html 趋势表「{heads[j]}」列 {miss}/{len(vals)} 格为「—」"
                         f"且未在同业结论框引用（表{ti} 第{j + 1}列）：该列无对比支撑——"
                         f"补 peers 数据或在结论框引用，否则删列（fill-schema 趋势表硬要求）")


def _peers_col_key(s: str) -> str:
    """趋势表列名归一（供列-引用比对）：去括号注与「3 年」类期限、只留中英文数字核。"""
    s = re.sub(r"[（(][^）)]*[）)]", "", s or "")
    s = re.sub(r"\d+\s*年?|年", "", s)
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", s)


def _check_price_history_pe(fill: dict, warns: list) -> None:
    """v4.10：price_history 的 pe 过半缺失 → 图只画股价线而标题仍挂 PE(TTM)（图文不符）。
    A 股 E2 月线自带月末 PE(TTM) 序列应照抄——工行 09-11 报告 12 个点 pe 全缺实证。
    v4.11.0：告警口径随图门槛改为「有效 pe <12 点」（图的 PE 线门槛同步放宽——亏损期
    PE 无定义是诚实断线，照抄 E2 全序列后过半缺失不再误杀；天齐 09-13 实证 29/68 点有效）。"""
    ph = fill.get("price_history") or {}
    series = ph.get("series") or []
    if not series:
        return
    # 审计 P1-2：有效口径与图同——点数按 m/close 可解析、pe 经 _num 解析
    #（"—"/"" 等占位字符串旧口径会被计为有效 → 图文不符从缝隙漏过）
    valid = [p for p in series if isinstance(p, dict) and p.get("m") and _num(p.get("close")) is not None]
    n_pe = sum(1 for p in valid if _num(p.get("pe")) is not None)
    if len(valid) >= 12 and n_pe < 12:
        warns.append(f"price_history 的 pe 字段仅 {n_pe}/{len(valid)} 点有效（<12 点）："
                     "PE(TTM) 折线将不生成——A股 E2 月线「全序列」行自带月末 PE(TTM)，逐点照抄即可"
                     "（禁手估；亏损期缺 PE 属正常断线，无需补齐）；"
                     "港股或数据确实不可得时请在图注/正文注明口径")


def _check_l4_form(fill: dict) -> None:
    """v4.10：L4 固定形态硬门禁（工行 09-11 报告照抄 09-09 旧形态实证——软规则不拦就没人守）。
    ①损失预演必须为三联卡（.pm-grid，骨架见 fill-schema），禁止退回单段 danger-card 长文；
    ②黄灯扣分明细表行数必须与顶层 yellow_deductions 条数一致——多列=零扣分空行该删，
    少列=扣分项没列全。类别字母缺失无法核对时降级告警。"""
    l4 = fill.get("l4_html") or ""
    if "pm-grid" not in l4:
        raise ValueError("l4_html 缺损失预演三联卡（.pm-grid 固定骨架，v4.10 起）："
                         "禁止退回单段 danger-card 长文——骨架见 fill-schema「损失预演三联卡骨架」")
    yellow = fill.get("yellow_deductions") or []
    rows = re.findall(r"<tr><td>\s*[abcd][\s　]", l4)
    if rows and len(rows) != len(yellow):
        raise ValueError(f"l4_html 黄灯扣分明细表 {len(rows)} 行与 yellow_deductions {len(yellow)} 条不一致："
                         "只列 points>0 的类别行（零扣分类别不入表，表末一句「其余类别已核查无扣分」兜底），"
                         "每行扣分须与 yellow_deductions 逐项对应")
    if not rows and yellow:
        print(f"⚠️ 内容校验: l4_html 黄灯扣分明细未检出表格形态（<td>a-d 类别行），但有 "
              f"{len(yellow)} 条 yellow_deductions——请用扣分表正典形态（fill-schema「L4 黄灯扣分明细」）",
              file=sys.stderr)


def _check_cn_placeholder(fill: dict) -> None:
    """fill 正文字段中文占位符硬校验（与渲染后 _check_leftover 同口径的前置版，v4.10.2）：
    【待填】类残留提前到校验期拦截——--check 与 render 对 fill 问题拦截面一致，
    不再出现「check 退出 0 但 render 才炸」。黄灯类别标注（【b 行业与政策环境】这类
    以单个 a-d 字母开头的）是合法引用，不算占位符；fill 里的字面 {{KEY}} 合法
    （渲染时实体化显示），不在此查。"""
    for name in _HTML_FIELDS:
        hits = [x for x in re.findall(r"【[^】]{0,40}】", fill.get(name) or "")
                if not re.match(r"【[a-dA-D][ 、\s]", x)]
        if hits:
            raise ValueError(f"{name} 残留中文占位符: {sorted(set(hits))}——请填写实际内容后重渲")


def _check_review_miss_diagnostics(fill: dict, warns: list) -> None:
    """复盘「未命中」判定缺诊断方向告警（v4.9，backtest.md 6.6 复盘纪律）：
    review_html 含「未命中」但未提「规律/反例」——未命中的旧假设必须写明是规律失效还是
    新反例（区分假设本身错 vs 触发条件变化），否则教训无法沉淀。"""
    rv = fill.get("review_html") or ""
    if "未命中" in rv and "规律" not in rv and "反例" not in rv:
        warns.append("review_html 含「未命中」判定但未提「规律/反例」：判定未命中的旧假设应写明"
                     "是规律失效还是本次反例（区分假设本身错 vs 触发条件变化），见 backtest.md 6.6 复盘纪律")


def _validate_content_impl(fill: dict, calc: dict, warns: list) -> None:
    """validate_content 的执行主体（拆出是为了硬拒前 flush 告警，见包装函数）。"""
    _check_price_date(fill)
    _check_quote_consistency(fill)
    _check_score_ranges(fill)

    _check_valuation_inputs(fill)
    _check_valuation_scenarios(fill, warns)
    _check_odds_floor(fill, warns)      # v5.0 机制三：赔率 ∞ 须配悲观地板证据（floor）
    _check_consensus_np(fill, warns)    # v5.0 机制二：乐观税一致预期照抄交叉校验
    _check_chart_fields(fill)
    _check_quote_present(fill, warns)   # v4.11.1（审核 D5）：date ≥ 2026-09-02 缺 quote 拒渲染
    _check_gap_plot(fill, calc, warns)  # v4.11.1：gap_plot 分布图字段校验（可选字段，缺失不查）

    _check_red_flag_breaker(fill)
    _check_thesis_consistency(fill, calc)
    _check_content_floor(fill)
    _check_l4_form(fill)
    _check_cn_placeholder(fill)

    _check_missing_required_warns(fill, warns)
    _check_stock_type_weights(fill, warns)
    _check_thesis_price_tags(fill, warns)
    _check_thesis_info_floor(fill, warns)
    _check_hero_band_claims(fill, warns)
    _check_peers_plot_target(fill, warns)
    _check_timing_table_cells(fill, warns)
    _check_dim_blocks(fill, warns)
    _check_internal_codes(fill, warns)
    _check_writing_discipline(fill, warns)
    _check_conclusion_structure(fill, warns)
    _check_governance_strip(fill, warns)
    _check_peers_orientation(fill, warns)
    _check_peers_bestworst(fill, warns)
    _check_peers_column_support(fill, warns)
    _check_price_history_pe(fill, warns)
    _check_prev_fields(fill, warns)
    _check_review_miss_diagnostics(fill, warns)
    _check_misc_required(fill, warns)
    _check_optional_charts(fill, warns)
    _check_driver_cards(fill, warns)      # v4.11.3：P0 驱动卡字段（drivers/driver_verdict）
    _check_cycle_stages(fill, warns)      # v4.11.3：周期阶段卡字段（cycle_stages）
    _check_dcf(fill, warns)               # v4.11.3：DCF 双卡字段（dcf）
    _check_period_track(fill, warns)      # v5.0：3 章 period_track（照抄落盘交叉校验/判词四选一/年报期整章消失）


def validate_content(fill: dict, calc: dict = None) -> None:
    """内容级校验（成稿前自动复核，借鉴 equity-research 检查器思路）。
    硬错误（拒渲染）：分数越界、valuation_inputs 缺失、valuation 三情景字段不全、
    fin_trend/growth_plot 必填图字段缺失或结构非法（v4.9）、
    红灯熔断缺"不建议参与"、thesis 手写价与脚本计算值不一致、内容地板（空心章节）、
    表格缺来源标注；其余 → stderr 告警（P1），模型看到即修正。
    calc 为 compute_valuation 结果（thesis 一致性校验用）。
    v4.11.1（热核审计 P2-1）：硬拒前先 flush 已积累告警——否则负 profit/存量 quote 豁免等
    提示会随异常湮灭，模型修 fill 丢上下文。"""
    warns = []
    try:
        _validate_content_impl(fill, calc, warns)
    except ValueError:
        for w in warns:
            print(f"⚠️ 内容校验: {w}", file=sys.stderr)
        raise
    for w in warns:
        print(f"⚠️ 内容校验: {w}", file=sys.stderr)


def _disp_w(s: str) -> int:
    """显示宽度：CJK/全角计 2、ASCII 计 1——槽位契约的宽度口径（纯字符数对中英混排
    过紧：「PE 25x→17.2x」26 字符实际只占 ~36 宽，单行可读）。"""
    return sum(2 if ord(c) > 0x2E7F else 1 for c in s)


def _check_driver_cards(fill: dict, warns: list) -> None:
    """v4.11.3：P0 驱动卡字段校验（drivers/driver_verdict，软告警迁移期——缺失不拒）。
    drivers 1-2 项、first_var 恰 1 个、chips 恰 悲观/基础/乐观 三情景档（+可选 unit）、
    name ≤12 字、note 显示宽 ≤300（≈3 行；宁德时代融合版备注 137 字实测可读，原 90 字过紧
    已放宽——宽度口径：CJK 计 2、ASCII 计 1）；first_var 名与 sensitivity 首行变量名不一致 → 告警；
    p0_html 仍手写「为什么…第一变量」info-card → 重复告警。"""
    drivers = [d for d in fill.get("drivers") or [] if isinstance(d, dict)]
    if not drivers:
        warns.append("drivers 字段未填：v4.11.3 起 P0 驱动卡由 drivers/driver_verdict 字段承载"
                     "（1-2 个关键驱动：name/elastic/note/chips 三情景锚；p0_html 不再手写"
                     "「为什么 X 是第一变量」info-card——判词由 driver_verdict 承载）")
        return
    if len(drivers) > 2:
        warns.append(f"drivers 共 {len(drivers)} 项（应 1-2 个）：只保留对利润弹性最大的 1-2 个驱动")
    firsts = [d for d in drivers if d.get("first_var")]
    if len(firsts) != 1:
        warns.append(f"drivers 的 first_var 应恰为 1 个（当前 {len(firsts)} 个）：第一变量只有一个")
    for d in drivers:
        tag = _plain_text(str(d.get("name") or "")).strip() or "?"
        short = tag[:8] + ("…" if len(tag) > 8 else "")
        if len(tag) > 12:
            warns.append(f"drivers[{short}] name {len(tag)} 字 > 12（槽位契约：变量名只放一个概念，"
                         "驱动因素写 note 不进名字）")
        note_w = _disp_w(_plain_text(str(d.get("note") or "")).strip())
        if note_w > 300:
            warns.append(f"drivers[{short}] note 显示宽 {note_w} > 300（槽位契约：≈3 行上限，"
                         "当前值+撕扯力量压缩表述，展开论证住正文）")
        scen = [c for c in d.get("chips") or []
                if isinstance(c, dict) and not c.get("unit")]
        labels = [str(c.get("label") or "").strip() for c in scen]
        if labels != ["悲观", "基础", "乐观"]:
            warns.append(f"drivers[{short}] chips 情景档为 {labels}（应恰为 悲观/基础/乐观 三档，"
                         "+可选 unit 标签）")
    if not str(fill.get("driver_verdict") or "").strip():
        warns.append("driver_verdict 未填：「为什么 X 是第一变量」判词缺失"
                     "（弹性对比+不确定性不对称一句，卡下横条承载）")
    sens = [s for s in fill.get("sensitivity") or [] if isinstance(s, dict)]
    if firsts and sens:
        fv = _plain_text(str(firsts[0].get("name") or "")).strip().replace(" ", "")
        sv = _plain_text(str(sens[0].get("name") or "")).strip().replace(" ", "")
        if fv and sv and fv != sv:
            warns.append(f"drivers 第一变量「{firsts[0].get('name')}」与 sensitivity 首行「{sens[0].get('name')}」"
                         "不同名：两处应一致（龙卷风图排序标签与驱动卡同源）")
    if re.search(r'<div class="info-card"><strong>为什么', fill.get("p0_html") or ""):
        warns.append("p0_html 仍含手写「为什么…」info-card：v4.11.3 起由 driver_verdict 判词横条承载，"
                     "请删除手写块（drivers 已填）")


def _check_cycle_stages(fill: dict, warns: list) -> None:
    """v4.11.3：周期阶段卡字段校验（cycle_stages，软告警迁移期——缺失不拒）。
    3-6 项、恰 1 个 current、name ≤8 字、driver 显示宽 ≤48（灭孤字契约；宽度口径：
    CJK 计 2、ASCII 计 1——混合串「PE 25x→17.2x」26 字符实测单行可读，纯字符数 24 过紧
    已改宽度）、period 必填；
    cycle_html 手写阶段表与字段的关系：字段未填 → 迁移告警；并存 → 重复告警。"""
    stages = [s for s in fill.get("cycle_stages") or [] if isinstance(s, dict)]
    hand_table = re.search(r"<th[^>]*>\s*阶段\s*</th>", fill.get("cycle_html") or "")
    if not stages:
        if hand_table:
            warns.append("cycle_html 含手写阶段拆解表：v4.11.3 起请迁移 cycle_stages 字段"
                         "（name/period/pe/price/driver 显示宽 ≤48/current 恰 1 个），手写表格写法废止")
        return
    if not 3 <= len(stages) <= 6:
        warns.append(f"cycle_stages 共 {len(stages)} 项（应 3-6 个阶段）")
    curs = [s for s in stages if s.get("current")]
    if len(curs) != 1:
        warns.append(f"cycle_stages 的 current 应恰为 1 个（当前 {len(curs)} 个）：「本轮」只有一个")
    for s in stages:
        tag = _plain_text(str(s.get("name") or "")).strip() or "?"
        short = tag[:6] + ("…" if len(tag) > 6 else "")
        if len(tag) > 8:
            warns.append(f"cycle_stages[{short}] name {len(tag)} 字 > 8（槽位契约）")
        driver_w = _disp_w(_plain_text(str(s.get("driver") or "")).strip())
        if driver_w > 48:
            warns.append(f"cycle_stages[{short}] driver 显示宽 {driver_w} > 48（槽位契约：超长必孤字折行，"
                         "压缩表述——demo 阶段 02「杀」字独占行实证；宽度口径：CJK 计 2、ASCII 计 1）")
        if not str(s.get("period") or "").strip():
            warns.append(f"cycle_stages[{short}] 缺 period（日期行是阶段卡的顺序主锚，必填）")
    if hand_table:
        warns.append("cycle_html 手写阶段表与 cycle_stages 字段并存（内容重复）：请删除手写表格")


def _check_dcf(fill: dict, warns: list) -> None:
    """v4.11.3：DCF 双卡字段校验（dcf，软告警迁移期——缺失不拒）。
    稳健成长分型 dcf 缺失 → 强制告警；填了 → 八键齐全性 + verdict ≥40 字；
    valuation_html 仍手写 DCF 表 → 重复告警。"""
    d = fill.get("dcf")
    if not isinstance(d, dict) or not d:
        if "稳健成长" in str(fill.get("stock_type") or ""):
            warns.append("dcf 字段未填：稳健成长分型 DCF 强制三行由 dcf 字段承载（v4.11.3 起；"
                         "value/fcf0/growth_5y/g_perp/wacc/net_cash/implied_g/verdict 八键，"
                         "现价比价脚本算，valuation_html 不再手写 DCF 表）")
        return
    missing = [k for k in ("value", "fcf0", "growth_5y", "g_perp", "wacc", "net_cash",
                           "implied_g", "verdict") if not str(d.get(k) or "").strip()]
    if missing:
        warns.append(f"dcf 缺键 {missing}：八键应齐全（value/implied_g/verdict 缺一时整卡不生成）")
    verdict_len = len(_plain_text(str(d.get("verdict") or "")).strip())
    if 0 < verdict_len < 40:
        warns.append(f"dcf.verdict {verdict_len} 字 < 40：判词须含隐含 g 对照与互证结论"
                     "（与现价比价由脚本算后自动拼接，不用手写）")
    vh = fill.get("valuation_html") or ""
    if "<table" in vh and re.search(r">[^<]*DCF", vh):
        warns.append("valuation_html 仍含手写 DCF 表：v4.11.3 起 DCF 由 dcf 字段承载，请删除手写表")


# ---------------- v5.0 第 3 章「最新报告期透视」period_track 校验 ----------------
_PERIOD_LABEL_KEYS = ("period", "sq_label", "sq_prev_label")
_PERIOD_NUM_KEYS = ("rev", "np", "np_dedt", "ocf", "sq_rev", "sq_np", "sq_prev_rev", "sq_prev_np")
_PERIOD_YOY_KEYS = ("rev_yoy", "np_yoy", "np_dedt_yoy", "ocf_yoy", "sq_rev_yoy", "sq_np_yoy")
_PERIOD_BAND_KEYS = ("band_np", "band_rev")
_PERIOD_VERDICT_ENUM = ("超前", "正常", "滞后", "无法判定")


def _check_period_track(fill: dict, warns: list) -> None:
    """v5.0 第 3 章 period_track 校验（quote 防伪同款纪律：照抄 em_fetch --out 落盘，禁手估）。
    硬拒：fill 有 period_track 而落盘无该键；照抄字段与落盘不一致（标签/文字同比完全一致，
    数值偏差 >1%；fill 有值而落盘 None=手估嫌疑）；consensus_np 与落盘 np_avg 失配；
    verdict_* 非四选一；goal_* 非正数。
    软告警：落盘有 period_track 而 fill 未回填（第 3 章缺席）；quote 缺失/落盘读不到
    （主键门禁 _check_quote_consistency/_check_quote_present 已管，不重复硬拒）；
    fill None 而落盘有值（漏抄，章内容缩水）；判词缺失（渲染兜底「无法判定」）；
    年报期填 industry/forecast/note（整章消失不渲染）；note_html 纯文本 >120 字。
    数值容差与 quote 同款（相对 1%）；百分数类字段（yoy/节奏带）叠加 0.1 绝对容差——
    fill 按一位小数照抄落盘原始 float，小值四舍五入会被纯相对容差误伤。"""
    pt = fill.get("period_track")
    if pt is not None and not isinstance(pt, dict):
        raise ValueError(f"period_track 字段需为对象，实际: {type(pt).__name__}")
    q = fill.get("quote") or {}
    src = q.get("source_file") if isinstance(q, dict) else None
    ref = None
    if src:
        try:
            with open(src, encoding="utf-8") as f:
                ref = json.load(f)
        except (OSError, json.JSONDecodeError):
            ref = None   # 落盘读不到：_check_quote_consistency 已硬拒，这里降级跳过比对
    ref_pt = (ref or {}).get("period_track")
    if pt and ref is None:
        warns.append("period_track 已填但 quote.source_file 缺失或读不到：第 3 章数据无法交叉校验"
                     "（quote 门禁已管主键，本条不重复硬拒）——请重跑 em_fetch --out 落盘并回填 quote 后重渲")
    if pt and ref is not None and not isinstance(ref_pt, dict):
        raise ValueError("fill.period_track 已填但 em_fetch 落盘 JSON 无 period_track 键："
                         "第 3 章数据必须照抄 em_fetch --out 落盘的 period_track 照抄行，禁手估"
                         "（神华现价造假同款防伪纪律）——请重跑 em_fetch --out 落盘，"
                         "或删除 fill 的 period_track 后重渲")
    if not pt and isinstance(ref_pt, dict):
        warns.append("em_fetch 落盘含 period_track 但 fill 未回填：第 3 章「最新报告期透视」将缺席"
                     "——请照抄落盘 period_track 行回填（年报期 is_annual=true 整章消失属预期，可忽略本条）")
    if pt and isinstance(ref_pt, dict):
        # 交叉比对（fill vs 落盘 period_track；报错带字段名/期望值/实际值/修复指向）
        def _mismatch(key, fv, rv, extra=""):
            raise ValueError(f"period_track.{key} 与 em_fetch 落盘值不一致: fill={fv!r} vs 落盘={rv!r}{extra}"
                             "——第 3 章数据照抄 em_fetch --out 落盘 period_track 照抄行，禁手改；"
                             "以落盘值为准修正后重渲")

        def _close(fv, rv, pct=False):
            """数值容差：相对 1%（quote 同款；落盘 0 时按两位小数精度 0.005 亿绝对容差）；
            pct=True（百分数字段）叠加 0.1pct 绝对容差（一位小数照抄的四舍五入）。"""
            if rv == 0:
                return abs(fv) <= 0.005
            return abs(fv - rv) / abs(rv) <= 0.01 or (pct and abs(fv - rv) <= 0.1)

        def _copy_missing(key, rv):
            warns.append(f"period_track.{key} 漏抄（落盘={rv!r}）：照抄行请完整回填")

        for key in _PERIOD_LABEL_KEYS:
            fv, rv = pt.get(key), ref_pt.get(key)
            if fv is None and rv is None:
                continue
            if fv is None or not str(fv).strip():
                _copy_missing(key, rv)
                continue
            if rv is None or str(fv).strip() != str(rv).strip():
                _mismatch(key, fv, rv)
        # F5：is_annual 进交叉校验——年报期整章消失是硬约束，布尔不等即拒渲染（不容改写）
        if bool(pt.get("is_annual")) != bool(ref_pt.get("is_annual")):
            _mismatch("is_annual", pt.get("is_annual"), ref_pt.get("is_annual"),
                      "（年报期整章消失是硬约束）")
        for key in _PERIOD_NUM_KEYS:
            raw = pt.get(key)
            fv = _strict_num(raw)
            if raw is not None and str(raw).strip() and fv is None:
                raise ValueError(f"period_track.{key} 不是纯数字: {raw!r}——照抄字段禁止夹带文字"
                                 f"（亿元两位小数；口径注请写进 note_html 后重渲）")
            rv = _num(ref_pt.get(key))
            if fv is None and rv is None:
                continue
            if fv is None:
                _copy_missing(key, rv)
                continue
            if rv is None:
                raise ValueError(f"period_track.{key} 落盘无值而 fill 填了 {fv:g}："
                                 f"落盘没有的数据禁止手估填入——以 em_fetch --out 落盘为准修正后重渲")
            if not _close(fv, rv):
                _mismatch(key, fv, rv, f"（偏差 {abs(fv - rv) / abs(rv) * 100:.1f}% > 1%）")
        for key in _PERIOD_YOY_KEYS:
            raw, rv_raw = pt.get(key), ref_pt.get(key)
            fv, rv = _strict_num(raw), _strict_num(rv_raw)
            if raw is None and rv_raw is None:
                continue
            if raw is None or not str(raw).strip():
                _copy_missing(key, rv_raw)
                continue
            if rv_raw is None:
                raise ValueError(f"period_track.{key} 落盘无值而 fill 填了 {raw!r}："
                                 f"落盘没有的数据禁止手估填入——以 em_fetch --out 落盘为准修正后重渲")
            if fv is not None and rv is not None:
                if not _close(fv, rv, pct=True):
                    _mismatch(key, fv, rv, f"（偏差 {abs(fv - rv):.2f}pct > 容差）")
            elif str(raw).strip() != str(rv_raw).strip():
                # 文字同比（扭亏/转亏/减亏/增亏）要求完全一致
                _mismatch(key, raw, rv_raw, "（文字同比要求完全一致）")
        for key in _PERIOD_BAND_KEYS:
            fb, rb = pt.get(key), ref_pt.get(key)
            if fb is None and rb is None:
                continue
            if fb is None:
                _copy_missing(key, rb)
                continue
            if rb is None:
                raise ValueError(f"period_track.{key} 落盘无值而 fill 填了 {fb!r}："
                                 f"落盘没有的数据禁止手估填入——以 em_fetch --out 落盘为准修正后重渲")
            fl = [_strict_num(x) for x in fb] if isinstance(fb, (list, tuple)) else []
            rl = [_strict_num(x) for x in rb] if isinstance(rb, (list, tuple)) else []
            if len(fl) < 2 or len(rl) < 2 or None in fl or None in rl:
                raise ValueError(f"period_track.{key} 结构非法: fill={fb!r} vs 落盘={rb!r}"
                                 f"（节奏带为 [下限%, 上限%] 两个纯数字）")
            for i in (0, 1):
                if not _close(fl[i], rl[i], pct=True):
                    _mismatch(f"{key}[{i}]", fl[i], rl[i])
        fy, ry = pt.get("band_years"), ref_pt.get("band_years")
        if fy is None and ry is None:
            pass
        elif fy is None:
            _copy_missing("band_years", ry)
        else:
            try:
                same_years = [int(x) for x in fy] == [int(x) for x in (ry or [])]
            except (TypeError, ValueError):
                same_years = False
            if not same_years:
                _mismatch("band_years", fy, ry)
        # consensus_np：fill 照抄的是落盘 consensus_np.np_avg（E5 当年净利均值）
        raw_c = pt.get("consensus_np")
        fc = _strict_num(raw_c)
        if raw_c is not None and str(raw_c).strip() and fc is None:
            raise ValueError(f"period_track.consensus_np 不是纯数字: {raw_c!r}——照抄字段禁止夹带文字")
        rc = _num(((ref or {}).get("consensus_np") or {}).get("np_avg"))
        if fc is not None and rc is None:
            raise ValueError(f"period_track.consensus_np 落盘无值而 fill 填了 {fc:g}：E5 未覆盖标的"
                             f"禁止手估一致预期——以 em_fetch --out 落盘为准修正后重渲")
        if fc is None and rc is not None:
            _copy_missing("consensus_np", f"consensus_np.np_avg={rc:g}")
        if fc is not None and rc is not None and not _close(fc, rc):
            _mismatch("consensus_np", fc, rc,
                      f"（偏差 {abs(fc - rc) / abs(rc) * 100:.1f}% > 1%，对照落盘 consensus_np.np_avg）")
    if pt:
        is_annual = bool(pt.get("is_annual"))
        for vk, ak in (("verdict_rev", "rev"), ("verdict_np", "np"), ("verdict_dedt", "np_dedt")):
            v = str(pt.get(vk) or "").strip()
            if v:
                if v not in _PERIOD_VERDICT_ENUM:
                    raise ValueError(f"period_track.{vk} 取值非法: {v!r}——判词四选一："
                                     f"{'/'.join(_PERIOD_VERDICT_ENUM)}（模型按节奏带+完成度判定）")
            elif not is_annual and _num(pt.get(ak)) is not None:
                warns.append(f"period_track.{vk} 未填：章内该指标判词将显示「无法判定」（判词四选一 "
                             f"{'/'.join(_PERIOD_VERDICT_ENUM)}，由模型按节奏带与完成度判定）")
        for gk in ("goal_rev", "goal_np"):
            raw = pt.get(gk)
            if raw is None or not str(raw).strip():
                continue
            gv = _strict_num(raw)
            if gv is None or gv <= 0:
                raise ValueError(f"period_track.{gk} 必须为正数（亿元；年报「经营计划」段披露口径，"
                                 f"未披露请填 null），实际: {raw!r}")
        if is_annual:
            extra = [k for k in ("industry_html", "forecast_html", "note_html")
                     if str(pt.get(k) or "").strip()]
            if extra:
                warns.append(f"period_track.is_annual=true（年报期第 3 章整章消失）：{'/'.join(extra)} "
                             f"已填内容不会渲染——年报期请省略这些字段，或留待下一季报期使用")
        note_len = len(_plain_text(str(pt.get("note_html") or "")))
        if note_len > 120:
            warns.append(f"period_track.note_html 纯文本 {note_len} 字 > 120：口径提示定位 ≤3 句，"
                         f"展开论证归各章")
