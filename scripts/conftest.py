#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""conftest.py — scripts/ 渲染测试共享样板（pytest 自动加载，测试文件亦可 import）

收编三份重复样板：
- minimal_fill / _dim / _calc / expect_valueerror：合法 fill 构造与拒渲染断言
- write_fill / render_workspace / render_fill：临时 fill 落盘 → render → 读回 HTML
- capture_stderr / validate_stderr：stdout/stderr 捕获（告警路径断言）
- period_fill（v5.0）：第 3 章「最新报告期透视」fill（minimal_fill + period_track +
  quote.source_file 会话级临时落盘参照，h1/q1/q3/annual 四态）

拆分自 test_render_core.py（v4.10.2），逻辑逐字沿用，仅作共享化。
"""
import contextlib
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_report as R


def _dim(text):
    return f'<div class="dim-block"><p>{text}</p></div>'


# minimal_fill/full_fill 共用的通用维度块文本与 4.5 治理紧凑块
_LONG_TEXT = "该维度分析：公司基本面稳健，数据支撑充分，论据详实可靠，行业地位稳固，具备长期参考价值。"
# v4.9.1 补充修订二：第 5 块用 4.5 治理 trig-strip 紧凑形态（单行 trig + 评分依据链）
_L1_GOV_BLOCK = ('<div class="dim-block"><div class="dim-header">'
                 '<span class="dim-name">4.5 治理与资本配置</span><span class="dim-weight">7%</span>'
                 '<span class="score-line" style="margin-left:auto;margin-bottom:0;">'
                 '<span class="badge badge-green">7.5</span></span></div>'
                 '<p><strong>判词：</strong>股权集中、激励覆盖充分，近三年资本运作记录干净，无质押风险。</p>'
                 '<div class="trig-strip">'
                 '<div class="trig"><span class="trig-dot hit"></span>'
                 '<span class="trig-cond">股权与控制权</span>'
                 '<span class="trig-mt">控股股东持股 34.2%，无质押冻结</span>'
                 '<span class="trig-status hit">正面</span></div>'
                 '<div class="trig"><span class="trig-dot hit"></span>'
                 '<span class="trig-cond">管理层与激励</span>'
                 '<span class="trig-mt">2024 限制性股票覆盖核心技术人员 312 人</span>'
                 '<span class="trig-status hit">正面</span></div>'
                 '<div class="trig"><span class="trig-dot miss"></span>'
                 '<span class="trig-cond">风险点</span>'
                 '<span class="trig-mt">关联交易占比 6.8%（高于同业 3% 均值）</span>'
                 '<span class="trig-status miss">关注</span></div></div>'
                 '<p><strong>评分：</strong>7.5——基准 7.0，股权/激励两项正面 +0.5；'
                 '关联交易关注项不扣分但列入 14 章跟踪。</p></div>')


def minimal_fill(**over):
    """最小合法 fill（能过 compute_scores + validate_content + compute_valuation_score）。"""
    long_text = _LONG_TEXT
    fill = {
        "company": "测试股份", "code": "600000", "date": "2026-08-27",
        "subtitle": "测试行业 · 测试定位",
        "price": "10", "mcap": "1000", "pe_ttm": "11",
        "price_sub_html": "—", "mcap_sub": "—", "pe_sub": "—",
        "horizon": "12个月", "target_range": "10-12", "target_sub_html": "—",
        "thesis_html": ('测试论点与关键证据。三情景目标价 '
                        '<span class="scenario-pess">7.2</span>/'
                        '<span class="scenario-base">11</span>/'
                        '<span class="scenario-opt">15.6</span> 元，结论：观察。'),
        "conclusion_html": (
            '<div class="concl-grid">'
            '<div class="concl-card"><div class="concl-head">关键优势</div>' + "优势证据。" * 20 +
            '<div class="concl-ref">详见 <a href="#s4">4 公司本质</a></div></div>'
            '<div class="concl-card"><div class="concl-head">关键弱点</div>' + "弱点证据。" * 20 +
            '<div class="concl-ref">详见 <a href="#s6">6 风险评估</a></div></div>'
            '<div class="concl-card"><div class="concl-head">当前市场认知</div>' + "卖方假设。" * 15 +
            '<div class="concl-ref">详见 <a href="#s9">9 市场预期差</a></div></div>'
            '<div class="concl-card"><div class="concl-head">核心投资逻辑</div>' + "论点证伪。" * 15 +
            '<div class="concl-ref">详见 <a href="#s8">8 估值与安全边际</a></div></div>'
            '</div>'),
        "p0_html": "<p>关键驱动分析。</p>",
        # v4.9.1 补充修订二：第 5 块用 4.5 治理 trig-strip 紧凑形态（单行 trig + 评分依据链）
        "l1_html": "".join(_dim(long_text) for _ in range(5)) + _L1_GOV_BLOCK,
        "l3_html": "".join(_dim(long_text) for _ in range(3)),
        # v4.9.1 补充修订二：l4 章首红灯 hero 三卡（pass=通过）；
        # v4.10：黄灯无扣分只写核查兜底句（不列空行表）+ 损失预演改固定三联卡
        "l4_html": ('<div class="flag-hero">'
                    '<div class="flag-hero-card pass"><div class="fh-name">a 财务造假与极高杠杆</div>'
                    '<div class="fh-verdict">通过</div>'
                    '<div class="fh-desc">审计标准无保留；商誉/净资产 3.2%；控股股东无质押；非 ST</div></div>'
                    '<div class="flag-hero-card pass"><div class="fh-name">b 立案调查与重大违规</div>'
                    '<div class="fh-verdict">通过</div>'
                    '<div class="fh-desc">近三年无立案调查/重大违规披露（公告检索）</div></div>'
                    '<div class="flag-hero-card pass"><div class="fh-name">c 主营不可逆衰退</div>'
                    '<div class="fh-verdict">通过</div>'
                    '<div class="fh-desc">核心产品收入连续增长，无被禁/被主要市场抛弃迹象</div></div>'
                    '</div>'
                    '<p>黄灯扣分：无——四类（a 交易与股东行为 / b 行业与政策环境 / '
                    'c 盈利与财务质量 / d 经营与公司治理）逐项核查无扣分。</p>'
                    '<p><strong>损失预演（假设两年后这笔投资亏损 30%）：</strong></p>'
                    '<div class="pm-grid">'
                    '<div class="pm-card"><div class="pm-head">最可能的亏损故事</div>'
                    '<p>商品价格深跌叠加产能释放不及预期，利润腰斩后估值随之下杀。</p></div>'
                    '<div class="pm-card"><div class="pm-head">与红黄灯清单的重合度</div>'
                    '<p>与黄灯 b 类（行业周期）高度重合，是同一回事的概率高。</p></div>'
                    '<div class="pm-card"><div class="pm-head">清单外新风险</div>'
                    '<p>未识别出清单外新风险：资产负债表干净，无重大单一客户依赖。</p></div>'
                    '</div>'),
        "valuation_method": "PE历史时段匹配法", "stock_type": "周期股",
        "valuation": {"shares": 100, "horizon": "12个月", "scenarios": [
            {"key": "pess", "label": "悲观", "trigger": "下行", "profit": 80, "pe": [8, 10]},
            {"key": "base", "label": "基础", "trigger": "中性", "profit": 100, "pe": [10, 12]},
            {"key": "opt", "label": "乐观", "trigger": "上行", "profit": 120, "pe": [12, 14]},
        ]},
        "valuation_inputs": {"pe_ttm": 11, "pe_band": [10, 12], "div_yield": 2, "risk_free": 1.7},
        "valuation_html": "<p>估值方法说明。</p>",
        "gap_tier": "B", "gap_html": "<p>预期差。</p>",
        "peers_meta": "—",
        "peers_html": ('<div class="table-scroll"><table class="freeze-first">'
                       '<tr><th>公司</th><th>PE(TTM)</th><th>ROE</th></tr>'
                       '<tr><td style="color:#4a6fa5;font-weight:700;">测试股份</td>'
                       '<td class="cell-best">11</td><td class="cell-best">14%</td></tr>'
                       '<tr><td>同业甲</td><td class="cell-worst">25</td><td>9%</td></tr>'
                       '</table></div>'
                       '<span class="source">数据来源：测试</span>'),
        "next_review": "2026-11-27",
        "dash_html": ('<div class="table-scroll"><table class="dash-table freeze-first">'
                      '<tr><th>指标</th><th>当前值</th><th>触发阈值</th><th>触发后操作</th>'
                      '<th>数据来源</th><th>更新频率</th></tr>'
                      '<tr><td>毛利率</td><td>34%</td><td>≥36%</td>'
                      '<td>加仓至标配（需要一段足够长的操作说明文字来验证长文列换行样式）</td>'
                      '<td>E3 年表</td><td>季度</td></tr></table></div>'
                      '<span class="source">数据来源：测试</span>'),
        "position_html": "<p>时机判定与决策逻辑。" * 12 + "</p>",
        "scores": {"1A": 7, "1B": 7, "1C": 7, "1D": 7, "1E": 7, "1F": 7,
                   "3A": 7, "3B": 7, "3C": 7},
        "timing_scores": {"筹码面": 5, "技术面": 5},
        "yellow_deductions": [],
        # v4.8 可选图字段：12 章股东户数趋势（v4.9.1 起移至章首）；golden 覆盖模板新顺序
        "holders": [{"date": "2025-03-31", "num": 188153, "chg": None},
                    {"date": "2025-06-30", "num": 175200, "chg": -6.9},
                    {"date": "2025-09-30", "num": 160800, "chg": -8.2},
                    {"date": "2025-12-31", "num": 152300, "chg": -5.3}],
        # v4.9 必填图字段：4.4 财务趋势图墙（组合面板）+ 5.1 利润增长图
        # v4.9.1 形态：归母净利面板带扣非第二柱；第 4 面板为纯线周转天数面板
        "fin_trend": {"years": ["2021", "2022", "2023", "2024", "2025"], "panels": [
            {"title": "营收 × 毛利率",
             # v5.1.2：数值成比例化（归母净利末年 93 亿 ≈ base.profit 100 ÷ (1+7.5%)，
             # 原 11 亿 vs base.profit 100 亿 → growth 换算对账恒定误报 809% 越界，热核 P2-1）
             "bars": [{"name": "营收", "unit": "亿", "values": [800, 850, 880, 920, 950]}],
             "lines": [{"name": "毛利率", "pct": True, "values": [30, 31, 32, 33, 34]}]},
            {"title": "归母净利+扣非净利 × 净利率 × ROE",
             "bars": [{"name": "归母净利", "unit": "亿", "values": [80, 84, 88, 91, 93]},
                      {"name": "扣非净利", "unit": "亿", "values": [75, 79, 83, 86, 88]}],
             "lines": [{"name": "净利率", "pct": True, "values": [10, 9.9, 10, 9.9, 9.8]},
                       {"name": "ROE", "pct": True, "values": [12, 13, 14, 14, 14]}]},
            {"title": "经营现金流+自由现金流 × 现金含量",
             "bars": [{"name": "经营现金流", "unit": "亿", "values": [10, 11, 12, 12, 13]},
                      {"name": "自由现金流", "unit": "亿", "values": [7, 8, 9, 9, 10]}],
             "lines": [{"name": "现金含量", "values": [1.2, 1.1, 1.0, 1.05, 1.1],
                        "threshold": 0.7}]},
            {"title": "运营资金周转天数",
             "lines": [{"name": "应收账款周转天数", "values": [65, 48, 62, 73, 60]},
                       {"name": "存货周转天数", "values": [122, 98, 96, 97, 120]}]},
        ]},
        "growth_plot": {"hist": [
            {"y": "2022", "rev": 10.0, "np": 12.5},
            {"y": "2023", "rev": 9.1, "np": 11.1},
            {"y": "2024", "rev": 4.2, "np": 5.0},
            {"y": "2025", "rev": 4.0, "np": 4.8}],
            "fcst": [{"y": "2026E", "np_lo": 4, "np_hi": 8, "np_consensus": 6.0}]},
    }
    fill.update(over)
    return fill


def full_fill(**over):
    """全功能 fill（golden 快照专用，v4.10.2）：cycle/review/peers_plot/sensitivity/segments/
    chain/triggers/consensus/price_history/pe_history/prev 全开——罩住第 11/13 章与
    可选 builder（segments/chain/peers_plot/tornado/triggers/pe_band/price_history/哑铃），
    minimal_fill 只罩主干。图形字段锚点全在位（无「缺锚点」告警）；内容类存量告警
    （thesis 薄/dim 薄/peers_meta 占位/quote 缺失）继承自 minimal_fill，与本 fixture 无关）。"""
    dims = [_dim(_LONG_TEXT) for _ in range(5)]
    dims[0] += "<!--SEGMENTS-->"   # 4.1 后原位挂业务构成图
    dims[1] += "<!--CHAIN-->"      # 4.2 后原位挂产业链图
    dims[3] += "<!--FIN_TREND-->"  # 4.4 块内原位挂财务趋势图墙
    l3 = _dim(_LONG_TEXT) + "<!--GROWTH-->" + "".join(_dim(_LONG_TEXT) for _ in range(2))
    months = []
    for y in (2023, 2024, 2025):
        for m in range(1, 13):
            # v5.0：补 OHLC 走季K 主形态分支——罩住 pettm 季频聚合路径（F 项验收：
            # golden diff 中该图 PE 点数由月数 36 变为季度数 12，图例改「（右轴，季度）」）
            c = 10 + (y - 2023) * 2 + m * 0.1
            months.append({"m": f"{y}-{m:02d}", "open": c - 0.2, "high": c + 0.3,
                           "low": c - 0.4, "close": c,
                           "pe": 12 + m * 0.3})
    fill = minimal_fill(
        l1_html="".join(dims) + _L1_GOV_BLOCK,
        l3_html=l3,
        segments={"period": "2025年报", "by": "按产品", "items": [
            {"name": "烯烃产品", "revenue": 156.2, "rev_pct": 48.1, "gross_margin": 36.4,
             "gross_profit": 56.8, "gp_pct": 62.0},
            {"name": "焦化产品", "revenue": 98.5, "rev_pct": 30.3, "gross_margin": 22.1,
             "gross_profit": 21.8, "gp_pct": 23.8},
            {"name": "其他", "revenue": 70.0, "rev_pct": 21.6, "gross_margin": 18.5,
             "gross_profit": 13.0, "gp_pct": 14.2}]},
        industry_chain={"upstream": ["煤炭开采", "电力"], "self_note": "煤制烯烃一体化",
                        "downstream": ["聚烯烃加工", "包装", "家电"]},
        sensitivity=[{"name": "金价", "impact": 20, "delta": "±10%", "amount": "净利约±9-10亿元"},
                     {"name": "产量", "impact": 13}],
        # v4.11.3：P0 驱动卡 + 周期阶段卡 + DCF 双卡进 golden
        # （v5.1.1：第一变量由脚本按 sensitivity impact 降序加冕——金价 20 > 产量 13，手标一致不告警）
        drivers=[{"name": "金价", "first_var": True,
                  "elastic": "±10% → 净利 ±20%", "elastic_sub": "±10%，金价 900 元/g 基数",
                  "note": "当前约 900 元/g，被三重力量撕扯：美元实际利率、央行购金、地缘溢价。",
                  "chips": [{"label": "悲观", "value": "800"}, {"label": "基础", "value": "900"},
                            {"label": "乐观", "value": "1,000"}, {"label": "元/g", "unit": True}]},
                 {"name": "产量", "elastic": "±10% → 净利 ±13%",
                  "note": "2026E 约 50 吨，可见度高（在建矿山年底投产）。",
                  "chips": [{"label": "悲观", "value": "45"}, {"label": "基础", "value": "50"},
                            {"label": "乐观", "value": "55"}, {"label": "吨", "unit": True}]}],
        driver_verdict="弹性（±20%）大于产量（±13%），且不确定性不对称——三情景围绕金价定义。",
        pe_history={"hist_lo": 13.7, "hist_hi": 83.2, "label": "近5年",
                    "milestones": [{"label": "2021H1", "pe": 46.9}, {"label": "2023Q2", "pe": 13.7}]},
        price_history={"label": "近3年", "series": months},
        cycle_html=('<p>当前处于阶段 03（修复重估）中段：业绩兑现中，PE 仍在历史带下沿。</p>'
                    '<span class="source">阶段拆解：E2 月线 + 当年 EPS 估算 PE</span>'
                    '<div class="conclusion-box"><strong>可复用规律：</strong>低分位≠便宜。</div>'),
        cycle_stages=[
            {"name": "景气顶", "period": "2021/01–2021/12", "pe": "30–47x", "price": "9–13",
             "driver": "商品价格见顶", "current": False},
            {"name": "双杀出清", "period": "2022/01–2024/01", "pe": "10–30x", "price": "6–12",
             "driver": "价格暴跌+估值先杀", "current": False},
            {"name": "修复重估", "period": "2024/02–2026/08", "pe": "10–16x", "price": "8–11",
             "driver": "业绩兑现重估", "current": True}],
        dcf={"value": 12.5, "fcf0": "95亿", "growth_5y": "5%", "g_perp": "2.5%", "wacc": "8.5%",
             "net_cash": "120亿", "implied_g": "0.5",
             "implied_note": "g=WACC−FCF₁/EV（EV=市值−净现金）",
             "verdict": "隐含 g≈0.5% vs 近5年净利复合 +8%——市场按低增长定价，DCF 值与基础中值互证。"},
        peers_plot={"points": [
            {"name": "测试股份", "roe": 14, "pe": 11, "target": True},  # 与 valuation_inputs.pe_ttm 一致
            {"name": "同业甲", "roe": 9, "pe": 25},
            {"name": "同业乙", "roe": 18, "pe": 16}]},
        # v4.10.3：时机判定小表（三行，末行 = tr.total）——此前三份 golden 无任何时机表用例，
        # 模板 `.timing-table tr.total td` 只选 td、行首 th 漏选的问题长期隐身（回归盲区补齐）
        position_html=('<table><thead><tr><th>维度</th><th>得分</th><th>命中信号与加减</th></tr></thead>'
                       '<tbody><tr><th>筹码面</th><td class="num">5.0</td>'
                       '<td>股东户数环比 -3%，集中</td></tr>'
                       '<tr><th>技术面</th><td class="num">5.0</td><td>站上 60 日线</td></tr>'
                       '<tr><th>时机分合计</th><td class="num">5.0</td>'
                       '<td>筹码面×67% + 技术面×33%</td></tr></tbody></table>'
                       '<span class="source">时机判定：中性 5 分起始，逐条信号加减（微调 ±1 档）。</span>'
                       + '<p>时机判定与决策逻辑。' * 12 + '</p>'),
        consensus={"lo": 9, "hi": 13},
        triggers=[{"cond": "提价兑现", "metric": "26H2 毛利率", "target": "≥46%｜实际 47.2%", "status": "hit"},
                  {"cond": "销量转正", "status": "pending"},
                  # v5.1.2：hit/miss 行 target 须写「阈值｜实际值」（方向与 status 不矛盾）
                  {"cond": "成本回落", "target": "存储成本环比转负｜实际 环比+3%", "status": "miss"}],
        prev={"date": "2026-08-08", "quality": 6.4, "valuation": 5.0, "timing": 4.8,
              "target_range": "9-11",
              # v5.1.0：prev.scenarios（extract_review 对上版报告 scenario-table 的照抄格式）——
              # 锚移动台账数据源；上版 base PE 11-13x ≠ 本版 10-12x → 罩住台账渲染与
              # 锚纪律门禁的合规路径（pe_band_evidence 在下方 fill 构建后补入）
              "scenarios": [
                  {"scenario": "悲观情景", "时间维度": "12个月", "触发条件": "上版悲观触发",
                   "归母净利": "75 亿", "EPS": "0.75", "PE": "9-11x",
                   "目标价": "6.8-8.3 元", "较现价": "-24.0%（中值7.6）"},
                  {"scenario": "基础情景", "时间维度": "12个月", "触发条件": "上版基础触发",
                   "归母净利": "95 亿", "EPS": "0.95", "PE": "11-13x",
                   "目标价": "10.5-12.4 元", "较现价": "+14.5%（中值11.5）"},
                  {"scenario": "乐观情景", "时间维度": "12个月", "触发条件": "上版乐观触发",
                   "归母净利": "110 亿", "EPS": "1.10", "PE": "13-15x",
                   "目标价": "14.3-16.5 元", "较现价": "+54.0%（中值15.4）"}]},
        review_html=('<table><tr><td>假设变更对比</td></tr></table>'
                     '<span class="source">数据来源：测试</span>'
                     '<span class="rev">甲</span><span class="rev">乙</span><span class="rev">丙</span>'),
    )
    # v5.1.0 锚纪律一：PE 带跨版移动（11-13x → 10-12x）必填增量证据且含基本面类——
    # 本夹具走合规路径（门禁通过），违规拦截用例见 test_render_gate.py
    fill["valuation"]["pe_band_evidence"] = [
        {"type": "基本面", "note": "上版至今煤价中枢下移 15%，2026E 盈利预测随之下修（新增证据）"},
        {"type": "市场参数", "note": "无风险利率 1.7%→1.6%（折现率环境变化）"}]
    fill.update(over)
    return fill


def mcap_fill(**over):
    """mcap 口径 fill（golden 快照专用，v4.10.2）：valuation 三情景走目标总市值（NAV/rNPV/SOTP
    行业附录口径），valuation_inputs 带 metric_label=P/NAV；thesis 三情景 span 价与
    mcap÷shares 中值一致（7.2/11/15.6，与 minimal_fill 同价便于对照）。"""
    fill = minimal_fill(
        valuation={"shares": 100, "horizon": "12个月", "scenarios": [
            {"key": "pess", "label": "悲观", "trigger": "折让扩大", "mcap": [640, 800]},
            {"key": "base", "label": "基础", "trigger": "折让中性", "mcap": [1000, 1200]},
            {"key": "opt", "label": "乐观", "trigger": "折让收敛", "mcap": [1440, 1680]}]},
        valuation_inputs={"pe_ttm": 0.55, "pe_band": [0.5, 0.6], "div_yield": 2, "risk_free": 1.7,
                          "metric_label": "P/NAV"},
    )
    fill.update(over)
    return fill


def _calc(dispersion=0.55, odds=1.2, floor_type=None):
    """手造估值 calc（只含 build_position_card 用到的键）。
    v5.0 机制三：floor_type 透传悲观地板（"net_cash"/"dividend"），
    赔率 ∞ 时调节链是否上浮取决于它（缺省 None = 无地板，不上浮）。"""
    c = {"central_raw": 0.15, "central": 0.15,
         "dispersion": dispersion, "odds": odds}
    if floor_type:
        c["pess_floor"] = {"type": floor_type, "value": 12.5,
                           "evidence": "测试地板证据：净现金125亿÷总股本10亿"}
    return c


def expect_valueerror(fill, msg, kw=None):
    """compute_scores + validate_content 均未抛 ValueError → AssertionError。
    kw 给定时锁定报错文案（v5.1.2 热核审计加固：防止「被无关规则误拒」的假绿）。"""
    try:
        R.compute_scores(fill)
        R.validate_content(fill, R.compute_valuation(fill))
    except ValueError as e:
        if kw is not None:
            assert kw in str(e), f"拒渲染来源不符：期望含「{kw}」，实际 {e}"
        return
    raise AssertionError(f"应拒渲染但未拒：{msg}")


def write_fill(fill, d, name="_fill_t.json", encoding="utf-8"):
    """把 fill（或任意 JSON 负载）写入目录 d，返回文件路径。"""
    p = os.path.join(d, name)
    with open(p, "w", encoding=encoding) as fp:
        json.dump(fill, fp, ensure_ascii=False)
    return p


@contextlib.contextmanager
def render_workspace():
    """临时工作目录（需多次渲染 / 自行落盘文件的用例在其内操作，退出即清理）。"""
    with tempfile.TemporaryDirectory() as d:
        yield d


def render_fill(fill, name="_fill_t.json"):
    """临时落盘 fill → 全量渲染 → 读回 HTML 文本（目录自动清理）。"""
    with tempfile.TemporaryDirectory() as d:
        p = write_fill(fill, d, name)
        out = R.render(p, out_path=os.path.join(d, "out.html"))
        return open(out, encoding="utf-8").read()


def capture_stderr(fn):
    """执行 fn()，返回其写入 stderr 的文本。"""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        fn()
    return buf.getvalue()


def capture_stderr_value(fn):
    """执行 fn()，返回 (返回值, stderr 文本)。"""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        value = fn()
    return value, buf.getvalue()


def validate_stderr(fill):
    """跑 validate_content(compute_valuation(fill))，返回 stderr 文本。"""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        R.validate_content(fill, R.compute_valuation(fill))
    return buf.getvalue()


# ---------------- v5.0 第 3 章「最新报告期透视」fixture（golden/门禁共用） ----------------
# 四态变体的 fill 侧 period_track（契约示例数；goal_*/verdict_*/summary/industry/forecast/note 为
# fill 侧手填键——经营目标手工查证、判词与小结句模型写，不进落盘参照）
_PERIOD_VARIANTS = {
    "h1": {"period": "2026中报", "is_annual": False,
           "rev": 301.98, "np": 97.28, "np_dedt": 92.10, "ocf": 119.64,
           "rev_yoy": 32.3, "np_yoy": 70.1, "np_dedt_yoy": 65.1, "ocf_yoy": 49.7,
           "sq_label": "2026Q2", "sq_rev": 169.61, "sq_np": 60.67,
           "sq_prev_label": "2025Q2", "sq_prev_rev": 120.49, "sq_prev_np": 32.81,
           "sq_rev_yoy": 40.8, "sq_np_yoy": 84.9,
           "sq_dedt": 48.55, "sq_ocf": 66.20,
           "sq_prev_dedt": 29.30, "sq_prev_ocf": 44.10,
           "sq_dedt_yoy": 65.7, "sq_ocf_yoy": 50.1,
           "band_np": [39.9, 52.1], "band_rev": [44.9, 51.2], "band_years": [2023, 2024, 2025],
           "goal_rev": None, "goal_np": 200.0, "consensus_np": 165.22,
           "verdict_rev": "正常", "verdict_np": "超前", "verdict_dedt": "正常",
           "summary_html": "上半年归母净利 97.28 亿、同比 +70.1%，完成卖方一致预期 58.9%，进度超前。",
           "industry_html": "", "forecast_html": "", "note_html": ""},
    # Q1：累计即单季（sq 值=累计口径），0331 占比带
    "q1": {"period": "2026一季", "is_annual": False,
           "rev": 132.37, "np": 36.61, "np_dedt": 33.40, "ocf": 51.02,
           "rev_yoy": 28.4, "np_yoy": 55.2, "np_dedt_yoy": 50.8, "ocf_yoy": 40.1,
           "sq_label": "2026Q1", "sq_rev": 132.37, "sq_np": 36.61,
           "sq_prev_label": "2025Q1", "sq_prev_rev": 103.09, "sq_prev_np": 23.59,
           "sq_rev_yoy": 28.4, "sq_np_yoy": 55.2,
           "sq_dedt": 33.40, "sq_ocf": 51.02,
           "sq_prev_dedt": 22.18, "sq_prev_ocf": 36.40,
           "sq_dedt_yoy": 50.6, "sq_ocf_yoy": 40.2,
           "band_np": [21.8, 26.4], "band_rev": [22.5, 25.9], "band_years": [2023, 2024, 2025],
           "goal_rev": None, "goal_np": 200.0, "consensus_np": 165.22,
           "verdict_rev": "正常", "verdict_np": "滞后", "verdict_dedt": "正常",
           "summary_html": "",
           "industry_html": "", "forecast_html": "", "note_html": ""},
    "q3": {"period": "2026三季", "is_annual": False,
           "rev": 470.50, "np": 150.20, "np_dedt": 141.00, "ocf": 178.30,
           "rev_yoy": 30.1, "np_yoy": 66.0, "np_dedt_yoy": 62.2, "ocf_yoy": 44.5,
           "sq_label": "2026Q3", "sq_rev": 168.52, "sq_np": 52.92,
           "sq_prev_label": "2025Q3", "sq_prev_rev": 128.66, "sq_prev_np": 30.36,
           "sq_rev_yoy": 31.0, "sq_np_yoy": 74.3,
           "sq_dedt": 48.90, "sq_ocf": 58.66,
           "sq_prev_dedt": 30.10, "sq_prev_ocf": 40.20,
           "sq_dedt_yoy": 62.5, "sq_ocf_yoy": 45.9,
           "band_np": [71.2, 79.8], "band_rev": [72.4, 78.9], "band_years": [2023, 2024, 2025],
           "goal_rev": None, "goal_np": 200.0, "consensus_np": 165.22,
           "verdict_rev": "正常", "verdict_np": "超前", "verdict_dedt": "无法判定",
           "summary_html": "",
           "industry_html": "", "forecast_html": "", "note_html": ""},
    # 年报期：整章消失；band 无（年报无节奏带），goal/consensus/verdict 均不填
    "annual": {"period": "2025年报", "is_annual": True,
               "rev": 612.40, "np": 158.90, "np_dedt": 150.20, "ocf": 210.50,
               "rev_yoy": 5.2, "np_yoy": 6.1, "np_dedt_yoy": 5.5, "ocf_yoy": 8.8,
               "sq_label": "2025Q4", "sq_rev": 141.90, "sq_np": 31.10,
               "sq_prev_label": "2024Q4", "sq_prev_rev": 136.00, "sq_prev_np": 29.70,
               "sq_rev_yoy": 4.3, "sq_np_yoy": 4.7,
               "sq_dedt": 40.10, "sq_ocf": 55.00,
               "sq_prev_dedt": 38.00, "sq_prev_ocf": 50.00,
               "sq_dedt_yoy": 5.5, "sq_ocf_yoy": 10.0,
               "band_np": None, "band_rev": None, "band_years": [],
               "goal_rev": None, "goal_np": None, "consensus_np": None,
               "industry_html": "", "forecast_html": "", "note_html": ""},
}
# 落盘参照保留的键（em_fetch period_track 原生输出；fill 侧手填键不入参照）
_PERIOD_REF_KEYS = ("period", "is_annual", "rev", "np", "np_dedt", "ocf",
                    "rev_yoy", "np_yoy", "np_dedt_yoy", "ocf_yoy",
                    "sq_label", "sq_rev", "sq_np", "sq_prev_label", "sq_prev_rev", "sq_prev_np",
                    "sq_rev_yoy", "sq_np_yoy", "sq_dedt", "sq_ocf", "sq_prev_dedt", "sq_prev_ocf",
                    "sq_dedt_yoy", "sq_ocf_yoy", "band_np", "band_rev", "band_years")
_PERIOD_TMPDIR = None


def _period_ref_file(variant: str, pt: dict) -> str:
    """把 em_fetch --out 形态的落盘 JSON（price/pe_ttm + period_track + consensus_np）写入
    测试会话级临时目录并返回路径。文件名故意不带 _em_ 前缀——render 成功后的归档会把
    _em_* 源文件移入 _archive，会话级共享参照被移走会让后续用例断链。"""
    global _PERIOD_TMPDIR
    if _PERIOD_TMPDIR is None:
        _PERIOD_TMPDIR = tempfile.mkdtemp(prefix="sda_period_ref_")
    payload = {"price": 10.0, "pe_ttm": 11.0,
               "period_track": {k: pt[k] for k in _PERIOD_REF_KEYS if k in pt}}
    if pt.get("consensus_np") is not None:
        payload["consensus_np"] = {"year": 2026, "np_avg": pt["consensus_np"], "orgs": 12}
    p = os.path.join(_PERIOD_TMPDIR, f"period_ref_{variant}.json")
    with open(p, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False)
    return p


def period_fill(variant="h1", **over):
    """第 3 章 fill（v5.0）：minimal_fill + 合法 period_track + quote.source_file 指向会话级
    临时落盘 JSON（em_fetch --out 形态，与 fill 侧数据一致——渲染器交叉校验可通过）。
    variant 四态：h1（中报，fill 契约示例数）/ q1（一季，单季图退化单柱）/ q3（三季）/
    annual（is_annual=true，整章消失）。over 透传 minimal_fill 顶层覆盖；
    period_track 单字段微调请直接改返回值的 fill["period_track"]。"""
    pt = dict(_PERIOD_VARIANTS[variant])
    fill = minimal_fill(period_track=pt,
                        quote={"source_file": _period_ref_file(variant, pt), "date": "2026-08-27"})
    fill.update(over)
    return fill
