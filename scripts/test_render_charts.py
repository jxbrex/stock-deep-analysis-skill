#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_render_charts.py — render_report 图表生成回归（无网络，直接 python 运行）

覆盖各 build_* 图（业务构成 / 产业链 / 财务趋势图墙 / 利润增长 / 散点 / 龙卷风 / 走廊 /
PE 历史带 / 触发条 / 三情景卡）与对齐机 fix_table_alignment。
图表符号直接从真身模块（charts_base / charts_l1 / charts_misc）导入，不经 render_report 垫片。
拆分自 test_render_core.py（v4.10.2），断言逐字沿用。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_report as R
from charts_base import _ticks, _text_w
from charts_l1 import build_segments_plot, build_chain_plot, build_fin_trend
from charts_misc import build_growth_plot
from conftest import (
    minimal_fill, expect_valueerror, capture_stderr, capture_stderr_value, render_fill,
)


def test_nice_ticks():
    """nice-number 刻度：步长取 1/2/2.5/5×10^k，刻度为步长整数倍且落在值域内。"""
    assert _ticks(19, 69) == [20, 40, 60]
    assert _ticks(0, 10, 6) == [0, 2, 4, 6, 8, 10]
    t3 = _ticks(8.7, 34.6)
    assert t3 == [10, 20, 30], f"实际 {t3}"
    t4 = _ticks(0.22, 0.88)
    diffs = {round(t4[i + 1] - t4[i], 9) for i in range(len(t4) - 1)}
    assert len(diffs) == 1 and all(0.22 - 1e-9 <= v <= 0.88 + 1e-9 for v in t4), f"实际 {t4}"


def test_optional_charts_render():
    """v4.8 可选图：sensitivity/pe_history 填了才出图，缺省时条件块整块删除；
    评分横条图（数据现成）与侧栏目录始终生成；走廊图横版含单位注；
    明细表已并入横条图（不再出现）；龙卷风 delta/amount 子行承载金额影响。
    v4.7.1：PE 历史带挪挂第 10 章（cycle_html 必填），垫在手写时段拆解前；milestones 时点标注。"""
    extra = {
        "sensitivity": [{"name": "金价", "impact": 20, "delta": "±10%", "amount": "净利约±9-10亿元"},
                        {"name": "产量", "impact": 13}],
        "pe_history": {"hist_lo": 13.7, "hist_hi": 83.2, "label": "近5年",
                       "milestones": [{"label": "2021H1", "pe": 46.9}, {"label": "2023Q2", "pe": 13.7}]},
        # v4.7.1 起 PE 历史带挂第 10 章：pe_history 与 cycle_html 绑定（schema 新规则）
        "cycle_html": '<table><thead><tr><th>阶段</th><th class="num">时间</th><th class="num">PE</th>'
                      '<th>驱动</th></tr></thead><tbody><tr><td>景气顶</td><td class="num">2021H1</td>'
                      '<td class="num">46.9x</td><td>商品价格见顶</td></tr></tbody></table>'
                      '<span class="source">阶段拆解：E2 月线 + 当年 EPS 估算 PE</span>'
                      '<div class="conclusion-box"><strong>可复用规律：</strong>低分位≠便宜。</div>',
    }
    html = render_fill(minimal_fill(**extra))
    for label in ("敏感性龙卷风", "PE(TTM)历史带", "九维评分分布", "目标价走廊"):
        assert f'aria-label="{label}"' in html, f"缺图：{label}"
    assert "净利约±9-10亿元" in html, "龙卷风应展示 delta/amount 子行"
    assert "单位：元" in html, "走廊图应标注币种单位"
    assert "质量分明细" not in html, "明细表已并入评分横条图，不应再出现"
    assert "良好" in html, "横条图条端应含判词（7.0 → 良好）"
    # v4.7.1：历史带位于第 10 章内、手写时段拆解之前（概览→明细）；milestones 时点标注渲染
    s10_pos = html.find('id="s10"')
    band_pos = html.find('aria-label="PE(TTM)历史带"')
    cycle_pos = html.find("景气顶")
    assert 0 <= s10_pos < band_pos < cycle_pos, "历史带应位于第 10 章内、时段表之前"
    assert "2021H1 46.9x" in html, "milestones 时点标注应渲染"
    # 缺省渲染：可选图条件块必须整块删除
    html2 = render_fill(minimal_fill())
    for label in ("敏感性龙卷风", "PE(TTM)历史带"):
        assert f'aria-label="{label}"' not in html2, f"缺字段时图应整块删除：{label}"
    assert 'aria-label="九维评分分布"' in html2, "评分横条图数据现成，应始终生成"
    assert 'class="toc-side"' in html2 and 'href="#s11"' in html2, "侧栏目录应生成且指向章节锚点"


def test_tornado_long_names():
    """v4.8.2：龙卷风变量名列自适应——超长名折两行、NL/X0/HALF 随最长行宽动态取值，
    文本不越出画布左缘；未超宽名称单行完整渲染。"""
    long_name = "产业互联网创新业务与新兴信息通信业务资本开支强度边际变化"  # 28 字 ≈ 364px + 后缀 → 超 388 折行
    fill = minimal_fill(sensitivity=[
        {"name": long_name, "impact": 20, "delta": "±10%", "amount": "净利约±9-10亿元"},
        {"name": "移动 ARPU 值", "impact": 13},
        {"name": "金价", "impact": 8}])
    html = R.build_sensitivity_tornado(fill)
    assert 'aria-label="敏感性龙卷风"' in html
    assert long_name not in html, "超长名应折行（不应单行完整出现）"
    plain = re.sub(r"<[^>]+>", "", html)
    for piece in ("产业互联网", "边际变化", "（第一变量）"):
        assert piece in plain, f"折行后名称缺段：{piece}"
    xs = [float(m) for m in re.findall(r'\bx="(-?[\d.]+)"', html)]
    assert xs and min(xs) >= 0, f"文本越出画布左缘：min x = {min(xs)}"
    # 中等长度名（name+后缀 ≈ 260px > 218）：名称列扩宽但不折行，单行完整出现
    mid = "传统固网宽带业务资本开支变化"
    html2 = R.build_sensitivity_tornado(minimal_fill(sensitivity=[
        {"name": mid, "impact": 20}, {"name": "金价", "impact": 8}]))
    assert mid + "（第一变量）" in html2, "未超宽名称应单行完整渲染"
    xs2 = [float(m) for m in re.findall(r'\bx="(-?[\d.]+)"', html2)]
    assert min(xs2) >= 0, f"名称列扩宽后文本越界：min x = {min(xs2)}"


def test_peers_label_within_bounds():
    """右缘点位标签不得越出 SVG 宽度（v4.8 修复回归：右缘公司标签曾被画布裁切）。"""
    html = R.build_peers_plot({"peers_plot": {"points": [
        {"name": "目标公司", "roe": 20, "pe": 15, "target": True},
        {"name": "右缘同业", "roe": 10, "pe": 31.06},
        {"name": "左缘同业", "roe": 25, "pe": 13.3}]}})
    assert html, "散点图应生成"
    found = False
    for m in re.finditer(r'<text x="([\d.]+)"([^>]*)>([^<]*)</text>', html):
        x, attrs, txt = float(m.group(1)), m.group(2), m.group(3)
        if "右缘同业" not in txt:
            continue
        found = True
        w = _text_w(txt, 12)
        anchor = "end" if 'text-anchor="end"' in attrs else ("middle" if 'text-anchor="middle"' in attrs else "start")
        x0 = x - w if anchor == "end" else (x - w / 2 if anchor == "middle" else x)
        assert x0 >= 0 and x0 + w <= 1000, f"标签越界: {txt} x0={x0:.0f} w={w:.0f}"
    assert found, "右缘同业标签未渲染"


def test_segments_chain_charts():
    """v4.8 业务构成图（3.1 锚点 <!--SEGMENTS-->）与产业链图（3.2 锚点 <!--CHAIN-->）：
    锚点在位→原位替换；锚点缺失→追加章末+告警；字段缺失→锚点静默清除；占比和偏离→告警。"""
    extra = {
        "segments": {"period": "2025年报", "by": "按产品", "items": [
            {"name": "烯烃产品", "revenue": 156.2, "rev_pct": 48.1, "gross_margin": 36.4,
             "gross_profit": 56.8, "gp_pct": 62.0},
            {"name": "焦化产品", "revenue": 98.5, "rev_pct": 30.3, "gross_margin": 22.1,
             "gross_profit": 21.8, "gp_pct": 23.8},
            {"name": "其他", "revenue": 70.0, "rev_pct": 21.6, "gross_margin": 18.5,
             "gross_profit": 13.0, "gp_pct": 14.2}]},
        "industry_chain": {"upstream": ["煤炭开采", "电力"], "self_note": "煤制烯烃一体化",
                           "downstream": ["聚烯烃加工", "包装", "家电"]},
    }
    long_text = "该维度分析：公司基本面稳健，数据支撑充分，论据详实可靠，行业地位稳固，具备长期参考价值。"
    dims = [f'<div class="dim-block"><p>{long_text}</p></div>' for _ in range(6)]
    # 锚点在位：分别钉在 3.1 / 3.2 维度块后
    dims[0] += "<!--SEGMENTS-->"
    dims[1] += "<!--CHAIN-->"
    fill = minimal_fill(l1_html="".join(dims), **extra)
    html = render_fill(fill)
    assert 'aria-label="业务构成"' in html, "业务构成图应生成"
    assert 'aria-label="产业链位置"' in html, "产业链图应生成"
    assert "<!--SEGMENTS-->" not in html and "<!--CHAIN-->" not in html, "锚点必须被替换"
    assert "毛利 56.8亿（占 62%）" in html, "柱下应标注毛利与毛利占比（_fmt 为 %g，62.0→62）"
    assert "利润口径为毛利" in html, "毛利口径注记必须在位（分部净利无公开披露）"
    assert "上游 · 供给端" in html and "煤制烯烃一体化" in html, "产业链三栏与公司定位注应渲染"
    # 锚点缺失但字段已填 → 追加第 3 章末尾 + stderr 告警
    l1_no_anchor = "".join(f'<div class="dim-block"><p>{long_text}</p></div>' for _ in range(6))
    fill2 = minimal_fill(l1_html=l1_no_anchor, **extra)
    html2, err2 = capture_stderr_value(lambda: R._fill_template(R._build_repl_map(
        fill2, "元", R.compute_valuation(fill2), R.compute_scores(fill2), 5.5,
        R.compute_valuation_score(R.compute_valuation(fill2), fill2["valuation_inputs"]),
        None, "", fill2["date"], fill2["subtitle"], "10-12", fill2["peers_html"],
        R.build_scenario_spectrum(fill2, R.compute_valuation(fill2)),
        R.build_scenario_block(R.compute_valuation(fill2), "元"),
        R.build_peers_plot(fill2))))
    assert "缺 <!--SEGMENTS--> 锚点" in err2, "锚点缺失应告警"
    assert 'aria-label="业务构成"' in html2, "锚点缺失时图应追加第 3 章末尾"
    # 字段缺失但锚点在 → 锚点静默清除、图不生成
    fill3 = minimal_fill(l1_html="".join(dims))  # dims 带锚点，但无 segments/industry_chain
    html3 = R._fill_template(R._build_repl_map(
        fill3, "元", R.compute_valuation(fill3), R.compute_scores(fill3), 5.5,
        R.compute_valuation_score(R.compute_valuation(fill3), fill3["valuation_inputs"]),
        None, "", fill3["date"], fill3["subtitle"], "10-12", fill3["peers_html"],
        R.build_scenario_spectrum(fill3, R.compute_valuation(fill3)),
        R.build_scenario_block(R.compute_valuation(fill3), "元"),
        R.build_peers_plot(fill3)))
    assert 'aria-label="业务构成"' not in html3, "字段未填图不应生成"
    assert "<!--SEGMENTS-->" not in html3 and "<!--CHAIN-->" not in html3, "空锚点应静默清除"
    # 占比和偏离 100% → 告警
    bad = minimal_fill(segments={"items": [{"name": "A", "rev_pct": 40}, {"name": "B", "rev_pct": 40}]})
    assert "偏离 100%" in capture_stderr(
        lambda: R.validate_content(bad, R.compute_valuation(bad))), "占比和偏离 100% 应告警"
    # v4.8.2：横条图——长名折两行不挤压、高度随行数自适应（不再固定 360）、毛利率圆点在位
    fill4 = minimal_fill(segments={"items": [
        {"name": "固网宽带及数据服务与产业互联网创新业务", "rev_pct": 45.0, "gross_margin": 30.0},
        {"name": "移动业务", "rev_pct": 35.0, "gross_margin": 40.0},
        {"name": "其他", "rev_pct": 20.0}]})
    html4 = build_segments_plot(fill4)
    assert 'aria-label="业务构成"' in html4
    assert "固网宽带及数据服务与产业互联网创新业务" not in html4, "超长分部名应折行"
    assert "产业互联网创新业务" in html4, "折行后名称缺段"
    assert '毛利率（同一 % 轴）' in html4 and 'r="4.5"' in html4, "毛利率圆点与图例应在位"
    vb = re.search(r'viewBox="0 0 1000 (\d+)"', html4)
    assert vb and int(vb.group(1)) < 300, f"3 行条图高度应自适应收紧（实际 {vb and vb.group(1)}）"


def test_price_history_and_holders():
    """v4.8 ①发丝图挂第 10 章（历史带之后、时段表之前）；②户数趋势挂第 11 章（v4.9.1 起
    移至章首：时机判定小表前、三轨判定卡之前）；缺字段时两图整块消失。"""
    months = []
    for y in (2023, 2024, 2025):
        for m in range(1, 13):
            months.append({"m": f"{y}-{m:02d}", "close": 10 + (y - 2023) * 2 + m * 0.1,
                           "pe": 12 + m * 0.3})
    extra = {
        "price_history": {"label": "近3年", "series": months},
        "holders": [{"date": "2025-03-31", "num": 188153, "chg": None},
                    {"date": "2025-06-30", "num": 175200, "chg": -6.9},
                    {"date": "2025-09-30", "num": 160800, "chg": -8.2},
                    {"date": "2025-12-31", "num": 152300, "chg": -5.3}],
        "cycle_html": '<table><tr><td>景气顶</td></tr></table>'
                      '<span class="source">阶段拆解：E2 月线</span>',
    }
    html = render_fill(minimal_fill(**extra))
    assert 'aria-label="股价与PE历史走势"' in html, "发丝图应生成"
    assert 'aria-label="股东户数趋势"' in html, "户数趋势图应生成"
    # 发丝图在第 10 章内；户数图在第 11 章章首（v4.9.1：时机判定小表前、三轨判定卡之前）
    assert html.find('id="s10"') < html.find('aria-label="股价与PE历史走势"'), "发丝图应在第 10 章"
    s11_pos = html.find('id="s11"')
    holders_pos = html.find('aria-label="股东户数趋势"')
    position_pos = html.find("时机判定与决策逻辑")
    card_pos = html.find("三轨判定与仓位结论")
    assert s11_pos < holders_pos < position_pos < card_pos, \
        "户数图应在第 11 章章首（时机判定小表前、三轨判定卡之前）"
    assert "188,153" in html, "户数应带千位符"
    # v4.8.2 原位美化：面积填充 / 发丝加粗 / 年末竖网格 / 末端药丸标签
    ph_seg = html.split('aria-label="股价与PE历史走势"', 1)[1].split('</svg>', 1)[0]
    assert 'fill="#efe9db"' in ph_seg, "股价线下应有浅沙色面积填充"
    assert 'stroke-width="1.8"' in ph_seg, "发丝线应加粗至 1.8"
    assert 'stroke="#f0ebdf"' in ph_seg, "年份 tick 应有竖向浅网格线"
    assert 'rx="8"' in ph_seg, "末端最新值标签应有药丸底色"
    # 缺字段：两图整块消失（v4.9.1 起 minimal_fill 默认含 holders，需显式置 None）
    html2 = render_fill(minimal_fill(holders=None))
    assert 'aria-label="股价与PE历史走势"' not in html2, "缺字段发丝图应消失"
    assert 'aria-label="股东户数趋势"' not in html2, "缺字段户数图应消失"


def test_consensus_band_and_pe_iqr():
    """v4.8 ③走廊图叠加卖方一致目标价带（consensus）；④PE 历史带 P25-P75 分位段。"""
    fill = minimal_fill(consensus={"lo": 9, "hi": 13})
    html = R.build_scenario_spectrum(fill, R.compute_valuation(fill))
    assert "卖方目标价" in html and "0.13" in html, "走廊图应渲染卖方目标价灰带"
    html_no = R.build_scenario_spectrum(minimal_fill(), R.compute_valuation(minimal_fill()))
    assert "卖方目标价" not in html_no, "缺 consensus 字段灰带不应出现"
    ph = {"hist_lo": 13.7, "hist_hi": 83.2, "label": "近5年", "p25": 18.5, "p75": 45.6}
    fill2 = minimal_fill(pe_history=ph)
    html2 = R.build_pe_band(fill2)
    assert "P25" in html2 and "18.5–45.6" in html2, "PE 带应渲染 P25-P75 分位段"
    assert "一半时间落在 18.5–45.6x" in html2, "v4.8.2：分位区行内标签应改人话"
    ph2 = {"hist_lo": 13.7, "hist_hi": 83.2}
    html3 = R.build_pe_band(minimal_fill(pe_history=ph2))
    assert "P25" not in html3, "缺 p25/p75 分位段不应出现"


def test_chain_columns_balanced():
    """v4.9：产业链图两栏各自在总高内均分——4 上游 vs 5 下游，首尾盒顶/底 y 两栏一致。"""
    fill = minimal_fill(company="测试股份",
                        industry_chain={"upstream": ["A1", "A2", "A3", "A4"],
                                        "downstream": ["B1", "B2", "B3", "B4", "B5"]})
    html = build_chain_plot(fill)
    ups = [float(y) for y in re.findall(r'<rect x="30" y="([\d.]+)" width="250" height="34"', html)]
    downs = [float(y) for y in re.findall(r'<rect x="720" y="([\d.]+)" width="250" height="34"', html)]
    assert len(ups) == 4 and len(downs) == 5
    assert ups[0] == downs[0], "首盒顶应两栏对齐"
    assert ups[-1] == downs[-1], "末盒顶应两栏对齐（短栏间距已拉开）"
    assert ups[1] - ups[0] > downs[1] - downs[0], "短栏间距应大于长栏"


def test_fin_trend_wall():
    """v4.9：fin_trend 组合图墙——4 面板、双轴（左亿右%）、阈值红虚线、柱图同比、
    第二条线灰虚线；v4.9.1：归母净利面板带扣非双柱、第 4 面板纯线（周转天数）、
    柱色只表系列归属（单柱不再有钢蓝最新年高亮）；缺字段/面板不足拒渲染。"""
    html = build_fin_trend(minimal_fill())
    assert html.count("mini-cell") == 4, "标准 4 面板"
    assert 'stroke-dasharray="3 3"' in html, "现金含量应画 0.7 阈值红虚线"
    assert 'stroke-dasharray="4 3"' in html, "ROE 第二条线应为灰虚线"
    assert "m-yoy" in html, "柱图应带同比标注"
    assert "左轴" in html and "右轴" in html, "图例应标明双轴"
    cells = html.split('<div class="mini-cell">')
    # v4.9.1：单柱面板（营收）柱全部沙色，取消钢蓝最新年高亮
    assert not re.search(r'<rect[^>]*fill="#4a6fa5"', cells[1]), "单柱面板不应有钢蓝柱"
    # 归母净利+扣非净利双柱面板：第二柱系列（扣非）钢蓝、第一柱（归母）沙色
    assert "扣非净利（亿，左轴）" in cells[2], "归母净利面板应含扣非第二柱图例"
    assert re.search(r'<rect[^>]*fill="#4a6fa5"', cells[2]), "扣非第二柱应为钢蓝"
    # 第 4 面板纯线（应收/存货周转天数）：无柱无图例色块、两条线、头行只列两条线末值
    assert "运营资金周转天数" in cells[4], "第 4 面板应为周转天数纯线面板"
    assert "<rect" not in cells[4], "纯线面板不应有柱或图例色块 rect"
    assert cells[4].count("<polyline") == 2, "周转天数应为双线"
    assert re.search(r'm-val">60 / 120<', cells[4]), "纯线面板头行只列两条线末值"
    assert not build_fin_trend(minimal_fill(fin_trend={"years": ["2024", "2025"], "panels": []}))
    expect_valueerror(minimal_fill(fin_trend=None), "fin_trend 缺失应拒渲染")
    f = minimal_fill()
    f["fin_trend"]["panels"] = f["fin_trend"]["panels"][:2]
    expect_valueerror(f, "fin_trend 有效面板 <3 应拒渲染")


def test_growth_plot():
    """v4.9：growth_plot——历史柱+预测区间条+一致预期◆+预期差；未盈利分型豁免必填。"""
    html = build_growth_plot(minimal_fill())
    assert "polygon" in html, "应有一致预期菱形"
    assert "fill-opacity=\"0.3\"" in html, "预测段应为区间竖条"
    assert "差 +0.0pct" in html, "预期差=本文中枢 6 − 一致 6 = 0"
    expect_valueerror(minimal_fill(growth_plot=None), "growth_plot 缺失应拒渲染")
    f = minimal_fill(stock_type="未盈利股", growth_plot=None)
    R.validate_content(f, R.compute_valuation(f))   # 未盈利豁免，不拒


def test_scenario_cards_eval_colors():
    """v4.9 颜色语义拆分：三指标卡赔率/离散度用 good/bad（评价色），中枢期望收益仍 up/down。"""
    calc = R.compute_valuation(minimal_fill())
    html = R.build_scenario_block(calc)
    assert 'value up' in html, "中枢期望收益为正应走方向色 up"
    assert 'value bad' in html, "赔率 <1.5 应走评价色 bad"
    f = minimal_fill()
    # 收窄悲观下限（98×10=9.8 贴近现价 10）→ 赔率 (11−10)/(10−9.8)=5 ≥1.5
    f["valuation"]["scenarios"][0]["profit"] = 98
    f["valuation"]["scenarios"][0]["pe"] = [10, 11]
    html2 = R.build_scenario_block(R.compute_valuation(f))
    assert 'value good' in html2, "赔率 ≥1.5 应走评价色 good"


def test_triggers_strip():
    """v4.9 触发条件状态条：三态类名/非法 status 归 pending/空字段空串/非法与超量告警。"""
    html = R.build_triggers_strip(minimal_fill(triggers=[
        {"cond": "提价兑现", "metric": "26H2 毛利率", "target": "≥46%", "status": "hit"},
        {"cond": "销量转正", "status": "pending"},
        {"cond": "成本回落", "status": "miss"},
        {"cond": "非法态", "status": "bogus"}]))
    assert 'trig-dot hit' in html and 'trig-dot pending' in html and 'trig-dot miss' in html
    assert "已兑现" in html and "未兑现" in html
    assert html.count('<span class="trig-status pending">待验证</span>') == 2, "非法 status 应归 pending"
    assert not R.build_triggers_strip(minimal_fill()), "无字段应为空串"
    f = minimal_fill(triggers=[{"cond": f"c{i}", "status": "bogus"} for i in range(9)])
    out = capture_stderr(lambda: R.validate_content(f, R.compute_valuation(f)))
    assert "非法 status" in out and "> 8" in out, "非法值与超量应告警"


def test_table_alignment_keeps_highlight_class():
    """v4.9.1：fix_table_alignment 只动 num/center，td 上的 cell-best/cell-worst 高亮类存活。"""
    html = R.fix_table_alignment(
        '<table><tr><th>公司</th><th>PE(TTM)</th><th>ROE</th></tr>'
        '<tr><td style="color:#4a6fa5;font-weight:700;">测试股份</td><td class="cell-best">11</td>'
        '<td>14%</td></tr>'
        '<tr><td>同业甲</td><td class="cell-worst">25</td><td>9%</td></tr></table>')
    assert "cell-best num" in html, "数字列应追加 num 且保留 cell-best"
    assert "cell-worst num" in html, "数字列应追加 num 且保留 cell-worst"


def test_scenario_table_alignment_fixed():
    """v4.10：三情景表触发条件行随列右对齐（工行触发行不一致实证）——表头/时间维度/触发条件
    全部 num 类；scenario-table 豁免 fix_table_alignment（长文本触发的长文剥类不再介入）。"""
    html = render_fill(minimal_fill())
    assert '<th class="num">悲观情景</th>' in html, "情景列表头应 num 右对齐"
    assert '<td class="num">下行</td>' in html, "触发条件行应随列 num"
    assert '<td class="num">12个月</td>' in html, "时间维度行应随列 num"
    long_trig = "NIM 降至 1.22%、信用成本升至 0.65% 的长触发条件文本"
    html2 = R.fix_table_alignment(
        f'<table class="scenario-table"><tr><th>指标</th><th class="num">悲观情景</th></tr>'
        f'<tr><td>触发条件</td><td class="num">{long_trig}</td></tr></table>')
    assert f'<td class="num">{long_trig}</td>' in html2, "scenario-table 应豁免长文剥类"
    print("OK 三情景表全列右对齐 + scenario-table 豁免对齐修正")


def test_fix_alignment_tie_goes_left():
    """v4.10：fix_table_alignment 平票判左——文本为主的表整表左对齐不再锯齿
    （工行 09-11 预期差表「净息差判断」行实证）；数字占多数的列仍右对齐。"""
    tbl = ('<table><thead><tr><th>维度</th><th>中金</th><th>光大</th></tr></thead><tbody>'
           '<tr><td>净利</td><td>基本不变</td><td>3,757 亿</td></tr>'
           '<tr><td>息差判断</td><td>息差企稳</td><td>负债成本降幅趋缓</td></tr>'
           '<tr><td>评级</td><td>跑赢行业</td><td>买入</td></tr></tbody></table>')
    html = R.fix_table_alignment(tbl)
    assert 'class="num"' not in html, "文本为主应整表左对齐"
    tbl3 = ('<table><thead><tr><th>维度</th><th>卖方</th></tr></thead><tbody>'
            '<tr><td>2026E 净利</td><td>3,757 亿</td></tr>'
            '<tr><td>增速</td><td>+2.7%</td></tr>'
            '<tr><td>息差判断</td><td>负债成本降幅趋缓</td></tr>'
            '<tr><td>评级</td><td>买入</td></tr></tbody></table>')
    html3 = R.fix_table_alignment(tbl3)
    assert '<th class="num">卖方</th>' not in html3, "平票列应判左（表头不加 num）"
    assert '>买入</td>' in html3, "平票列文字格不加 num"
    tbl2 = ('<table><thead><tr><th>公司</th><th>PE</th></tr></thead><tbody>'
            '<tr><td>甲</td><td>11</td></tr><tr><td>乙</td><td>25</td></tr>'
            '<tr><td>丙</td><td>—</td></tr></tbody></table>')
    html2 = R.fix_table_alignment(tbl2)
    assert '<th class="num">PE</th>' in html2, "数字占多数的列仍应右对齐"
    print("OK 对齐平票判左（文本表整表左 / 平票列左 / 数字列右不变）")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"全部 {len(tests)} 项测试通过")
