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
                     _SCENARIO_NAMES, _parse_prev_scenarios,
                     REGIME_DEV_THRESHOLD, regime_scale_devs,
                     _cn_placeholders, growth_sigma)
from charts_base import (_C_BLUE, _sensitivity_items, _var_key, _gap_dim_ok, _period_ratio,
                         parse_stage_period, _PERIOD_VERDICTS)


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


def _quote_ref(fill: dict):
    """读 quote.source_file 落盘 JSON（各照抄/对账校验共用入口，v5.1.2）；未声明/读不到 → None。
    quote 防伪主校验（_check_quote_consistency）读不到会拒渲染，这里只做降级返回。"""
    q = fill.get("quote")
    if not isinstance(q, dict) or not q.get("source_file"):
        return None
    try:
        with open(q["source_file"], encoding="utf-8") as f:
            ref = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return ref if isinstance(ref, dict) else None

def _check_quote_consistency(fill: dict, warns: list) -> None:
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
            warns.append(f"valuation_inputs.{k}（{fv:g}）与 E1 落盘值（{rv:g}）偏差 >0.3pct"
                         f"——若为手工估算或税后折算口径，请在 .source 注明")


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


def _check_valuation_scenarios(fill: dict, warns: list) -> None:
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
            if profit < 0:
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
    # v5.1.2：「净利」维度对账——consensus 照抄落盘 consensus_np.np_avg（>1% 告警）；
    # ours 与 valuation 基础情景 profit 一致（>2% 告警，镜像目标价维度口径）
    ref = _quote_ref(fill)
    cnp = (ref or {}).get("consensus_np") or {}
    np_avg = _num(cnp.get("np_avg"))
    base_profit = None
    for sc in (fill.get("valuation") or {}).get("scenarios") or []:
        if isinstance(sc, dict) and sc.get("key") == "base":
            base_profit = _num(sc.get("profit"))
    for d in dims:
        if not _gap_dim_ok(d):
            continue
        nm_ = str(d.get("name") or "")
        if "净利" not in nm_:
            continue
        yr = re.search(r"20\d{2}", nm_)
        cnp_yr = _num(cnp.get("year"))   # 落盘 year 非整数串时跳过比对（热核 P1-3）
        yr_i = int(yr.group(0)) if yr else None
        cons, ours = _num(d.get("consensus")), _num(d.get("ours"))
        if (np_avg and cnp_yr and yr_i and yr_i == int(cnp_yr)
                and cons and abs(cons - np_avg) / abs(np_avg) > 0.01):
            warns.append(f"gap_plot「{nm_}」consensus（{cons:g} 亿）与落盘 consensus_np.np_avg"
                         f"（{np_avg:g} 亿）偏差 >1%：一致预期照抄 E5 落盘、禁手估（v5.1.2）")
        # ours 只比对预测年（带 E）维度——历史年实绩本就不该等于当年假设（热核 P1-1）
        if (base_profit and ours and "E" in nm_ and yr_i and (not cnp_yr or yr_i == int(cnp_yr))
                and abs(ours - base_profit) / abs(base_profit) > 0.02):
            warns.append(f"gap_plot「{nm_}」ours（{ours:g} 亿）与 valuation 基础情景净利"
                         f"（{base_profit:g} 亿）偏差 >2%：本文假设两处应一致（v5.1.2）")
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


def _check_odds_floor(fill: dict, warns: list, calc=None) -> None:
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
    # 悲观下限与 compute_valuation 同源（v5.1.5 热核 P0-5 公式双写收敛）：有 calc 直取
    # pess 行 low；calc 为 None（纯 --check 无估值输入路径）按同公式复算兜底
    if calc is not None:
        row = next((r for r in calc.get("rows") or [] if r.get("key") == "pess"), None)
        if row is None:
            return
        low = row["low"]
    else:
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
    ref = _quote_ref(fill)   # 落盘读不到：_check_quote_consistency 已硬拒，这里降级跳过比对
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


# v5.1.0 估值锚纪律一：PE 带跨版移动的增量证据类型白名单
_ANCHOR_EVIDENCE_TYPES = ("基本面", "价格", "卖方观点", "市场参数")


def _check_anchor_discipline(fill: dict, warns: list) -> None:
    """v5.1.0 估值锚纪律（恒瑞 2026-09 实证：两版报告间无新增基本面证据——中报对两版
    均为存量——悲观 PE 带却 35-40→26-32，驱动量只有股价与卖方研报，循环论证）：
    ①回测模式 prev.scenarios 必填（锚移动台账数据源，照抄 extract_review 输出禁手改）；
    ②增量证据锁死：基础情景 PE 带相对上版移动 → valuation.pe_band_evidence 必填且至少
      一条 type=基本面；带未移动 → 该键须缺席/空（防口径漂移）。价格/卖方观点不构成
      移动理由（双向禁用：跌不许下修、涨不许上修）；上版解析失败降级告警不拒；
    ③回滚条款前置（v5.4.0 双尺全量生效）：合理带与基础情景带任一中枢偏离历史 P25-P75
      中枢 >15%（重构声明）→ valuation.rollback_html 必填——首版（无 prev）同样执行；
      两尺混用（一尺越界一尺不越、或两尺越界但偏离异号）→ 拒渲染（纪律四）；
      两尺同向同越界 = 一致重构，只要求 rollback_html。
    ①②为复盘专属（prev 缺失才跳过）；③全量生效（尺子一致性不因是否复盘而变）。
    尺子不可算（None：市值口径 metric_label / 情景无 pe / pe_history 缺 p25/p75）→ 该尺
    不参与判定，混用检查仅在两尺均可算时执行（不可算 ≠ 未越界）。"""
    prev = fill.get("prev")
    if prev:
        if not isinstance(prev.get("scenarios"), list) or not prev["scenarios"]:
            raise ValueError("回测模式 prev.scenarios 缺失或非数组：照抄 extract_review 输出的 "
                             "scenarios 数组（锚移动台账数据源，禁手改；v5.1.0 起必填）")
        v = fill.get("valuation") or {}
        scen = v.get("scenarios") or []
        base = next((s for s in scen if isinstance(s, dict)
                     and str(s.get("key") or "").lower() == "base"), None)
        prev_pe = (_parse_prev_scenarios(prev["scenarios"]).get("base") or {}).get("pe")
        ev = v.get("pe_band_evidence")
        if base is not None and prev_pe is not None:
            pe = base.get("pe") or []
            cur_pe = (_num(pe[0]) if len(pe) >= 1 else None, _num(pe[1]) if len(pe) >= 2 else None)
            if None not in cur_pe:
                moved = (cur_pe[0], cur_pe[1]) != prev_pe
                if moved:
                    if not ev or not isinstance(ev, list):
                        raise ValueError(
                            f"基础情景 PE 带相对上版移动（{prev_pe[0]:g}-{prev_pe[1]:g}x → "
                            f"{cur_pe[0]:g}-{cur_pe[1]:g}x）但 valuation.pe_band_evidence 缺失："
                            f"增量证据锁死纪律——两版间无新增基本面证据时 PE 带不得移动"
                            f"（v5.1.0 估值锚纪律一）")
                    for i, e in enumerate(ev):
                        if not isinstance(e, dict) or e.get("type") not in _ANCHOR_EVIDENCE_TYPES:
                            raise ValueError(
                                f"pe_band_evidence[{i}].type 非法: {(e or {}).get('type') if isinstance(e, dict) else e!r}"
                                f"——四选一：{'/'.join(_ANCHOR_EVIDENCE_TYPES)}")
                        if not str(e.get("note") or "").strip():
                            raise ValueError(f"pe_band_evidence[{i}].note 为空——证据须写明可核查内容")
                    if not any(e["type"] == "基本面" for e in ev):
                        raise ValueError(
                            f"pe_band_evidence 无「基本面」类条目（现有："
                            f"{'/'.join(e['type'] for e in ev)}）——PE 带移动必须锚定新增基本面证据，"
                            f"纯价格/卖方观点触发不合法；若无新增基本面证据，请将 PE 带锁回上版数值")
                elif ev:
                    raise ValueError("PE 带与上版一致，pe_band_evidence 应缺席（画蛇添足防口径漂移）")
        elif ev:
            warns.append("上版三情景 PE 解析失败或本版为市值口径：PE 带移动校验跳过，"
                         "pe_band_evidence 已填无法比对——请人工核对锚移动归因")
    # ③ 回滚门禁 + 双尺混用（v5.4.0 全量生效，首版同样执行；形状单源 regime_scale_devs）
    v = fill.get("valuation") or {}
    devs = regime_scale_devs(fill)          # 只含可算的尺，顺序固定：合理带、基础情景带
    if len(devs) == 2:                       # 两尺都可算才判混用（缺一尺=不可判定，不误判）
        (n_band, dev_band), (n_base, dev_base) = devs
        out_band = abs(dev_band) > REGIME_DEV_THRESHOLD
        out_base = abs(dev_base) > REGIME_DEV_THRESHOLD
        if out_band != out_base:
            raise ValueError(
                f"估值锚双尺混用：{n_band}中枢偏离历史 P25-P75 中枢 {dev_band * 100:+.0f}%、"
                f"{n_base} {dev_base * 100:+.0f}%——一尺越界一尺未越（{n_band if out_band else n_base}"
                f"越界），属「纪律四：禁止评分用旧尺、目标价用新尺」的精选混合；"
                f"请把两把尺对齐（同越界须配 rollback_html，同不越界则两处都锁回历史带）后重渲")
        if out_band and (dev_band > 0) != (dev_base > 0):
            raise ValueError(
                f"估值锚双尺偏离方向相反：{n_band} {dev_band * 100:+.0f}%、{n_base} {dev_base * 100:+.0f}%"
                f"（两尺均 >15% 但一上一下）——同一份报告的合理带与目标价 PE 带指向相反的重构方向，"
                f"属「纪律四：禁止评分用旧尺、目标价用新尺」的双尺混用；请统一重构方向后重渲")
    off = [(n, d) for n, d in devs if abs(d) > REGIME_DEV_THRESHOLD]
    if off:
        rb = str(v.get("rollback_html") or "").strip()
        if not rb:
            which = "合理带/基础情景带两尺" if len(off) == 2 else off[0][0]
            deltas = "、".join(f"{n} {d * 100:+.0f}%" for n, d in off)
            absent = "；另一把尺输入缺失不可算，未参与判定" if len(devs) == 1 else ""
            raise ValueError(
                f"{which}中枢偏离历史 P25-P75 中枢（{deltas}）>15%，属估值重构声明"
                f"但 valuation.rollback_html 缺失：回滚条款前置纪律——必须写明"
                f"「回滚条件：〈可观测证据〉→ 回滚至历史带/上版带」（v5.1.0 估值锚纪律二，"
                f"v5.4.0 起首版同样生效）{absent}")


def _check_anchor_blind_fly(fill: dict, warns: list) -> None:
    """v5.4.0 校验盲飞（软告警）：估值带依赖历史 PE 时段锚的分型（周期股 / 稳定价值 /
    困境反转 / 成长型·中速层——四型对应 _anchor_unanchored_type），若既无行业口径
    metric_label 又缺 pe_history.p25/p75，则两把尺的偏离度都算不出来——形态合规但校准
    零机械校验（盲飞），要求正文写明降级取数路径（时段 PE 自算口径与出处）。"""
    if not _anchor_unanchored_type(fill):
        return
    vi = fill.get("valuation_inputs") or {}
    if vi.get("metric_label"):
        return
    ph = fill.get("pe_history") or {}
    if _num(ph.get("p25")) is not None and _num(ph.get("p75")) is not None:
        return
    warns.append("校验盲飞：本分型（估值带依赖历史 PE 时段锚）既无 metric_label 行业口径、"
                 "pe_history 又缺 p25/p75——双尺偏离与时段校准均无法机械对账（形态合规但无尺）。"
                 "请在 valuation_html 写明降级取数路径：时段 PE 自算口径 + 数据出处"
                 "（E2 月线/自算 PE 的月份与公式），并注明 p25/p75 缺失原因（E1 落盘 pe_p25/pe_p75 未回填）")


def _anchor_unanchored_type(fill: dict) -> bool:
    """估值带依赖历史 PE 时段锚的四型（v5.4.0 单源判定，校验盲飞与 calib 时段数共用）：
    周期股 / 稳定价值 / 困境反转 / 成长型·中速层（growth_tier ≠ high）。
    成熟·停滞走 PE 绝对带 + 股息率锚、未盈利·管线走 rNPV/P/S，不在此列。"""
    st = str(fill.get("stock_type") or "")
    if any(k in st for k in ("周期", "稳定价值", "困境反转")):
        return True
    return "成长" in st and str(fill.get("growth_tier") or "").strip().lower() != "high"


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


def _check_hero_cross(fill: dict, warns: list) -> None:
    """v5.1.2：Hero 指标卡与估值结构化字段互查（存量 fill 无 quote 时两处自说自话实证）——
    顶层 pe_ttm 与 valuation_inputs.pe_ttm 并存且偏差 >1% → 拒渲染（metric_label 行业口径
    跳过，语义非 PE(TTM)）；horizon 顶层 vs valuation 不一致 → 告警；
    mcap vs price×shares 偏差 >5% → 告警。"""
    vi = fill.get("valuation_inputs") or {}
    if not vi.get("metric_label"):
        hpe, vpe = _num(fill.get("pe_ttm")), _num(vi.get("pe_ttm"))
        if hpe is not None and vpe:
            dev = abs(hpe - vpe) / abs(vpe)
            if dev > 0.01:
                raise ValueError(f"Hero pe_ttm（{hpe:g}）与 valuation_inputs.pe_ttm（{vpe:g}）"
                                 f"偏差 {dev * 100:.1f}% > 1%：同一 PE 两处填写必有一处错"
                                 "（v5.1.2 起拒渲染；行业口径见 metric_label 豁免）")
    v = fill.get("valuation") or {}
    vh = str(v.get("horizon") or "").strip()
    if not vh:
        hs = {str(s.get("horizon") or "").strip()
              for s in v.get("scenarios") or [] if isinstance(s, dict)}
        hs.discard("")
        vh = hs.pop() if len(hs) == 1 else ""
    hh = str(fill.get("horizon") or "").strip()
    if hh and vh and hh != vh:
        warns.append(f"horizon 顶层「{hh}」与 valuation「{vh}」不一致：Hero 目标价卡与情景表"
                     "时间维度同源，请统一（v5.1.2）")
    mc, pr, sh = _num(fill.get("mcap")), _num(fill.get("price")), _num(v.get("shares"))
    if mc is not None and pr is not None and sh:
        exp = pr * sh
        if exp > 0 and abs(mc - exp) / exp > 0.05:
            warns.append(f"mcap（{mc:g} 亿）与 price×shares（{pr:g}×{sh:g}={exp:g} 亿）偏差 "
                         f"{abs(mc - exp) / exp * 100:.1f}% > 5%：总市值两处应基本一致（v5.1.2）")


def _check_growth_consistency(fill: dict, warns: list) -> None:
    """v5.1.2：growth_plot 增速与落盘一致预期/valuation 基础情景换算对账（条件不齐静默跳过）——
    基数=fin_trend「归母净利」柱末年值（标准 4 面板之一）；落盘 np_avg÷基数−1 vs
    fcst.np_consensus（>2pct 告警）；base.profit÷基数−1 应落在 [np_lo−2, np_hi+2]（越界告警）。
    基数 ≤0（亏损期）换算无意义，跳过。"""
    ft = fill.get("fin_trend") or {}
    gp = fill.get("growth_plot") or {}
    years = [str(y) for y in (ft.get("years") or [])]
    base_np = None
    for p in ft.get("panels") or []:
        if not isinstance(p, dict):
            continue
        for b in p.get("bars") or []:
            nm = str((b or {}).get("name") or "")
            if "归母净利" in nm and "扣非" not in nm:
                vals = [_num(x) for x in (b.get("values") or [])]
                if vals and len(vals) == len(years) and None not in vals:
                    base_np = vals[-1]
    fcst = [f for f in (gp.get("fcst") or []) if isinstance(f, dict)]
    if base_np is None or base_np <= 0 or not years or not fcst:
        return
    m_y = re.fullmatch(r"20\d{2}", years[-1])
    if not m_y:
        return
    last_year = int(m_y.group(0))
    cnp = (_quote_ref(fill) or {}).get("consensus_np") or {}
    np_avg = _num(cnp.get("np_avg"))
    base_profit = None
    for s in (fill.get("valuation") or {}).get("scenarios") or []:
        if isinstance(s, dict) and s.get("key") == "base":
            base_profit = _num(s.get("profit"))
    for f in fcst:
        ym = re.search(r"20\d{2}", str(f.get("y") or ""))
        if not ym or int(ym.group(0)) != last_year + 1:
            continue
        cnp_yr = _num(cnp.get("year"))
        if np_avg and cnp_yr and int(cnp_yr) == last_year + 1:
            g_cons = (np_avg / base_np - 1) * 100
            npc = _num(f.get("np_consensus"))
            if npc is not None and abs(npc - g_cons) > 2:
                warns.append(f"growth_plot {f['y']} np_consensus（{npc:g}%）与落盘一致预期换算增速"
                             f"（{g_cons:.1f}%＝np_avg {np_avg:g}亿÷上年归母净利 {base_np:g}亿−1）差 "
                             f"{abs(npc - g_cons):.1f}pct > 2pct：一致预期照抄 E5 落盘（v5.1.2）")
        if base_profit:
            g_base = (base_profit / base_np - 1) * 100
            lo, hi = _num(f.get("np_lo")), _num(f.get("np_hi"))
            if lo is not None and hi is not None and not (lo - 2 <= g_base <= hi + 2):
                warns.append(f"valuation 基础情景换算增速（{g_base:.1f}%）越出 growth_plot 本文区间 "
                             f"[{lo:g}, {hi:g}]（容差 ±2pct）：5 章图与 7 章情景应口径一致（v5.1.2）")

# 分型判据 v2（v5.3.0）常量表——判据全文见 scoring.md「分型判据（v2）」节
_TYPE_ALIASES = [  # 顺序敏感：先具体后笼统（「稳定价值」先于「成长」，「稳健/快速成长」先于裸「成长」）
    ("稳定价值", "稳定价值", None),
    ("稳健成长", "成长型", "mid"),
    ("快速成长", "成长型", "high"),
    ("停滞", "成熟/停滞", None),
    ("未盈利", "未盈利/管线", None),
    ("管线", "未盈利/管线", None),
    ("困境反转", "困境反转", None),
    ("周期", "周期股", None),
    ("成长", "成长型", None),
]
_TYPE_LAYER = {"周期股": (70, 30), "稳定价值": (85, 15), "未盈利/管线": (75, 25),
               "困境反转": (70, 30), "成熟/停滞": (80, 20)}
_GROWTH_LAYER = {"high": (60, 40), "mid": (70, 30)}
_TYPE_EVIDENCE_KEYS = {
    "周期股": ("commodity_link", "volatility_fact", "comparable_periods"),
    "成长型": ("cagr_hist", "driver_nature", "shock_history"),
    "成熟/停滞": ("cagr_hist", "growth_narrative", "three_exclusions"),
    "稳定价值": ("franchise", "dividend_streak"),
    "未盈利/管线": ("loss_reason", "milestones"),
    "困境反转": ("normal_anchor", "catalyst_timeline", "cash_runway"),
}
_TYPE_NONDEFAULT_WEIGHTS = ("稳定价值", "未盈利/管线", "困境反转", "成熟/停滞")  # 层内权重非默认的型


def _normalize_stock_type(st):
    """stock_type 自由文本 → (标准型, 默认成长层, legacy 旧名)；无法映射 → (None, None, None)。"""
    st = str(st or "")
    for kw, std, tier in _TYPE_ALIASES:
        if kw in st:
            legacy = st if (std == "成长型" and kw in ("稳健成长", "快速成长")) else None
            return std, tier, legacy
    return None, None, None


def _bar_values(fill, key):
    """fin_trend 中 name 含 key 且 values 非空的柱 values（标准 4 面板之净利面板）。"""
    ft = fill.get("fin_trend") or {}
    for p in ft.get("panels") or []:
        for b in p.get("bars") or []:
            if key in str((b or {}).get("name") or ""):
                vals = (b or {}).get("values") or []
                if vals:
                    return vals
    return None


def _hist_cagr(fill, key="扣非"):
    """fin_trend 复算历史 CAGR（v5.4.0 改扣非口径）：years + panels 内 name 含 key 的
    bar 的 values（**与 years 等长且全可解析**、首尾正数、≥3 点）；数据不足/口径异常
    （不等长/含非数字/含负值）→ None——回落人工判定，不给门禁喂错窗口。
    归母柱不再作对账基准——一次性损益会把正常化路径算歪，口径例外由 cagr_adjustments 承接。"""
    ft = fill.get("fin_trend") or {}
    years = [str(y) for y in (ft.get("years") or [])]
    vals = _bar_values(fill, key)
    # v5.4.0 审计 P0-2：柱值与 years 不等长时 zip 静默截断 → CAGR 算错窗口（本数驱动拒渲染门禁）
    if not vals or len(vals) != len(years):
        return None
    nums = [_num(v) for v in vals]
    if len(nums) < 3 or any(v is None or v <= 0 for v in nums):
        return None  # <3 年/含非数字或非正值（亏损年、口径异常）→ 跳过对账（甘李/快手实证）
    y0 = re.sub(r"\D", "", years[0])[:4]
    y1 = re.sub(r"\D", "", years[-1])[:4]
    span = (int(y1) - int(y0)) if (y0 and y1) else (len(nums) - 1)
    if span < 1:
        return None
    return (nums[-1] / nums[0]) ** (1 / span) - 1


# v5.4.0 口径例外明细四键（typing_evidence.cagr_adjustments 每项必须齐全且非空）
_CAGR_ADJ_KEYS = ("year", "item", "amount", "reason")
# 例外 c 的触发词（v5.4.0 审计收窄）：去掉裸「调整」——「目标价调整」等无关说法不得触发
# 强制明细门禁；只认口径语义的词形（剔除/口径调整/重述/正常化/经调整）。
_CAGR_ADJ_KEYWORDS = ("剔除", "口径调整", "重述", "正常化", "经调整")


def _cagr_adj_reasons(fill: dict, te: dict) -> list:
    """cagr_adjustments 强制的三条例外（v5.4.0 口径收口）：
    a 港股 5 位代码（经调整口径）；b 扣非柱不可用（无柱/不等长/含非数字或非正值/有效年 <3）；
    c cagr_hist 含 _CAGR_ADJ_KEYWORDS（剔除/口径调整/重述/正常化/经调整，不含裸「调整」）。
    三条皆不成立 → 空列表（默认扣非口径直接复算）。"""
    reasons = []
    if re.fullmatch(r"\d{5}", str(fill.get("code") or "").strip()):
        reasons.append("港股 5 位代码（经调整口径）")
    if _hist_cagr(fill) is None:
        reasons.append("扣非柱不可用（无扣非柱/不等长/含非数字或非正值/有效年 <3）")
    hist = str(te.get("cagr_hist") or "")
    kw = [k for k in _CAGR_ADJ_KEYWORDS if k in hist]
    if kw:
        reasons.append(f"cagr_hist 含口径调整词「{'/'.join(kw)}」")
    return reasons


def _check_typing_v2(fill: dict, warns: list) -> None:
    """分型判据 v2 校验组（v5.3.0）：枚举标准化（无法映射拒渲染）+ 型↔层占比对账 +
    成长层 CAGR 对账 + typing_evidence 必填键 + 撞车白名单（非白名单拒渲染）+
    weights 完整性（半填拒渲染）。首版软约束项均在文案注明，观察一轮后升级。
    v5.4.0：CAGR 对账改扣非口径；分型要求 cagr_hist 键时三条例外（港股 5 位代码 /
    扣非柱不可用 / cagr_hist 含口径调整词）任一命中 → cagr_adjustments 四键明细缺失或
    结构不全即拒渲染；明细齐备 → 按声明调整口径处理（人工判定）不复算（③扣非不可用
    分支经此到达——无明细时已被门禁先行拒渲染）。te/ok_adj 一次算清，对账与门禁共用。"""
    st_raw = str(fill.get("stock_type") or "")
    std, tier, legacy = _normalize_stock_type(st_raw)
    if not std:
        raise ValueError(
            f"stock_type={st_raw!r} 无法映射六型枚举（v5.3.0 判据 v2）："
            "周期股 / 稳定价值[子类] / 成长型（配 growth_tier）/ 成熟·停滞 / 未盈利·管线 / 困境反转；"
            "旧名「稳健/快速成长」请改为「成长型」+growth_tier")
    if legacy:
        warns.append(f"stock_type 旧名 {legacy!r}：v5.3.0 两型已合并为「成长型」，"
                     f"本报告按映射 成长型·{tier} 层处理——请改用新名 + growth_tier（首版软约束）")

    te = fill.get("typing_evidence") or {}
    need = _TYPE_EVIDENCE_KEYS.get(std) or ()
    # v5.4.0 口径收口：明细结构一次判定（对账跳过与强制门禁共用同一 ok_adj，
    # 残件如 [{}] 不再「非空即算数」静默关掉对账）
    adj = te.get("cagr_adjustments")
    ok_adj = (isinstance(adj, list) and bool(adj)
              and all(isinstance(a, dict)
                      and all(a.get(k) not in (None, "") and str(a.get(k)).strip() for k in _CAGR_ADJ_KEYS)
                      for a in adj))

    if std == "成长型":
        gt = str(fill.get("growth_tier") or "").strip().lower()
        if gt in ("high", "mid"):
            tier = gt
        elif tier is None:
            warns.append("growth_tier 缺失：成长型须声明 high（扣非 CAGR>25%）/ mid 分层（v5.3.0），本报告按 mid 处理")
            tier = "mid"
        if ok_adj:
            # ① 明细齐备 → 人工判定（按声明调整口径），脚本不复算扣非 CAGR
            warns.append("growth_tier 对账按声明调整口径处理（人工判定）：typing_evidence.cagr_adjustments 非空，"
                         "脚本不复算扣非 CAGR——分层以声明为准，调整明细已入账")
            cagr = None
        else:
            # ② 扣非柱复算（口径例外走 ①；扣非不可用/不等长 → None——成长型此时无明细，
            # 已被下方门禁先拒渲染，故「人工判定」只经 ① 到达）
            cagr = _hist_cagr(fill)
        if cagr is not None:
            if tier == "high" and cagr < 0.20:
                warns.append(f"growth_tier=high 但 fin_trend 扣非 CAGR={cagr * 100:.1f}%"
                             "（高速层门槛 >25%，缓冲带 ±5pct 外）：分层与财务事实不符——"
                             "口径异常请在 typing_evidence.cagr_hist/cagr_adjustments 注明正常化依据")
            elif tier == "mid" and cagr > 0.30:
                warns.append(f"growth_tier=mid 但 fin_trend 扣非 CAGR={cagr * 100:.1f}%"
                             "（中速层 5-25%，缓冲带 ±5pct 外）：应归高速层（60:40 + 高速层权重），请复核")

    want = _GROWTH_LAYER.get(tier) if std == "成长型" else _TYPE_LAYER.get(std)
    ls_raw = fill.get("layer_share") or {}
    if want and ls_raw:
        l1 = _num(ls_raw.get("L1"))
        if l1 is not None and (int(l1), int(100 - l1)) != want:
            warns.append(f"layer_share {l1:g}:{100 - l1:g} 与 {std}{'·' + tier if std == '成长型' else ''} "
                         f"映射 {want[0]}:{want[1]} 不符（v5.3.0 型↔占比对账，首版软约束）")
    elif want and want != (70, 30):
        warns.append(f"{std} 层占比应为 {want[0]}:{want[1]}，未填 layer_share 将按默认 70:30 计算，分数可能错误")
    if (std in _TYPE_NONDEFAULT_WEIGHTS or (std == "成长型" and tier == "high")) and not fill.get("weights"):
        warns.append(f"{std}{'·高速层' if std == '成长型' else ''} 层内权重非默认，未填 weights——脚本将用基础权重计算，分数可能错误")

    miss = [k for k in need if not te.get(k)]
    if miss:
        warns.append(f"typing_evidence 缺键 {miss}（{std} 判据答案结构化，v5.3.0 首版软约束，观察一轮后升拒渲染）")
    # v5.4.0 口径收口：正常化口径须落明细——三条例外任一命中即强制 cagr_adjustments
    if "cagr_hist" in need:
        reasons = _cagr_adj_reasons(fill, te)
        if reasons and not ok_adj:
            raise ValueError(
                "typing_evidence.cagr_adjustments 缺失或结构不全（命中：" + "；".join(reasons) + "）："
                "正常化口径不成立时历史 CAGR 必须逐条给出调整明细——"
                '格式 [{"year":2024,"item":"处置子公司股权收益","amount":-6.2,"reason":"一次性损益剔除"}]'
                "（四键 year/item/amount/reason 齐全且非空，amount 单位亿元；v5.4.0 口径收口，拒渲染）")
        if ok_adj and not reasons:
            warns.append("typing_evidence.cagr_adjustments 已填但三条例外（港股 / 扣非柱不可用 / "
                         "cagr_hist 口径调整词）均不成立：默认扣非口径可直接复算，多余明细易成口径漂移口"
                         "——请删除该键（确需调整则把理由写进 cagr_hist）")

    tc = fill.get("typing_clash")
    if tc:
        w_std, _, _ = _normalize_stock_type(tc.get("with"))
        if not w_std or {std, w_std} != {"周期股", "成长型"}:
            raise ValueError(
                f"typing_clash.with={tc.get('with')!r} 非白名单共存对（仅 周期股×成长型）："
                "高成本撞车（涉红灯豁免或占比跳变 ≥15pct）必须消歧，禁止共存声明（v5.3.0）")
        cc = re.sub(r"<[^>]+>", "", str(tc.get("cross_check") or "")).strip()
        if len(cc) < 30:
            warns.append("typing_clash.cross_check <30 字：对照方法目标价互证/背离说明不足")

    w = fill.get("weights") or {}
    if w:
        has_l1 = any(k in w for k in ("1A", "1B", "1C", "1D", "1E", "1F"))
        has_l3 = any(k in w for k in ("3A", "3B", "3C"))
        if has_l1 != has_l3:
            raise ValueError("weights 半填：L1（1A-1F）与 L3（3A-3C）只填一层，另一层将静默回落默认权重拼算"
                             "（冰轮 2026-09-13 实证，侥幸零影响非设计）——两层必须同填或同不填（v5.3.0）")


def _check_thesis_price_tags(fill: dict, warns: list) -> None:
    """thesis 三情景价格标注完整性。"""
    th = fill.get("thesis_html", "")
    if th and not any(c in th for c in ("scenario-pess", "scenario-base", "scenario-opt")):
        # 价格形态只认带「元」的数字组（含 15.7/37.5/61.8 元 斜杠组）——年份区间
        # 「2023-2025」、数量区间「3-5 家」「10%-15%」不带元，不误拒（热核 P0-1）
        price_nums = 0
        for pm in re.finditer(r"(\d+(?:\.\d+)?(?:\s*[-–~/]\s*\d+(?:\.\d+)?)*)\s*元", th):
            price_nums += len(re.findall(r"\d+(?:\.\d+)?", pm.group(1)))
        if price_nums >= 2:
            raise ValueError("thesis_html 含价格形态但三情景 span（scenario-pess/base/opt）全缺："
                             "手写价绕过了与 valuation 的一致性硬校验（v5.1.2 起拒渲染）——"
                             "三价必须写入 span 由脚本对账")
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
    if pp is not None and not isinstance(pp, dict):
        raise ValueError("peers_plot 必须为 {points, pe_bands, roe_bands} 对象，数组简写已废止")
    pts = (pp or {}).get("points") or []
    if pts:
        # v5.1.2：比对对象与渲染同源——渲染只画 roe/pe 可解析的点（charts_scenario），
        # 不可解析的 target 点不落图（此前拿原始数组第一个 target 点比对）
        tg_all = [p for p in pts if isinstance(p, dict) and p.get("target")]
        tg = [p for p in tg_all
              if _num(p.get("roe")) is not None and _num(p.get("pe")) is not None]
        if not tg_all:
            warns.append("peers_plot 没有 target=true 的目标公司点")
        else:
            if len(tg_all) > 1:
                warns.append(f"peers_plot 共 {len(tg_all)} 个 target=true 点（应恰 1 个）："
                             "图中会出现多个钢蓝目标点，请只保留目标公司")
            if not tg:
                warns.append("peers_plot 目标点 roe/pe 均不可解析：图中无蓝色目标点"
                             "（渲染丢弃），请核对 target 点数据")
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
                         if isinstance(p, dict) and not p.get("target")
                         and _num(p.get("roe")) is not None and _num(p.get("roe")) > 0]
            if troe is not None and troe > 0 and len(peers_roe) >= 2:
                p_lo, p_hi = min(peers_roe), max(peers_roe)
                if troe < p_lo / 2 or troe > p_hi * 2:
                    warns.append(f"peers_plot 目标公司 ROE（{troe:g}%）脱离同业量级（同业 {p_lo:g}-{p_hi:g}%）"
                                 f"——ROE 口径疑似不一（年报/加权/TTM、不同年份）或取数错误，请核对")


def _peers_name_key(s: str) -> str:
    """同业名归一（表图一致比对键，v5.4.0 热核审计）：去括号注（（…）/(…)）、空白（含全角）
    与尾部交易所标记（-U 未盈利/-W 同股不同权/-SW 二次上市等）——「宁德时代（CATL）」
    ≡「宁德时代」、「百济神州-U」≡「百济神州」（恒瑞 2026-09-19 存量实证：表图两处同一家
    公司带了没带 -U 后缀）；近似名不互相放行——此前双向子串匹配会把「比亚迪」与
    「比亚迪电子」当同一家，是硬门禁的假阴性口。"""
    s = re.sub(r"[（(][^）)]*[）)]", "", str(s or ""))
    s = re.sub(r"[\s\u3000]+", "", s)
    return re.sub(r"-(?:SW|WD|U|W|S)$", "", s, flags=re.I)


def _check_peers_selection(fill: dict, warns: list) -> None:
    """v5.4.0 peer 选取硬化（五条，与 peers_plot/peers_meta/peers_html 三方对账）：
    ⑨表图一致（**拒渲染**）：peers_plot 非 target 点必须出现在 peers_html **非 matrix-table
      的表**的行首格（名字归一后精确相等），或名点写进 peers_meta（= 已声明剔出理由）；
      未声明的名字 → 拒渲染，target 点豁免。九宫格兜底表（行=ROE 档、公司名在单元格里）
      不作名字来源、且渲染器会删除它——peers_html 只剩 matrix-table 时整条检查跳过
      （审计 P0-1：同存路径此前把九宫格行首档位名当公司名 → 误拒）。
    ⑩尺子一致（告警）：target 点 roe 与 fin_trend 的 ROE 线末值 >3pct 且 peers_meta 无
      「口径词（TTM/加权/经调整/静态）+ 点名目标」双命中的注明 → 告警。
    ⑪peer ≥3（告警）：非 target 有效点（name+roe+pe 可解析）<3 → 告警；peers_meta 已写明
      凑不齐原因（含「仅/凑不齐/可比公司不足」）→ 抑制（与「meta 注明后可忽略」惯例一致）。
    ⑫rationale（软告警）：有 peer 章节实体（peers_plot 或非占位 peers_meta）时即检查——
      peers_meta 须含两把尺（同行业/同规模/同商业模式 ≥2 种）+ 排除语（排除/未选/剔出），
      缺一告警（占位「—」由 _check_misc_required 的占位告警兜底，不重复报）。
    ⑬PE 交叉（软告警）：valuation base 情景 pe 下限高于全部非 target 点 pe → 须溢价论证。
    数据缺失的分支一律跳过（不误报）。"""
    meta = str(fill.get("peers_meta") or "")
    pp = fill.get("peers_plot")
    pts = (pp or {}).get("points") or [] if isinstance(pp, dict) else []
    # ⑨ 表图一致（硬）：非 matrix-table 表内公司名集合（归一）+ peers_meta 声明名单
    if pts:
        tbl_names, n_plain = set(), 0
        for tbl in re.findall(r"<table\b[^>]*>.*?</table>", fill.get("peers_html") or "",
                              flags=re.I | re.S):
            if "matrix-table" in tbl:
                continue
            n_plain += 1
            for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", tbl, flags=re.I | re.S):
                cells = re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", tr, flags=re.I | re.S)
                key = _peers_name_key(_plain_text(cells[0])) if cells else ""
                if key:
                    tbl_names.add(key)
        if n_plain:
            undeclared = []
            for p in pts:
                if not isinstance(p, dict) or p.get("target"):
                    continue
                nm = str(p.get("name") or "").strip()
                if not nm or nm in meta or _peers_name_key(nm) in tbl_names:
                    continue
                undeclared.append(nm)
            if undeclared:
                raise ValueError("peers_plot 点位未出现在 peers_html 表格、peers_meta 亦无声明："
                                 + "、".join(undeclared)
                                 + "——表图一致纪律（v5.4.0，拒渲染）：散点图每家同业必须在当前指标表/"
                                   "趋势表有一行，或在 peers_meta 点名说明未列/剔出理由"
                                   "（target 点豁免；matrix-table 九宫格不作名字来源）")
    # ⑩ 尺子一致（告警）：散点图 ROE vs fin_trend ROE 线末值
    tg = [p for p in pts if isinstance(p, dict) and p.get("target")
          and _num(p.get("roe")) is not None]
    roe_ref = None
    for p in (fill.get("fin_trend") or {}).get("panels") or []:
        if not isinstance(p, dict):
            continue
        for ln in p.get("lines") or []:
            if isinstance(ln, dict) and "ROE" in str(ln.get("name") or ""):
                vals = [_num(v) for v in (ln.get("values") or [])]
                if vals and vals[-1] is not None:
                    roe_ref = vals[-1]
                    break
        if roe_ref is not None:
            break
    if tg and roe_ref is not None:
        troe = _num(tg[0].get("roe"))
        # 口径注明须「口径词 + 点名目标」双命中（热核审计 P2：裸「口径」是万能逃生口——
        # 只在偏离存在时才需要注明，而偏离的正当理由必然指向目标公司的特殊口径）
        co = str(fill.get("company") or "")
        calib_noted = (re.search(r"TTM|加权|经调整|静态", meta)
                       and bool((co and co in meta) or "目标" in meta))
        if abs(troe - roe_ref) > 3 and not calib_noted:
            warns.append(f"peers_plot 目标点 ROE（{troe:g}%）与 fin_trend ROE 线末值（{roe_ref:g}%）"
                         f"绝对差 {abs(troe - roe_ref):.1f}pct > 3pct：两处口径须一致——"
                         f"在 peers_meta 注明目标公司口径（含 TTM/加权/经调整/静态并点名目标公司）"
                         f"或改齐数据后重渲")
    # ⑪ peer ≥3（告警）：有效同业点计数（peers_meta 已写明凑不齐原因 → 抑制，同「注明后可忽略」惯例）
    peer_pts = [p for p in pts if isinstance(p, dict) and not p.get("target")
                and str(p.get("name") or "").strip()
                and _num(p.get("roe")) is not None and _num(p.get("pe")) is not None]
    if pts and len(peer_pts) < 3 and not re.search(r"仅|凑不齐|可比公司不足", meta):
        warns.append(f"peers_plot 有效同业点仅 {len(peer_pts)} 家（<3）：同业对比至少 3 家可比公司"
                     f"（表与散点同源）——凑不齐请在 peers_meta 写明原因（如「可比公司仅 2 家」）")
    # ⑫ rationale（软告警）：三选二 + 排除语；有 peer 章节实体即检查（占位「—」由占位告警兜底）
    if pts or meta.strip() not in ("", "—"):
        kinds = [k for k in ("同行业", "同规模", "同商业模式") if k in meta]
        if len(kinds) < 2 or not re.search(r"排除|未选|剔出", meta):
            warns.append(f"peers_meta 选取理由不完整（现含 {'/'.join(kinds) or '无'}；"
                         f"{'有' if re.search(r'排除|未选|剔出', meta) else '缺'}排除语）："
                         f"须含「同行业/同规模/同商业模式」≥2 种 + 「排除/未选/剔出」说明"
                         f"（为何不选近邻标的）")
    # ⑬ PE 交叉（软告警）：基础带下限高于全部同业 PE
    base_pe = None
    for s in (fill.get("valuation") or {}).get("scenarios") or []:
        if isinstance(s, dict) and str(s.get("key") or "").lower() == "base":
            pe = s.get("pe") or []
            base_pe = _num(pe[0]) if len(pe) >= 1 else None
    peer_pes = [_num(p.get("pe")) for p in pts
                if isinstance(p, dict) and not p.get("target") and _num(p.get("pe")) is not None]
    if base_pe is not None and peer_pes and base_pe > max(peer_pes):
        warns.append(f"valuation 基础情景 PE 下限（{base_pe:g}x）高于全部同业散点 PE"
                     f"（最高 {max(peer_pes):g}x）：基础带高于全部同业，须溢价论证"
                     f"（在 valuation_html 写明溢价来源：护城河/成长差/资产质量）")


def _check_timing_table_cells(fill: dict, warns: list) -> None:
    """时机判定小表单元格超长告警（长句塞格会溢出横向滚动；长解释应挪到表下 .source 行）。
    v5.1.2：小表「筹码面/技术面」得分 vs timing_scores 数值比对（>0.1 告警）；技术面信号中的
    现价/MA60/MA120/52 周高低 数值与方向词 vs quote 落盘 timing（神华假 MA60 修复闭环——信号取自落盘、
    禁手估，数值偏差 >1% 或方向矛盾告警；自由文本全量语义比对不做）。"""
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
        # v5.1.2：得分比对（固定行形态：维度 ｜ 得分 ｜ 命中信号与加减）
        ts = fill.get("timing_scores") or {}
        for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", tbl, re.I | re.S):
            cells = [_plain_text(c) for c in re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", tr, re.I | re.S)]
            if len(cells) < 2 or "合计" in cells[0]:
                continue
            for dim in ("筹码面", "技术面"):
                if dim in cells[0]:
                    sm = re.search(r"\d+(?:\.\d+)?", cells[1])
                    ref_s = _num(ts.get(dim))
                    if sm and ref_s is not None and abs(float(sm.group(0)) - ref_s) > 0.1:
                        warns.append(f"时机判定小表「{dim}」得分（{sm.group(0)}）与 timing_scores"
                                     f"（{ref_s:g}）不一致（>0.1）：两处应同源（v5.1.2）")
        # v5.1.2：信号数字/方向 vs 落盘 timing（神华假 MA60 同源修复闭环）
        # v5.1.5（热核 P0-1，文档虚言闭合）：52 周高低补入比对（fill-schema/SKILL 承诺的
        # 技术面信号四件套此前只查三键）——「52周高低 高/低」合并写法（照抄 E1 时机素材行
        # 形态）与「52周高 X」「52周低 X」分拆写法都认；方向词比对仍只做 MA60/MA120
        ref_t = (_quote_ref(fill) or {}).get("timing") or {}
        rp = _num(ref_t.get("price"))
        txt = _plain_text(tbl)
        for hi_s, lo_s in re.findall(r"52周高低\s*[:：=]?\s*(\d+(?:\.\d+)?)\s*[/／]\s*(\d+(?:\.\d+)?)", txt):
            for lbl, v_s, rv2 in (("52周高", hi_s, _num(ref_t.get("high_52w"))),
                                  ("52周低", lo_s, _num(ref_t.get("low_52w")))):
                if rv2 and abs(float(v_s) - rv2) / rv2 > 0.01:
                    warns.append(f"时机小表信号 {lbl}={v_s} 与落盘值 {rv2:g} 偏差 >1%："
                                 "技术面信号一律取自 quote 落盘 timing、禁手估（v5.1.2）")
        for label, rv in (("现价", rp), ("MA60", _num(ref_t.get("ma60"))),
                          ("MA120", _num(ref_t.get("ma120"))),
                          ("52周高", _num(ref_t.get("high_52w"))),
                          ("52周低", _num(ref_t.get("low_52w")))):
            if not rv:
                continue
            pat = ("52周高(?!低)" if label == "52周高" else label) + r"\s*[:：=]?\s*(\d+(?:\.\d+)?)"
            for nm_ in re.findall(pat, txt):
                if abs(float(nm_) - rv) / rv > 0.01:
                    warns.append(f"时机小表信号 {label}={nm_} 与落盘值 {rv:g} 偏差 >1%："
                                 "技术面信号一律取自 quote 落盘 timing、禁手估（v5.1.2）")
            if label not in ("MA60", "MA120") or not rp:
                continue
            up = re.search(r"(站上|突破|收复|高于|上穿).{0,6}" + label, txt, re.S) or \
                re.search(label + r".{0,4}(上方|之上)", txt, re.S)
            down = re.search(r"(跌破|失守|低于|下穿).{0,6}" + label, txt, re.S) or \
                re.search(label + r".{0,4}(下方|之下)", txt, re.S)

            def _now(m):
                """命中词所在句不含翻转/过去时标记才算现在时叙述（热核 P1-5：
                「9 月曾跌破 MA60，现已收复」与落盘现价>MA60 一致，不应误报）。"""
                for seg in re.split(r"[，。；、]", txt):
                    if m.group(0) in seg:
                        return not re.search(r"曾|收复|回升|重返|现已", seg)
                return True
            if up and rp < rv and _now(up):
                warns.append(f"时机小表信号「{label} 上方/站上」与落盘矛盾：现价 {rp:g} < "
                             f"{label} {rv:g}（v5.1.2）")
            if down and rp > rv and _now(down):
                warns.append(f"时机小表信号「{label} 下方/跌破」与落盘矛盾：现价 {rp:g} > "
                             f"{label} {rv:g}（v5.1.2）")


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
    # v5.1.2：Hero 指标卡 ✓ 必填字段缺失告警（渲染层有 —/默认值兜底，不拒但不该静默）
    for name in ("pe_ttm", "mcap", "horizon", "price_sub_html", "mcap_sub", "pe_sub"):
        if name == "horizon":
            # horizon 契约允许只放 valuation 级或情景级（_check_valuation_scenarios 明文），
            # 顶层缺失但下两级有值时不告警（热核 P2-6：两处契约打架）
            _v = fill.get("valuation") or {}
            if (str(_v.get("horizon") or "").strip()
                    or any(str(s.get("horizon") or "").strip()
                           for s in _v.get("scenarios") or [] if isinstance(s, dict))):
                continue
        if not str(fill.get(name) or "").strip():
            warns.append(f"Hero {name} 缺失：指标卡对应位置将显示空白或默认值（fill-schema 标 ✓ 必填）")
    tsub = str(fill.get("target_sub_html") or "")
    if re.search(r"\d+(?:\.\d+)?\s*(?:%|元)", tsub):
        warns.append("target_sub_html 含具体百分比/价格数字：目标价区间由脚本按 valuation 覆盖，"
                     "覆盖后手写数字与卡面失配——空间说明只写定性（v5.1.2）")


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
    """v4.8 可选图字段纪律：业务构成占比和 / 产业链两端 / 发丝图与第 11 章绑定 / 户数期数。
    v5.4.1：pe_history 禁填（成长型·高速层 / 未盈利·管线 → 软告警，fill-schema 填写条件）。"""
    seg = fill.get("segments") or {}
    items = seg.get("items") or []
    if items:
        # v5.1.2：合计口径与渲染同源——渲染只画 name+rev_pct 齐全的行（charts_l1），
        # 缺名/缺占比的行不落图，其占比不得计入「≈100%」判定
        drawn = [it for it in items
                 if isinstance(it, dict) and str(it.get("name") or "").strip()
                 and _num(it.get("rev_pct")) is not None]
        if len(drawn) < len(items):
            warns.append(f"segments 有 {len(items) - len(drawn)} 行缺 name 或 rev_pct：该行不落图，"
                         "占比缺口会在图上去向不明，请补齐或删除")
        s = sum(_num(it.get("rev_pct")) or 0 for it in drawn)
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
    # v5.4.1：pe_history 禁填告警（fill-schema 填写条件长期只写在文档里、零校验）——
    # 成长型·高速层（含旧名「快速成长」）与 未盈利/管线：历史区间锚不住合理带，禁填本字段
    if fill.get("pe_history"):
        std_ph, legacy_tier_ph, _leg_ph = _normalize_stock_type(fill.get("stock_type"))
        gt_ph = str(fill.get("growth_tier") or "").strip().lower()
        tier_ph = gt_ph if gt_ph in ("high", "mid") else legacy_tier_ph
        if (std_ph == "成长型" and tier_ph == "high") or std_ph == "未盈利/管线":
            shows = f"{std_ph}·高速层" if std_ph == "成长型" else std_ph
            warns.append(f"pe_history 已填但本分型（{shows}）禁填：历史区间锚不住合理带"
                         "（fill-schema 填写条件：周期股/成长型·中速层/成熟·停滞/稳定价值/困境反转"
                         "按数据可得性填；成长型·高速层/未盈利·管线禁填——第 11 章时段表仍可写，"
                         "但本字段删除，估值带改用远期 PE 折现或 rNPV/P/S）")
    holders = fill.get("holders") or []
    # v5.1.2：有效点口径与渲染同源——渲染先滤 num 可解析且带日期的行（charts_misc）
    h_valid = [p for p in holders if isinstance(p, dict) and _num(p.get("num")) is not None
               and str(p.get("date") or "").strip()]
    if holders and len(h_valid) < 3:
        warns.append("holders 有效点 <3（num 可解析且带日期）：户数趋势图不生成"
                     "（E4 默认返回近 8 期，请回填 ≥3 期）")
    # v4.11.0：同一截止日多行告警（E4 上游偶发重复，天齐 20260710 双行且变动值不一致实证；
    # 图内已去重保留后写行，此处提示模型核对哪一行为准）。审计修订：去重键按数字序列归一
    #（"20260710" 与 "2026-07-10" 同日）；去重后 <3 期时图不生成，与图门槛同口径告警
    hdates = ["".join(ch for ch in str((p or {}).get("date") or "") if ch.isdigit())
              for p in h_valid]
    dup = sorted({d for d in hdates if d and hdates.count(d) > 1})
    if dup:
        warns.append(f"holders 存在重复截止日：{'、'.join(dup)}——图内已去重（保留后写行），"
                     f"请核对 E4 原始输出哪一行的变动值为准")
    if len(h_valid) >= 3 and len({d for d in hdates if d}) < 3:
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
        # v5.1.2：hit/miss 行 target「阈值｜实际值」核对（状态语义色正确性不再全靠自觉）
        for t in trg:
            if not isinstance(t, dict):
                continue
            st_ = str(t.get("status") or "pending").strip().lower()
            if st_ not in ("hit", "miss"):
                continue
            tgt = str(t.get("target") or "")
            cond = str(t.get("cond") or "")[:8]
            if "实际" not in tgt:
                warns.append(f"triggers[{cond}] status={st_} 但 target 未写实际值"
                             "（回测核对行格式「阈值｜实际值」，v5.1.2）")
                continue
            m = re.search(r"([≥≤<>])\s*(\d+(?:\.\d+)?)\s*%?\s*[｜|]\s*实际\s*(\d+(?:\.\d+)?)", tgt)
            if m:
                op, thr, act = m.group(1), float(m.group(2)), float(m.group(3))
                hit = act >= thr if op in ("≥", ">") else act <= thr
                if ("hit" if hit else "miss") != st_:
                    warns.append(f"triggers[{cond}] status={st_} 与 target「{tgt}」矛盾："
                                 f"实际 {act:g} {'满足' if hit else '不满足'}阈值 {op}{thr:g}（v5.1.2）")


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


def _check_l4_form(fill: dict, warns: list) -> None:
    """v4.10：L4 固定形态硬门禁（工行 09-11 报告照抄 09-09 旧形态实证——软规则不拦就没人守）。
    ①损失预演必须为三联卡（.pm-grid，骨架见 fill-schema），禁止退回单段 danger-card 长文；
    ②黄灯扣分明细表行数必须与顶层 yellow_deductions 条数一致——多列=零扣分空行该删，
    少列=扣分项没列全。类别字母缺失无法核对时降级告警。"""
    l4 = fill.get("l4_html") or ""
    if "pm-grid" not in l4:
        raise ValueError("l4_html 缺损失预演三联卡（.pm-grid 固定骨架，v4.10 起）："
                         "禁止退回单段 danger-card 长文——骨架见 fill-schema「损失预演三联卡骨架」")
    yellow = fill.get("yellow_deductions") or []
    # v5.1.2：行检出放宽（容忍 <tr>/<td> 带属性——原紧邻形态漏检走降级）+ 逐项数值比对
    row_ms = list(re.finditer(r"<tr[^>]*>\s*<td[^>]*>\s*[abcd][\s　].*?</tr>", l4, re.S))
    # 分母=points>0 的条目（零扣分类别不入表是契约正典，0 分合法——热核 P1-4）
    pos_y = [y for y in yellow if isinstance(y, dict) and (_num(y.get("points")) or 0) > 0]
    if row_ms and len(row_ms) != len(pos_y):
        raise ValueError(f"l4_html 黄灯扣分明细表 {len(row_ms)} 行与 yellow_deductions 正扣分 "
                         f"{len(pos_y)} 条不一致："
                         "只列 points>0 的类别行（零扣分类别不入表，表末一句「其余类别已核查无扣分」兜底），"
                         "每行扣分须与 yellow_deductions 对应")
    if row_ms and len(row_ms) == len(pos_y):
        row_pts = []
        for rm in row_ms:
            nm_ = re.search(r'class="num"[^>]*>\s*([\d.]+)', rm.group(0))
            row_pts.append(round(float(nm_.group(1)), 3) if nm_ else None)
        y_pts = sorted(round(_num(y.get("points")), 3) for y in pos_y)
        if None in row_pts:
            warns.append("l4_html 黄灯表扣分单元格未检出数值（class=num）：逐项数值比对降级，"
                         "请人工核对与 yellow_deductions 一致（v5.1.2）")
        elif sorted(row_pts) != y_pts:
            raise ValueError(f"l4_html 黄灯表扣分值 {sorted(row_pts)} 与 yellow_deductions {y_pts} 不一致："
                             "表与字段数值多重集一致（脚本按 yellow_deductions 扣分，v5.1.2 起拒渲染）")
    if not row_ms and pos_y:
        warns.append(f"l4_html 黄灯扣分明细未检出表格形态（<td>a-d 类别行），但有 "
                     f"{len(yellow)} 条 yellow_deductions——请用扣分表正典形态"
                     f"（fill-schema「L4 黄灯扣分明细」）")


def _check_cn_placeholder(fill: dict) -> None:
    """fill 正文字段中文占位符硬校验（与渲染后 _check_leftover 同口径的前置版，v4.10.2）：
    【待填】类残留提前到校验期拦截——--check 与 render 对 fill 问题拦截面一致，
    不再出现「check 退出 0 但 render 才炸」。黄灯类别标注（【b 行业与政策环境】这类
    以单个 a-d 字母开头的）是合法引用，不算占位符；fill 里的字面 {{KEY}} 合法
    （渲染时实体化显示），不在此查。"""
    for name in _HTML_FIELDS:
        hits = _cn_placeholders(fill.get(name))
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
    _check_quote_consistency(fill, warns)
    _check_score_ranges(fill)

    _check_valuation_inputs(fill)
    _check_valuation_scenarios(fill, warns)
    _check_odds_floor(fill, warns, calc)  # v5.0 机制三：赔率 ∞ 须配悲观地板证据（floor）
    _check_consensus_np(fill, warns)    # v5.0 机制二：乐观税一致预期照抄交叉校验
    _check_anchor_discipline(fill, warns)  # v5.1.0 估值锚纪律：增量证据锁死+回滚条款前置（v5.4.0 双尺）
    _check_anchor_blind_fly(fill, warns)   # v5.4.0：无历史分位可对账 → 校验盲飞告警
    _check_chart_fields(fill)
    _check_quote_present(fill, warns)   # v4.11.1（审核 D5）：date ≥ 2026-09-02 缺 quote 拒渲染
    _check_gap_plot(fill, calc, warns)  # v4.11.1：gap_plot 分布图字段校验（可选字段，缺失不查）

    _check_red_flag_breaker(fill)
    _check_red_flag_conclusion(fill)  # v5.1.2：红旗 ≥2 项 → 首卡首句存疑句硬门禁
    _check_thesis_consistency(fill, calc)
    _check_content_floor(fill)
    _check_l4_form(fill, warns)
    _check_cn_placeholder(fill)

    _check_missing_required_warns(fill, warns)
    _check_typing_v2(fill, warns)
    _check_thesis_price_tags(fill, warns)
    _check_thesis_info_floor(fill, warns)
    _check_hero_band_claims(fill, warns)
    _check_peers_plot_target(fill, warns)
    _check_peers_selection(fill, warns)   # v5.4.0：表图一致（硬）+ 尺子一致/peer≥3/rationale/PE 交叉
    _check_hero_cross(fill, warns)        # v5.1.2：Hero 与估值结构化字段互查
    _check_growth_consistency(fill, warns)  # v5.1.2：growth_plot 换算对账
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
    _check_sensitivity_units(fill, warns)  # v5.1.1：sensitivity.delta 量纲规范
    _check_slot_widths(fill, warns)       # v5.1.2：槽位契约补闸（trigger/chips 长度）
    _check_handwritten_dupes(fill, warns)  # v5.1.2：手写表与脚本生成并存检测
    _check_threshold_coverage(fill, warns)  # v5.1.2：4.3 阈值 14 章承载
    _check_cycle_stages(fill, warns)      # v4.11.3：周期阶段卡字段（cycle_stages）
    _check_dcf(fill, warns)               # v4.11.3：DCF 双卡字段（dcf）
    _check_cycle_position(fill, warns)    # v5.2.0：当前周期位置刻度条（cycle_position，首版软告警）
    _check_earnings_stability(fill, warns)  # v5.2.0：盈利波动性软锚（sigma 照抄比对，软告警）
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


def _check_red_flag_conclusion(fill: dict) -> None:
    """v5.1.2：红旗命中 ≥2 项（red_deductions 条数，1D 红旗扣分明细）→ conclusion_html
    首卡首句必须含「利润真实性存疑」（fill-schema:61 长期承诺、此前零实现——多红旗报告
    静默缺失全文最强的利润真实性警示）。与 red_flag→「不建议参与」同强度：拒渲染。"""
    red = fill.get("red_deductions") or []
    if len(red) < 2:
        return
    concl = fill.get("conclusion_html") or ""
    parts = concl.split("concl-head", 2)
    first_card = "concl-head".join(parts[:2]) if len(parts) > 2 else concl
    if "利润真实性存疑" not in first_card:
        raise ValueError(f"红旗命中 {len(red)} 项 ≥2：conclusion_html 首卡必须含「利润真实性存疑」"
                         "（fill-schema 既定要求，v5.1.2 起执行）——盈利质量红旗多项命中时，"
                         "结论必须先于一切优点声明存疑")


def _check_handwritten_dupes(fill: dict, warns: list) -> None:
    """v5.1.2：手写表与脚本生成并存检测（v4.11.3 三处手写迁移模式的补全——当时只堵了
    为什么卡/阶段表/DCF 表，其余四种同类形态无检测，图与表同屏各说各话）：
    ① p0_html 手写敏感性表（sensitivity 已填）；② valuation_html 手写三情景表/三指标卡；
    ③ l1_html 手写多年年表（fin_trend 已填）；④ gap_html 手写逐机构对照表（gap_plot 图会生成）。"""
    p0 = fill.get("p0_html") or ""
    if _sensitivity_items(fill) and "<table" in p0 and re.search(r"敏感|变量.{0,6}影响|弹性", p0):
        warns.append("p0_html 仍含手写敏感性表：sensitivity 字段已填、龙卷风图替代表，请删除手写表")
    vh = fill.get("valuation_html") or ""
    if "scenario-table" in vh:
        warns.append("valuation_html 含手写三情景表（scenario-table）：情景表由脚本按 valuation "
                     "生成，请删除手写表")
    if "metric-row" in vh and re.search(r"年化中枢|赔率|离散度", vh):
        warns.append("valuation_html 含手写三指标卡（年化中枢/赔率/离散度）：指标卡由脚本生成，"
                     "请删除手写卡")
    l1 = fill.get("l1_html") or ""
    if fill.get("fin_trend") and "<table" in l1:
        for tm in re.finditer(r"<table\b[^>]*>.*?</table>", l1, re.I | re.S):
            if len(set(re.findall(r"20\d{2}", tm.group(0)))) >= 4 and tm.group(0).count("<tr") >= 3:
                warns.append("l1_html 含多年年表（≥4 个年份列）：fin_trend 图墙已替代表"
                             "（v4.9 起禁写手写年表），请删除")
                break
    gp_dims = [d for d in ((fill.get("gap_plot") or {}).get("dims") or []) if _gap_dim_ok(d)]
    gh = fill.get("gap_html") or ""
    if len(gp_dims) >= 2 and "<table" in gh and re.search(r"机构|卖方", gh):
        warns.append("gap_html 含逐机构对照表：v4.11.1 起由 gap_plot 图承载（文字信息进 note "
                     "附注），请删除手写对照表")


def _check_slot_widths(fill: dict, warns: list) -> None:
    """v5.1.2：槽位契约补闸——scenario.trigger ≤15 字 / drivers.chips 档值 ≤12 字
    （fill-schema 槽位契约表早已声明，此前无检查；工行 24 字 trigger 撑爆表格实证可复发）。"""
    for s in (fill.get("valuation") or {}).get("scenarios") or []:
        if not isinstance(s, dict):
            continue
        trg = str(s.get("trigger") or "").strip()
        if len(trg) > 15:
            warns.append(f"scenario[{s.get('key')}] trigger {len(trg)} 字 > 15（槽位契约：短语——"
                         "三情景表触发条件行随列右对齐，长句换行难看，工行 24 字实证）")
    for d in fill.get("drivers") or []:
        if not isinstance(d, dict):
            continue
        tag = _plain_text(str(d.get("name") or "")).strip() or "?"
        for c in d.get("chips") or []:
            if isinstance(c, dict) and not c.get("unit") and len(str(c.get("value") or "")) > 12:
                warns.append(f"drivers[{tag[:8]}] chips 档值「{c.get('value')}」> 12 字"
                             "（槽位契约：三情景锚短值）")


def _check_threshold_coverage(fill: dict, warns: list) -> None:
    """v5.1.2：4.3 护城河压力测试给出的阈值须在 14 章 triggers/dash_html 有对应行
    （fill-schema 既定「给了阈值的 14 章必须有对应行，否则删阈值句」——此前只写在文档里）。
    4.3 dim-block 内阈值数字串在 triggers+dash_html 找不到 → 告警（启发式，误报请调表述）。"""
    l1 = fill.get("l1_html") or ""
    m43 = re.search(r"dim-name[^>]*>\s*4\.3", l1)
    if not m43:
        return
    nxt = re.search(r"dim-name", l1[m43.end():])
    block = l1[m43.start(): m43.end() + (nxt.start() if nxt else len(l1))]
    targets = str(fill.get("triggers") or "") + (fill.get("dash_html") or "")
    missing = []
    for mm in re.finditer(
            r"(?:≥|≤|大于|小于|跌破|突破|升至|降至|超过|低于|高于|超)\s*(\d+(?:\.\d+)?)"
            r"\s*(?:%|pct|亿|元|万户|万人|倍|x)?", block):
        if not re.search(r"(?<![\d.])" + re.escape(mm.group(1)) + r"(?![\d.])", targets):
            missing.append(mm.group(0).strip())
    if missing:
        warns.append(f"4.3 压力测试阈值 {sorted(set(missing))[:4]} 在 14 章 triggers/dash_html "
                     "无对应行：给了阈值的必须在 14 章可跟踪，否则删阈值句"
                     "（fill-schema 既定，v5.1.2 起告警）")


def _check_driver_cards(fill: dict, warns: list) -> None:
    """v4.11.3：P0 驱动卡字段校验（drivers/driver_verdict，软告警迁移期——缺失不拒）。
    drivers 1-2 项、chips 恰 悲观/基础/乐观 三情景档（+可选 unit）、name ≤12 字、
    note 显示宽 ≤300（≈3 行；宁德时代融合版备注 137 字实测可读，原 90 字过紧
    已放宽——宽度口径：CJK 计 2、ASCII 计 1）；
    v5.1.1：第一变量改由脚本按 sensitivity |impact| 降序加冕（与龙卷风图同源，
    charts_base._first_var_name；影石创新驱动卡手标与排序图各执一词、校验比数组
    第 0 项放过矛盾实证）——sensitivity 有有效行时首行无同名驱动卡 → 拒渲染，
    手标 first_var 与加冕不一致 → 告警（手标忽略）；sensitivity 缺失时回退手标、仍须恰 1 个；
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
    sens_items = _sensitivity_items(fill)
    if sens_items:
        crowned = sens_items[0]["name"]
        ck = _var_key(crowned)
        if not any(_var_key(d.get("name")) == ck for d in drivers):
            raise ValueError(
                f"sensitivity 首行（|impact| 降序）「{crowned}」在 drivers 中无同名驱动卡："
                "第一变量必须是 1-2 张驱动卡之一（v5.1.1 起拒渲染——驱动卡角标与龙卷风图"
                "由脚本同源加冕；对齐变量名或修正 impact 后重渲）")
        for d in firsts:
            if _var_key(d.get("name")) != ck:
                warns.append(f"drivers 手标 first_var「{d.get('name')}」与 sensitivity 首行（|impact| 降序）"
                             f"「{crowned}」不一致：v5.1.1 起第一变量由脚本按 sensitivity 加冕，"
                             "手标忽略（可删 first_var 键）")
    elif len(firsts) != 1:
        warns.append(f"drivers 的 first_var 应恰为 1 个（当前 {len(firsts)} 个）：第一变量只有一个"
                     "（sensitivity 缺失时角标与判词前缀仍由手标承载）")
    if re.search(r'<div class="info-card"><strong>为什么', fill.get("p0_html") or ""):
        warns.append("p0_html 仍含手写「为什么…」info-card：v4.11.3 起由 driver_verdict 判词横条承载，"
                     "请删除手写块（drivers 已填）")


def _check_sensitivity_units(fill: dict, warns: list) -> None:
    """v5.1.1：sensitivity.delta 量纲规范——变量自身变动幅度必须带单位：比例写 ±10%、
    百分点写 ±1pct（毛利率/利差类变量的变动是百分点，与脚本按 impact 生成的净利影响 %
    区分；影石创新报告同屏混排 1pct 与 20%、读者无从分辨两种量纲实证）。delta 非空但
    不合规 → 告警。"""
    for s in _sensitivity_items(fill):
        d = s["delta"]
        if d and not re.fullmatch(r"±?\d+(\.\d+)?([~–-]\d+(\.\d+)?)?(pct|%)", d.replace(" ", "")):
            warns.append(f"sensitivity[{s['name'][:8]}] delta「{d}」量纲不规范：变动幅度须带单位——"
                         "比例写 ±10%、百分点写 ±1pct（条端/坐标轴的净利影响 % 由脚本按 impact 生成）")

def _parse_pe_range(text):
    """cycle_stages.pe 声明区间解析：「60–216x」/「10-16」/「12x」→ (低, 高)（容 en dash/
    连字符/波浪号）；单值 → (v, v)；无数字 → None。先剔除四位年份——「2021 年 60x」
    的 2021 不是区间端点（热核审计 P2）。"""
    text = re.sub(r"(?:19|20)\d{2}", " ", str(text or ""))
    vals = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)[:2]]
    if not vals:
        return None
    return (vals[0], vals[0]) if len(vals) == 1 else (min(vals), max(vals))


def _series_month_pe(series):
    """price_history.series → [(年, 月, pe)]（m 可解析「YYYY-MM」才入列；pe 缺失记 None）。"""
    out = []
    for p in series or []:
        if not isinstance(p, dict):
            continue
        m = str(p.get("m") or "").strip()
        if len(m) >= 7 and m[:4].isdigit() and m[5:7].isdigit():
            out.append((int(m[:4]), int(m[5:7]), _num(p.get("pe"))))
    return out


def _check_cycle_stages(fill: dict, warns: list) -> None:
    """v4.11.3：周期阶段卡字段校验（cycle_stages，软告警迁移期——缺失不拒）。
    3-6 项、name ≤8 字、driver 显示宽 ≤48（灭孤字契约；宽度口径：CJK 计 2、ASCII 计 1）、
    period 必填；
    v5.1.2：条数/本轮判定与渲染同源——渲染跳过缺 name/period 的项
    （charts_misc.build_cycle_stages），被跳过的项单独告警不落图；
    current 恰 1 个升级为拒渲染（0 或 ≥2 个「本轮」徽章同屏即事实矛盾；
    本轮由分析师划段标注，脚本不加冕）；字段已填而 cycle_html 缺失 → 告警
    （阶段卡挂第 11 章条件块内，整章消失则卡无处显示，同 pe_history 绑定规则）；
    cycle_html 手写阶段表与字段的关系：字段未填 → 迁移告警；并存 → 重复告警；
    v5.1.3：period 格式校验——解析不出起止月份软告警「季K图阶段分界不落该段」
    （格式 YYYY/MM–YYYY/MM；与渲染同源 parse_stage_period，单源防漂移）；
    v5.4.0：校准锚（calib）三校验（全部软告警）——①calib:true 项须含 similarity/discount；
    ②分型属四型（周期/稳定价值/困境反转/成长·中速层）时 calib 项须 ≥2（v5.4.1 起含 0 个：
    0 个走「未标注校准锚（calib）」专用文案，非四型不告警）；
    ③窗口内对账：calib 时段落在 price_history 月份窗口内 → 窗口实测 PE 极值与声明区间
    端点比对（相对偏差 >25% 告警），窗口外/序列无 pe 跳过，全部未核验 → 汇总告警一条。"""
    stages = [s for s in fill.get("cycle_stages") or [] if isinstance(s, dict)]
    hand_table = re.search(r"<th[^>]*>\s*阶段\s*</th>", fill.get("cycle_html") or "")
    if not stages:
        if hand_table:
            warns.append("cycle_html 含手写阶段拆解表：v4.11.3 起请迁移 cycle_stages 字段"
                         "（name/period/pe/price/driver 显示宽 ≤48/current 恰 1 个），手写表格写法废止")
        return
    valid = [s for s in stages
             if str(s.get("name") or "").strip() and str(s.get("period") or "").strip()]
    for s in stages:
        if str(s.get("name") or "").strip() and str(s.get("period") or "").strip():
            continue
        tag = _plain_text(str(s.get("name") or "")).strip() or "?"
        warns.append(f"cycle_stages[{tag[:6]}] 缺 name 或 period：该项不落图（渲染跳过、"
                     "序号按落图项重排），请补齐或删除")
    if not valid:
        warns.append("cycle_stages 全部项缺 name 或 period：无一落图（渲染整体跳过），"
                     "请补齐或整字段删除（热核审计：此时 current 计数无意义，不硬拒）")
        if hand_table:
            warns.append("cycle_html 手写阶段表与 cycle_stages 字段并存（内容重复）：请删除手写表格")
        return
    if not 3 <= len(valid) <= 6:
        warns.append(f"cycle_stages 有效项 {len(valid)} 个（应 3-6 个阶段；缺 name/period 的项不落图）")
    curs = [s for s in valid if s.get("current")]
    if len(curs) != 1:
        raise ValueError(f"cycle_stages 的 current 应恰为 1 个（有效项中当前 {len(curs)} 个）："
                         "「本轮」只有一个——0 个或 2 个以上徽章同屏即事实矛盾（v5.1.2 起拒渲染）")
    for s in stages:
        tag = _plain_text(str(s.get("name") or "")).strip() or "?"
        short = tag[:6] + ("…" if len(tag) > 6 else "")
        period = str(s.get("period") or "").strip()
        if period and parse_stage_period(period) is None:
            warns.append(f"cycle_stages[{short}] period「{period[:14]}」解析不出起止月份："
                         "季K图阶段分界不落该段（格式 YYYY/MM–YYYY/MM）")
        if len(tag) > 8:
            warns.append(f"cycle_stages[{short}] name {len(tag)} 字 > 8（槽位契约）")
        driver_w = _disp_w(_plain_text(str(s.get("driver") or "")).strip())
        if driver_w > 48:
            warns.append(f"cycle_stages[{short}] driver 显示宽 {driver_w} > 48（槽位契约：超长必孤字折行，"
                         "压缩表述——demo 阶段 02「杀」字独占行实证；宽度口径：CJK 计 2、ASCII 计 1）")
    if not str(fill.get("cycle_html") or "").strip():
        warns.append("cycle_stages 已填但 cycle_html 缺失：阶段卡挂第 11 章条件块内，"
                     "整章不渲染则卡无处显示（同 pe_history/price_history 绑定规则）")
    if hand_table:
        warns.append("cycle_html 手写阶段表与 cycle_stages 字段并存（内容重复）：请删除手写表格")
    # v5.4.0 校准锚（calib）三校验（全部软告警；非四型 / 无有效项不受影响）
    calibs = [s for s in valid if s.get("calib")]
    for s in calibs:
        tag = _plain_text(str(s.get("name") or "")).strip() or "?"
        short = tag[:6] + ("…" if len(tag) > 6 else "")
        miss_keys = [k for k in ("similarity", "discount") if not str(s.get(k) or "").strip()]
        if miss_keys:
            warns.append(f"cycle_stages[{short}] calib:true 缺 {'/'.join(miss_keys)}：校准时段须写明"
                         "与当前时段的相似性（similarity：增速/规模/宏观背景）与规模折价（discount："
                         "当前利润更大时 PE 应更低）——否则「为何拿这几段校准」无据（v5.4.0 软约束）")
    # v5.4.1：四型零标记不再静默豁免（一个 calib 都不标 = 软约束失去观察意义）
    if _anchor_unanchored_type(fill) and len(calibs) < 2:
        if calibs:
            warns.append(f"cycle_stages 校准锚（calib:true）仅 {len(calibs)} 个（应 ≥2）：估值带校准"
                         "依赖 ≥2 个可比历史时段（scoring.md「三情景构建」PE 时段匹配）——"
                         "请在阶段卡标注 ≥2 个 calib 时段（首版软约束，观察一轮后升拒渲染）")
        else:
            warns.append("cycle_stages 未标注校准锚（calib）：本分型（估值带依赖历史 PE 时段锚）"
                         "的估值带须有 ≥2 个校准时段——在对应阶段加 \"calib\":true 并写 "
                         "similarity/discount（渲染「校准锚」角标；首版软约束，观察一轮后升拒渲染）")
    if calibs:
        pts = _series_month_pe((fill.get("price_history") or {}).get("series"))
        verified = 0
        for s in calibs:
            span = parse_stage_period(str(s.get("period") or "").strip())
            if span is None or not pts:
                continue   # period 解析失败已单独告警；无序列无从对账
            (y0, m0), (y1, m1) = span
            if (y1, m1) == (9999, 12):   # 「至今」开口 → 夹取到序列末月（与渲染同源规则）
                y1, m1 = max((y, m) for y, m, _pe in pts)
            inwin = [pe for y, m, pe in pts if (y0, m0) <= (y, m) <= (y1, m1)]
            pes = [pe for pe in inwin if pe is not None]
            dec = _parse_pe_range(s.get("pe"))
            if not inwin or not pes or dec is None:
                continue   # 窗口外 / 序列无 pe / 未写 PE 区间 → 跳过（不计入已核验）
            verified += 1
            lo, hi = dec
            bad = []
            if lo and abs(min(pes) - lo) / lo > 0.25:
                bad.append(f"下限 {lo:g}x vs 实测最低 {min(pes):g}x")
            if hi and abs(max(pes) - hi) / hi > 0.25:
                bad.append(f"上限 {hi:g}x vs 实测最高 {max(pes):g}x")
            if bad:
                tag = _plain_text(str(s.get("name") or "")).strip() or "?"
                short = tag[:6] + ("…" if len(tag) > 6 else "")
                warns.append(f"cycle_stages[{short}] calib 时段 PE 声明与 price_history 同窗口实测"
                             f"端点偏差 >25%（{'；'.join(bad)}）：校准时段声明须与取数窗口同源"
                             f"（E2 月线月末 PE）——请核对阶段 pe 或校准时段划段")
        if not verified:
            warns.append("cycle_stages 的 calib 时段均在取数窗口外（或窗口内无 PE 序列/未写 PE 区间）："
                         "校准声明未核验——请核对 price_history.series 的月份覆盖与阶段 pe 声明")


def _check_cycle_position(fill: dict, warns: list) -> None:
    """v5.2.0：当前周期位置刻度条（cycle_position，首版软告警——观察一轮后再升拒渲染）。
    周期股（stock_type 含「周期」）且 cycle_html 存在 → 字段必答且五键齐全
    （stage/price_pctile/capacity/stock_spread/implication——「上行期」无刻度的云铝实证）；
    stage 与 cycle_stages 本轮项不一致 → 告警（当前阶段只许一个说法）。"""
    cp = fill.get("cycle_position")
    is_cyc = "周期" in str(fill.get("stock_type") or "")
    has_cycle_html = bool(str(fill.get("cycle_html") or "").strip())
    if not isinstance(cp, dict) or not cp:
        if is_cyc and has_cycle_html:
            warns.append("cycle_position 未填：周期股当前位置刻度条为必答（v5.2.0）——五键："
                         "stage/price_pctile/capacity/stock_spread/implication；"
                         "首版软约束，下轮升拒渲染")
        return
    for k in ("stage", "price_pctile", "capacity", "stock_spread", "implication"):
        if not str(cp.get(k) or "").strip():
            warns.append(f"cycle_position.{k} 缺失：阶段名 + 三件套刻度 + 位置含义句须五键齐全")
    curs = [s for s in (fill.get("cycle_stages") or [])
            if isinstance(s, dict) and s.get("current")
            # 与 _check_cycle_stages/渲染同源：缺 name/period 的项不落图，不参与本轮比对
            and str(s.get("name") or "").strip() and str(s.get("period") or "").strip()]
    stage = str(cp.get("stage") or "").strip()
    if curs and stage:
        cur_name = _plain_text(str(curs[0].get("name") or "")).strip()
        if cur_name and cur_name not in stage and stage not in cur_name:
            warns.append(f"cycle_position.stage「{stage[:12]}」与 cycle_stages 本轮「{cur_name[:12]}」"
                         "不一致：当前阶段只许一个说法")


def _check_earnings_stability(fill: dict, warns: list) -> None:
    """v5.2.0：盈利波动性软锚（earnings_stability，软告警——本轮只展示不进定档）。
    sigma 照抄 E3「扣非增速波动」行（禁手算）：按 fin_trend 扣非柱（与 E3 同源）复算比对，
    偏差 >0.15pct 告警（照抄纪律的落盘比对同款）；verdict 缺失 → 告警；
    peer_median 可空（角标只显 σ，不告警）。
    找不到扣非柱或复算不可用（增速点 <3/亏损基数跳过）→ 补「无法复算」软告警——
    与渲染层「无扣非面板兜底挂 section-tag，不静默丢」对称，照抄纪律不做免检通道。
    debt: 比对口径天花板——E3 行用 API 全精度值，fin_trend 柱为展示舍入值，扣非仅个位数
    亿的小市值公司舍入可使 σ 偏移 >0.15pct，正确照抄也会误报；误报增多再放宽容差。"""
    es = fill.get("earnings_stability")
    if not isinstance(es, dict) or not es:
        return
    sig = _num(es.get("sigma"))
    if sig is None:
        warns.append("earnings_stability.sigma 缺失或非数字：照抄 E3「扣非增速波动」行"
                     "（E3 行标「不适用/数据不足」时整字段勿填）")
        return
    if not str(es.get("verdict") or "").strip():
        warns.append("earnings_stability.verdict 缺失：4.6 判词引用处须有一句定性结论")
    ft = fill.get("fin_trend") or {}
    dedt_bar = next((b for p in ft.get("panels") or [] if isinstance(p, dict)
                     for b in p.get("bars") or []
                     if isinstance(b, dict) and "扣非" in str(b.get("name") or "")), None)
    if dedt_bar is None:
        warns.append("earnings_stability 已填但 fin_trend 无扣非柱可复算：请人工核对 E3 行照抄值")
        return
    ref, n_g, _drop = growth_sigma(dedt_bar.get("values"))
    if ref is None:
        warns.append("earnings_stability 已填但 fin_trend 扣非柱复算不可用（增速点 <3 或亏损基数）："
                     "请人工核对 E3 行照抄值")
    elif abs(ref - sig) > 0.15:
        warns.append(f"earnings_stability.sigma（{sig:g}）与 fin_trend 扣非柱复算 σ"
                     f"（{ref:g}，{n_g} 个增速点）偏差 >0.15pct：照抄 E3 行，禁手算")


def _check_dcf(fill: dict, warns: list) -> None:
    """v4.11.3：DCF 双卡字段校验（dcf，软告警迁移期——缺失不拒）。
    强制分型（v5.4.1 归一判定）：**成长型·中速层/未声明 high**（含旧名「稳健成长股」）与
    **稳定价值（非金融）**缺 dcf → 告警；成长型·高速层（含旧名「快速成长」）走远期 PE 折现、
    金融类稳定价值走 PB-ROE/DDM，均不强制。填了 → 八键齐全性 + verdict ≥40 字；
    valuation_html 仍手写 DCF 表 → 重复告警。"""
    d = fill.get("dcf")
    if not isinstance(d, dict) or not d:
        st = str(fill.get("stock_type") or "")
        std, legacy_tier, _legacy = _normalize_stock_type(st)
        gt = str(fill.get("growth_tier") or "").strip().lower()
        tier = gt if gt in ("high", "mid") else legacy_tier
        if std == "成长型" and tier != "high":
            warns.append("dcf 字段未填：成长型（中速层 / 未声明 high）分型 DCF 强制三行由 dcf 字段"
                         "承载（v4.11.3 起；原「稳健成长」改名后于 v5.4.1 重新对齐；"
                         "value/fcf0/growth_5y/g_perp/wacc/net_cash/implied_g/verdict 八键，"
                         "现价比价脚本算，valuation_html 不再手写 DCF 表）")
        elif std == "稳定价值" and not re.search(r"(?<!非)金融|银行|保险|券商", st):
            # v5.1.5（热核 P0-6，用户拍板补校验）：fill-schema/SKILL 承诺「稳定价值（非金融）
            # 必填」此前零执行——与成长型·中速层同态（软告警）；金融类稳定价值股豁免
            # （银行/保险走 PB-ROE/DDM，见 scoring.md）
            warns.append("dcf 字段未填：稳定价值（非金融）分型 DCF 双卡由 dcf 字段承载"
                         "（v5.1.5 起；金融类稳定价值股豁免）")
        return
    missing = [k for k in ("value", "fcf0", "growth_5y", "g_perp", "wacc", "net_cash",
                           "implied_g", "verdict") if not str(d.get(k) or "").strip()]
    if missing:
        warns.append(f"dcf 缺键 {missing}：八键应齐全（value/implied_g/verdict 缺一时整卡不生成）")
    for k in ("value", "implied_g"):
        raw = str(d.get(k) or "").strip()
        if raw and _num(raw) is None:
            warns.append(f"dcf.{k}「{raw}」非空但不可解析为数值：渲染要求数值，"
                         "否则双卡整体不生成（v5.1.2——此前校验只查非空，整卡静默消失）")
    verdict_len = len(_plain_text(str(d.get("verdict") or "")).strip())
    if 0 < verdict_len < 40:
        warns.append(f"dcf.verdict {verdict_len} 字 < 40：判词须含隐含 g 对照与互证结论"
                     "（与现价比价由脚本算后自动拼接，不用手写）")
    vh = fill.get("valuation_html") or ""
    if "<table" in vh and re.search(r">[^<]*DCF", vh):
        warns.append("valuation_html 仍含手写 DCF 表：v4.11.3 起 DCF 由 dcf 字段承载，请删除手写表")


# ---------------- v5.0 第 3 章「最新报告期透视」period_track 校验 ----------------
_PERIOD_LABEL_KEYS = ("period", "sq_label", "sq_prev_label")
_PERIOD_NUM_KEYS = ("rev", "np", "np_dedt", "ocf", "sq_rev", "sq_np", "sq_prev_rev", "sq_prev_np",
                    "sq_dedt", "sq_prev_dedt", "sq_ocf", "sq_prev_ocf")
_PERIOD_YOY_KEYS = ("rev_yoy", "np_yoy", "np_dedt_yoy", "ocf_yoy", "sq_rev_yoy", "sq_np_yoy",
                    "sq_dedt_yoy", "sq_ocf_yoy")
_PERIOD_BAND_KEYS = ("band_np", "band_rev")


def _period_time_pct(period: str):
    """报告期 → 时间进度（中报/H1/上半年 .50 / 一季 .25 / 三季 .75）；无法解析 → None。
    不写裸「半年」——「近半年」类表述会误命中（热核 P1-2：conftest 的 2026一季/三季 标签
    曾认不出，对账对一季/三季期整体失效）。"""
    if re.search(r"中报|H1|上半年", period, re.I):
        return 0.5
    if re.search(r"一季报|一季度|一季|Q1|1季报", period, re.I):
        return 0.25
    if re.search(r"三季报|三季度|三季|Q3|3季报", period, re.I):
        return 0.75
    return None

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
    ref = _quote_ref(fill)   # 落盘读不到：_check_quote_consistency 已硬拒，这里降级跳过比对
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
                if v not in _PERIOD_VERDICTS:
                    raise ValueError(f"period_track.{vk} 取值非法: {v!r}——判词四选一："
                                     f"{'/'.join(_PERIOD_VERDICTS)}（模型按节奏带+完成度判定）")
            elif not is_annual and _num(pt.get(ak)) is not None:
                warns.append(f"period_track.{vk} 未填：章内该指标判词将显示「无法判定」（判词四选一 "
                             f"{'/'.join(_PERIOD_VERDICTS)}，由模型按节奏带与完成度判定）")
        # v5.1.2：判词与完成度机械对账（分母与子弹图同源：一致预期优先、缺则经营目标）
        t_pct = _period_time_pct(str(pt.get("period") or ""))
        if t_pct is not None and not is_annual:
            for vk, ak, gk, ck in (("verdict_rev", "rev", "goal_rev", None),
                                   ("verdict_np", "np", "goal_np", "consensus_np")):
                v = str(pt.get(vk) or "").strip()
                r = _period_ratio(pt, ak, gk, ck)
                if not v or r is None:
                    continue
                if v == "超前" and r < t_pct - 0.15:
                    warns.append(f"period_track.{vk}=超前 但完成度 {r * 100:.0f}% 低于时间进度 "
                                 f"{t_pct * 100:.0f}%−15pct（分母=一致预期/经营目标，与子弹图同源；"
                                 "判词与数据矛盾请复核，v5.1.2）")
                if v == "滞后" and r > t_pct + 0.15:
                    warns.append(f"period_track.{vk}=滞后 但完成度 {r * 100:.0f}% 高于时间进度 "
                                 f"{t_pct * 100:.0f}%+15pct（分母=一致预期/经营目标，与子弹图同源；"
                                 "判词与数据矛盾请复核，v5.1.2）")
        for gk in ("goal_rev", "goal_np"):
            raw = pt.get(gk)
            if raw is None or not str(raw).strip():
                continue
            gv = _strict_num(raw)
            if gv is None or gv <= 0:
                raise ValueError(f"period_track.{gk} 必须为正数（亿元；年报「经营计划」段披露口径，"
                                 f"未披露请填 null），实际: {raw!r}")
        if is_annual:
            extra = [k for k in ("industry_html", "forecast_html", "note_html", "summary_html")
                     if str(pt.get(k) or "").strip()]
            if extra:
                warns.append(f"period_track.is_annual=true（年报期第 3 章整章消失）：{'/'.join(extra)} "
                             f"已填内容不会渲染——年报期请省略这些字段，或留待下一季报期使用")
        note_len = len(_plain_text(str(pt.get("note_html") or "")))
        if note_len > 120:
            warns.append(f"period_track.note_html 纯文本 {note_len} 字 > 120：口径提示定位 ≤3 句，"
                         f"展开论证归各章")
        summary_len = len(_plain_text(str(pt.get("summary_html") or "")))
        if summary_len > 100:
            warns.append(f"period_track.summary_html 纯文本 {summary_len} 字 > 100：进度小结定位 ≤2 句，"
                         f"展开论证归 4.4/5.1/9 章")
