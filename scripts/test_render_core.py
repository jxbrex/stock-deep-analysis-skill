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


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"全部 {len(tests)} 项测试通过")
