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


def _check_valuation_scenarios(fill: dict) -> None:
    """valuation 结构化三情景必填且完整（每情景：profit+PE 区间 或 mcap 市值区间 + horizon）。"""
    v = fill.get("valuation")
    if not isinstance(v, dict) or not v.get("scenarios"):
        raise ValueError("valuation 为必填字段：结构化三情景假设（shares / horizon / scenarios），"
                         "目标价与估值分全部由脚本计算")
    shares_n = _num(v.get("shares"))
    if shares_n is None or shares_n <= 0:
        raise ValueError("valuation.shares 缺失、非法或 ≤0（总股本，亿股，必须为正数）")
    skeys = set()
    modes = set()
    for s in v.get("scenarios") or []:
        skeys.add(str(s.get("key") or "").lower())
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
        else:
            if not has_profit:
                raise ValueError(f"valuation.scenarios[{slab}] 缺净利假设（profit，归母净利亿元）"
                                 f"或目标市值区间（mcap: [低, 高]，亿元）")
            if pe_lo is None or pe_hi is None:
                raise ValueError(f"valuation.scenarios[{slab}] 缺 PE 区间（pe: [低, 高]）")
            # 与 mcap 侧对称的区间校验：倒挂（高<低）或非正值一律拒渲染
            if pe_lo <= 0 or pe_hi < pe_lo:
                raise ValueError(f"valuation.scenarios[{slab}] PE 区间非法（pe: [低, 高]，需 0<低≤高）")
            modes.add("pe")
        if not str(s.get("horizon") or v.get("horizon") or "").strip():
            raise ValueError(f"valuation.scenarios[{slab}] 缺时间维度（horizon，可放情景级或 valuation 级）")
    if len(modes) > 1:
        raise ValueError("valuation.scenarios 口径混用：profit+pe 与 mcap 三情景必须统一口径")
    if not {"pess", "base", "opt"} <= skeys:
        raise ValueError(f"valuation.scenarios 必须含 pess/base/opt 三情景，当前只有: {sorted(skeys)}")


def _check_chart_fields(fill: dict) -> None:
    """v4.9 必填图字段硬校验：fin_trend（3.4 小图墙，替手写年表）/ growth_plot（4.1 增长图）。
    两字段数据均来自标准采集（E3 年表 / E5 一致预期），缺失=空心趋势章节 → 拒渲染。
    growth_plot 豁免：stock_type 含「未盈利/管线」（净利无意义）。"""
    ft = fill.get("fin_trend")
    if not isinstance(ft, dict):
        raise ValueError('fin_trend 为必填字段（v4.9 起 3.4 财务健康年表由脚本图墙替代）：'
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
            raise ValueError('growth_plot 为必填字段（v4.9 起 4.1 利润增长配历史+预测图）：'
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
            raise ValueError("thesis_html 三情景手写价与 valuation 计算值不一致（相对偏差>2% 且绝对差>0.1）："
                             + "；".join(bad)
                             + f"。手写={ {k: span_prices[k] for k in ('pess','base','opt')} }，"
                             + f"脚本={ {k: round(cmap.get(k, 0), 2) for k in ('pess','base','opt')} }")


def _check_content_floor(fill: dict) -> None:
    """内容地板（空心章节一律拒渲染）+ 表格来源标注数必须 ≥ 表格数。"""
    concl_len = len(_plain_text(fill.get("conclusion_html")))
    if concl_len < 120:
        raise ValueError(f"conclusion_html 纯文本仅 {concl_len} 字 < 120：核心结论四卡不能为空洞"
                         f"（v4.9.1 补充修订四：四卡 ul 短列表化，地板由 200 下调）")
    for name, need in (("l1_html", 6), ("l3_html", 3)):
        # 与下方字数地板同口径（re.split），避免 class="dim-block x" 之类写法两口径打架
        n = len(re.split(r'<div class="dim-block">', fill.get(name) or "")) - 1
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
    thin_reject, thin_warn = [], []
    for field, layer in (("l1_html", "L1"), ("l3_html", "L3")):
        blocks = re.split(r'<div class="dim-block">', fill.get(field) or "")[1:]
        for (key, _l, name, _dw), blk in zip([d for d in DIMS if d[1] == layer], blocks):
            blen = len(_plain_text(blk))
            if blen < 40:
                thin_reject.append(f"{name} 仅 {blen} 字")
            elif blen < 80:
                thin_warn.append(f"{name} 仅 {blen} 字")
            sv = (fill.get("scores") or {}).get(key)
            if sv is None:
                continue
            sv = float(sv)
            if (sv >= 8 or sv <= 3) and blen < 50:
                warns.append(f"{name} 得分 {sv:g}（极端分）但 dim-block 纯文本仅 {blen} 字 < 50："
                             f"≥8 或 ≤3 必须配具体量化依据")
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
                         f"请改用章节编号/名称（第 3 章 / 3.4 / 第 5 章风险评估）")


def _check_writing_discipline(fill: dict, warns: list) -> None:
    """v4.7.1 写作纪律告警（东方电气反馈）：四拍挤段 / 3 年趋势三年并排 / pe_history 无第 10 章承载。"""
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
    # pe_history 图已挂第 10 章（v4.7.1）：cycle_html 缺失 → 整章删除，图无处显示
    if (fill.get("pe_history") or {}).get("hist_lo") is not None and not (fill.get("cycle_html") or "").strip():
        warns.append("pe_history 已填但 cycle_html 缺失：PE 历史带图挂第 10 章，整章被删后图不显示"
                     "——v4.7.1 起四类分型（周期/稳健成长/稳定价值/困境反转）应写第 10 章，或删除 pe_history")


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
    """quote 缺失 → 告警不拒（存量 fill 兼容）；quote 存在但不一致已在 _check_quote_consistency 拒渲染。"""
    if not fill.get("quote"):
        warns.append("quote 字段缺失：现价/PE(TTM) 无 em_fetch --out 落盘防伪（神华 601088 事故修复项）"
                     "——新报告应在 em_fetch 时加 --out 落盘，并在 fill 回填 quote.source_file")


def _check_optional_charts(fill: dict, warns: list) -> None:
    """v4.8 可选图字段纪律：业务构成占比和 / 产业链两端 / 发丝图与第 10 章绑定 / 户数期数。"""
    seg = fill.get("segments") or {}
    items = seg.get("items") or []
    if items:
        s = sum(_num(it.get("rev_pct")) or 0 for it in items)
        if abs(s - 100) > 5:
            warns.append(f"segments 收入占比合计 {s:.1f}% 偏离 100%：请核对是否漏列分部"
                         f"（E6 各分部占比之和应≈100%，若有「其他」项请补列）")
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
        warns.append("price_history 已填但 cycle_html 缺失：股价/PE 发丝图挂第 10 章，整章被删后图不显示"
                     "——与 pe_history 同规则（v4.7.1 绑定关系）")
    holders = fill.get("holders") or []
    if holders and len(holders) < 3:
        warns.append("holders 有效点 <3：户数趋势图不生成（E4 默认返回近 8 期，请回填 ≥3 期）")
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
    概念必须在 pe_history（第 10 章同源数据，与 E1 落盘 pe_p25/pe_p75、历史带同口径）有对应字段
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
    """v4.9.1 补充修订二：3.5 治理与资本配置分块单行化——整块 <p> 恰为 2 个
    （判词段 + 评分末拍段）；trig 行后另起 <p> 正文 → 告警（论据应内联进 .trig-mt）。
    未用 trig-strip 的旧存量 fill 不打扰。
    补充修订四：同款清单推广到 3.3 护城河 / 4.3 催化剂（4.2 为可选形态不强制），
    <p> 恰为 2 规则同步覆盖（4.3 评分段可省，校验只看 >2）。"""
    for field, tags in (("l1_html", ("3.3", "3.5")), ("l3_html", ("4.3",))):
        for blk in re.split(r'<div class="dim-block">', fill.get(field) or "")[1:]:
            tag = next((t for t in tags if t in blk), None)
            if tag is None or "trig-strip" not in blk:
                continue
            np = len(re.findall(r"<p[ >]", blk))
            if np > 2:
                warns.append(f"{tag} 维度块含 {np} 个 <p>（应恰为 2：判词段+评分末拍段）："
                             f"trig 行后不要另起 <p> 正文，论据压进 .trig-mt 一句内联（fill-schema 条款）")


def _check_peers_orientation(fill: dict, warns: list) -> None:
    """v4.9.1 补充修订二：同业两表公司强制行标题——目标公司蓝色加粗应标在行首格；
    蓝 style 落在 <th> 表头 = 误写成「公司=列」旧方向 → 告警。"""
    peers = fill.get("peers_html") or ""
    if re.search(r"<th[^>]*style\s*=\s*[\"'][^\"']*color\s*:\s*" + re.escape(_C_BLUE), peers, flags=re.I):
        warns.append("peers_html 目标公司蓝色加粗落在 <th> 表头（写成了公司=列旧方向）："
                     "当前指标表与趋势表应公司=行标题，目标公司蓝色加粗标在行首格（fill-schema peers 规则）")


def _check_peers_bestworst(fill: dict, warns: list) -> None:
    """v4.10：同业当前指标表每列最优/最差标注（cell-best/cell-worst）缺失告警——
    工行 09-11 报告两表零标注实证（软规则无门禁就不会被遵守）。matrix-table 兜底形态不适用。"""
    peers = fill.get("peers_html") or ""
    if ("<table" in peers and "matrix-table" not in peers
            and "cell-best" not in peers and "cell-worst" not in peers):
        warns.append("peers_html 当前指标表无 cell-best/cell-worst 最优/最差标注："
                     "每列按指标方向性各标一格（低为优：PE/PB/负债率；高为优：ROE/增速等），"
                     "规则见 fill-schema「表格」节")


def _check_price_history_pe(fill: dict, warns: list) -> None:
    """v4.10：price_history 的 pe 过半缺失 → 图只画股价线而标题仍挂 PE(TTM)（图文不符）。
    A 股 E2 月线自带月末 PE(TTM) 序列应照抄——工行 09-11 报告 12 个点 pe 全缺实证。"""
    ph = fill.get("price_history") or {}
    series = ph.get("series") or []
    if not series:
        return
    n_pe = sum(1 for p in series if isinstance(p, dict) and p.get("pe") is not None)
    if n_pe * 2 < len(series):
        warns.append(f"price_history 的 pe 字段仅 {n_pe}/{len(series)} 点有效（过半缺失）："
                     "PE(TTM) 折线将不生成——A股 E2 月线输出自带月末 PE(TTM) 序列，照抄即可（禁手估）；"
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


def validate_content(fill: dict, calc: dict = None) -> None:
    """内容级校验（成稿前自动复核，借鉴 equity-research 检查器思路）。
    硬错误（拒渲染）：分数越界、valuation_inputs 缺失、valuation 三情景字段不全、
    fin_trend/growth_plot 必填图字段缺失或结构非法（v4.9）、
    红灯熔断缺"不建议参与"、thesis 手写价与脚本计算值不一致、内容地板（空心章节）、
    表格缺来源标注；其余 → stderr 告警（P1），模型看到即修正。
    calc 为 compute_valuation 结果（thesis 一致性校验用）。"""
    _check_price_date(fill)
    _check_quote_consistency(fill)
    _check_score_ranges(fill)

    _check_valuation_inputs(fill)
    _check_valuation_scenarios(fill)
    _check_chart_fields(fill)

    _check_red_flag_breaker(fill)
    _check_thesis_consistency(fill, calc)
    _check_content_floor(fill)
    _check_l4_form(fill)
    _check_cn_placeholder(fill)

    warns = []
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
    _check_price_history_pe(fill, warns)
    _check_prev_fields(fill, warns)
    _check_review_miss_diagnostics(fill, warns)
    _check_misc_required(fill, warns)
    _check_quote_present(fill, warns)
    _check_optional_charts(fill, warns)
    for w in warns:
        print(f"⚠️ 内容校验: {w}", file=sys.stderr)
