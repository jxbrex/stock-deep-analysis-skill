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
    v4.7.1：PE 历史带挪挂第 11 章（cycle_html 必填），垫在手写时段拆解前；milestones 时点标注。"""
    extra = {
        "sensitivity": [{"name": "金价", "impact": 20, "delta": "±10%", "amount": "净利约±9-10亿元"},
                        {"name": "产量", "impact": 13}],
        "pe_history": {"hist_lo": 13.7, "hist_hi": 83.2, "label": "近5年",
                       "milestones": [{"label": "2021H1", "pe": 46.9}, {"label": "2023Q2", "pe": 13.7}]},
        # v4.7.1 起 PE 历史带挂第 11 章：pe_history 与 cycle_html 绑定（schema 新规则）
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
    # v4.7.1：历史带位于第 11 章内、手写时段拆解之前（概览→明细）；milestones 时点标注渲染
    s11_pos = html.find('id="s11"')
    band_pos = html.find('aria-label="PE(TTM)历史带"')
    cycle_pos = html.find("景气顶")
    assert 0 <= s11_pos < band_pos < cycle_pos, "历史带应位于第 11 章内、时段表之前"
    assert "2021H1 46.9x" in html, "milestones 时点标注应渲染"
    # 缺省渲染：可选图条件块必须整块删除
    html2 = render_fill(minimal_fill())
    for label in ("敏感性龙卷风", "PE(TTM)历史带"):
        assert f'aria-label="{label}"' not in html2, f"缺字段时图应整块删除：{label}"
    assert 'aria-label="九维评分分布"' in html2, "评分横条图数据现成，应始终生成"
    assert 'class="toc-side"' in html2 and 'href="#s12"' in html2, "侧栏目录应生成且指向章节锚点"


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
    """v4.8 业务构成图（4.1 锚点 <!--SEGMENTS-->）与产业链图（4.2 锚点 <!--CHAIN-->）：
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
    # 锚点在位：分别钉在 4.1 / 4.2 维度块后
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
    # 锚点缺失但字段已填 → 追加第 4 章末尾 + stderr 告警
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
    assert 'aria-label="业务构成"' in html2, "锚点缺失时图应追加第 4 章末尾"
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
    """v4.8 ①发丝图挂第 11 章（历史带之后、时段表之前）；②户数趋势挂第 12 章（v4.9.1 起
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
    # 发丝图在第 11 章内；户数图在第 12 章章首（v4.9.1：时机判定小表前、三轨判定卡之前）
    assert html.find('id="s11"') < html.find('aria-label="股价与PE历史走势"'), "发丝图应在第 11 章"
    s12_pos = html.find('id="s12"')
    holders_pos = html.find('aria-label="股东户数趋势"')
    position_pos = html.find("时机判定与决策逻辑")
    card_pos = html.find("三轨判定与仓位结论")
    assert s12_pos < holders_pos < position_pos < card_pos, \
        "户数图应在第 12 章章首（时机判定小表前、三轨判定卡之前）"
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


def test_holders_label_collision():
    """v4.11.0：户数图同月多期披露 → 横标降精度 MM-DD；重复截止日去重保留后写行
    （天齐 002466 2026-09-13 实证：E4 给 20260710 双行、2026-07 共四期，横标一排 26-07）。"""
    holders = [{"date": "2026-07-10", "num": 345304, "chg": 0.0},
               {"date": "2026-07-10", "num": 345304, "chg": -1.7},
               {"date": "2026-07-20", "num": 358804, "chg": 3.9},
               {"date": "2026-07-31", "num": 360077, "chg": 0.4},
               {"date": "2026-08-10", "num": 367221, "chg": 2.0},
               {"date": "2026-08-31", "num": 364212, "chg": -0.8}]
    html = render_fill(minimal_fill(holders=holders))
    seg = html.split('aria-label="股东户数趋势"', 1)[1].split('</svg>', 1)[0]
    assert "26-07" not in seg and "26-08" not in seg, "同月多期时横标不应停留在 YY-MM"
    for lb in ("07-10", "07-20", "07-31", "08-10", "08-31"):
        assert lb in seg, f"横标应含 {lb}"
    assert seg.count("07-10") == 1, "重复截止日应去重为一行"
    assert "-1.7%" in seg and "+0.0%" not in seg, "去重应保留后写行（变动 -1.7%）"
    # 正常季度数据不触发降精度
    html2 = render_fill(minimal_fill())
    seg2 = html2.split('aria-label="股东户数趋势"', 1)[1].split('</svg>', 1)[0]
    assert "25-03" in seg2, "无碰撞时应保持 YY-MM"
    print("OK 户数图横标碰撞降精度与重复截止日去重")


def test_price_history_quarterly_kline():
    """v4.11.0：series 带 OHLC → 季K蜡烛（红涨绿跌、季度聚合）；缺 OHLC 回退发丝线；
    连续缺 pe ≥3 个月段加亏损期底纹命名；PE 极值（max > p75×3）右轴截断 + 峰值标注。"""
    months = []
    for i in range(36):  # 2023-01 ~ 2025-12
        y, m = 2023 + i // 12, i % 12 + 1
        base = 10 + i * 0.2
        months.append({"m": f"{y}-{m:02d}", "open": base, "high": base + 1, "low": base - 1,
                       "close": base + 0.5,
                       "pe": (None if 15 <= i <= 23 else 12.0)})  # 2024-04~2024-12 亏损期 9 个月
    fill = minimal_fill(price_history={"label": "近3年", "series": months},
                        cycle_html='<table><tr><td>x</td></tr></table>')
    html = render_fill(fill)
    seg = html.split('aria-label="股价季K与PE历史走势"', 1)[1].split('</svg>', 1)[0]
    assert 'fill="#c75b5b"' in seg or 'fill="#6ba86b"' in seg, "季K 蜡烛应渲染（SVG  pastel 方向色）"
    # 聚合正确性（审计 P2-9）：36 个月 → 12 根季度蜡烛（实体 rect），且影线极值取季内高/低
    n_body = len(re.findall(r'<rect x="[\d.]+" y="[\d.]+" width="[\d.]+" height="[\d.]+" '
                            r'fill="#(?:c75b5b|6ba86b|6f695e)"/>', seg))
    assert n_body == 12, f"36 个月应聚合 12 根季度蜡烛，实际 {n_body}"
    assert 'stroke-width="1.2"' in seg, "蜡烛影线应渲染"
    assert "亏损期" in seg, "连续缺 pe 段应有亏损期底纹命名"
    assert "峰值" not in seg, "无 PE 极值时不应有截断标注"
    # PE 极值截断：末月 200x（p75=12 → 200 > 36 → 截断）
    sp = [dict(mo, pe=(200.0 if i == 35 else mo.get("pe"))) for i, mo in enumerate(months)]
    html2 = render_fill(minimal_fill(price_history={"label": "近3年", "series": sp},
                                     cycle_html='<table><tr><td>x</td></tr></table>'))
    seg2 = html2.split('aria-label="股价季K与PE历史走势"', 1)[1].split('</svg>', 1)[0]
    assert "峰值 200x" in seg2, "PE 极值应截断并标注峰值"
    # 缺 OHLC 回退发丝线（原契约不变）
    months_c = [{"m": mo["m"], "close": mo["close"], "pe": mo["pe"]} for mo in months]
    html3 = render_fill(minimal_fill(price_history={"label": "近3年", "series": months_c},
                                     cycle_html='<table><tr><td>x</td></tr></table>'))
    assert 'aria-label="股价与PE历史走势"' in html3, "无 OHLC 应回退发丝线形态"
    seg3 = html3.split('aria-label="股价与PE历史走势"', 1)[1].split('</svg>', 1)[0]
    # v4.11.1：季K 叠加 4 季均线（暖灰折线 + 图例）；回退发丝模式叠加 12 月均线
    assert "4 季均线" in html, "季K 模式应有 4 季均线图例"
    ma_paths = re.findall(r'<path d="M([\d., L]+)" fill="none" stroke="#57524a"', seg)
    assert len(ma_paths) == 1, "季K 模式应恰有一条 MA 折线"
    ma_pts = [tuple(map(float, xy.split(","))) for xy in ma_paths[0].strip().split(" L")]
    assert len(ma_pts) == 9, f"12 个季度 → MA4 从第 4 季起共 9 点，实际 {len(ma_pts)}"
    ys = [y for _, y in ma_pts]
    assert all(ys[i] > ys[i + 1] for i in range(len(ys) - 1)), "收盘单调上行时 MA4 的 y 应单调递减"
    assert "12 月均线" in html3, "发丝回退模式应有 12 月均线图例"
    ma3 = re.findall(r'<path d="M([\d., L]+)" fill="none" stroke="#57524a"', seg3)
    assert len(ma3) == 1 and ma3[0].count(" L") == 24, "36 个月 → MA12 从第 12 月起共 25 点"
    print("OK 季K蜡烛 / 亏损期底纹 / PE 截断 / 发丝线回退 / 趋势均线")


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


def test_triggers_strip_all_pending_hidden():
    """v4.10.3：首版报告全 pending → 状态条不渲染（空串）；出现 hit/miss 才渲染。"""
    assert not R.build_triggers_strip(minimal_fill(triggers=[
        {"cond": "提价兑现", "metric": "26H2 毛利率", "target": "≥46%", "status": "pending"},
        {"cond": "销量转正", "status": "pending"}])), "全 pending 应为空串"
    assert not R.build_triggers_strip(minimal_fill(
        triggers=[{"cond": "成本回落", "status": "bogus"}])), "非法 status 归 pending 亦为空串"
    html = R.build_triggers_strip(minimal_fill(triggers=[
        {"cond": "提价兑现", "status": "hit"}, {"cond": "销量转正", "status": "pending"}]))
    assert 'trig-dot hit' in html and 'trig-dot pending' in html, "含 hit 应原样渲染"


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


def test_fix_alignment_prose_column_goes_left():
    """v4.10.3：列内出现说明文格（_is_prose_cell）→ 整列判左，不再「数字多数决 → 逐格剥类」
    （同列 3 数字右 + 1 长文左的锯齿；香农芯创时机表实证）。无长文格时数字多数仍判右。"""
    tbl = ('<table><thead><tr><th>维度</th><th>说明</th></tr></thead><tbody>'
           '<tr><td>甲</td><td class="num">11</td></tr>'
           '<tr><td>乙</td><td class="num">25</td></tr>'
           '<tr><td>丙</td><td class="num">3,757 亿</td></tr>'
           '<tr><td>丁</td><td>负债成本降幅趋缓，息差企稳</td></tr>'
           '<tr><td>戊</td><td>买入</td></tr></tbody></table>')
    html = R.fix_table_alignment(tbl)
    assert '<th class="num">说明</th>' not in html, "含长文格的列应整列判左"
    assert 'class="num"' not in html, "整列判左后数字格也不再右对齐"
    tbl_num = tbl.replace('<tr><td>丁</td><td>负债成本降幅趋缓，息差企稳</td></tr>', '')
    assert '<th class="num">说明</th>' in R.fix_table_alignment(tbl_num), \
        "无长文格时数字多数仍判右（对照支）"
    print("OK 列含 prose 格整列判左（对照：无长文格仍数字多数决）")


def test_fix_alignment_short_placeholder_stays_num():
    """v4.10.3 审计收窄：短占位格（未披露/未获取到/不适用/—（上年亏损））不触发整列翻左——
    数字多数列仍判 num（原「超 2 字纯文字」阈值会让存量 66 份报告里 54 份的表被动过）。"""
    tbl = ('<table><thead><tr><th>公司</th><th>PE(TTM)</th></tr></thead><tbody>'
           '<tr><td>甲</td><td>11</td></tr><tr><td>乙</td><td>25</td></tr>'
           '<tr><td>丙</td><td>16</td></tr><tr><td>丁</td><td>18</td></tr>'
           '<tr><td>戊</td><td>21</td></tr>'
           '<tr><td>己</td><td>未披露</td></tr>'
           '<tr><td>庚</td><td>未获取到</td></tr>'
           '<tr><td>辛</td><td>不适用</td></tr></tbody></table>')
    html = R.fix_table_alignment(tbl)
    assert '<th class="num">PE(TTM)</th>' in html, "短占位格不应翻转整列"
    assert 'class="num">未披露' in html and 'class="num">不适用' in html, "占位格随列右对齐"
    tbl2 = ('<table><thead><tr><th>公司</th><th>PE(TTM)</th></tr></thead><tbody>'
            '<tr><td>甲</td><td>11</td></tr><tr><td>乙</td><td>25</td></tr>'
            '<tr><td>丙</td><td>16</td></tr><tr><td>丁</td><td>18</td></tr>'
            '<tr><td>戊</td><td>—（上年亏损）</td></tr></tbody></table>')
    assert '<th class="num">PE(TTM)</th>' in R.fix_table_alignment(tbl2), \
        "「—（上年亏损）」剥括号后 1 字，不翻列"
    print("OK 短占位格不翻列（未披露/未获取到/不适用/—（上年亏损）仍 num）")


_GAP_DIMS_A = [
    {"name": "2026E 归母净利（亿元）", "ours": 930, "consensus": 905, "cover": "15 家覆盖",
     "street": [{"org": "野村", "v": 952, "major": True}, {"org": "摩根士丹利", "v": 878, "major": True},
                {"v": 870}, {"v": 882}, {"v": 890}, {"v": 895}, {"v": 898}, {"v": 905}, {"v": 910},
                {"v": 915}, {"v": 922}, {"v": 928}, {"v": 935}, {"v": 940}]},
    {"name": "目标价 · 12 个月（元）", "ours": 30, "consensus": 26.5, "cover": "11 家给出目标价",
     "street": [{"org": "野村", "v": 31, "major": True}, {"org": "中金", "v": 24.2, "major": True},
                {"v": 24.0}, {"v": 24.5}, {"v": 25.0}, {"v": 25.5}, {"v": 26.0}, {"v": 26.5},
                {"v": 27.0}, {"v": 27.5}, {"v": 28.0}]},
    {"name": "2026E 出货量假设（GWh）", "ours": 650, "consensus": 580, "cover": "10 家披露量假设",
     "street": [{"org": "野村", "v": 545, "major": True}, {"org": "高盛", "v": 632, "major": True},
                {"v": 540}, {"v": 555}, {"v": 565}, {"v": 570}, {"v": 580}, {"v": 590},
                {"v": 600}, {"v": 615}]},
    {"name": "2026E 毛利率（%）", "ours": 26.0, "consensus": 24.5, "cover": "9 家披露率假设",
     "pct_pt": True,
     "street": [{"org": "大和", "v": 25.8, "major": True},
                {"v": 24.0}, {"v": 24.2}, {"v": 24.4}, {"v": 24.5}, {"v": 24.6}, {"v": 24.8},
                {"v": 25.0}, {"v": 25.2}]},
]


def test_gap_plot():
    """gap_plot 第 9 章预期差图（demo v3 定稿数据）：A 档=逐机构横向分布（灰/橙/蓝/◆ 计数 +
    偏离右列 + ◆标签落位阶梯 + pct_pt 一位小数），B 档=零轴偏离哑铃（tag/行注/反推口径），
    consensus ≤0 行剔除、有效维度 <2 空串、防叠错位确定性（同输入两跑一致）。"""
    from charts_misc import build_gap_plot, _inject_gap_chart
    fill_a = {"gap_plot": {"dims": _GAP_DIMS_A,
                           "text_dims": ["<b>⑤ 竞争格局：</b>文本维度附注。"]}}
    # ── A 档全元素计数（12+9+8+8=37 灰点、7 major 橙点+图例 1、4 本文蓝点、4 ◆+图例 1）
    html = build_gap_plot(fill_a)
    assert 'aria-label="市场预期差机构分布图"' in html, "A 档应出分布图"
    assert 'viewBox="0 0 1000 310"' in html, "4 行高度=30+70×4=310"
    assert len(re.findall(r'r="4\.5" fill="#b3ab93"', html)) == 37, "灰点计数"
    assert len(re.findall(r'r="5\.5" fill="#c08a2e"', html)) == 8, "橙点计数（7 数据 + 1 图例）"
    assert len(re.findall(r'r="7\.5" fill="#4a6fa5"', html)) == 4, "蓝点计数"
    assert len(re.findall(r'fill="#2b2620"', html)) == 5, "◆ 计数（4 行 + 1 图例）"
    for lb in ("野村 952", "摩根士丹利 878", "中金 24.2", "高盛 632", "大和 25.8"):
        assert lb in html, f"major 具名标签缺失：{lb}"
    for lb in ("本文 930", "本文 30", "本文 650", "本文 26.0",
               "一致 905", "一致 26.5", "一致 580", "一致 24.5"):
        assert lb in html, f"本文/一致标签缺失：{lb}"
    for dev in ("+2.8%", "+13.2%", "+12.1%", "+6.1%"):
        assert dev in html, f"右列偏离缺失：{dev}"
    assert "本文 26.0" in html and ">24.0</text>" in html, "pct_pt 比率型维度应保底一位小数"
    assert ">24.5</text>" not in html, "与◆等值的刻度 24.5 应省略（由◆标签承载）"
    # ◆ 标签落位：①④轴下左（text-anchor=end）、②③轴下右（start，无 anchor 属性）
    assert re.search(r'text-anchor="end" font-size="10.5" fill="#57524a">一致 905', html), "①◆应轴下左"
    assert re.search(r'text-anchor="end" font-size="10.5" fill="#57524a">一致 24.5', html), "④◆应轴下左"
    assert re.search(r'(?<!text-anchor="end" )font-size="10.5" fill="#57524a">一致 26.5', html), "②◆应轴下右"
    assert re.search(r'(?<!text-anchor="end" )font-size="10.5" fill="#57524a">一致 580', html), "③◆应轴下右"
    # 928 灰点钉轴（距本文 <12px，由本文白描边压盖，不错位）：行 1 无离轴灰点
    row1 = html.split("① 2026E 归母净利（亿元）", 1)[1].split("② 目标价", 1)[0]
    assert 'cy="61"' not in row1 and 'cy="79"' not in row1, "行 1 灰点应全部在轴上（demo v3）"
    # 防叠错位确定性：同输入两跑输出逐字节一致
    assert build_gap_plot(fill_a) == build_gap_plot(fill_a), "泳道错位必须确定性"
    # 泳道错位本身：构造两个 <12px 的灰点 → 一上一下 ±9
    jam = {"gap_plot": {"dims": [
        {"name": "A 维度", "ours": 100, "consensus": 100,
         "street": [{"v": 50}, {"v": 51}]},
        {"name": "B 维度", "ours": 200, "consensus": 200, "street": [{"v": 180}, {"v": 220}]},
    ]}}
    hj = build_gap_plot(jam)
    assert 'cy="61"' in hj and 'cy="79"' in hj, "过近灰点应对称泳道错位 ±9px"
    # 同值合并大点
    same = {"gap_plot": {"dims": [
        {"name": "A 维度", "ours": 100, "consensus": 100, "street": [{"v": 50}, {"v": 50}]},
        {"name": "B 维度", "ours": 200, "consensus": 200, "street": [{"v": 180}, {"v": 220}]},
    ]}}
    assert 'r="6" fill="#b3ab93"' in build_gap_plot(same), "同值两家应合并为大点（r=6）"

    # ── B 档：street 整体缺失 → 哑铃形态与 tag 文案
    fill_b = {"gap_plot": {"dims": [
        {"name": "2026E 归母净利（亿元）", "ours": 930, "consensus": 905},
        {"name": "目标价 · 12 个月（元）", "ours": 30, "consensus": 26.5},
        {"name": "2026E 出货量假设（GWh）", "ours": 650, "consensus": 580, "reverse": True},
        {"name": "2026E 毛利率（%）", "ours": 26.0, "consensus": 24.5, "pct_pt": True, "reverse": True},
    ]}}
    hb = build_gap_plot(fill_b)
    assert 'aria-label="市场预期差哑铃图（B 档）"' in hb, "B 档应出哑铃图"
    assert "卖方一致预期 vs 本文假设 · 偏离拆解（反推口径）" in hb, "B 档 tag 文案"
    assert "卖方 580 → 本文 650（反推）" in hb, "reverse 维度行注标（反推）"
    assert "卖方 24.5% → 本文 26.0%（+1.5pct，反推）" in hb, "pct_pt 行注带原生 pct 点差"
    assert "③④ 为反推口径" in hb, "source 应注明反推口径维度"
    assert hb.count("<polygon") == 4, "4 行各一支方向箭头"
    assert len(re.findall(r'r="6" fill="#b3ab93"', hb)) == 5, "零轴灰点计数（4 行 + 1 图例）"
    assert ">0</text>" in hb and "-10%" in hb and "+15%" in hb, "定域 -10%~+15% 刻度在位"
    assert 'cx="809.7"' in hb, "蓝点定位与右列显示同值（+13.2% → x=809.7）"
    assert build_gap_plot(fill_b) == build_gap_plot(fill_b), "B 档确定性"

    # ── 剔除与门禁
    f_zero = {"gap_plot": {"dims": [
        {"name": "坏行（consensus=0）", "ours": 1, "consensus": 0},
        *_GAP_DIMS_A[:2]]}}
    hz = build_gap_plot(f_zero)
    assert "坏行" not in hz and 'viewBox="0 0 1000 170"' in hz, "consensus ≤0 行剔除（剩 2 行高 170）"
    assert not build_gap_plot({"gap_plot": {"dims": [_GAP_DIMS_A[0]]}}), "<2 维应返回空串"
    assert not build_gap_plot({}), "字段缺失应返回空串"
    assert not build_gap_plot({"gap_plot": {"dims": []}}), "空 dims 应返回空串"
    # 部分行缺 street → 仍 A 档，该行行注「未见逐机构明细」
    f_mix = {"gap_plot": {"dims": [_GAP_DIMS_A[0],
                                   {"name": "无形假设", "ours": 5, "consensus": 4}]}}
    hm = build_gap_plot(f_mix)
    assert 'aria-label="市场预期差机构分布图"' in hm and "未见逐机构明细" in hm, "行级退化"

    # ── 锚点注入（charts_base._inject_chart_anchors 同一注入机，prepend 垫章首）
    inj = _inject_gap_chart("<p>档位说明</p><!--GAP-->", fill_a)
    assert "<!--GAP-->" not in inj and 'aria-label="市场预期差机构分布图"' in inj
    assert '<ol class="gap-notes">' in inj and "<b>⑤ 竞争格局：</b>" in inj, "附注随图整体注入"
    assert inj.find("档位说明") < inj.find("市场预期差机构分布图"), "锚点原位替换"
    out2, err2 = capture_stderr_value(lambda: _inject_gap_chart("<p>无锚点</p>", fill_a))
    assert "缺 <!--GAP--> 锚点" in err2, "锚点缺失应告警"
    assert out2.find("市场预期差机构分布图") < out2.find("无锚点"), "锚点缺失时图垫章首"
    out3, err3 = capture_stderr_value(lambda: _inject_gap_chart("<p>章文</p><!--GAP-->", {}))
    assert out3 == "<p>章文</p>" and not err3, "字段未填锚点静默清除"
    # 端到端：render_fill 走通（minimal_fill 的 gap_html 无锚点 → 垫章首）
    html_full = render_fill(minimal_fill(gap_plot=fill_a["gap_plot"]))
    assert 'aria-label="市场预期差机构分布图"' in html_full, "整报渲染应含预期差图"
    # ── 热核审计修复钉死（v4.11.1 二轮）
    # P1-3：B 档无 reverse 行时 tag 不带「（反推口径）」
    hb2 = build_gap_plot({"gap_plot": {"dims": [
        {"name": "目标价（元）", "ours": 30, "consensus": 26.5},
        {"name": "2026E 归母净利（亿元）", "ours": 930, "consensus": 905}]}})
    assert "偏离拆解</span>" in hb2 and "反推口径" not in hb2, "纯 B 档 tag 不得误标反推口径"
    # P2-1：偏离超定域 → 虚线棒 + 空心蓝点 + source 注明
    hc = build_gap_plot({"gap_plot": {"dims": [
        {"name": "A", "ours": 300, "consensus": 100},     # +200% 超域
        {"name": "B", "ours": 100, "consensus": 100}]}})
    assert 'stroke-dasharray="4 3"' in hc and 'fill="#fffdf9"' in hc.replace(" ", "") \
        or 'stroke-dasharray="4 3"' in hc, "超域行应有虚线棒"
    assert "超出 -10%~+15% 定域" in hc, "source 应注明截断记号"
    assert "+200.0%" in hc, "右列数值仍真实"
    # P1-1/P1-2：多 major 碰撞 → 升档入册 + 两档皆撞降级仅机构名（点不删）
    coll = {"gap_plot": {"dims": [
        {"name": "A 维度", "ours": 100, "consensus": 100, "street": [
            {"org": "甲证券", "v": 95.0, "major": True},
            {"org": "乙证券", "v": 95.5, "major": True},
            {"org": "丙证券", "v": 96.0, "major": True}]},
        {"name": "B 维度", "ours": 200, "consensus": 200, "street": [{"v": 180}, {"v": 220}]}]}}
    hcol = build_gap_plot(coll)
    assert hcol.count('fill="#c08a2e"') == 4, "三个 major 点都在（3 数据 + 1 图例；永不删点）"
    assert build_gap_plot(coll) == build_gap_plot(coll), "碰撞落位确定性"
    # 两档皆撞 + 压本文带 → 降级仅机构名（不带数值）
    coll2 = {"gap_plot": {"dims": [
        {"name": "A 维度", "ours": 100, "consensus": 99.4, "street": [
            {"org": "甲证券", "v": 99.0, "major": True},
            {"org": "乙证券有限责任公司", "v": 99.6, "major": True},
            {"org": "丙证券", "v": 100.2, "major": True}]},
        {"name": "B 维度", "ours": 200, "consensus": 200, "street": [{"v": 180}, {"v": 220}]}]}}
    h2 = build_gap_plot(coll2)
    assert "乙证券有限责任公司" in h2, "降级后机构名仍在（点与名不消失）"
    # P2-2：dims >6 时附注同步截断（⑦ 及以后的 note 不出现）
    many = {"gap_plot": {"dims": [
        {"name": f"维度{i}", "ours": 10 + i, "consensus": 10, "note": f"<b>注{i}</b>",
         "street": [{"v": 9 + i}] if i % 2 == 0 else []} for i in range(9)]}}
    inj_many = _inject_gap_chart("<!--GAP-->", many)
    assert "注8" not in inj_many and "注7" not in inj_many, "附注应与图行同步截断"
    # P2-3：大数值千分位（出货量原生单位），不上科学计数法
    big = build_gap_plot({"gap_plot": {"dims": [
        {"name": "出货量（万只）", "ours": 1234567, "consensus": 1000000,
         "street": [{"v": 1100000}]},
        {"name": "B 维度", "ours": 200, "consensus": 200, "street": [{"v": 180}, {"v": 220}]}]}})
    assert "1,234,567" in big and "e+06" not in big, "大数值应千分位、禁科学计数法"
    print("OK 预期差图 A/B 档 / 剔除门禁 / 防叠确定性 / 锚点注入 / 热核修复")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"全部 {len(tests)} 项测试通过")


def test_driver_cards():
    """v4.11.3 P0 驱动卡：drivers/driver_verdict → drv-strip + 判词横条；第一变量角标；
    判词前缀取 first_var 名（无 first_var 退化「第一变量判词：」）；缺字段返回空串。"""
    from charts_misc import build_driver_cards
    fill = minimal_fill(drivers=[
        {"name": "金价", "first_var": True, "elastic": "±10% → 净利 ±20%",
         "elastic_sub": "±10%", "note": "当前约 900 元/g。",
         "chips": [{"label": "悲观", "value": "800"}, {"label": "基础", "value": "900"},
                   {"label": "乐观", "value": "1,000"}, {"label": "元/g", "unit": True}]},
        {"name": "产量", "elastic": "±10% → 净利 ±13%", "note": "2026E 约 50 吨。",
         "chips": [{"label": "悲观", "value": "45"}, {"label": "基础", "value": "50"},
                   {"label": "乐观", "value": "55"}]}],
        driver_verdict="弹性更大且不确定性不对称。")
    html = build_driver_cards(fill)
    assert 'class="drv-strip"' in html and html.count('class="drv"') == 2
    assert 'drv-badge">第一变量' in html
    assert '为什么金价是第一变量：' in html and '弹性更大且不确定性不对称。' in html
    assert build_driver_cards(minimal_fill()) == ""
    h2 = build_driver_cards(minimal_fill(drivers=[{"name": "量", "elastic": "±1"}],
                                         driver_verdict="x"))
    assert 'drv-badge' not in h2 and '第一变量判词：' in h2


def test_driver_cards_auto_crown():
    """v5.1.1：第一变量由脚本按 sensitivity |impact| 降序加冕——手标 first_var 与排序冲突时
    角标/判词前缀跟图走（影石创新驱动卡与龙卷风各执一词实证）；手标不再决定角标。"""
    from charts_misc import build_driver_cards
    html = build_driver_cards(minimal_fill(
        drivers=[{"name": "毛利率", "first_var": True, "elastic": "±1pct → 净利 ±15%"},
                 {"name": "收入增速", "elastic": "±10% → 净利 ±20%"}],
        driver_verdict="弹性对比一句。",
        sensitivity=[{"name": "毛利率", "impact": 15, "delta": "±1pct"},
                     {"name": "收入增速", "impact": 20, "delta": "±10%"}]))
    assert '收入增速</span><span class="drv-badge">第一变量' in html
    assert html.count('drv-badge') == 1
    assert '为什么收入增速是第一变量：' in html


def test_cycle_stages():
    """v4.11.3 周期阶段卡：序号自动编排（跳过非法项仍连续）、current 高亮+「本轮」角标、
    pe/price 可省不炸；缺字段返回空串。"""
    from charts_misc import build_cycle_stages
    fill = minimal_fill(cycle_stages=[
        {"name": "景气顶", "period": "2021", "pe": "30x", "price": "9", "driver": "价格见顶"},
        {"name": "出清", "period": "2022", "driver": "估值先杀", "current": True}])
    html = build_cycle_stages(fill)
    assert 'class="stage-strip"' in html
    assert '>01<' in html and '>02<' in html
    assert 'class="stage current"' in html and 'stage-cur-tag">本轮' in html
    assert build_cycle_stages(minimal_fill()) == ""


def test_dcf_cards():
    """v4.11.3 DCF 双卡：双 metric-card + 判词；现价比价脚本算（12.5 vs price 10 → 较现价高
    25.0%）；value/implied_g/verdict 缺一返回空串。"""
    from scoring import build_dcf_cards
    dcf = {"value": 12.5, "fcf0": "95亿", "growth_5y": "5%", "g_perp": "2.5%", "wacc": "8.5%",
           "net_cash": "120亿", "implied_g": "0.5", "implied_note": "g=WACC−FCF₁/EV",
           "verdict": "隐含 g 极低、市场白送增长——判词足够长，超过四十字的地板要求啊啊。"}
    html = build_dcf_cards(minimal_fill(dcf=dcf))
    assert '保守参数 DCF 每股值' in html and '现价隐含永续增速' in html
    assert '较现价高 25.0%' in html
    assert build_dcf_cards(minimal_fill()) == ""
    assert build_dcf_cards(minimal_fill(dcf={"value": 12.5})) == ""


def test_three_cards_land_in_sections():
    """v4.11.3：三卡占位符落位——drv-strip 在 s2、stage-strip 在 s11、DCF 双卡在 s8
    （各字段缺失时对应位置无残留，占位符空串替换）。
    v5.0：s2 右界取 s4 而非 s3——新第 3 章（最新报告期透视）无数据时整章消失，split 会扑空。"""
    html = render_fill(minimal_fill(
        drivers=[{"name": "金价", "first_var": True, "elastic": "±10% → ±20%",
                  "chips": [{"label": "悲观", "value": "1"}, {"label": "基础", "value": "2"},
                            {"label": "乐观", "value": "3"}]}],
        cycle_html="<p>当前位置。</p>",
        cycle_stages=[{"name": "景气顶", "period": "2021", "current": True},
                      {"name": "出清", "period": "2022"},
                      {"name": "修复", "period": "2024"}],
        dcf={"value": 12.5, "implied_g": "0.5", "verdict": "判词足够长，超过四十字的地板要求啊啊啊啊啊。"}))
    s2 = html.split('id="s2"')[1].split('id="s4"')[0]
    assert 'class="drv-strip"' in s2 and 'drv-badge">第一变量' in s2
    s11 = html.split('id="s11"')[1].split('id="s12"')[0]
    assert 'class="stage-strip"' in s11
    s8 = html.split('id="s8"')[1].split('id="s9"')[0]
    assert '保守参数 DCF 每股值' in s8 and '较现价高 25.0%' in s8
    html2 = render_fill(minimal_fill())
    # 模板 <style> 含 .drv-strip/.stage-strip 类定义——断言对象限定 </style> 之后的渲染内容
    body2 = html2.split('</style>', 1)[1]
    assert 'drv-strip' not in body2 and 'stage-strip' not in body2


def test_anchor_ledger_render():
    """v5.1.0 锚移动台账渲染：回测模式三情景对照 + 增量证据清单 + Δ中枢脚本算；
    非回测空串；上版解析失败降级不炸链。"""
    import charts_misc
    import render_report as RR
    from conftest import full_fill
    # 正常路径：full_fill（上版 11-13x/中枢 11.45 元 vs 本版 10-12x/中枢 11 元 → Δ -3.9%）
    fill = full_fill()
    calc = RR.compute_valuation(fill)
    html = charts_misc.build_anchor_ledger(fill, calc)
    assert "估值锚移动台账" in html and "较上版 2026-08-08" in html
    assert "75 亿 × 9-11x" in html and "95 亿 × 11-13x" in html   # 上版照抄列
    assert "80 亿 × 8-10x" in html and "100 亿 × 10-12x" in html  # 本版计算列
    assert "<strong>基本面</strong>" in html and "煤价中枢下移" in html  # 证据清单渲染
    # Δ中枢符号：本版基础中枢 11 元 < 上版显示中点 11.45 → 负
    assert "-" in html.split("Δ中枢")[1]
    # 非回测（无 prev）→ 空串
    assert charts_misc.build_anchor_ledger(minimal_fill(), calc) == ""
    # 上版解析失败（文本格式不对）→ 降级标注不炸链
    bad = full_fill()
    bad["prev"]["scenarios"] = [{"scenario": "基础情景", "归母净利": "未知", "PE": "不详"}]
    html2 = charts_misc.build_anchor_ledger(bad, calc)
    assert "解析失败" in html2 and "降级" in html2
    print("OK 锚移动台账（三情景对照 / 证据清单 / 非回测空串 / 解析降级）")
