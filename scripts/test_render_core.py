#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_render_core.py — render_report 核心逻辑回归测试（无网络，直接 python 运行）

覆盖 v4.5 修复的关键路径：
- P0 回归：质量分 <4 → 最终仓位结论必须是「不建议参与」（而非观察池）
- 三情景按 key 取值：scenarios 含多余 key 且排在 base 前时中枢仍按 base 计算
- 年化中枢时间维度取 base 情景级 horizon
- 负扣分 / PE 区间倒挂 / timing 缺维 / yellow_deductions 缺键 → 拒渲染
- 带 BOM 的 fill JSON 可解析
- currency="港元" 时输出含「港元」
"""
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_report as R


def _dim(text):
    return f'<div class="dim-block"><p>{text}</p></div>'


def minimal_fill(**over):
    """最小合法 fill（能过 compute_scores + validate_content + compute_valuation_score）。"""
    long_text = "该维度分析：公司基本面稳健，数据支撑充分，论据详实可靠，行业地位稳固，具备长期参考价值。"
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
        "conclusion_html": "<p><strong>关键优势：</strong>" + "优势证据。" * 60 + "</p>",
        "p0_html": "<p>关键驱动分析。</p>",
        "l1_html": "".join(_dim(long_text) for _ in range(6)),
        "l3_html": "".join(_dim(long_text) for _ in range(3)),
        "l4_html": "<p>风险评估。</p>",
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
        "peers_html": ('<table><tr><td>同业</td></tr></table>'
                       '<span class="source">数据来源：测试</span>'),
        "next_review": "2026-11-27", "dash_html": "<p>仪表盘。</p>",
        "position_html": "<p>时机判定与决策逻辑。" * 12 + "</p>",
        "scores": {"1A": 7, "1B": 7, "1C": 7, "1D": 7, "1E": 7, "1F": 7,
                   "3A": 7, "3B": 7, "3C": 7},
        "timing_scores": {"筹码面": 5, "技术面": 5},
        "yellow_deductions": [],
    }
    fill.update(over)
    return fill


def _calc(dispersion=0.55, odds=1.2):
    """手造估值 calc（只含 build_position_card 用到的键）。"""
    return {"central_raw": 0.15, "central": 0.15,
            "dispersion": dispersion, "odds": odds}


def test_p0_low_quality_not_observation_pool():
    """P0 回归：quality <4 时最终仓位结论必须是「不建议参与」。"""
    html = R.build_position_card(minimal_fill(), quality=3.5, valuation=5.0,
                                 timing=5.0, calc=None, red_flag="")
    assert "不建议参与" in html, "质量<4 应得「不建议参与」"
    assert "观察池" not in html, "质量<4 不得落入观察池分支"


def test_uplift_cap_blocks_heavy_from_light():
    """上浮封顶：质地一般（4.27×4.3）落轻仓，时机+离散度+赔率三连浮
    合计净效应 ≤1 档 → 最终标准仓 ≤10%，绝不允许重仓 ≤20%。"""
    html = R.build_position_card(minimal_fill(), quality=4.27, valuation=4.3,
                                 timing=7.0, calc=_calc(dispersion=0.30, odds=None),
                                 red_flag="")
    assert "矩阵落位：质量 4.27 × 估值 4.3 → 质地一般 → 轻仓 ≤5%" in html, \
        "落位文案缺失"
    assert "标准仓 ≤10%" in html, f"应止步标准仓，实际：{html}"
    assert "重仓 ≤20%" not in html, "轻仓不得被调节目测推成重仓"
    assert "上浮封顶" in html, "被拦的上浮项应在轨迹中说明"


def test_down_floors_at_zero():
    """下调兜底：轻仓落位 + 时机差(<4)降一档到 0 后，高离散度再触发下调必须
    兜底在 0，不得经 Python 负索引回卷成重仓 ≤20%。"""
    html = R.build_position_card(minimal_fill(), quality=4.27, valuation=4.3,
                                 timing=3.5, calc=_calc(dispersion=0.95),
                                 red_flag="")
    assert "不建议参与" in html, "两连降至底应为「不建议参与」（0 兜底）"
    assert "重仓" not in html, "负索引回卷会把兜底档错误显示为重仓"


def test_matrix_direct_entry_to_heavy_untouched():
    """好公司·好价格（≥7 × ≥8）矩阵直落重仓不受封顶误伤；此时调节全被
    封顶/顶格拦截且不产生噪音条目以外的误导。"""
    html = R.build_position_card(minimal_fill(), quality=7.2, valuation=8.5,
                                 timing=5.0, calc=_calc(),
                                 red_flag="")
    assert "重仓 ≤20%" in html, "矩阵直落重仓必须保留"


def test_scenario_lookup_by_key():
    """scenarios 含多余 key 且排在 base 前：中枢必须仍按 base 计算。"""
    fill = minimal_fill()
    fill["valuation"]["scenarios"] = [
        {"key": "pess", "label": "悲观", "profit": 80, "pe": [8, 10]},
        {"key": "xtra", "label": "干扰", "profit": 1, "pe": [1, 1]},   # 极值，取错即暴露
        {"key": "base", "label": "基础", "profit": 100, "pe": [10, 12]},
        {"key": "opt", "label": "乐观", "profit": 120, "pe": [12, 14]},
    ]
    calc = R.compute_valuation(fill)
    assert abs(calc["central_raw"] - (11 / 10 - 1)) < 1e-9, \
        f"中枢应来自 base 情景（中值 11），实际 {calc['central_raw']}"


def test_horizon_from_base_scenario():
    """horizon 只写在 base 情景级时，年化按 base 的时长（2 年 = 24 个月）。"""
    fill = minimal_fill()
    del fill["valuation"]["horizon"]
    fill["valuation"]["scenarios"][1]["horizon"] = "2年"
    calc = R.compute_valuation(fill)
    assert calc["months"] == 24.0, f"应按 base 情景 horizon 年化（24 个月），实际 {calc['months']}"


def _expect_valueerror(fill, msg):
    try:
        R.compute_scores(fill)
        R.validate_content(fill, R.compute_valuation(fill))
    except ValueError:
        return
    raise AssertionError(f"应拒渲染但未拒：{msg}")


def test_rejections():
    _expect_valueerror(minimal_fill(yellow_deductions=[{"label": "x", "points": -0.5}]),
                       "黄灯负扣分")
    f = minimal_fill(); f["red_deductions"] = [{"item": "x", "points": -1}]
    _expect_valueerror(f, "红旗负扣分")
    f = minimal_fill(); f["valuation"]["scenarios"][0]["pe"] = [10, 8]
    _expect_valueerror(f, "PE 区间倒挂")
    f = minimal_fill(); del f["timing_scores"]["技术面"]
    _expect_valueerror(f, "timing_scores 缺维")
    f = minimal_fill(); del f["yellow_deductions"]
    _expect_valueerror(f, "yellow_deductions 缺键")
    f = minimal_fill(); f["date"] = "2026/08/27"
    _expect_valueerror(f, "date 格式非法")
    f = minimal_fill(); f["price"] = "未知"
    _expect_valueerror(f, "price 非数字")


def test_fmt_thousands():
    """Hero 金额卡千位符归一：裸数字补逗号，已有逗号幂等，<1000/非数字不动，price 类不走此路。"""
    assert R._fmt_thousands("10330.7") == "10,330.7"
    assert R._fmt_thousands("10,330.7") == "10,330.7"
    assert R._fmt_thousands("999.9") == "999.9"
    assert R._fmt_thousands("188153") == "188,153"
    assert R._fmt_thousands("—") == "—"
    assert R._fmt_thousands("23.34万") == "23.34万"  # 带单位不归一
    print("OK 千位符归一（补逗号 / 幂等 / <1000 不动 / 非数字不动）")


def test_quote_consistency():
    """quote 防伪（神华事故修复）：一致过 / 偏差>1% 拒 / 源文件读不到拒 / 缺 quote 仅告警不拒。"""
    with tempfile.TemporaryDirectory() as d:
        ref = os.path.join(d, "_em_quote.json")
        with open(ref, "w", encoding="utf-8") as fp:
            json.dump({"price": 10.0, "pe_ttm": 11.0}, fp)
        f = minimal_fill(quote={"source_file": ref, "date": "2026-08-27"})
        R.validate_content(f, R.compute_valuation(f))  # 一致 → 过
        f["price"] = "10.05"  # 0.5% 偏差 → 仍过
        R.validate_content(f, R.compute_valuation(f))
        f["price"] = "10.5"  # 5% 偏差 → 拒
        _expect_valueerror(f, "price 与落盘值偏差>1%")
        f = minimal_fill(quote={"source_file": os.path.join(d, "不存在.json"),
                                "date": "2026-08-27"})
        _expect_valueerror(f, "quote.source_file 读不到")
        # 缺 quote → 不拒（告警走 stderr）
        g = minimal_fill()
        R.validate_content(g, R.compute_valuation(g))
    print("OK quote 防伪（一致过 / 0.5%过 / 5%拒 / 文件缺失拒 / 缺字段不拒）")


def test_bom_fill_loads():
    """带 BOM 的 UTF-8 fill JSON 必须可解析。"""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "_fill_t.json")
        with open(p, "w", encoding="utf-8-sig") as fp:  # 写带 BOM
            json.dump(minimal_fill(), fp, ensure_ascii=False)
        fill = R._load_fill(p)
    assert fill["company"] == "测试股份"


def test_currency_hkd():
    """currency="港元"：输出 HTML 含「港元」，情景表目标价行不用默认「元」。"""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "_fill_t.json")
        with open(p, "w", encoding="utf-8") as fp:
            json.dump(minimal_fill(currency="港元"), fp, ensure_ascii=False)
        out = R.render(p, out_path=os.path.join(d, "out.html"))
        html = open(out, encoding="utf-8").read()
    assert "港元" in html, "输出应含「港元」"
    assert "10-12 港元" in html, "情景表目标价行应用港元"
    assert "{{CUR}}" not in html, "{{CUR}} 必须被替换"


def test_nice_ticks():
    """nice-number 刻度：步长取 1/2/2.5/5×10^k，刻度为步长整数倍且落在值域内。"""
    assert R._ticks(19, 69) == [20, 40, 60]
    assert R._ticks(0, 10, 6) == [0, 2, 4, 6, 8, 10]
    t3 = R._ticks(8.7, 34.6)
    assert t3 == [10, 20, 30], f"实际 {t3}"
    t4 = R._ticks(0.22, 0.88)
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
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "_fill_t.json")
        with open(p, "w", encoding="utf-8") as fp:
            json.dump(minimal_fill(**extra), fp, ensure_ascii=False)
        out = R.render(p, out_path=os.path.join(d, "out.html"))
        html = open(out, encoding="utf-8").read()
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
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "_fill_t.json")
        with open(p, "w", encoding="utf-8") as fp:
            json.dump(minimal_fill(), fp, ensure_ascii=False)
        out = R.render(p, out_path=os.path.join(d, "out.html"))
        html2 = open(out, encoding="utf-8").read()
    for label in ("敏感性龙卷风", "PE(TTM)历史带"):
        assert f'aria-label="{label}"' not in html2, f"缺字段时图应整块删除：{label}"
    assert 'aria-label="九维评分分布"' in html2, "评分横条图数据现成，应始终生成"
    assert 'class="toc-side"' in html2 and 'href="#s11"' in html2, "侧栏目录应生成且指向章节锚点"


def test_tornado_long_names():
    """v4.8.2：龙卷风变量名列自适应——超长名折两行、NL/X0/HALF 随最长行宽动态取值，
    文本不越出画布左缘；未超宽名称单行完整渲染。"""
    import re as _re
    long_name = "产业互联网创新业务与新兴信息通信业务资本开支强度边际变化"  # 28 字 ≈ 364px + 后缀 → 超 388 折行
    fill = minimal_fill(sensitivity=[
        {"name": long_name, "impact": 20, "delta": "±10%", "amount": "净利约±9-10亿元"},
        {"name": "移动 ARPU 值", "impact": 13},
        {"name": "金价", "impact": 8}])
    html = R.build_sensitivity_tornado(fill)
    assert 'aria-label="敏感性龙卷风"' in html
    assert long_name not in html, "超长名应折行（不应单行完整出现）"
    plain = _re.sub(r"<[^>]+>", "", html)
    for piece in ("产业互联网", "边际变化", "（第一变量）"):
        assert piece in plain, f"折行后名称缺段：{piece}"
    xs = [float(m) for m in _re.findall(r'\bx="(-?[\d.]+)"', html)]
    assert xs and min(xs) >= 0, f"文本越出画布左缘：min x = {min(xs)}"
    # 中等长度名（name+后缀 ≈ 260px > 218）：名称列扩宽但不折行，单行完整出现
    mid = "传统固网宽带业务资本开支变化"
    html2 = R.build_sensitivity_tornado(minimal_fill(sensitivity=[
        {"name": mid, "impact": 20}, {"name": "金价", "impact": 8}]))
    assert mid + "（第一变量）" in html2, "未超宽名称应单行完整渲染"
    xs2 = [float(m) for m in _re.findall(r'\bx="(-?[\d.]+)"', html2)]
    assert min(xs2) >= 0, f"名称列扩宽后文本越界：min x = {min(xs2)}"


def test_review_dumbbell():
    """回测模式：prev 填了才出三轨哑铃图；回测章=第 12 章（v4.8.1 起提前，在跟踪仪表盘之前）。"""
    fill = minimal_fill(prev={"date": "2026-08-08", "quality": 7.0, "valuation": 5.5,
                              "timing": 5.0, "target_range": "10-12"},
                        review_html='<table><tr><td>假设变更对比</td></tr></table>'
                                    '<span class="source">数据来源：测试</span>'
                                    '<span class="rev">甲</span><span class="rev">乙</span><span class="rev">丙</span>')
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "_fill_t.json")
        with open(p, "w", encoding="utf-8") as fp:
            json.dump(fill, fp, ensure_ascii=False)
        out = R.render(p, out_path=os.path.join(d, "out.html"))
        html = open(out, encoding="utf-8").read()
    assert 'aria-label="三轨分新旧对比"' in html, "回测模式应生成哑铃图"
    assert 'id="s12"' in html and "回测复盘" in html, "回测章节应出现（v4.8.1 起为第 12 章）"
    assert html.find('id="s12"') < html.find('id="s13"'), "回测复盘应排在跟踪仪表盘（s13）之前"


def test_peers_caliber_warn():
    """peers_plot 口径一致性：目标点 PE 与 valuation_inputs.pe_ttm 偏差 >30% → 告警（不拒渲染）。"""
    import contextlib
    import io
    fill = minimal_fill(peers_plot={"points": [
        {"name": "测试股份", "roe": 20, "pe": 20, "target": True},  # vs pe_ttm 11 → 偏差 82%
        {"name": "同业甲", "roe": 15, "pe": 18}]})
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        R.validate_content(fill, R.compute_valuation(fill))
    assert "偏差 >30%" in buf.getvalue(), "口径偏差 >30% 应告警"
    fill2 = minimal_fill(peers_plot={"points": [
        {"name": "测试股份", "roe": 20, "pe": 11, "target": True},
        {"name": "同业甲", "roe": 15, "pe": 18}]})
    buf2 = io.StringIO()
    with contextlib.redirect_stderr(buf2):
        R.validate_content(fill2, R.compute_valuation(fill2))
    assert "偏差 >30%" not in buf2.getvalue(), "口径一致不应告警"


def test_peers_label_within_bounds():
    """右缘点位标签不得越出 SVG 宽度（v4.8 修复回归：右缘公司标签曾被画布裁切）。"""
    import re as _re
    html = R.build_peers_plot({"peers_plot": {"points": [
        {"name": "目标公司", "roe": 20, "pe": 15, "target": True},
        {"name": "右缘同业", "roe": 10, "pe": 31.06},
        {"name": "左缘同业", "roe": 25, "pe": 13.3}]}})
    assert html, "散点图应生成"
    found = False
    for m in _re.finditer(r'<text x="([\d.]+)"([^>]*)>([^<]*)</text>', html):
        x, attrs, txt = float(m.group(1)), m.group(2), m.group(3)
        if "右缘同业" not in txt:
            continue
        found = True
        w = R._text_w(txt, 12)
        anchor = "end" if 'text-anchor="end"' in attrs else ("middle" if 'text-anchor="middle"' in attrs else "start")
        x0 = x - w if anchor == "end" else (x - w / 2 if anchor == "middle" else x)
        assert x0 >= 0 and x0 + w <= 1000, f"标签越界: {txt} x0={x0:.0f} w={w:.0f}"
    assert found, "右缘同业标签未渲染"


def test_writing_discipline_warns():
    """v4.7.1 写作纪律告警：四拍挤段 / 三年并排 / pe_history 无第 10 章承载。"""
    import contextlib
    import io

    def capture(fill):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            R.validate_content(fill, R.compute_valuation(fill))
        return buf.getvalue()

    # 四拍挤段：同一 <p> 含 ≥2 个拍名 → 告警
    l1 = ('<div class="dim-block"><p><strong>判词：</strong>矿山服务龙头，海外占比 72% 是核心阿尔法。'
          '<strong>论据：</strong>2025 年报海外毛利 31.2 亿（+24%），续约率 91%（年报 P17）。'
          '<strong>评分：</strong>8.0——护城河在长期服务协议锁定，铜价下行期续约率是唯一先行指标。</p></div>')
    fill4beat = minimal_fill(l1_html="".join(_dim("该维度分析：公司基本面稳健，数据支撑充分，论据详实可靠，"
                                                  "行业地位稳固，具备长期参考价值。") for _ in range(5)) + l1)
    assert "四拍挤段" in capture(fill4beat), "四拍挤段应告警"
    l1_ok = "".join(_dim("该维度分析：公司基本面稳健，数据支撑充分，论据详实可靠，"
                         "行业地位稳固，具备长期参考价值。") for _ in range(6))
    assert "四拍挤段" not in capture(minimal_fill(l1_html=l1_ok)), "分段的四拍不应告警"
    # 三年并排：连续三个年份 th / td 内年份:数值堆叠 → 告警
    peers = ('<table><thead><tr><th>指标</th><th>2023</th><th>2024</th><th>2025</th></tr></thead>'
             '<tbody><tr><td>ROE变化</td><td>8.0</td><td>15.2</td><td>30.8</td></tr></tbody></table>'
             '<span class="source">来源：mx 批量</span>')
    assert "三年数字并排" in capture(minimal_fill(peers_html=peers)), "三年并排应告警"
    peers_stacked = ('<table><thead><tr><th>指标</th><th>3年走势</th></tr></thead>'
                     '<tbody><tr><td>归母净利</td><td>2023: 8.0，2024: 15.2，2025: 30.8</td></tr></tbody></table>'
                     '<span class="source">来源：mx 批量</span>')
    assert "三年数字并排" in capture(minimal_fill(peers_html=peers_stacked)), "td 内年份堆叠应告警"
    peers_ok = ('<table><thead><tr><th>指标</th><th>同业甲</th></tr></thead>'
                '<tbody><tr><td>ROE变化</td><td>8.0→30.8（大升）</td></tr></tbody></table>'
                '<span class="source">来源：mx 批量</span>')
    assert "三年数字并排" not in capture(minimal_fill(peers_html=peers_ok)), "起→终格式不应告警"
    # pe_history 与第 10 章绑定：cycle_html 缺失 → 告警；填了 → 不告警
    ph = {"hist_lo": 13.7, "hist_hi": 83.2}
    assert "cycle_html 缺失" in capture(minimal_fill(pe_history=ph)), "pe_history 无第 10 章承载应告警"
    fill_ok = minimal_fill(pe_history=ph, cycle_html='<p>周期阶段分析正文，非空即渲染整章。</p>')
    assert "cycle_html 缺失" not in capture(fill_ok), "cycle_html 已填不应告警"


def test_segments_chain_charts():
    """v4.8 业务构成图（3.1 锚点 <!--SEGMENTS-->）与产业链图（3.2 锚点 <!--CHAIN-->）：
    锚点在位→原位替换；锚点缺失→追加章末+告警；字段缺失→锚点静默清除；占比和偏离→告警。"""
    import contextlib
    import io
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
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "_fill_t.json")
        with open(p, "w", encoding="utf-8") as fp:
            json.dump(fill, fp, ensure_ascii=False)
        out = R.render(p, out_path=os.path.join(d, "out.html"))
        html = open(out, encoding="utf-8").read()
    assert 'aria-label="业务构成"' in html, "业务构成图应生成"
    assert 'aria-label="产业链位置"' in html, "产业链图应生成"
    assert "<!--SEGMENTS-->" not in html and "<!--CHAIN-->" not in html, "锚点必须被替换"
    assert "毛利 56.8亿（占 62%）" in html, "柱下应标注毛利与毛利占比（_fmt 为 %g，62.0→62）"
    assert "利润口径为毛利" in html, "毛利口径注记必须在位（分部净利无公开披露）"
    assert "上游 · 供给端" in html and "煤制烯烃一体化" in html, "产业链三栏与公司定位注应渲染"
    # 锚点缺失但字段已填 → 追加第 3 章末尾 + stderr 告警
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        l1_no_anchor = "".join(f'<div class="dim-block"><p>{long_text}</p></div>' for _ in range(6))
        fill2 = minimal_fill(l1_html=l1_no_anchor, **extra)
        html2 = R._fill_template(R._build_repl_map(
            fill2, "元", R.compute_valuation(fill2), R.compute_scores(fill2), 5.5,
            R.compute_valuation_score(R.compute_valuation(fill2), fill2["valuation_inputs"]),
            None, "", fill2["date"], fill2["subtitle"], "10-12", fill2["peers_html"],
            R.build_scenario_spectrum(fill2, R.compute_valuation(fill2)),
            R.build_scenario_block(R.compute_valuation(fill2), "元"),
            R.build_peers_plot(fill2)))
    assert "缺 <!--SEGMENTS--> 锚点" in buf.getvalue(), "锚点缺失应告警"
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
    buf2 = io.StringIO()
    with contextlib.redirect_stderr(buf2):
        R.validate_content(bad, R.compute_valuation(bad))
    assert "偏离 100%" in buf2.getvalue(), "占比和偏离 100% 应告警"
    # v4.8.2：横条图——长名折两行不挤压、高度随行数自适应（不再固定 360）、毛利率圆点在位
    fill4 = minimal_fill(segments={"items": [
        {"name": "固网宽带及数据服务与产业互联网创新业务", "rev_pct": 45.0, "gross_margin": 30.0},
        {"name": "移动业务", "rev_pct": 35.0, "gross_margin": 40.0},
        {"name": "其他", "rev_pct": 20.0}]})
    html4 = R.build_segments_plot(fill4)
    assert 'aria-label="业务构成"' in html4
    assert "固网宽带及数据服务与产业互联网创新业务" not in html4, "超长分部名应折行"
    assert "产业互联网创新业务" in html4, "折行后名称缺段"
    assert '毛利率（同一 % 轴）' in html4 and 'r="4.5"' in html4, "毛利率圆点与图例应在位"
    vb = re.search(r'viewBox="0 0 1000 (\d+)"', html4)
    assert vb and int(vb.group(1)) < 300, f"3 行条图高度应自适应收紧（实际 {vb and vb.group(1)}）"


def test_price_history_and_holders():
    """v4.8 ①发丝图挂第 10 章（历史带之后、时段表之前）；②户数趋势挂第 11 章（时机判定后、
    三轨判定卡之前）；缺字段时两图整块消失。"""
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
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "_fill_t.json")
        with open(p, "w", encoding="utf-8") as fp:
            json.dump(minimal_fill(**extra), fp, ensure_ascii=False)
        out = R.render(p, out_path=os.path.join(d, "out.html"))
        html = open(out, encoding="utf-8").read()
    assert 'aria-label="股价与PE历史走势"' in html, "发丝图应生成"
    assert 'aria-label="股东户数趋势"' in html, "户数趋势图应生成"
    # 发丝图在第 10 章内；户数图在第 11 章内、三轨判定卡之前
    assert html.find('id="s10"') < html.find('aria-label="股价与PE历史走势"'), "发丝图应在第 10 章"
    s11_pos = html.find('id="s11"')
    holders_pos = html.find('aria-label="股东户数趋势"')
    card_pos = html.find("三轨判定与仓位结论")
    assert s11_pos < holders_pos < card_pos, "户数图应在第 11 章内、三轨判定卡之前"
    assert "188,153" in html, "户数应带千位符"
    # v4.8.2 原位美化：面积填充 / 发丝加粗 / 年末竖网格 / 末端药丸标签
    ph_seg = html.split('aria-label="股价与PE历史走势"', 1)[1].split('</svg>', 1)[0]
    assert 'fill="#efe9db"' in ph_seg, "股价线下应有浅沙色面积填充"
    assert 'stroke-width="1.8"' in ph_seg, "发丝线应加粗至 1.8"
    assert 'stroke="#f0ebdf"' in ph_seg, "年份 tick 应有竖向浅网格线"
    assert 'rx="8"' in ph_seg, "末端最新值标签应有药丸底色"
    # 缺字段：两图整块消失
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "_fill_t.json")
        with open(p, "w", encoding="utf-8") as fp:
            json.dump(minimal_fill(), fp, ensure_ascii=False)
        out = R.render(p, out_path=os.path.join(d, "out.html"))
        html2 = open(out, encoding="utf-8").read()
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


def test_quote_four_piece():
    """v4.8 防伪链四件套扩展：valuation_inputs.pe_ttm 偏差>1% 拒；pe_band 完全越界历史带拒；
    risk_free 偏差>0.3pct 告警不拒；港股 div_yield 不比对。"""
    import contextlib
    import io
    with tempfile.TemporaryDirectory() as d:
        ref = os.path.join(d, "_em_quote.json")
        with open(ref, "w", encoding="utf-8") as fp:
            json.dump({"price": 10.0, "pe_ttm": 11.0, "pe_band": [8.0, 20.0],
                       "risk_free": 1.7, "div_yield": 2.0, "market": "A股"}, fp)
        q = {"source_file": ref, "date": "2026-08-27"}
        # 一致 → 过
        f = minimal_fill(quote=q)
        R.validate_content(f, R.compute_valuation(f))
        # valuation_inputs.pe_ttm 偏差 9% → 拒
        f = minimal_fill(quote=q)
        f["valuation_inputs"]["pe_ttm"] = 12.0
        _expect_valueerror(f, "valuation_inputs.pe_ttm 与落盘值偏差>1%")
        # pe_band [30,40] 完全落在历史带 [8,20] 之外 → 拒
        f = minimal_fill(quote=q)
        f["valuation_inputs"]["pe_band"] = [30, 40]
        _expect_valueerror(f, "pe_band 完全越界历史带")
        # pe_band 部分重叠 → 过
        f = minimal_fill(quote=q)
        f["valuation_inputs"]["pe_band"] = [15, 25]
        R.validate_content(f, R.compute_valuation(f))
        # risk_free 偏差 0.8pct → 告警不拒
        f = minimal_fill(quote=q)
        f["valuation_inputs"]["risk_free"] = 2.5
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            R.validate_content(f, R.compute_valuation(f))  # 不拒
        assert "risk_free" in buf.getvalue() and ">0.3pct" in buf.getvalue(), "risk_free 偏差应告警"
        # 港股 div_yield 偏差不做机械比对（税后折算差异天然大）
        with open(ref, "w", encoding="utf-8") as fp:
            json.dump({"price": 10.0, "pe_ttm": 11.0, "market": "港股"}, fp)
        f = minimal_fill(quote=q)
        f["valuation_inputs"]["div_yield"] = 3.5
        buf2 = io.StringIO()
        with contextlib.redirect_stderr(buf2):
            R.validate_content(f, R.compute_valuation(f))
        assert "div_yield" not in buf2.getvalue(), "港股 div_yield 不应机械比对"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"全部 {len(tests)} 项测试通过")
