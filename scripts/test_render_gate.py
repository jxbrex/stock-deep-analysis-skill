#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_render_gate.py — render_report 门禁/校验回归（无网络；pytest 唯一入口，无 __main__ 直跑契约）

覆盖：拒渲染（负扣分 / PE 倒挂 / timing 缺维 / 黄灯缺键 / date 非法）、quote 四件套防伪、
写作纪律与内容告警、L4 形态硬门禁、仓位决策链（_position_steps）纯函数分支。
拆分自 test_render_core.py（v4.10.2），断言逐字沿用。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_report as R
from validate import _is_hk_code
from scoring import (_position_steps, _quality_verdict, _valuation_verdict,
                     _edge_info, build_edge_upgrade_rows)
from conftest import (
    minimal_fill, full_fill, mcap_fill, _dim, _calc, expect_valueerror,
    capture_stderr, validate_stderr, write_fill, render_fill, period_fill,
    _L1_GOV_BLOCK, _LONG_TEXT, _period_ref_file, _PERIOD_REF_KEYS,
)


def test_p0_low_quality_not_observation_pool():
    """P0 回归：quality <4 时最终仓位结论必须是「不建议参与」。"""
    html = R.build_position_card(minimal_fill(), quality=3.5, valuation=5.0,
                                 timing=5.0, calc=None, red_flag="")
    assert "不建议参与" in html, "质量<4 应得「不建议参与」"
    assert "观察池" not in html, "质量<4 不得落入观察池分支"


def test_uplift_cap_blocks_heavy_from_light():
    """上浮封顶：质地一般（4.5×4.5，非临界——v5.0 机制一：原 4.27/4.3 距 4.0 边界 ≤0.3
    属临界会降档冻结上浮）落轻仓，时机+离散度+赔率三连浮
    合计净效应 ≤1 档 → 最终标准仓 ≤10%，绝不允许重仓 ≤20%。"""
    html = R.build_position_card(minimal_fill(), quality=4.5, valuation=4.5,
                                 timing=7.0, calc=_calc(dispersion=0.30, odds=None,
                                                        floor_type="net_cash"),
                                 red_flag="")
    assert "矩阵落位：质量 4.50 × 估值 4.5 → 质地一般 → 轻仓 ≤5%" in html, \
        "落位文案缺失"
    assert "标准仓 ≤10%" in html, f"应止步标准仓，实际：{html}"
    assert "重仓 ≤20%" not in html, "轻仓不得被调节目测推成重仓"
    assert "上浮封顶" in html, "被拦的上浮项应在轨迹中说明"


def test_down_floors_at_zero():
    """下调兜底：轻仓落位 + 时机差(<4)降一档到 0 后，高离散度再触发下调必须
    兜底在 0，不得经 Python 负索引回卷成重仓 ≤20%。"""
    html = R.build_position_card(minimal_fill(), quality=4.5, valuation=4.5,
                                 timing=3.5, calc=_calc(dispersion=0.95),
                                 red_flag="")
    assert "不建议参与" in html, "两连降至底应为「不建议参与」（0 兜底）"
    assert "重仓" not in html, "负索引回卷会把兜底档错误显示为重仓"


def test_matrix_direct_entry_to_heavy_untouched():
    """好公司·好价格（≥7 × ≥8）矩阵直落重仓不受封顶误伤；此时调节全被
    封顶/顶格拦截且不产生噪音条目以外的误导。"""
    html = R.build_position_card(minimal_fill(), quality=7.5, valuation=8.5,
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


def test_rejections():
    expect_valueerror(minimal_fill(yellow_deductions=[{"label": "x", "points": -0.5}]),
                      "黄灯负扣分")
    f = minimal_fill(); f["red_deductions"] = [{"item": "x", "points": -1}]
    expect_valueerror(f, "红旗负扣分")
    f = minimal_fill(); f["valuation"]["scenarios"][0]["pe"] = [10, 8]
    expect_valueerror(f, "PE 区间倒挂")
    f = minimal_fill(); del f["timing_scores"]["技术面"]
    expect_valueerror(f, "timing_scores 缺维")
    f = minimal_fill(); del f["yellow_deductions"]
    expect_valueerror(f, "yellow_deductions 缺键")
    f = minimal_fill(); f["date"] = "2026/08/27"
    expect_valueerror(f, "date 格式非法")
    f = minimal_fill(); f["price"] = "未知"
    expect_valueerror(f, "price 非数字")


def test_quote_consistency():
    """quote 防伪（神华事故修复）：一致过 / 偏差>1% 拒 / 源文件读不到拒 / 缺 quote 仅告警不拒。"""
    with tempfile.TemporaryDirectory() as d:
        ref = write_fill({"price": 10.0, "pe_ttm": 11.0}, d, name="_em_quote.json")
        f = minimal_fill(quote={"source_file": ref, "date": "2026-08-27"})
        R.validate_content(f, R.compute_valuation(f))  # 一致 → 过
        f["price"] = "10.05"  # 0.5% 偏差 → 仍过
        R.validate_content(f, R.compute_valuation(f))
        f["price"] = "10.5"  # 5% 偏差 → 拒
        expect_valueerror(f, "price 与落盘值偏差>1%")
        f = minimal_fill(quote={"source_file": os.path.join(d, "不存在.json"),
                                "date": "2026-08-27"})
        expect_valueerror(f, "quote.source_file 读不到")
        # 缺 quote → 不拒（告警走 stderr）
        g = minimal_fill()
        R.validate_content(g, R.compute_valuation(g))
    print("OK quote 防伪（一致过 / 0.5%过 / 5%拒 / 文件缺失拒 / 缺字段不拒）")


def test_peers_caliber_warn():
    """peers_plot 口径一致性：目标点 PE 与 valuation_inputs.pe_ttm 偏差 >30% → 告警（不拒渲染）。"""
    fill = minimal_fill(peers_plot={"points": [
        {"name": "测试股份", "roe": 20, "pe": 20, "target": True},  # vs pe_ttm 11 → 偏差 82%
        {"name": "同业甲", "roe": 15, "pe": 18}]})
    assert "偏差 >30%" in validate_stderr(fill), "口径偏差 >30% 应告警"
    fill2 = minimal_fill(peers_plot={"points": [
        {"name": "测试股份", "roe": 20, "pe": 11, "target": True},
        {"name": "同业甲", "roe": 15, "pe": 18}]})
    assert "偏差 >30%" not in validate_stderr(fill2), "口径一致不应告警"


def test_writing_discipline_warns():
    """v4.7.1 写作纪律告警：四拍挤段 / 三年并排 / pe_history 无第 11 章承载。"""
    # 四拍挤段：同一 <p> 含 ≥2 个拍名 → 告警
    l1 = ('<div class="dim-block"><p><strong>判词：</strong>矿山服务龙头，海外占比 72% 是核心阿尔法。'
          '<strong>论据：</strong>2025 年报海外毛利 31.2 亿（+24%），续约率 91%（年报 P17）。'
          '<strong>评分：</strong>8.0——护城河在长期服务协议锁定，铜价下行期续约率是唯一先行指标。</p></div>')
    fill4beat = minimal_fill(l1_html="".join(_dim("该维度分析：公司基本面稳健，数据支撑充分，论据详实可靠，"
                                                  "行业地位稳固，具备长期参考价值。") for _ in range(5)) + l1)
    assert "四拍挤段" in validate_stderr(fill4beat), "四拍挤段应告警"
    l1_ok = "".join(_dim("该维度分析：公司基本面稳健，数据支撑充分，论据详实可靠，"
                         "行业地位稳固，具备长期参考价值。") for _ in range(6))
    assert "四拍挤段" not in validate_stderr(minimal_fill(l1_html=l1_ok)), "分段的四拍不应告警"
    # 三年并排：连续三个年份 th / td 内年份:数值堆叠 → 告警
    peers = ('<table><thead><tr><th>指标</th><th>2023</th><th>2024</th><th>2025</th></tr></thead>'
             '<tbody><tr><td>ROE变化</td><td>8.0</td><td>15.2</td><td>30.8</td></tr></tbody></table>'
             '<span class="source">来源：mx 批量</span>')
    assert "三年数字并排" in validate_stderr(minimal_fill(peers_html=peers)), "三年并排应告警"
    peers_stacked = ('<table><thead><tr><th>指标</th><th>3年走势</th></tr></thead>'
                     '<tbody><tr><td>归母净利</td><td>2023: 8.0，2024: 15.2，2025: 30.8</td></tr></tbody></table>'
                     '<span class="source">来源：mx 批量</span>')
    assert "三年数字并排" in validate_stderr(minimal_fill(peers_html=peers_stacked)), "td 内年份堆叠应告警"
    peers_ok = ('<table><thead><tr><th>公司</th><th>ROE变化</th></tr></thead>'
                '<tbody><tr><td>同业甲</td><td>8.0→30.8（大升）</td></tr></tbody></table>'
                '<span class="source">来源：mx 批量</span>')
    assert "三年数字并排" not in validate_stderr(minimal_fill(peers_html=peers_ok)), "起→终格式不应告警"
    # pe_history 与第 11 章绑定：cycle_html 缺失 → 告警；填了 → 不告警
    ph = {"hist_lo": 13.7, "hist_hi": 83.2}
    assert "cycle_html 缺失" in validate_stderr(minimal_fill(pe_history=ph)), "pe_history 无第 11 章承载应告警"
    fill_ok = minimal_fill(pe_history=ph, cycle_html='<p>周期阶段分析正文，非空即渲染整章。</p>')
    assert "cycle_html 缺失" not in validate_stderr(fill_ok), "cycle_html 已填不应告警"


def test_quote_four_piece():
    """v4.8 防伪链四件套扩展：valuation_inputs.pe_ttm 偏差>1% 拒；pe_band 完全越界历史带拒；
    risk_free 偏差>0.3pct 告警不拒；港股 div_yield 不比对。"""
    with tempfile.TemporaryDirectory() as d:
        ref = write_fill({"price": 10.0, "pe_ttm": 11.0, "pe_band": [8.0, 20.0],
                          "risk_free": 1.7, "div_yield": 2.0, "market": "A股"},
                         d, name="_em_quote.json")
        q = {"source_file": ref, "date": "2026-08-27"}
        # 一致 → 过
        f = minimal_fill(quote=q)
        R.validate_content(f, R.compute_valuation(f))
        # valuation_inputs.pe_ttm 偏差 9% → 拒
        f = minimal_fill(quote=q)
        f["valuation_inputs"]["pe_ttm"] = 12.0
        expect_valueerror(f, "valuation_inputs.pe_ttm 与落盘值偏差>1%")
        # pe_band [30,40] 完全落在历史带 [8,20] 之外 → 拒
        f = minimal_fill(quote=q)
        f["valuation_inputs"]["pe_band"] = [30, 40]
        expect_valueerror(f, "pe_band 完全越界历史带")
        # pe_band 部分重叠 → 过
        f = minimal_fill(quote=q)
        f["valuation_inputs"]["pe_band"] = [15, 25]
        R.validate_content(f, R.compute_valuation(f))
        # risk_free 偏差 0.8pct → 告警不拒
        f = minimal_fill(quote=q)
        f["valuation_inputs"]["risk_free"] = 2.5
        out = validate_stderr(f)  # 不拒
        assert "risk_free" in out and ">0.3pct" in out, "risk_free 偏差应告警"
        # 港股 div_yield 偏差不做机械比对（税后折算差异天然大）
        write_fill({"price": 10.0, "pe_ttm": 11.0, "market": "港股"}, d, name="_em_quote.json")
        f = minimal_fill(quote=q)
        f["valuation_inputs"]["div_yield"] = 3.5
        assert "div_yield" not in validate_stderr(f), "港股 div_yield 不应机械比对"


def test_position_steps_direct():
    """v4.9：仓位决策链已抽成纯函数 _position_steps——直接测决策分支
    （红灯熔断 / 中枢为负 / 直落重仓 / 上浮封顶 / 0 兜底 / 观察池下调）。
    v5.0：返回值扩为 4 元组（+crit 档位临界列表）；分支覆盖改用非临界分数
    （原 7.2/4.27/4.3/5.8 均落在 ±0.3 临界带，临界分支见 test_position_steps_edge_critical）。"""
    # 红灯熔断：后续调节不再适用
    label, steps, slot, crit = _position_steps(7.5, 8.5, 7.0, _calc(odds=None), "财务造假嫌疑")
    assert label == "不建议参与" and slot is None and "红灯熔断" in steps[0] and not crit
    # 中枢为负拦截器（不落矩阵）
    label, steps, slot, crit = _position_steps(7.5, 8.5, 7.0, _calc(), "")
    assert label == "重仓 ≤20%" and "矩阵落位" in slot, "无红灯无负中枢应走矩阵直落"
    label, steps, slot, crit = _position_steps(7.5, 8.5, 7.0, {"central_raw": -0.1, "central": -0.1}, "")
    assert label == "回避（中枢为负，等价格）" and slot is None and "中枢为负" in steps[0]
    # 上浮封顶：质地一般轻仓 + 时机/离散/赔率三连浮仍止步标准仓
    label, steps, slot, crit = _position_steps(4.5, 4.5, 7.0, _calc(dispersion=0.30, odds=None, floor_type="net_cash"), "")
    assert label == "标准仓 ≤10%" and "上浮封顶" in "".join(steps)
    # 下调 0 兜底：两次下调不得回卷
    label, steps, slot, crit = _position_steps(4.5, 4.5, 3.5, _calc(dispersion=0.95), "")
    assert label == "不建议参与" and "重仓" not in "".join(steps)
    # 观察池：中上质地 + 差价格；时机差 → 下调不建议参与
    label, steps, slot, crit = _position_steps(5.9, 5.0, 5.0, None, "")
    assert label == "观察池" and "观察池" in slot
    label, steps, slot, crit = _position_steps(5.9, 5.0, 3.0, None, "")
    assert label == "不建议参与" and "观察池下调" in "".join(steps)
    # 与卡片渲染同源：build_position_card 输出含同一结论（行为零变更冒烟）
    html = R.build_position_card(minimal_fill(), 4.5, 4.5, 7.0,
                                 _calc(dispersion=0.30, odds=None, floor_type="net_cash"), "")
    assert "标准仓 ≤10%" in html
    print("OK _position_steps 直接单测（红灯/负中枢/直落/封顶/兜底/观察池）")


def test_try_up_wording_nailed():
    """v4.10.2 热核审计钉死：try_up 三条上浮路径的轨迹文案逐字断言。
    背景：try_up 收敛曾把赔率分支「）→ 上浮一档」（无空格）归一为「） → 上浮一档」
    （有空格）——1 字节漂移，因该分支零断言零快照覆盖而溜过。此处把三条路径
    （时机/离散度/赔率）的成功上浮文案逐字钉死，上浮分支统一「detail → 上浮一档」写法。"""
    # 时机分上浮成功（落轻仓 → 标准仓）
    label, steps, _slot, _crit = _position_steps(4.5, 4.5, 6.5, _calc(), "")
    assert label == "标准仓 ≤10%"
    assert steps == ["时机分调节：时机分 6.50 ≥ 6 → 上浮一档（轻仓 ≤5%→标准仓 ≤10%）"], steps
    # 离散度上浮成功
    label, steps, _slot, _crit = _position_steps(4.5, 4.5, 5.0, _calc(dispersion=0.30), "")
    assert label == "标准仓 ≤10%"
    assert steps == ["离散度调节：离散度 30.0% < 40% → 上浮一档（轻仓 ≤5%→标准仓 ≤10%）"], steps
    # 赔率 ∞ 上浮成功（归一化前此分支无空格，本轮有意归一——见 handoff 审计修补段）
    label, steps, _slot, _crit = _position_steps(4.5, 4.5, 5.0, _calc(dispersion=0.50, odds=None, floor_type="net_cash"), "")
    assert label == "标准仓 ≤10%"
    assert steps == ["赔率调节：赔率 ∞（悲观仍正收益） → 上浮一档（轻仓 ≤5%→标准仓 ≤10%）"], steps
    print("OK try_up 三上浮路径文案逐字钉死（时机/离散度/赔率）")


def test_verdict_word_boundaries():
    """v4.10.2：hero 判词分档边界——hero 副标直接消费 _quality_verdict/_valuation_verdict，
    此前只有 golden 快照覆盖 7.0/5.5 两个点，边界档逐点钉死。"""
    q_cases = [(3.99, "回避"), (4.0, "一般"), (5.49, "一般"), (5.5, "中上"), (6.99, "中上"), (7.0, "好公司")]
    for score, word in q_cases:
        assert _quality_verdict(score) == word, f"质量分 {score} 应为「{word}」，实际「{_quality_verdict(score)}」"
    v_cases = [(3.99, "贵"), (4.0, "合理无安全边际"), (5.99, "合理无安全边际"),
               (6.0, "合理偏便宜"), (7.99, "合理偏便宜"), (8.0, "深度安全边际")]
    for score, word in v_cases:
        assert _valuation_verdict(score) == word, f"估值分 {score} 应为「{word}」，实际「{_valuation_verdict(score)}」"
    print("OK hero 判词分档边界（质量 6 点 + 估值 6 点）")


def test_hero_band_claims_warns():
    """v4.9 Hero 文案引用分位/历史带概念时的数据支撑告警：
    无 p25/p75 支撑 / 极性矛盾 → 告警；概念齐备且无矛盾 → 不告警。
    v5.4.0：p25/p75 与合理带中枢偏离 >15% 即触发双尺回滚门禁（拒渲染），
    本用例只关心 Hero 文案，换数后的 fixture 统一配 rollback_html。"""
    def _rb(f):
        f["valuation"]["rollback_html"] = "回滚条件：连续两季扣非同比转正 → PE 带回滚至历史带"
        return f

    # 引「分位」但 pe_history 无 p25/p75 → 告警（数据支撑缺失）
    out = validate_stderr(minimal_fill(pe_sub="PE 处近 5 年低分位"))
    assert "分位" in out and "未填 p25/p75" in out, "引用分位而缺 p25/p75 应告警"
    # 有 p25/p75 但极性矛盾：现价 PE 高于 P75 却说低分位
    ph = {"hist_lo": 5, "hist_hi": 30, "p25": 8, "p75": 10, "label": "近5年"}
    out = validate_stderr(_rb(minimal_fill(pe_sub="现价 PE 处于低分位", pe_history=ph)))
    assert "低分位" in out and "矛盾" in out, "低分位说法与高于 P75 的现价应告警"
    # 极性正确（现价 < P25 说低分位）→ 不告警（p25 20/p75 30 偏离合理带 → 配回滚条款）
    out = validate_stderr(_rb(minimal_fill(pe_sub="现价 PE 处于低分位",
                                           pe_history={"p25": 20, "p75": 30})))
    assert "分位" not in out, "低分位说法与低于 P25 的现价不应告警"
    # 引用历史带但 pe_history 无 hist_lo/hist_hi → 告警
    out = validate_stderr(_rb(minimal_fill(pe_sub="PE 高于历史带上沿", pe_history={"p25": 8, "p75": 10})))
    assert "历史带" in out and "hist_lo" in out, "引用历史带而缺极值字段应告警"
    # 无概念字面 → 不告警
    out = validate_stderr(minimal_fill())
    assert "分位" not in out and "历史带" not in out
    print("OK Hero 分位/历史带文案支撑告警（缺支撑/极性矛盾告警，概念齐备放行）")


def test_conclusion_structure_warns():
    """v4.9.1 补充修订二：conclusion_html 四卡结构——缺卡 / 乱序 → 告警；四卡顺序正确 → 不告警。
    校验按纯文本关键词，对容器形式不敏感（旧四段 <p> 写法同样检出，但新规范为 .concl-grid 卡）。"""
    body = "（数据证据支撑充分，论据详实可靠，具备参考价值。）" * 6

    def card(head, ref):
        return (f'<div class="concl-card"><div class="concl-head">{head}</div>{body}'
                f'<div class="concl-ref">详见 {ref}</div></div>')

    four = ('<div class="concl-grid">' + card("关键优势", '<a href="#s4">4 公司本质</a>')
            + card("关键弱点", '<a href="#s6">6 风险评估</a>')
            + card("当前市场认知", '<a href="#s9">9 市场预期差</a>')
            + card("核心投资逻辑", '<a href="#s8">8 估值与安全边际</a>') + '</div>')
    assert "缺卡" not in validate_stderr(minimal_fill(conclusion_html=four)), "四卡齐全不应告警"
    three = four.replace(card("当前市场认知", '<a href="#s9">9 市场预期差</a>'), "")
    out = validate_stderr(minimal_fill(conclusion_html=three))
    assert "缺卡" in out and "当前市场认知" in out, "缺卡应告警并点名缺失卡头"
    mixed = ('<div class="concl-grid">' + card("核心投资逻辑", "8") + card("关键优势", "4")
             + card("关键弱点", "6") + card("当前市场认知", "9") + '</div>')
    out = validate_stderr(minimal_fill(conclusion_html=mixed))
    assert "顺序错误" in out, "四卡乱序应告警"
    print("OK conclusion 四卡结构（齐全放行 / 缺卡点名 / 乱序告警）")


def test_review_miss_diagnostics_warns():
    """v4.9 复盘「未命中」缺诊断方向：含未命中而无规律/反例字样 → 告警。"""
    prev = {"date": "2026-08-08", "quality": 7.0, "valuation": 5.5,
            "timing": 5.0, "target_range": "10-12",
            # v5.1.0：回测模式 prev.scenarios 必填；base PE 与本版一致（10-12x）不触发移动校验
            "scenarios": [{"scenario": "基础情景", "归母净利": "95 亿", "PE": "10-12x",
                           "目标价": "9.5-11.4 元"}]}
    tbl = '<table><tr><td>假设</td></tr></table><span class="source">数据来源：测试</span>'
    miss_key = "未提「规律/反例」"  # 告警文案关键字（与用户正文的「规律/反例」区分）
    out = validate_stderr(minimal_fill(prev=prev, review_html=tbl + "判定：未命中"))
    assert miss_key in out, "含未命中而无规律/反例字样应告警"
    out2 = validate_stderr(minimal_fill(prev=prev,
                                        review_html=tbl + "判定：未命中——本次属原规律失效的现场反例"))
    assert miss_key not in out2, "已写明规律失效/反例方向不应告警"
    print("OK 复盘未命中诊断告警（无规律/反例措辞告警，已写失效方向放行）")


def test_peers_roe_outlier_warns():
    """v4.9 peers_plot ROE 量级倒挂：目标点 ROE 脱离同业量级 → 告警；同量级 → 不告警。
    v5.4.0：散点同业须在 peers_html 表内或有 peers_meta 声明（表图一致拒渲染），
    本用例的「同业乙」走 peers_meta 声明路径。"""
    meta = "同行业、同规模筛选；同业乙口径不一已剔出"
    # 目标 ROE 2% vs 同业 12-15% → 倒挂告警
    fill = minimal_fill(peers_meta=meta, peers_plot={"points": [
        {"name": "测试股份", "roe": 2, "pe": 11, "target": True},
        {"name": "同业甲", "roe": 12, "pe": 18},
        {"name": "同业乙", "roe": 15, "pe": 20}]})
    out = validate_stderr(fill)
    assert "ROE" in out and "脱离同业量级" in out, "目标 ROE 明显低于同业应告警"
    # 目标 ROE 34 vs 同业 12-15 → 倒挂告警
    fill = minimal_fill(peers_meta=meta, peers_plot={"points": [
        {"name": "测试股份", "roe": 34, "pe": 11, "target": True},
        {"name": "同业甲", "roe": 12, "pe": 18},
        {"name": "同业乙", "roe": 15, "pe": 20}]})
    assert "脱离同业量级" in validate_stderr(fill)
    # 目标 14 vs 同业 12-15 → 不告警
    fill = minimal_fill(peers_meta=meta, peers_plot={"points": [
        {"name": "测试股份", "roe": 14, "pe": 11, "target": True},
        {"name": "同业甲", "roe": 12, "pe": 18},
        {"name": "同业乙", "roe": 15, "pe": 20}]})
    assert "脱离同业量级" not in validate_stderr(fill)
    print("OK peers ROE 量级倒挂告警（<同业一半 / >同业两倍告警，同量级放行）")


def test_peers_column_without_support_warns():
    """v4.10.3：peers 趋势表某列超半数格为「—」且未在同业结论框引用 → 告警
    （fill-schema「无引用=删列」的可判定落地）；结论框引用该列、或数据补齐 ≥ 半数 → 放行。"""
    thr = ('<div class="table-scroll"><table class="freeze-first">'
           '<tr><th>公司</th><th>净利现金含量 3 年</th><th>PE(TTM)</th></tr>'
           '<tr><td>测试股份</td><td>—</td><td>11</td></tr>'
           '<tr><td>同业甲</td><td>—</td><td>25</td></tr>'
           '<tr><td>同业乙</td><td>0.9</td><td>16</td></tr></table></div>'
           '<div class="conclusion-box"><strong>结论：</strong>规模与估值见上表。</div>'
           '<span class="source">数据来源：测试。</span>')
    out = validate_stderr(minimal_fill(peers_html=thr))
    assert "净利现金含量" in out and "无对比支撑" in out, "超半数缺失且未引用应告警"
    cited = thr.replace("规模与估值见上表", "净利现金含量仅同业乙可得")
    assert "无对比支撑" not in validate_stderr(minimal_fill(peers_html=cited)), \
        "结论框已引用该列不应告警"
    filled = thr.replace('<td>测试股份</td><td>—</td>', '<td>测试股份</td><td>0.8</td>')
    assert "无对比支撑" not in validate_stderr(minimal_fill(peers_html=filled)), \
        "可得数据 ≥ 半数不应告警"
    print("OK peers 无对比支撑列告警（超半数「—」且未引用告警，引用/补齐放行）")


def test_validate_warns_reach_stderr():
    """v4.9 validate 告警路径：触发告警的 fill → stderr 有「内容校验」前缀输出。"""
    fill = minimal_fill(subtitle="测试行业 · 报告日期：2026-01-01")
    out = validate_stderr(fill)
    assert "⚠️ 内容校验" in out, "告警路径必须打印到 stderr"
    assert "subtitle 含「报告日期」" in out, "具体告警文案应到达 stderr"
    print("OK validate 告警抵达 stderr（subtitle 含报告日期）")


def test_backtest_triggers_warning():
    """v4.9.1：回测模式（prev 已填）triggers 缺失 → 告警（旧触发条件核对由状态条承载，
    dash_html 不再手写核对表）；triggers 已填 → 无此告警。
    v4.10.3：全 pending 视同未核对（状态条条件渲染后一条也不显示）→ 同样告警。"""
    prev = {"date": "2026-08-05", "quality": 7.0, "valuation": 6.0, "timing": 5.0,
            "target_range": "10-12"}
    out = capture_stderr(lambda: R._check_backtest_flags(
        minimal_fill(prev=prev, review_html="<p>复盘。</p>")))
    assert "triggers 未填" in out, "prev 已填而 triggers 缺失应告警"
    out2 = capture_stderr(lambda: R._check_backtest_flags(
        minimal_fill(prev=prev, review_html="<p>复盘。</p>",
                     triggers=[{"cond": "提价兑现", "status": "hit"}])))
    assert "triggers 未填" not in out2, "triggers 已填不应再告警"
    out3 = capture_stderr(lambda: R._check_backtest_flags(
        minimal_fill(prev=prev, review_html="<p>复盘。</p>",
                     triggers=[{"cond": "提价兑现", "status": "pending"}])))
    assert "视同未核对" in out3, "全 pending 视同未核对，应告警"
    out4 = capture_stderr(lambda: R._check_backtest_flags(
        minimal_fill(prev=prev, review_html="<p>复盘。</p>",
                     triggers=[{"cond": "提价兑现", "status": "pending"},
                               {"cond": "销量转正", "status": "miss"}])))
    assert "视同未核对" not in out4 and "triggers 未填" not in out4, "含 hit/miss 不应告警"


def test_governance_strip_compact_warns():
    """v4.9.1 补充修订二：4.5 治理块单行化——trig-strip 块内 <p> 恰为 2（判词+评分）→ 不告警；
    trig 行后另起 <p> 正文（>2 个 <p>）→ 告警；4.5 未用 trig-strip 的存量写法 → 不打扰。"""

    def l1_with_35(inner):
        dims = [('<div class="dim-block"><p>该维度分析：公司基本面稳健，数据支撑充分，'
                 '论据详实可靠，行业地位稳固，具备长期参考价值。</p></div>')] * 5
        return "".join(dims) + ('<div class="dim-block"><div class="dim-header">'
                                '<span class="dim-name">4.5 治理与资本配置</span></div>'
                                + inner + '</div>')

    trig = ('<div class="trig"><span class="trig-dot hit"></span>'
            '<span class="trig-cond">股权与控制权</span>'
            '<span class="trig-mt">控股股东持股 34.2%，无质押冻结</span>'
            '<span class="trig-status hit">正面</span></div>')
    compact = ('<p><strong>判词：</strong>股权集中、激励充分，论据详实可靠具备参考价值。</p>'
               f'<div class="trig-strip">{trig}{trig}</div>'
               '<p><strong>评分：</strong>7.5——基准 7.0，激励到位 +0.5；关联交易关注 −0.0。</p>')
    assert "恰为 2" not in validate_stderr(minimal_fill(l1_html=l1_with_35(compact))), "紧凑形态不应告警"
    loose = compact.replace('</div><p><strong>评分',
                            f'</div><p>补充正文一段，论据详实可靠具备参考价值和数据支撑。</p>{trig}'
                            '<p><strong>评分')
    out = validate_stderr(minimal_fill(l1_html=l1_with_35(loose)))
    assert "恰为 2" in out, "trig 行后另起 <p> 正文应告警"
    legacy = ('<p>公司治理正文一段，未用分块列示的存量写法，论据详实可靠具备参考价值与数据支撑。'
              '治理结构稳定，激励到位，分红持续。</p>')
    assert "恰为 2" not in validate_stderr(minimal_fill(l1_html=l1_with_35(legacy))), "未用 trig-strip 不打扰"

    # 补充修订四：4.3 护城河 / 5.3 催化剂同款 <p> 恰为 2 规则
    def dim_with(name, inner):
        return ('<div class="dim-block"><div class="dim-header">'
                f'<span class="dim-name">{name}</span></div>' + inner + '</div>')
    dims5 = [('<div class="dim-block"><p>该维度分析：公司基本面稳健，数据支撑充分，'
              '论据详实可靠，行业地位稳固，具备长期参考价值。</p></div>')] * 5
    assert "恰为 2" not in validate_stderr(minimal_fill(
        l1_html="".join(dims5) + dim_with("4.3 商业模式与护城河", compact))), "4.3 紧凑形态不应告警"
    assert "恰为 2" in validate_stderr(minimal_fill(
        l1_html="".join(dims5) + dim_with("4.3 商业模式与护城河", loose))), "4.3 另起正文应告警"
    l3_43 = ("".join(dims5[:2]) + dim_with("5.3 催化剂", loose))
    assert "恰为 2" in validate_stderr(minimal_fill(l3_html=l3_43)), "5.3 另起正文应告警"
    print("OK 4.5 治理块单行化（紧凑放行 / 另起正文告警 / 存量不打扰 / 4.3+5.3 同款覆盖）")


def test_peers_orientation_warns():
    """v4.9.1 补充修订二：同业表公司强制行标题——目标公司蓝 style 落 <th> 表头（公司列旧方向）
    → 告警；标在行首格（<td>）→ 不告警。"""
    col_form = ('<table><thead><tr><th>指标</th>'
                '<th style="color:#4a6fa5;font-weight:700;">测试股份</th><th>同业甲</th></tr></thead>'
                '<tbody><tr><td>PE(TTM)</td><td>11</td><td>25</td></tr></tbody></table>'
                '<span class="source">来源：mx 批量</span>')
    assert "公司=行" in validate_stderr(minimal_fill(peers_html=col_form)), "公司列旧方向应告警"
    assert "公司=行" not in validate_stderr(minimal_fill()), "行标题形态不应告警"
    print("OK peers 公司行标题（th 蓝 style 告警 / 行首格放行）")


def test_l4_order_table_form():
    """v4.10：黄灯四类顺序检查覆盖扣分表形态（<td>a …</td>）——跳号（b→c）放行，乱序告警。"""
    ordered = ('<table><tbody>'
               '<tr><td>b 行业与政策环境</td><td>x</td></tr>'
               '<tr><td>c 盈利与财务质量</td><td>y</td></tr></tbody></table>')
    assert capture_stderr(lambda: R._check_l4_order(ordered)) == "", "跳号但有序应放行"
    messy = ordered.replace("<td>b 行业", "<td>c 行业").replace("<td>c 盈利", "<td>b 盈利")
    assert "a→b→c→d" in capture_stderr(lambda: R._check_l4_order(messy)), "乱序应告警"
    print("OK 黄灯扣分表形态顺序检查（跳号放行 / 乱序告警）")


def test_peers_bestworst_warn():
    """v4.10：同业当前指标表零 cell-best/cell-worst 标注 → 告警（工行 09-11 两表零标注实证）。"""
    bare = ('<div class="table-scroll"><table class="freeze-first">'
            '<tr><th>公司</th><th>PE(TTM)</th></tr>'
            '<tr><td style="color:#4a6fa5;font-weight:700;">测试股份</td><td>11</td></tr>'
            '<tr><td>同业甲</td><td>25</td></tr></table></div>'
            '<span class="source">数据来源：测试</span>')
    assert "cell-best" in validate_stderr(minimal_fill(peers_html=bare)), "零标注应告警"
    assert "cell-best" not in validate_stderr(minimal_fill()), "fixture 自带标注不应告警"
    # v4.11.0 逐列检查（天齐 09-13 实证：7 列只标 4 列，零标注告警不触发）——数值列缺标注按列名告警
    partial = ('<div class="table-scroll"><table class="freeze-first">'
               '<tr><th>公司</th><th class="num">PE(TTM)</th><th class="num">ROE</th></tr>'
               '<tr><td style="color:#4a6fa5;font-weight:700;">测试股份</td>'
               '<td class="cell-best num">11</td><td class="num">14%</td></tr>'
               '<tr><td>同业甲</td><td class="cell-worst num">25</td><td class="num">9%</td></tr>'
               '</table></div><span class="source">数据来源：测试</span>')
    err = validate_stderr(minimal_fill(peers_html=partial))
    assert "缺最优/最差标注" in err and "ROE" in err, "ROE 列裸奔应按列名告警"
    print("OK peers 最优/最差标注缺失告警（零标注告警 / 逐列裸奔告警 / 自带放行）")


def test_peers_plot_array_form_rejected():
    """peers_plot 数组简写废止（v5.1.5，与 fill-schema「直接给数组亦可」删除同步）：
    传裸数组 → 拒渲染。"""
    expect_valueerror(minimal_fill(peers_plot=[{"name": "同业甲", "roe": 15, "pe": 18}]),
                      kw="数组简写已废止")


def test_governance_deduct_row_warn():
    """v4.11.0：4.5 治理块评分段含扣分项时，trig 行必须有 miss「扣分」状态行
    （天齐 09-13 实证：评分段写「折价配售摊薄 −0.3」，四个方块却无一扣分档，结论断层）。"""
    gov = _L1_GOV_BLOCK
    deducted = gov.replace("关联交易关注项不扣分但列入 14 章跟踪",
                           "扣分项（H 股折价配售摊薄 −0.3）")
    l1 = "".join(_dim(_LONG_TEXT) for _ in range(5)) + deducted
    err = validate_stderr(minimal_fill(l1_html=l1))
    assert "无「扣分」状态" in err, "评分段有扣分项、块内无扣分行 → 应告警"
    fixed = deducted.replace('<span class="trig-status miss">关注</span>',
                             '<span class="trig-status miss">扣分</span>')
    err2 = validate_stderr(minimal_fill(l1_html="".join(_dim(_LONG_TEXT) for _ in range(5)) + fixed))
    assert "无「扣分」状态" not in err2, "块内有扣分行后应放行"
    assert "无「扣分」状态" not in validate_stderr(minimal_fill()), "fixture 无扣分项不应告警"
    print("OK 治理块扣分项-扣分行一致性校验")


def test_holders_dup_date_warn():
    """v4.11.0：holders 重复截止日 → 告警（E4 上游偶发双行且变动值不一致，天齐 20260710 实证）。"""
    dup = [{"date": "2026-07-10", "num": 345304, "chg": 0.0},
           {"date": "2026-07-10", "num": 345304, "chg": -1.7},
           {"date": "2026-07-20", "num": 358804, "chg": 3.9},
           {"date": "2026-07-31", "num": 360077, "chg": 0.4}]
    assert "重复截止日" in validate_stderr(minimal_fill(holders=dup)), "重复截止日应告警"
    assert "重复截止日" not in validate_stderr(minimal_fill()), "fixture 无重复不应告警"
    print("OK holders 重复截止日告警")


def test_price_history_pe_warn():
    """v4.10：price_history 的 pe 缺失告警（v4.11.0 起口径=有效 <12 点，图门槛同步）——
    提示照抄 E2 全序列月末 PE（工行 09-11 报告 12 点全缺、图只剩股价线实证）。"""
    ph = {"label": "近12个月", "series": [{"m": f"2025-{m:02d}", "close": 7.5} for m in range(1, 13)]}
    assert "月末 PE" in validate_stderr(minimal_fill(price_history=ph)), "pe 全缺应告警"
    ph2 = {"label": "近12个月",
           "series": [{"m": f"2025-{m:02d}", "close": 7.5, "pe": 7.6} for m in range(1, 13)]}
    assert "月末 PE" not in validate_stderr(minimal_fill(price_history=ph2)), "pe 齐全不应告警"
    # v4.11.0：门槛放宽为 ≥12 点（亏损期断线属诚实形态）——68 点 29 有效不再告警
    ph3 = {"label": "近5年", "series": [
        {"m": f"{2021 + i // 12}-{i % 12 + 1:02d}", "close": 40.0,
         "pe": (15.0 if 16 <= i < 40 or i >= 62 else None)} for i in range(68)]}
    assert sum(1 for p in ph3["series"] if p["pe"]) == 30
    assert "月末 PE" not in validate_stderr(minimal_fill(price_history=ph3)), \
        "30/68 点有效（≥12）不应再告警"
    print("OK price_history pe 缺失告警（全缺告警 / 齐全放行 / 亏损期断线放行）")


def test_l4_form_gates():
    """v4.10：L4 固定形态硬门禁——缺 pm-grid 三联卡拒渲染（旧 danger-card 单段形态打回）；
    黄灯扣分明细表行数 ≠ yellow_deductions 条数拒渲染（工行 09-11 照抄旧形态实证）。"""
    f = minimal_fill()
    f["l4_html"] = ('<div class="danger-card"><strong>损失预演：</strong>单段长文旧形态，'
                    '故事与重合度与清单外风险糊在一个段落里。</div>')
    expect_valueerror(f, kw="损失预演三联卡")
    f2 = minimal_fill(yellow_deductions=[{"label": "x", "points": 0.5},
                                         {"label": "y", "points": 0.5}])
    f2["l4_html"] = (f2["l4_html"] + '<div class="table-scroll"><table><tbody>'
                     '<tr><td>a 交易与股东行为</td><td>无</td><td>0</td></tr>'
                     '<tr><td>b 行业与政策环境</td><td>x</td><td class="num">0.5</td></tr>'
                     '<tr><td>c 盈利与财务质量</td><td>y</td><td class="num">0.5</td></tr>'
                     '<tr><td>d 经营与公司治理</td><td>无</td><td>0</td></tr>'
                     '</tbody></table></div><span class="source">数据来源：测试</span>')
    expect_valueerror(f2, kw="只列 points>0")
    f3 = minimal_fill(yellow_deductions=[{"label": "x", "points": 0.5}])
    f3["l4_html"] = (f3["l4_html"] + '<div class="table-scroll"><table><tbody>'
                     '<tr><td>b 行业与政策环境</td><td>x</td><td class="num">0.5</td></tr>'
                     '</tbody></table></div><span class="source">数据来源：测试</span>')
    R.validate_content(f3, R.compute_valuation(f3))  # 匹配形态不拒即通过
    print("OK L4 形态门禁（旧形态拒 / 零扣分行拒 / 合规放行）")


def test_negative_profit_central_no_crash():
    """v4.11.1（审核 D1）：负利润 base + 2年 horizon → 中枢不年化、保持实数，不崩 TypeError；
    中枢为负拦截器照常生效；validate 对负 profit 告警不拒。"""
    f = minimal_fill()
    f["valuation"]["horizon"] = "2年"
    for s in f["valuation"]["scenarios"]:
        s["profit"] = {"pess": -80, "base": -50, "opt": -20}[s["key"]]
    calc = R.compute_valuation(f)
    assert isinstance(calc["central"], float), f"负中枢不得年化为复数：{calc['central']!r}"
    assert calc["central"] < -1, f"central_raw=-6（-50×11/10/10−1），实际 {calc['central']}"
    label, steps, _slot, _crit = _position_steps(6.0, 5.0, 5.0, calc, "")
    assert "中枢为负" in label, f"负中枢应走拦截器，实际 {label}"
    f["thesis_html"] = "<p>困境反转论点：产能出清后正常化利润回归，本句仅作测试占位文本。</p>"
    warns = validate_stderr(f)
    assert "profit=-50" in warns and "口径" in warns, "负 profit 应有口径提示告警（不拒渲染）"


def test_cross_scenario_inversion_rejected():
    """v4.11.1（审核 D2）：三情景中枢跨档倒挂（pess>base 或 base>opt）→ 拒渲染；
    负离散度不得被决策链当作「低不确定性」上浮（校验漏网时的第二道防线）。"""
    f = minimal_fill()
    # pess 315 / base 105 / opt 63（profit 填反方向）
    for s, p in zip(f["valuation"]["scenarios"], (30, 10, 6)):
        s["profit"] = p
        s["pe"] = [100, 110]
    expect_valueerror(f, "跨档倒挂")
    calc = {"central_raw": 0.5, "central": 0.5, "dispersion": -25.2, "odds": 1.5}
    html = R.build_position_card(minimal_fill(), quality=6.0, valuation=6.5,
                                 timing=5.0, calc=calc, red_flag="")
    assert "离散度调节" not in html, "负离散度不得触发上浮（审核 D2 防线二）"


def test_dim_blocks_by_dim_name():
    """v4.11.1（审核 D3）：dim-block 乱序时按 dim-name 编号映射维度——
    4.3 块写最前，极端分 1C=8.5 的证据校验仍须命中 4.3 块（旧位置 zip 会错配到 1A 漏检）。"""
    f = minimal_fill()
    f["scores"]["1C"] = 8.5
    thin_txt = "护城河论据较薄但越过地板线，此处补充字数" + "据" * 13   # 块总长 45（含头部11字）：过 40 地板、踩 <50 极端分门槛

    def _named(num, name, txt):
        return (f'<div class="dim-block"><div class="dim-header">'
                f'<span class="dim-name">{num} {name}</span></div><p>{txt}</p></div>')
    long_txt = "该维度分析：论据与数据充分，行业地位稳固，具备长期参考价值，结论可靠。"
    f["l1_html"] = (_named("4.3", "商业模式与护城河", thin_txt)
                    + _named("4.1", "赛道与宏观", long_txt) + _named("4.2", "产业链位置", long_txt)
                    + _named("4.4", "财务健康", long_txt) + _named("4.5", "治理与资本配置", long_txt)
                    + _named("4.6", "资本回报质量", long_txt))
    err = validate_stderr(f)
    assert "4.3 商业模式与护城河 得分 8.5（极端分）" in err, \
        f"乱序下极端分校验应命中 4.3 块，实际 stderr：{err[:400]}"


def test_quote_present_date_gate():
    """v4.11.1（审核 D5）：date ≥ 2026-09-02（v4.8 引入 quote）缺 quote → 拒渲染；
    此前存量 fill → 维持告警（豁免）。"""
    f = minimal_fill()
    f["date"] = "2026-09-13"
    expect_valueerror(f, "新报告缺 quote 应拒渲染")
    g = minimal_fill()  # date=2026-08-27 存量
    err = validate_stderr(g)
    assert "quote 字段缺失" in err, "存量 fill 缺 quote 应走告警豁免"


def test_dim_block_extra_class_tolerated():
    """v4.11.1（审核 D8）：class="dim-block extra" 附加类形态仍计入块数，不误触发 <6 拒渲染。"""
    f = minimal_fill()
    f["l1_html"] = f["l1_html"].replace('<div class="dim-block">',
                                        '<div class="dim-block extra">', 1)
    R.validate_content(f, R.compute_valuation(f))  # 不拒即通过


def test_gap_plot_validate():
    """v4.11.1：gap_plot 校验——非法行（缺 name/ours/consensus）拒渲染；
    有效维度 <2 / 同机构多点 / 目标价与脚本中枢失配 → 告警。"""
    f = minimal_fill()
    f["gap_plot"] = {"dims": [{"name": "2026E 归母净利（亿元）", "ours": 110, "consensus": 100}]}
    err = validate_stderr(f)
    assert "有效数值维度仅 1 个" in err, "有效维度 <2 应告警（图不生成）"
    f["gap_plot"] = {"dims": [{"name": "x", "consensus": 100}]}
    expect_valueerror(f, "gap_plot 行缺 ours 应拒渲染")
    f["gap_plot"] = {"dims": [
        {"name": "目标价·12个月（元）", "ours": 30, "consensus": 26,
         "street": [{"org": "野村", "v": 31}, {"org": "野村", "v": 30}]},
        {"name": "2026E 归母净利（亿元）", "ours": 110, "consensus": 100},
        {"name": "废行", "ours": 1, "consensus": 0}]}
    err = validate_stderr(f)
    assert "同机构多点" in err, "street 同机构多点应告警"
    assert "口径须一致" in err, "目标价与 valuation 中枢失配应告警"
    assert "≤0" in err, "consensus ≤0 行剔除应告警"



def test_driver_cards_validate():
    """v4.11.3 驱动卡校验：缺失告警；chips 非三情景档告警；p0_html 手写「为什么…」info-card
    且 drivers 已填 → 重复告警。v5.1.1：第一变量改由脚本按 sensitivity |impact| 降序加冕——
    首行无同名驱动卡 → 拒渲染（原「不同名」告警升级；校验曾比数组第 0 项而图按 impact 排序，
    影石创新矛盾静默穿过实证）；加冕与手标 first_var 不一致 → 告警（手标忽略）。"""
    warns = validate_stderr(minimal_fill())
    assert "drivers 字段未填" in warns
    good_chips = [{"label": "悲观", "value": "1"}, {"label": "基础", "value": "2"},
                  {"label": "乐观", "value": "3"}]
    warns = validate_stderr(minimal_fill(
        drivers=[{"name": "金价", "elastic": "x", "chips": [{"label": "高", "value": "1"}]}],
        driver_verdict="v"))
    assert "chips 情景档" in warns
    # 首行无同名卡 → 拒渲染（数组第 0 项同名不算数：按 |impact| 降序首行为准）
    expect_valueerror(minimal_fill(
        drivers=[{"name": "金价", "first_var": True, "elastic": "x", "chips": good_chips}],
        driver_verdict="v", sensitivity=[{"name": "铜价", "impact": 10}]), "首行无同名驱动卡",
        kw="无同名驱动卡")
    expect_valueerror(minimal_fill(
        drivers=[{"name": "毛利率", "first_var": True, "elastic": "x", "chips": good_chips}],
        driver_verdict="v",
        sensitivity=[{"name": "毛利率", "impact": 15}, {"name": "收入增速", "impact": 20}]),
        "数组第 0 项同名但 impact 非最大仍拒", kw="无同名驱动卡")
    # 加冕名在卡中、手标与加冕不一致 → 告警不拒
    warns = validate_stderr(minimal_fill(
        drivers=[{"name": "毛利率", "first_var": True, "elastic": "x", "chips": good_chips},
                 {"name": "收入增速", "elastic": "x", "chips": good_chips}],
        driver_verdict="v",
        sensitivity=[{"name": "毛利率", "impact": 15}, {"name": "收入增速", "impact": 20}]))
    assert "手标" in warns and "加冕" in warns
    warns = validate_stderr(minimal_fill(
        p0_html='<div class="info-card"><strong>为什么X是第一变量</strong></div>',
        drivers=[{"name": "金价", "first_var": True, "elastic": "x", "chips": good_chips}],
        driver_verdict="v"))
    assert "info-card" in warns and "为什么" in warns


def test_sensitivity_units_validate():
    """v5.1.1：sensitivity.delta 量纲规范——比例 ±10% / 百分点 ±1pct 合规；裸数字或
    文字单位 → 告警（条端/坐标轴净利影响 % 由脚本按 impact 生成）。"""
    warns = validate_stderr(minimal_fill(sensitivity=[
        {"name": "毛利率", "impact": 15, "delta": "±1pct"},
        {"name": "收入增速", "impact": 20, "delta": "±10%"}]))
    assert "量纲不规范" not in warns
    warns = validate_stderr(minimal_fill(sensitivity=[
        {"name": "毛利率", "impact": 15, "delta": "1个百分点"},
        {"name": "量", "impact": 8, "delta": "10"}]))
    assert warns.count("量纲不规范") == 2


def test_hero_cross_validate():
    """v5.1.2：Hero 与估值结构化字段互查——顶层 pe_ttm vs valuation_inputs.pe_ttm >1% 拒
    （metric_label 豁免）；horizon 不一致告警；mcap vs price×shares >5% 告警；
    Hero ✓ 字段缺失告警；target_sub_html 含具体数字告警。"""
    warns = validate_stderr(minimal_fill())
    assert "horizon 顶层" not in warns and "price×shares" not in warns
    expect_valueerror(minimal_fill(pe_ttm="11.5"), "Hero pe_ttm 与四件套偏差 >1%", kw="Hero pe_ttm")
    warns = validate_stderr(minimal_fill(horizon="24个月"))
    assert "horizon 顶层" in warns
    warns = validate_stderr(minimal_fill(mcap="1200"))
    assert "price×shares" in warns
    f = minimal_fill()
    del f["pe_ttm"]
    warns = validate_stderr(f)
    assert "Hero pe_ttm 缺失" in warns
    warns = validate_stderr(minimal_fill(target_sub_html="较现价 +21%"))
    assert "target_sub_html 含具体" in warns


def test_gap_growth_consensus_validate():
    """v5.1.2：gap_plot 净利维度（consensus 对落盘 np_avg、ours 对 base.profit）与
    growth_plot 换算对账（np_consensus 对落盘换算增速、base.profit 换算增速越界）。"""
    ref = _period_ref_file("v512_gap", {"consensus_np": 905})
    warns = validate_stderr(minimal_fill(
        quote={"source_file": ref},
        gap_plot={"dims": [
            {"name": "2026E 归母净利（亿元）", "ours": 90, "consensus": 870},
            {"name": "2026E 目标价（元）", "ours": 11, "consensus": 10}]}))
    assert "np_avg" in warns and "基础情景净利" in warns
    # 合规路径：年份不一致（2027E vs 落盘 2026）静默跳过；一致不告警
    warns = validate_stderr(minimal_fill(
        quote={"source_file": ref},
        gap_plot={"dims": [
            {"name": "2027E 归母净利（亿元）", "ours": 100, "consensus": 870},
            {"name": "2026E 归母净利（亿元）", "ours": 100, "consensus": 905},
            {"name": "2026E 目标价（元）", "ours": 11, "consensus": 10}]}))
    assert "gap_plot「" not in warns
    # growth_plot：np_avg=120 ÷ 上年归母净利 100 − 1 = 20% vs np_consensus 15% → 差 5pct 告警；
    # base.profit=100 → 换算 0% 越出本文区间 [5,10]（容差 ±2pct）→ 告警
    warns = validate_stderr(minimal_fill(
        quote={"source_file": _period_ref_file("v512_g", {"consensus_np": 120})},
        fin_trend={"years": ["2023", "2024", "2025"], "panels": [
            {"title": "盈利", "bars": [{"name": "归母净利", "unit": "亿", "values": [80.0, 90.0, 100.0]}]},
            {"title": "营收", "bars": [{"name": "营收", "unit": "亿", "values": [800.0, 900.0, 1000.0]}]},
            {"title": "毛利", "lines": [{"name": "毛利率", "pct": True, "values": [29.0, 30.0, 31.0]}]}]},
        growth_plot={"hist": [{"y": "2023", "np": 10.0}, {"y": "2024", "np": 11.0},
                              {"y": "2025", "np": 12.0}],
                     "fcst": [{"y": "2026E", "np_lo": 5, "np_hi": 10, "np_consensus": 15}]}))
    assert "np_consensus" in warns and "基础情景换算增速" in warns


def test_l4_yellow_points_validate():
    """v5.1.2：L4 黄灯表逐项数值比对——行数一致但扣分值不一致 → 拒渲染；行检出容忍带属性。"""
    tbl = ('<div class="pm-grid"><div>a</div><div>b</div><div>c</div></div>'
           '<div class="table-scroll"><table><thead><tr><th>类别</th><th>风险</th><th>扣分</th></tr></thead>'
           '<tbody><tr class="x"><td>a 交易与股东行为</td><td>减持</td><td class="num">0.5</td>'
           '<td>据公告</td></tr></tbody></table></div><span class="source">数据来源：x</span>')
    warns = validate_stderr(minimal_fill(
        l4_html=tbl, yellow_deductions=[{"label": "减持", "points": 0.5}]))
    assert "扣分值" not in warns
    expect_valueerror(minimal_fill(
        l4_html=tbl, yellow_deductions=[{"label": "减持", "points": 0.8}]), "逐项数值不一致",
        kw="多重集")
    # 热核 P0-2：points 不可解析不崩——pos_y 过滤后行数不符按「正扣分 0 条」拒（报错可定位）；
    # P1-4：0 分条目不啝分母；表侧 class=num 缺失 → 降级告警不拒
    expect_valueerror(minimal_fill(
        l4_html=tbl, yellow_deductions=[{"label": "减持", "points": None}]),
        "points 不可解析", kw="points 缺失或不可解析")
    warns = validate_stderr(minimal_fill(
        l4_html=tbl, yellow_deductions=[{"label": "减持", "points": 0.5},
                                        {"label": "零分项", "points": 0}]))
    assert "多重集" not in warns
    warns = validate_stderr(minimal_fill(
        l4_html=tbl.replace('<td class="num">0.5</td>', '<td>0.5</td>'),
        yellow_deductions=[{"label": "减持", "points": 0.5}]))
    assert "降级" in warns


def test_thesis_baretext_validate():
    """v5.1.2：thesis 三 span 全缺且含价格形态 → 拒渲染（手写价绕行一致性硬校验）。
    热核 P0-1：价格形态只认带「元」的数字组——年份/数量/百分比区间不带元，不误拒。"""
    expect_valueerror(minimal_fill(
        thesis_html="好公司但坏价格，三情景目标价 15.7/37.5/61.8 元，年化中枢 -10.9%，回避。"),
        "三 span 全缺含价格形态", kw="全缺")
    warns = validate_stderr(minimal_fill(thesis_html="只是定性判断，没有价格，文字量足够撑过地板就行。"))
    assert "绕行" not in warns
    # P0-1 回归：年份区间/数量区间/百分比区间/单个现价数字，不得误拒
    warns = validate_stderr(minimal_fill(
        thesis_html="公司 2023-2025 营收复合增速 20%，覆盖 3-5 家核心客户，市占率 10%-15%，"
                    "当前股价 11 元，估值不便宜，继续观望等待更好的价格出现。"))
    assert "绕行" not in warns
    # 带元的区间=价格形态，仍拒
    expect_valueerror(minimal_fill(
        thesis_html="基本面稳健但估值偏高，等 25-29 元观察区再介入，当前回避为宜。"),
        "带元区间仍拒", kw="全缺")


def test_triggers_target_validate():
    """v5.1.2：triggers hit/miss 行 target 核对——缺「实际值」告警；阈值方向矛盾告警。"""
    warns = validate_stderr(minimal_fill(triggers=[
        {"cond": "提价兑现", "metric": "26H2 毛利率", "target": "≥46%", "status": "hit"}]))
    assert "未写实际值" in warns
    warns = validate_stderr(minimal_fill(triggers=[
        {"cond": "提价兑现", "target": "≥46%｜实际 44.1%", "status": "hit"}]))
    assert "矛盾" in warns
    warns = validate_stderr(minimal_fill(triggers=[
        {"cond": "提价兑现", "target": "≥46%｜实际 47.2%", "status": "hit"}]))
    assert "矛盾" not in warns and "未写实际值" not in warns
    # miss 方向矛盾（阈值满足却标 miss）同样检出
    warns = validate_stderr(minimal_fill(triggers=[
        {"cond": "提价兑现", "target": "≥46%｜实际 47.2%", "status": "miss"}]))
    assert "矛盾" in warns


def test_timing_table_validate():
    """v5.1.2：时机小表得分 vs timing_scores（>0.1 告警）；信号数值/方向 vs 落盘 timing。"""
    tbl = ('<p>时机判定：筹码面改善、技术面偏弱，仓位维持观察池不变，决策逻辑见下表与正文。</p>'
           '<table><thead><tr><th>维度</th><th>得分</th><th>命中信号与加减</th></tr></thead>'
           '<tbody><tr><td>筹码面</td><td>6.0</td><td>户数下降 +1</td></tr>'
           '<tr><td>技术面</td><td>4.0</td><td>现价 10.5 站上 MA60 9.8</td></tr>'
           '<tr><td>合计</td><td>5.3</td><td>微调 ±1 档</td></tr></tbody></table>'
           '<span class="source">时机信号：quote 落盘 timing（现价/MA60/MA120/52 周高低），'
           '筹码面数据：E4 股东户数，均取自 em_fetch 落盘输出。</span>'
           '<div class="info-card"><strong>决策逻辑：</strong>质量分好公司但估值无安全边际，'
           '时机微调不足以升档，维持观察池，等估值回到合理带下沿再评估。</div>')
    with tempfile.TemporaryDirectory() as d:
        ref = write_fill({"price": 10.0, "pe_ttm": 11.0,
                          "timing": {"price": 10.0, "ma60": 9.9, "ma120": 9.5,
                                     "high_52w": 12.0, "low_52w": 8.0}}, d, "_ref_t.json")
        # 筹码面 6.0 vs timing_scores 5 → 告警；现价 10.5 vs 落盘 10.0 差 5% → 告警；
        # 「站上 MA60」与 10.0 > 9.9 不矛盾 → 无方向告警
        warns = validate_stderr(minimal_fill(quote={"source_file": ref}, position_html=tbl))
        assert "「筹码面」得分" in warns and "现价=10.5" in warns
        assert "上方/站上" not in warns
        # 方向矛盾：现价 10.0 < MA120 12.0 却写「站上 MA120」→ 告警
        tbl2 = tbl.replace("现价 10.5 站上 MA60 9.8", "现价 10.0 站上 MA120")
        ref2 = write_fill({"price": 10.0, "pe_ttm": 11.0,
                           "timing": {"price": 10.0, "ma60": 9.9, "ma120": 12.0,
                                      "high_52w": 13.0, "low_52w": 8.0}}, d, "_ref_t2.json")
        warns = validate_stderr(minimal_fill(quote={"source_file": ref2}, position_html=tbl2))
        assert "上方/站上" in warns


def test_timing_table_52w_cross_validate():
    """P0-1 文档虚言闭合：时机小表 52 周高低信号 vs 落盘 timing（fill-schema/SKILL 承诺
    技术面信号取自落盘，此前只比对现价/MA60/MA120）——合并写法「52周高低 高/低」与
    分拆写法「52周低 X」同口径 >1% 告警。"""
    tbl = ('<p>时机判定：筹码面改善、技术面偏弱，仓位维持观察池不变，决策逻辑见下表与正文。</p>'
           '<table><thead><tr><th>维度</th><th>得分</th><th>命中信号与加减</th></tr></thead>'
           '<tbody><tr><td>筹码面</td><td>5.0</td><td>户数下降 +1</td></tr>'
           '<tr><td>技术面</td><td>5.0</td><td>现价 10.0 站上 MA60 9.9；52周高低 12.0/8.0</td></tr>'
           '<tr><td>合计</td><td>5.0</td><td>微调 ±1 档</td></tr></tbody></table>'
           '<span class="source">时机信号：quote 落盘 timing（现价/MA60/MA120/52 周高低）。</span>'
           '<div class="info-card"><strong>决策逻辑：</strong>质量分好公司但估值无安全边际，'
           '时机微调不足以升档，维持观察池，等估值回到合理带下沿再评估。</div>')
    with tempfile.TemporaryDirectory() as d:
        ref = write_fill({"price": 10.0, "pe_ttm": 11.0,
                          "timing": {"price": 10.0, "ma60": 9.9, "ma120": 9.5,
                                     "high_52w": 12.0, "low_52w": 8.0}}, d, "_ref_52w.json")
        warns = validate_stderr(minimal_fill(quote={"source_file": ref}, position_html=tbl))
        assert "52周高" not in warns and "52周低" not in warns, "一致不应告警"
        # 合并写法高值偏差：12.0 vs 落盘 15.0 → 告警
        ref2 = write_fill({"price": 10.0, "pe_ttm": 11.0,
                           "timing": {"price": 10.0, "ma60": 9.9, "ma120": 9.5,
                                      "high_52w": 15.0, "low_52w": 8.0}}, d, "_ref_52w2.json")
        warns = validate_stderr(minimal_fill(quote={"source_file": ref2}, position_html=tbl))
        assert "52周高=12.0" in warns and "禁手估" in warns, "合并写法高值偏差应告警"
        # 分拆写法低值偏差：「52周低 7.0」vs 落盘 8.0 → 告警
        tbl2 = tbl.replace("52周高低 12.0/8.0", "52周低 7.0")
        warns = validate_stderr(minimal_fill(quote={"source_file": ref}, position_html=tbl2))
        assert "52周低=7.0" in warns, "分拆写法低值偏差应告警"
    print("OK 时机小表 52 周高低对账（一致放行 / 合并写法高值告警 / 分拆写法低值告警）")


def test_period_verdict_cross_validate():
    """v5.1.2：period_track 判词 vs 完成度机械对账（分母=一致预期优先、时间进度按报告期）。"""
    pt = {"period": "2026中报", "is_annual": False, "np": 30, "consensus_np": 100,
          "verdict_np": "超前"}
    warns = validate_stderr(minimal_fill(
        quote={"source_file": _period_ref_file("v512_pv", pt)}, period_track=dict(pt)))
    assert "超前 但完成度" in warns
    pt2 = {"period": "2026中报", "is_annual": False, "np": 60, "consensus_np": 100,
           "verdict_np": "超前"}
    warns = validate_stderr(minimal_fill(
        quote={"source_file": _period_ref_file("v512_pv2", pt2)}, period_track=dict(pt2)))
    assert "超前 但完成度" not in warns
    # 一季/三季标签同样生效（热核 P1-2：此前认不出项目自家标签）
    pt3 = {"period": "2026一季", "is_annual": False, "np": 5, "consensus_np": 100,
           "verdict_np": "超前"}
    warns = validate_stderr(minimal_fill(
        quote={"source_file": _period_ref_file("v512_pv3", pt3)}, period_track=dict(pt3)))
    assert "超前 但完成度" in warns
    # 亏损期累计 ≤0 → 完成度无意义静默跳过（热核 P1，_period_ratio 返回 None）
    pt4 = {"period": "2026中报", "is_annual": False, "np": -5, "consensus_np": 100,
           "verdict_np": "超前"}
    warns = validate_stderr(minimal_fill(
        quote={"source_file": _period_ref_file("v512_pv4", pt4)}, period_track=dict(pt4)))
    assert "超前 但完成度" not in warns


def _l1_with_43(body_43: str) -> str:
    """6 个规范 dim-name 的 l1_html，4.3 块正文由参数给定。"""
    plain = "该维度分析：公司基本面稳健，数据支撑充分，论据详实可靠，行业地位稳固，具备长期参考价值。"
    out = []
    for nm in ("4.1 赛道与宏观", "4.2 产业链位置", "4.3 商业模式与护城河", "4.4 财务健康",
               "4.5 治理与资本配置", "4.6 资本回报质量"):
        body = body_43 if nm.startswith("4.3") else plain
        out.append(f'<div class="dim-block"><div class="dim-header"><span class="dim-name">{nm}</span>'
                   f'</div><p>{body}</p></div>')
    return "".join(out)


def test_handwritten_dupes_validate():
    """v5.1.2：手写表与脚本生成并存检测——p0 敏感性表 / valuation 三情景表与指标卡 /
    l1 多年年表 / gap 机构对照表，均已由字段或脚本承载。"""
    warns = validate_stderr(minimal_fill(
        p0_html=('<span class="section-tag">分型：周期股</span><p>识别特征一段，周期定位与弹性来源。</p>'
                 '<table><thead><tr><th>变量</th><th>净利影响</th></tr></thead>'
                 '<tbody><tr><td>金价</td><td>±20%</td></tr></tbody></table>'
                 '<span class="source">数据来源：x</span>'),
        sensitivity=[{"name": "金价", "impact": 20, "delta": "±10%"},
                     {"name": "产量", "impact": 13}]))
    assert "手写敏感性表" in warns
    warns = validate_stderr(minimal_fill(
        valuation_html=('<div class="table-scroll"><table class="scenario-table">'
                        '<thead><tr><th>指标</th></tr></thead><tbody><tr><td>x</td></tr></tbody>'
                        '</table></div><span class="source">数据来源：x</span>')))
    assert "手写三情景表" in warns
    warns = validate_stderr(minimal_fill(
        valuation_html=('<div class="metric-row"><div class="metric-card"><div class="label">年化中枢'
                        '</div></div></div><p>校准逻辑说明一段。</p>')))
    assert "手写三指标卡" in warns
    warns = validate_stderr(minimal_fill(l1_html=_l1_with_43(
        '护城河分析一段。'
        '<table><thead><tr><th>指标</th><th>2021</th><th>2022</th><th>2023</th><th>2024</th>'
        '<th>2025</th></tr></thead><tbody><tr><td>营收</td><td>1</td><td>2</td><td>3</td>'
        '<td>4</td><td>5</td></tr><tr><td>净利</td><td>1</td><td>2</td><td>3</td><td>4</td>'
        '<td>5</td></tr></tbody></table><span class="source">数据来源：x</span>')))
    assert "手写年表" in warns
    warns = validate_stderr(minimal_fill(
        gap_plot={"dims": [{"name": "2026E 归母净利（亿元）", "ours": 100, "consensus": 100},
                           {"name": "2026E 目标价（元）", "ours": 11, "consensus": 10}]},
        gap_html=('<table><thead><tr><th>机构</th><th>预测</th></tr></thead>'
                  '<tbody><tr><td>野村</td><td>952</td></tr></tbody></table>'
                  '<span class="source">数据来源：x</span>')))
    assert "逐机构对照表" in warns


def test_red_flag_conclusion_validate():
    """v5.1.2：红旗 ≥2 项 → conclusion 首卡首句必须含「利润真实性存疑」（拒渲染）。"""
    red2 = [{"item": "现金含量连续2年<0.7", "points": 0.5},
            {"item": "应收增速远超营收", "points": 0.5}]
    expect_valueerror(minimal_fill(red_deductions=red2), "首卡首句存疑句", kw="利润真实性存疑")
    f = minimal_fill(red_deductions=red2)
    f["conclusion_html"] = f["conclusion_html"].replace(
        "关键优势</div>", "关键优势</div>利润真实性存疑，", 1)
    validate_stderr(f)  # 不拒即通过


def test_slot_widths_validate():
    """v5.1.2：槽位契约补闸——scenario.trigger >15 字 / drivers.chips 档值 >12 字告警。"""
    warns = validate_stderr(minimal_fill(valuation={
        "shares": 100, "horizon": "12个月", "scenarios": [
            {"key": "pess", "label": "悲观", "trigger": "下", "profit": 80, "pe": [8, 10]},
            {"key": "base", "label": "基础", "trigger": "NIM 降至 1.22%、信用成本升至 0.65%",
             "profit": 100, "pe": [10, 12]},
            {"key": "opt", "label": "乐观", "trigger": "上", "profit": 120, "pe": [12, 14]}]}))
    assert "trigger" in warns and "字 > 15" in warns
    warns = validate_stderr(minimal_fill(
        drivers=[{"name": "金价", "elastic": "x",
                  "chips": [{"label": "悲观", "value": "800"}, {"label": "基础", "value": "900"},
                            {"label": "乐观", "value": "1,000"},
                            {"label": "悲观另注", "value": "这是一个超过十二字的档值啊"}]}],
        driver_verdict="v", sensitivity=[{"name": "金价", "impact": 20}]))
    assert "chips 档值" in warns


def test_threshold_coverage_validate():
    """v5.1.2：4.3 压力测试阈值须在 14 章 triggers/dash_html 有对应行，否则告警。"""
    l1 = _l1_with_43("护城河压力测试：若市占率跌破 15% 则逻辑失效，需要持续跟踪该指标变化。")
    warns = validate_stderr(minimal_fill(l1_html=l1))
    assert "无对应行" in warns
    warns = validate_stderr(minimal_fill(l1_html=l1, dash_html=(
        '<div class="table-scroll"><table class="dash-table"><thead><tr><th>指标</th><th>当前值</th>'
        '<th>触发阈值</th></tr></thead><tbody><tr><td>市占率</td><td>17%</td><td>跌破 15%</td></tr>'
        '</tbody></table></div><span class="source">数据来源：x</span>')))
    assert "无对应行" not in warns


def test_cycle_stages_validate():
    """v4.11.3 阶段卡校验：手写阶段表迁移告警；driver 超宽告警。
    v5.1.2：current ≠1（与渲染同源的有效项口径）→ 拒渲染；缺 name/period 项告警不落图；
    字段已填但 cycle_html 缺失 → 告警（阶段卡挂第 11 章条件块内）。"""
    warns = validate_stderr(minimal_fill(cycle_html='<table><tr><th>阶段</th></tr></table>'))
    assert "迁移 cycle_stages" in warns
    expect_valueerror(minimal_fill(cycle_stages=[
        {"name": "a", "period": "2021", "current": True},
        {"name": "b", "period": "2022", "current": True},
        {"name": "c", "period": "2023"}]), "current 恰 1 个", kw="恰为 1 个")
    expect_valueerror(minimal_fill(cycle_stages=[
        {"name": "a", "period": "2021"},
        {"name": "b", "period": "2022"},
        {"name": "c", "period": "2023"}]), "0 个 current 同拒", kw="恰为 1 个")
    warns = validate_stderr(minimal_fill(cycle_stages=[
        {"name": "a", "period": "2021", "current": True},
        {"name": "b", "current": True},
        {"name": "c", "period": "2023", "driver": "长" * 30},
        {"name": "d", "period": "2024"}]))
    assert "不落图" in warns and "> 48" in warns and "cycle_html 缺失" in warns


def test_cycle_position_validate():
    """v5.2.0 周期位置刻度条校验（首版软告警）：周期股+cycle_html 缺 cycle_position → 告警；
    缺键 → 逐键告警；stage 与 cycle_stages 本轮不一致 → 告警；无 cycle_html 不告警。"""
    warns = validate_stderr(minimal_fill(cycle_html="<p>周期分析。</p>"))
    assert "cycle_position 未填" in warns
    warns = validate_stderr(minimal_fill(
        cycle_html="<p>x</p>",
        cycle_position={"stage": "上行期后段", "price_pctile": "铝价分位 70%"}))
    assert "cycle_position.capacity" in warns and "cycle_position.implication" in warns
    warns = validate_stderr(minimal_fill(
        cycle_html="<p>x</p>",
        cycle_stages=[{"name": "出清", "period": "2022", "current": True},
                      {"name": "复苏", "period": "2023"},
                      {"name": "上行", "period": "2024"}],
        cycle_position={"stage": "下行末段", "price_pctile": "a", "capacity": "b",
                        "stock_spread": "c", "implication": "d"}))
    assert "不一致" in warns
    warns = validate_stderr(minimal_fill(
        cycle_html="<p>x</p>",
        cycle_stages=[{"name": "出清", "period": "2022", "current": True},
                      {"name": "复苏", "period": "2023"},
                      {"name": "上行", "period": "2024"}],
        cycle_position={"stage": "出清末段", "price_pctile": "a", "capacity": "b",
                        "stock_spread": "c", "implication": "d"}))
    assert "不一致" not in warns
    assert "cycle_position" not in validate_stderr(minimal_fill())


def test_earnings_stability_validate():
    """v5.2.0 盈利波动性软锚校验（软告警）：sigma 与 fin_trend 扣非柱复算（夹具 σ=1.4）
    偏差 >0.15pct → 告警；verdict 缺失 → 告警；一致且键齐 → 不告警。
    热核修复补齐边界：sigma 缺失分支 / 无扣非柱 / 复算不可用（亏损基数致增速点不足）
    均不得静默放过；字符串 sigma 经 _num 归一不误报。"""
    warns = validate_stderr(minimal_fill(earnings_stability={"sigma": 15, "verdict": "x"}))
    assert "偏差 >0.15pct" in warns
    warns = validate_stderr(minimal_fill(earnings_stability={"sigma": 1.4}))
    assert "verdict 缺失" in warns
    warns = validate_stderr(minimal_fill(
        earnings_stability={"sigma": 1.4, "peer_median": None, "verdict": "波动低"}))
    assert "earnings_stability" not in warns
    # sigma 缺失分支
    warns = validate_stderr(minimal_fill(earnings_stability={"verdict": "x"}))
    assert "sigma 缺失" in warns
    # 字符串 sigma（"1.4" 经 _num 归一）不误报
    warns = validate_stderr(minimal_fill(
        earnings_stability={"sigma": "1.4", "verdict": "波动低"}))
    assert "偏差 >0.15pct" not in warns and "sigma 缺失" not in warns
    # 无扣非柱 → 「无法复算」告警（不静默放过）
    f0 = minimal_fill()
    ft = f0["fin_trend"]
    ft["panels"] = [p for p in ft["panels"]
                    if not any("扣非" in b.get("name", "") for b in p.get("bars", []))]
    warns = validate_stderr(minimal_fill(
        fin_trend=ft, earnings_stability={"sigma": 1.4, "verdict": "波动低"}))
    assert "无扣非柱可复算" in warns
    # 亏损基数致增速点 <3 → 复算不可用告警
    f1 = minimal_fill()
    ft1 = f1["fin_trend"]
    for p in ft1["panels"]:
        for b in p.get("bars", []):
            if "扣非" in b.get("name", ""):
                b["values"] = [10, -5, -8, 12, 13]
    warns = validate_stderr(minimal_fill(
        fin_trend=ft1, earnings_stability={"sigma": 9.9, "verdict": "波动低"}))
    assert "复算不可用" in warns


def test_dcf_validate():
    """v4.11.3 DCF 校验：稳健成长缺 dcf 告警；缺键告警；valuation_html 手写 DCF 表重复告警。
    v5.4.1：分型改归一判定——「成长型」+ mid / 未声明 high 与旧名「稳健成长股」同样命中，
    「成长型」+ high 走远期 PE 折现不强制。"""
    warns = validate_stderr(minimal_fill(stock_type="稳健成长股"))
    assert "dcf 字段未填" in warns
    for over in ({"stock_type": "成长型", "growth_tier": "mid"},      # v5.3.0 新名 + 中速层
                 {"stock_type": "成长型"}):                            # 未声明 growth_tier（按 mid）
        assert "dcf 字段未填" in validate_stderr(minimal_fill(**over)), f"{over} 缺 dcf 应告警"
    assert "dcf 字段未填" not in validate_stderr(
        minimal_fill(stock_type="成长型", growth_tier="high")), "高速层走远期 PE 折现，不强制 dcf"
    warns = validate_stderr(minimal_fill(dcf={"value": 12}))
    assert "缺键" in warns
    warns = validate_stderr(minimal_fill(
        dcf={"value": 12, "fcf0": "1", "growth_5y": "1", "g_perp": "1", "wacc": "1",
             "net_cash": "1", "implied_g": "1", "verdict": "长" * 50},
        valuation_html='<table><tr><th>DCF三行</th></tr></table>'
                       '<span class="source">数据来源：测试</span>'))  # 表须带来源标注，否则先撞内容地板硬拒
    assert "手写 DCF 表" in warns


def test_dcf_stable_value_required_warn():
    """P0-6（用户拍板补校验）：稳定价值（非金融）缺 dcf → 告警（fill-schema/SKILL 承诺的
    零执行闭合）；stock_type 含「金融」（银行/保险走 PB-ROE/DDM，scoring.md）→ 豁免。"""
    warns = validate_stderr(minimal_fill(stock_type="稳定价值（非金融）"))
    assert "dcf 字段未填" in warns and "稳定价值" in warns, "非金融稳定价值缺 dcf 应告警"
    warns = validate_stderr(minimal_fill(stock_type="稳定价值（金融）"))
    assert "dcf 字段未填" not in warns, "金融类稳定价值股应豁免"
    # v5.5.0 P1：子类词表单源（_fin_subclass）——证券与银行/保险同豁免，与 B6 参考带同口径
    for st in ("稳定价值（证券）", "稳定价值/金融（券商）", "稳定价值/金融（保险）"):
        assert "dcf 字段未填" not in validate_stderr(minimal_fill(stock_type=st)), f"{st} 应豁免"
    print("OK dcf 稳定价值分型校验（非金融告警 / 金融豁免 / 证券券商同源）")


def test_pe_history_banned_types():
    """v5.4.1：pe_history 禁填告警（fill-schema 填写条件此前只写在文档里、零校验）——
    成长型·高速层（含旧名「快速成长」）与未盈利/管线填了 → 软告警；
    周期股 / 成长型·中速层 / 成熟·停滞 / 稳定价值 / 困境反转填了 → 不告警；未填永不告警。"""
    ph = {"hist_lo": 13.7, "hist_hi": 83.2, "label": "近5年"}
    assert "pe_history 已填但本分型" in validate_stderr(
        minimal_fill(pe_history=ph, stock_type="成长型", growth_tier="high"))
    assert "pe_history 已填但本分型" in validate_stderr(
        minimal_fill(pe_history=ph, stock_type="快速成长（强周期属性）")), "旧名快速成长同样命中"
    assert "pe_history 已填但本分型" in validate_stderr(
        minimal_fill(pe_history=ph, stock_type="未盈利/管线"))
    for over in ({"stock_type": "成长型", "growth_tier": "mid"}, {"stock_type": "周期股"},
                 {"stock_type": "成熟/停滞"}, {"stock_type": "稳定价值/金融（银行）"},
                 {"stock_type": "困境反转"}):
        assert "pe_history 已填但本分型" not in validate_stderr(minimal_fill(pe_history=ph, **over)), \
            f"{over} 允许填 pe_history，不应告警"
    assert "pe_history 已填但本分型" not in validate_stderr(
        minimal_fill(stock_type="成长型", growth_tier="high"))
    print("OK pe_history 禁填（高速层/旧名快速成长/未盈利告警，其余分型放行）")


# ---------------- v5.5.0 B4 sensitivity 业务线覆盖硬闸 ----------------

_SEG_ITEMS = [{"name": "手机", "rev_pct": 60.0, "gp_pct": 55.0},
              {"name": "互联网服务", "rev_pct": 25.0, "gp_pct": 30.0},
              {"name": "其他", "rev_pct": 15.0, "gp_pct": 8.0}]   # 8% < 15 → 不参与覆盖


def _cov_fill(**over):
    """B4 夹具：两个大分部（手机 55% / 互联网服务 30%）+ 一条 sensitivity 变量。"""
    base = minimal_fill(
        segments={"period": "2025年报", "by": "产品", "items": _SEG_ITEMS},
        sensitivity=[{"name": "手机毛利率", "impact": 12, "delta": "±1pct"}],
        drivers=[{"name": "手机毛利率", "elastic": "±1pct → 净利 ±12%",
                  "chips": [{"label": "悲观", "value": "30"}, {"label": "基础", "value": "33"},
                            {"label": "乐观", "value": "35"}]}],
        sensitivity_meta={"coverage": [
            {"segment": "手机", "var": "手机毛利率"},
            {"segment": "互联网服务", "excluded": "ARPU 稳定，±10% 收入 → 净利 ±3%，不足以改变情景结论"}]},
    )
    base.update(over)
    return base


def test_sensitivity_coverage_gate():
    """v5.5.0 B4：sensitivity_meta.coverage 覆盖硬闸（拒渲染）——gp_pct ≥15 的大分部必须
    逐条登记（var 或带数字的 excluded）；双填/双缺、var 瞎指、excluded 无数字均拒；
    合规放行；segments 缺失/无大分部整条跳过。"""
    R.validate_content(_cov_fill(), R.compute_valuation(_cov_fill()))   # 合规 → 过
    # 大分部未登记 → 拒（报错列出分部名与 gp_pct）
    f = _cov_fill()
    f["sensitivity_meta"] = {"coverage": [{"segment": "手机", "var": "手机毛利率"}]}
    try:
        R.validate_content(f, R.compute_valuation(f))
        raise AssertionError("大分部未覆盖应拒")
    except ValueError as e:
        assert "未覆盖大分部" in str(e), f"拒渲染来源不符：{e}"
        assert "互联网服务（毛利占比 30%）" in str(e), "报错须列出未覆盖分部及其 gp_pct"
    # var + excluded 双填 → 拒
    f = _cov_fill()
    f["sensitivity_meta"] = {"coverage": [
        {"segment": "手机", "var": "手机毛利率", "excluded": "±10% → 净利 ±3%"},
        {"segment": "互联网服务", "excluded": "±10% → 净利 ±3%"}]}
    expect_valueerror(f, "双填应拒", kw="双填")
    # 双缺 → 拒
    f = _cov_fill()
    f["sensitivity_meta"] = {"coverage": [{"segment": "手机"},
                                          {"segment": "互联网服务", "excluded": "±10% → 净利 ±3%"}]}
    expect_valueerror(f, "双缺应拒", kw="双缺")
    # var 瞎指（不在 sensitivity 集合）→ 拒
    f = _cov_fill()
    f["sensitivity_meta"] = {"coverage": [
        {"segment": "手机", "var": "不存在的变量"},
        {"segment": "互联网服务", "excluded": "±10% → 净利 ±3%"}]}
    expect_valueerror(f, "var 瞎指应拒", kw="不在 sensitivity 变量集合")
    # excluded 无数字 → 拒
    f = _cov_fill()
    f["sensitivity_meta"] = {"coverage": [
        {"segment": "手机", "var": "手机毛利率"},
        {"segment": "互联网服务", "excluded": "影响不大，不单独入图"}]}
    expect_valueerror(f, "排除理由无数字应拒", kw="excluded 无数字")
    # sensitivity 全缺 + 有大分部 → 拒
    f = _cov_fill()
    f.pop("sensitivity")
    expect_valueerror(f, "sensitivity 全缺应拒", kw="sensitivity 字段缺失")
    # coverage 引用不存在的分部 → 软告警
    f = _cov_fill()
    f["sensitivity_meta"] = {"coverage": [
        {"segment": "手机", "var": "手机毛利率"},
        {"segment": "互联网服务", "excluded": "±10% → 净利 ±3%"},
        {"segment": "不存在的分部", "excluded": "±10% → 净利 ±2%"}]}
    assert "引用了 segments 中不存在的分部" in validate_stderr(f)
    # segments 缺失 / 大分部全无（gp_pct 均 <15）→ 整条跳过
    R.validate_content(minimal_fill(), R.compute_valuation(minimal_fill()))
    small = minimal_fill(segments={"items": [{"name": "A", "rev_pct": 60, "gp_pct": 12},
                                             {"name": "B", "rev_pct": 40, "gp_pct": 9}]})
    R.validate_content(small, R.compute_valuation(small))
    # v5.5.0 P1：有行缺 gp_pct（摘除 gp_pct 绕行）→ 软告警；不阻断渲染
    f = _cov_fill()
    f["segments"]["items"][0].pop("gp_pct")
    out = validate_stderr(f)
    assert "行缺 gp_pct" in out and "绕过覆盖闸" in out, "缺 gp_pct 应软告警"
    R.validate_content(f, R.compute_valuation(f))
    # 全部行都缺 gp_pct（硬闸无从生效）→ 同样告警、仍不拒
    allno = minimal_fill(segments={"items": [{"name": "A", "rev_pct": 60},
                                             {"name": "B", "rev_pct": 40}]})
    out2 = validate_stderr(allno)
    assert "行缺 gp_pct" in out2, "全行缺 gp_pct 也应告警"
    R.validate_content(allno, R.compute_valuation(allno))
    print("OK B4 覆盖硬闸（未覆盖/双填/双缺/瞎指/无数字拒，合规放行，无大分部跳过，缺 gp_pct 告警）")


# ---------------- v5.5.0 B5 3B 无项目型数字义务 / B6 折现率参考带 ----------------

_L3_BLOCK = ('<div class="dim-block"><div class="dim-header">'
             '<span class="dim-name">5.2 项目确定性</span><span class="dim-weight">35%</span>'
             '<span class="score-line" style="margin-left:auto;margin-bottom:0;">'
             '<span class="badge badge-green">7.0</span></span></div>'
             '<p>{t}</p>'
             '<p><strong>评分：</strong>7.0——基准 6.5，按利润贡献加权后 +0.5。</p></div>')


def _l3_fill(text, **over):
    """B5 夹具：l3_html 首块写 5.2 项目确定性文本（其余块用通用长文本凑地板）。"""
    l3 = _L3_BLOCK.format(t=text) + "".join(_dim(_LONG_TEXT) for _ in range(2))
    return minimal_fill(l3_html=l3, **over)


def test_readthrough_3b_narrative_warn():
    """v5.5.0 B5：无项目型 3B ≥6.5 且 5.2 块**正文**（剥标题/徽章/评分末拍）无数字 → 软告警；
    正文带数字放行；非无项目型（无关键词）不查；3B <6.5 不查。
    热核审计 P0：评分末拍是 schema 强制段且必含分值数字——不剥则门禁在合规报告上恒不触发。"""
    narrative = ("无项目型的存量扩张逻辑：公司为行业龙头，客户粘性强、转换成本高，"
                 "收入结构持续优化，渠道壁垒稳固，可见度长期偏高。")
    f = _l3_fill(narrative)
    f["scores"]["3B"] = 7.0
    assert "无项目型 ≥6.5" in validate_stderr(f), "schema 形态（带评分末拍）论据无数字应告警"
    # 正文带指标 + 数值 → 放行
    f2 = _l3_fill("无项目型的存量扩张：两融余额 1,240 亿、环比 +6%，保有客户 3,120 万，"
                  "续约率 92%，存量指标趋势向上且口径可复核。")
    f2["scores"]["3B"] = 7.0
    assert "无项目型 ≥6.5" not in validate_stderr(f2), "带指标+数值应放行"
    # 有项目型（无关键词）→ 不查
    f3 = _l3_fill("在建产能：计划 2026Q2 投产，资金到位、审批齐全，滑期风险小于一年，"
                  "投产即为利润贡献主体。")
    f3["scores"]["3B"] = 7.5
    assert "无项目型 ≥6.5" not in validate_stderr(f3), "有项目型（无关键词）不查"
    # 3B < 6.5 → 不查
    f4 = _l3_fill(narrative)
    f4["scores"]["3B"] = 6.0
    assert "无项目型 ≥6.5" not in validate_stderr(f4), "3B <6.5 不查"
    # 剥段口径自证：dim-header 带附加类 / 评分末拍带属性时仍能正确剥净
    f5 = _l3_fill(narrative)
    f5["scores"]["3B"] = 7.0
    f5["l3_html"] = f5["l3_html"].replace('<div class="dim-header">',
                                          '<div class="dim-header extra" data-x="1">')
    f5["l3_html"] = f5["l3_html"].replace('<p><strong>评分：</strong>',
                                          '<p class="score-beat"><strong>评分：</strong>')
    assert "无项目型 ≥6.5" in validate_stderr(f5), "容忍型剥离：附加类/属性下仍应告警"
    print("OK B5 无项目型 3B 数字义务（正文无数字告警 / 有数字放行 / 有项目型与低分不查）")


def test_discount_rate_band_warn():
    """v5.5.0 B6：`dcf.wacc` 与国债距离超参考带 +2pct → 软告警（**WACC sanity 粗筛**，非 r 带执法）；
    各分型带内/恰等号线放行、超带告警；未盈利·管线/困境反转跳过；不可解析跳过。
    热核审计 P1：银行带 9%（非金融带 8.2 会告警、银行带 9.2 放行）——能判别银行行确实生效。"""
    KW = "与国债距离超参考带"
    dcf0 = {"value": 12.5, "fcf0": "95亿", "growth_5y": "5%", "g_perp": "2.5%", "wacc": "8.5%",
            "net_cash": "120亿", "implied_g": "0.5", "verdict": "长" * 45}

    def w(st, pct, **over):
        return minimal_fill(stock_type=st, dcf=dict(dcf0, wacc=pct), **over)

    # 稳定价值（非金融）线上限 4.5+2+1.7 = 8.2%
    assert KW in validate_stderr(w("稳定价值（非金融）", "10%")), "超带应告警"
    assert KW not in validate_stderr(w("稳定价值（非金融）", "8.2%")), "恰等号线应放行"
    assert KW in validate_stderr(w("稳定价值（非金融）", "8.3%")), "越线一线应告警"
    # 银行带 5.5+2+1.7 = 9.2%
    assert KW not in validate_stderr(w("稳定价值/金融（银行）", "9%")), "银行 9% 应放行（非金融带会误告）"
    assert KW in validate_stderr(w("稳定价值/金融（银行）", "10%")), "银行 10% 超带应告警"
    # 保险/券商带 7.3+2+1.7 = 11.0%
    for st in ("稳定价值/金融（保险）", "稳定价值/金融（券商）", "稳定价值（证券）"):
        assert KW not in validate_stderr(w(st, "10%")), f"{st} 10% 沿高贝塔带放行"
        assert KW in validate_stderr(w(st, "12%")), f"{st} 12% 超带应告警"
    # 成长型 6+2+1.7 = 9.7%｜周期股 7+2+1.7 = 10.7%｜成熟·停滞 4.5+2+1.7 = 8.2%
    assert KW not in validate_stderr(w("成长型", "9.5%"))
    assert KW in validate_stderr(w("成长型", "10%"))
    assert KW not in validate_stderr(w("周期股", "10%")), "周期股 10% 边缘放行（云铝实证）"
    assert KW in validate_stderr(w("周期股", "11%"))
    assert KW not in validate_stderr(w("成熟/停滞", "8.2%"))
    assert KW in validate_stderr(w("成熟/停滞", "9%"))
    # 跳过面：未盈利·管线 / 困境反转（无股权成本锚）、wacc 不可解析、risk_free 不可解析
    for st in ("未盈利/管线", "困境反转"):
        assert KW not in validate_stderr(w(st, "30%")), f"{st} 跳过"
    assert KW not in validate_stderr(w("稳定价值（非金融）", "—")), "wacc 占位跳过"
    f = w("稳定价值（非金融）", "12%",
          valuation_inputs={"pe_ttm": 11, "pe_band": [10, 12], "div_yield": 2, "risk_free": "—"})
    assert KW not in validate_stderr(f), "risk_free 不可解析跳过"
    print("OK B6 WACC sanity 粗筛（各带内/等号线放行、超带告警、银行行可判别、跳过面齐）")


def test_dcf_param_parse_warn():
    """v5.5.0 P1：dcf 参数型三键（wacc/growth_5y/g_perp）非空但不可解析 → 告警
    （对齐 value/implied_g 的 v5.1.2 先例）；「—」占位跳过；wacc <1 提示疑为小数口径。"""
    dcf0 = {"value": 12.5, "fcf0": "95亿", "growth_5y": "5%", "g_perp": "2.5%", "wacc": "8.5%",
            "net_cash": "120亿", "implied_g": "0.5", "verdict": "长" * 45}
    f = minimal_fill(dcf=dict(dcf0, wacc="八五"))
    assert "dcf.wacc「八五」非空但不可解析为数值" in validate_stderr(f)
    f2 = minimal_fill(dcf=dict(dcf0, growth_5y="未定"))
    assert "dcf.growth_5y「未定」非空但不可解析为数值" in validate_stderr(f2)
    f3 = minimal_fill(dcf=dict(dcf0, g_perp="待定"))
    assert "dcf.g_perp「待定」非空但不可解析为数值" in validate_stderr(f3)
    f4 = minimal_fill(dcf=dict(dcf0, wacc="—", growth_5y="—", g_perp="—"))
    out4 = validate_stderr(f4)
    assert "不可解析为数值" not in out4, "「—」占位应跳过"
    f5 = minimal_fill(dcf=dict(dcf0, wacc="0.085"))
    assert "疑为小数口径" in validate_stderr(f5), "wacc <1 应提示小数口径"
    f6 = minimal_fill(dcf=dict(dcf0, wacc="8.5%"))
    assert "疑似为小数口径" not in validate_stderr(f6) and "疑为小数口径" not in validate_stderr(f6)
    print("OK dcf 参数可解析性（三键不可解析告警 / 占位跳过 / wacc<1 提示）")


# ---------------- v5.0 第 3 章「最新报告期透视」校验与渲染 ----------------

def test_period_track_cross_check():
    """v5.0 period_track 落盘交叉校验（quote 防伪同款纪律）：一致过 / 数值偏差>1% 拒 /
    照抄字段夹带文字拒 / 落盘无 period_track 键拒 / 文字同比完全一致 / fill 有值落盘 None
    （手估嫌疑）拒 / consensus_np 失配拒 / 漏抄软告警 / quote 缺失软告警。"""
    f = period_fill()
    R.validate_content(f, R.compute_valuation(f))  # 一致 → 过
    f = period_fill()
    f["period_track"]["np"] = 120.0
    expect_valueerror(f, "period_track.np 与落盘不一致应拒")
    f = period_fill()
    f["period_track"]["sq_ocf"] = 999.0
    expect_valueerror(f, "period_track.sq_ocf（v5.0.1 新增照抄键）与落盘不一致应拒")
    f = period_fill()
    f["period_track"]["rev"] = "301.98（H股口径）"
    expect_valueerror(f, "照抄字段夹带文字应拒")
    f = period_fill()
    f["period_track"]["consensus_np"] = 150.0
    expect_valueerror(f, "consensus_np 与落盘 np_avg 不一致应拒")
    with tempfile.TemporaryDirectory() as d:
        # 落盘无 period_track 键 → 拒（禁手估，神华同款）
        ref = write_fill({"price": 10.0, "pe_ttm": 11.0}, d, name="em_ref.json")
        f = period_fill(quote={"source_file": ref, "date": "2026-08-27"})
        expect_valueerror(f, "落盘无 period_track 键应拒")
        # 文字同比：完全一致过 / 不一致拒
        pt_ref = {"period": "2026中报", "is_annual": False, "rev": 10.0, "np": 5.2,
                  "np_yoy": "扭亏", "sq_label": None, "band_years": []}
        ref2 = write_fill({"price": 10.0, "pe_ttm": 11.0, "period_track": pt_ref},
                          d, name="em_ref2.json")
        pt = dict(pt_ref, goal_np=200.0)
        f = minimal_fill(quote={"source_file": ref2, "date": "2026-08-27"}, period_track=pt)
        R.validate_content(f, R.compute_valuation(f))  # 文字一致 → 过
        f["period_track"]["np_yoy"] = "转亏"
        expect_valueerror(f, "文字同比不完全一致应拒")
        # fill 有值而落盘 None（手估嫌疑）→ 拒
        f = minimal_fill(quote={"source_file": ref2, "date": "2026-08-27"},
                         period_track=dict(pt, np_dedt=9.99))
        expect_valueerror(f, "落盘无值 fill 手估应拒")
        # 落盘有 period_track 而 fill 未回填 → 软告警不拒
        out = validate_stderr(minimal_fill(quote={"source_file": ref2, "date": "2026-08-27"}))
        assert "第 3 章" in out and "将缺席" in out, "落盘有 fill 无应软告警"
    # 漏抄（fill None 落盘有值）→ 软告警不拒
    f = period_fill()
    f["period_track"]["np_dedt"] = None
    out = validate_stderr(f)
    assert "漏抄" in out and "np_dedt" in out, "漏抄字段应软告警"
    # F5：is_annual 进交叉校验——fill 篡改 true→false 拒渲染（年报期整章消失是硬约束）
    f = period_fill("annual")
    f["period_track"]["is_annual"] = False
    try:
        R.validate_content(f, R.compute_valuation(f))
        raise AssertionError("is_annual 篡改应拒但未拒")
    except ValueError as e:
        assert "is_annual" in str(e), f"应报 is_annual 不一致，实际: {e}"
    # quote 缺失（存量日期软门禁）→ 无法交叉校验软告警，不拒
    f = period_fill()
    del f["quote"]
    assert "无法交叉校验" in validate_stderr(f), "quote 缺失应软告警不拒"
    print("OK period_track 交叉校验（一致过/偏差拒/夹带文字拒/落盘缺键拒/文字同比/手估拒/漏抄告警）")


def test_period_track_verdict_goal_gate():
    """v5.0：verdict_* 非四选一拒 / 缺失软告警（渲染兜底无法判定）；goal_* 非正数或夹带
    文字拒；年报期填 industry/forecast/note 软告警不拒；note_html 纯文本 >120 字软告警。"""
    f = period_fill()
    f["period_track"]["verdict_np"] = "超预期"
    expect_valueerror(f, "判词非法取值应拒")
    f = period_fill()
    del f["period_track"]["verdict_np"]
    out = validate_stderr(f)
    assert "verdict_np 未填" in out and "无法判定" in out, "判词缺失应软告警"
    f = period_fill()
    f["period_track"]["goal_np"] = -5
    expect_valueerror(f, "经营目标负数应拒")
    f = period_fill()
    f["period_track"]["goal_np"] = "约200亿"
    expect_valueerror(f, "经营目标夹带文字应拒")
    # 年报期填内容 → 软告警不拒；verdict 缺失不告警（整章消失，判词无意义）
    f = period_fill("annual")
    f["period_track"]["note_html"] = "年报口径提示一句。"
    out = validate_stderr(f)
    assert "整章消失" in out and "不会渲染" in out, "年报期填内容应软告警"
    assert "verdict_" not in validate_stderr(period_fill("annual")), "年报期判词缺失不告警"
    f = period_fill()
    f["period_track"]["note_html"] = "口径提示超长" * 25
    out = validate_stderr(f)
    assert "note_html" in out and "> 120" in out, "note_html 超长应软告警"
    f = period_fill()
    f["period_track"]["summary_html"] = "小结超长" * 30
    out = validate_stderr(f)
    assert "summary_html" in out and "> 100" in out, "summary_html 超长应软告警"
    print("OK period_track 判词/目标门禁（非法拒/缺失告警/负数拒/年报期内容告警/note 与 summary 超长告警）")


def test_period_chapter_render():
    """v5.0.1 第 3 章渲染：TOC 与章节同生共灭（锚件=累计一览卡）；小结条/一览卡/子弹图/
    单季双联图落位；双分母缺失 → 子弹图无参照行整图缺席、章节靠一览卡存活；
    四项金额全缺 → 整章消失（TOC 同灭）。"""
    html = render_fill(period_fill())
    assert 'href="#s3"' in html and 'id="s3"' in html, "has_period 时 TOC 与章节同生"
    assert "进度小结" in html and "本期累计一览" in html, "小结条与一览卡落位"
    assert 'aria-label="报告期进度子弹图"' in html and 'aria-label="单季同比对比图"' in html
    assert "经营目标 200 亿 · 已完成 48.6%" in html and "一致预期 165 亿 · 已完成 58.9%" in html, \
        "双分母刻度带完成度"
    assert "节奏带（按" in html, "节奏带注"
    for frag in ("营业收入（亿元）", "经营现金流（亿元）", "归母净利（亿元）", "扣非净利（亿元）"):
        assert frag in html, f"单季双联四组缺 {frag}"
    s3_blk = html.split('id="s3"', 1)[1].split('id="s4"', 1)[0]
    assert "<table" not in s3_blk, "v5.0.1 绝对额表已删除（信息并入一览卡与子弹图刻度）"
    assert html.find('id="s3"') < html.find('id="s4"'), "第 3 章应插在原 s3（现 s4）之前"
    # 年报期：TOC 与章节同灭
    html_a = render_fill(period_fill("annual"))
    assert 'href="#s3"' not in html_a and 'id="s3"' not in html_a, "年报期整章消失"
    # 双分母缺失：子弹图无参照行整图缺席（不画空轨道），章节靠一览卡存活（TOC 不死链）
    f = period_fill()
    f["period_track"]["goal_np"] = None
    f["period_track"]["consensus_np"] = None
    html2 = render_fill(f)
    assert 'id="s3"' in html2 and 'href="#s3"' in html2 and "本期累计一览" in html2
    assert 'aria-label="报告期进度子弹图"' not in html2, "无全年参照不画子弹图"
    assert "一致预期 165 亿" not in html2 and "经营目标 200 亿" not in html2
    # 四项金额全缺 → 一览卡空串 → 整章消失（TOC 同灭，无死链）
    f = period_fill()
    f["period_track"] = {"period": "2026中报", "is_annual": False}
    html3 = render_fill(f)
    assert 'id="s3"' not in html3 and 'href="#s3"' not in html3, "四值全缺整章消失"
    print("OK 第 3 章渲染（TOC 同生共灭/小结条/一览卡/完成度刻度/无参照不画子弹图/全缺整章消失）")


def test_period_charts_shapes():
    """v5.0.1 图函数形态：小结条徽章合成与 summary_html 直通 / 一览卡四卡与全缺空串 /
    子弹图仅画有参照行（无分母行跳过并图注点名、扣非永不入图）/ 刻度带完成度 /
    缺判词兜底无法判定 / 单季双联四组与 Q1 退化单柱 / 缺 sq_label 或四组全 None 返回空串。"""
    from charts_period import (build_period_summary, build_period_kpi,
                             build_period_bullets, build_period_sqplot)
    h1 = period_fill("h1")["period_track"]
    # 小结条：徽章合成 + 无参照点名 + summary_html 手填句直通
    s = build_period_summary(h1)
    assert "进度小结" in s and ">超前</span>" in s and ">正常</span>" in s
    assert "完成卖方一致预期 58.9%" in s, "summary_html 手填句直通"
    assert "营业收入、扣非净利无金额化全年参照" in s and "经营现金流不设判词" in s
    assert build_period_summary({"ocf": 10.0}) == "", "无判词指标且无手填句 → 空串"
    # 一览卡：四卡齐全、缺值标—、全缺空串
    k = build_period_kpi(h1)
    assert k.count("metric-card") == 4 and "92.10" in k and "+49.7%" in k
    k2 = build_period_kpi({"rev": 10.0})
    assert k2.count("metric-card") == 4 and ">—<" in k2, "缺值卡标—"
    assert build_period_kpi({"rev": None, "np": None, "np_dedt": None, "ocf": None}) == ""
    # 子弹图：仅归母行（goal/cons 在），营业收入不画行、扣非永不入图
    b = build_period_bullets(h1)
    assert ">归母净利</text>" in b and ">营业收入</text>" not in b and ">扣非净利</text>" not in b
    assert "经营目标 200 亿 · 已完成 48.6%" in b and "一致预期 165 亿 · 已完成 58.9%" in b
    assert "营业收入无金额化全年参照" in b, "跳过行图注点名"
    assert ">超前</text>" in b
    assert build_period_bullets({"np_dedt": 21.47}) == "", "扣非无分母口径不画"
    assert build_period_bullets({"rev": 100.0}) == "", "营收无 goal_rev 不画"
    assert build_period_bullets({"rev": None, "np": None, "np_dedt": None}) == ""
    # 缺判词 → 无法判定兜底
    b2 = build_period_bullets({"np": 5.0, "consensus_np": 100.0})
    assert ">无法判定</text>" in b2
    # 单季双联：四组齐（收入/现金流左联，归母/扣非右联）
    svg = build_period_sqplot(h1)
    for frag in ("营业收入（亿元）", "经营现金流（亿元）", "归母净利（亿元）", "扣非净利（亿元）",
                 "收入与经营现金流", "归母与扣非", "+40.8%", "+84.9%", "+65.7%", "+50.1%",
                 "2025Q2", "2026Q2"):
        assert frag in svg, f"双联图缺 {frag}"
    # Q1 退化单柱
    q1 = build_period_sqplot(period_fill("q1")["period_track"])
    assert "2025Q1" not in q1 and "累计即单季" in q1, "Q1 期应退化单柱"
    # 空串门禁
    assert build_period_sqplot({"sq_rev": 1}) == "", "缺 sq_label 返回空串"
    assert build_period_sqplot({"sq_label": "2026Q2", "sq_rev": None, "sq_np": None,
                                "sq_dedt": None, "sq_ocf": None}) == ""
    # 整联缺席：只剩收入/现金流 → 右联标题缺席（联标题以 </text> 收尾，与图注措辞区分）
    svg2 = build_period_sqplot({"sq_label": "2026Q2", "sq_rev": 10.0, "sq_ocf": 5.0,
                                "sq_prev_label": "2025Q2", "sq_prev_rev": 8.0,
                                "sq_prev_ocf": 4.0})
    assert ">收入与经营现金流</text>" in svg2 and ">归母与扣非</text>" not in svg2
    print("OK 第 3 章图函数形态（小结条/一览卡/子弹图有参照才画/单季双联/Q1 退化/空串门禁）")


def test_period_track_key_drift():
    """period_track 键集漂移守卫（v5.1.5）：生产端（em_finance._PERIOD_TRACK_KEYS 常量与
    _period_track_calc 实际产出）、校验端（validate 四组键 + is_annual/band_years）、落盘参照
    （conftest._PERIOD_REF_KEYS）三处必须对齐——任一处加键忘同步即红
    （end_date/gm 为生产端内部键，不入参照）。"""
    import em_finance
    import validate as V
    ref = set(_PERIOD_REF_KEYS)
    assert set(em_finance._PERIOD_TRACK_KEYS) - {"end_date", "gm"} == ref, \
        "生产端常量 vs 落盘参照键集漂移"
    vkeys = (set(V._PERIOD_LABEL_KEYS) | set(V._PERIOD_NUM_KEYS) | set(V._PERIOD_YOY_KEYS)
             | set(V._PERIOD_BAND_KEYS) | {"is_annual", "band_years"})
    assert vkeys == ref, "校验端四组键 vs 落盘参照键集漂移"
    rows = [{"ED": "20260630", "TOTALOPERATEREVE": 1e8, "PARENTNETPROFIT": 1e7,
             "KCFJCXSYJLR": None, "NETCASH_OPERATE_PK": None, "XSMLL": None}]
    assert set(em_finance._period_track_calc(rows)) == set(em_finance._PERIOD_TRACK_KEYS), \
        "常量与 _period_track_calc 实际产出键集漂移"
    print("OK period_track 键集三方对齐（生产端常量=实际产出=校验端=落盘参照）")


# ---------------- v5.0 决策层三机制（临界档透明化 / 乐观税门禁 / 赔率∞地板分级） ----------------

def test_position_steps_edge_critical():
    """v5.0 机制一（临界档透明化）：距最近边界 ≤0.3 → 有效分压到边界下侧（相邻两档孰低），
    上浮类调节（时机≥6/离散度<40%/赔率∞）一律冻结、下调照常；slot_txt 带临界说明。"""
    # q=7.2 临界（距 7.0 边界 0.2）→ 降档落 10 档（中上·好价格）；三条上浮路径全冻结
    label, steps, slot, crit = _position_steps(
        7.2, 8.5, 7.0, _calc(dispersion=0.30, odds=None, floor_type="net_cash"), "")
    assert label == "标准仓 ≤10%", f"临界降档+上浮冻结应止步标准仓，实际 {label}"
    assert [c["track"] for c in crit] == ["质量"] and abs(crit[0]["dist"] - 0.2) < 1e-9
    assert "档位临界：质量分 7.20 距 7.0 边界 0.20，按相邻两档孰低降档执行" in slot
    assert sum("上浮冻结" in s for s in steps) == 3, f"三条上浮路径应全冻结：{steps}"
    assert "重仓" not in label
    # q=7.0 恰在边界（dist=0）→ 同样降档
    label, steps, slot, crit = _position_steps(7.0, 8.5, 5.0, _calc(), "")
    assert label == "标准仓 ≤10%" and crit and crit[0]["dist"] == 0.0
    # v=8.2 临界 → 落「中上·合理偏便宜」5 档（质量 5.5-7 行 × 估值 6-8 列）
    label, steps, slot, crit = _position_steps(6.0, 8.2, 5.0, _calc(), "")
    assert label == "轻仓 ≤5%" and [c["track"] for c in crit] == ["估值"]
    assert "估值分 8.20 距 8.0 边界 0.20" in slot
    # 临界 + 时机 3.5 → 下调照常（10 档 → 5 档），无冻结噪音
    label, steps, slot, crit = _position_steps(7.2, 8.5, 3.5, _calc(), "")
    assert label == "轻仓 ≤5%", f"下调照常应落轻仓，实际 {label}"
    assert any("下调一档" in s for s in steps) and not any("上浮冻结" in s for s in steps)
    # 非临界对照：7.5×8.5 直落重仓，crit 为空
    label, steps, slot, crit = _position_steps(7.5, 8.5, 5.0, _calc(), "")
    assert label == "重仓 ≤20%" and crit == []
    # 双轨同时临界：7.2×8.2 → 双双降档（中上·合理偏便宜 5 档）
    label, steps, slot, crit = _position_steps(7.2, 8.2, 5.0, _calc(), "")
    assert label == "轻仓 ≤5%" and len(crit) == 2
    print("OK 临界档决策链（降档执行/上浮冻结/下调照常/边界值/双轨临界）")


def test_position_steps_odds_floor_gate():
    """v5.0 机制三（调节链侧）：赔率 ∞ 上浮一档仅硬地板=net_cash 享受；dividend 软地板
    记「估值分 +1 封顶 7.5，调节链不上浮」；floor 缺失不上浮（防御，validate 已硬拒）。"""
    label, steps, _s, _c = _position_steps(
        4.5, 4.5, 5.0, _calc(dispersion=0.50, odds=None, floor_type="net_cash"), "")
    assert label == "标准仓 ≤10%"
    assert steps == ["赔率调节：赔率 ∞（悲观仍正收益） → 上浮一档（轻仓 ≤5%→标准仓 ≤10%）"], steps
    label, steps, _s, _c = _position_steps(
        4.5, 4.5, 5.0, _calc(dispersion=0.50, odds=None, floor_type="dividend"), "")
    assert label == "轻仓 ≤5%"
    assert steps == ["赔率 ∞（软地板=保底分红折现）：估值分 +1 封顶 7.5，调节链不上浮"], steps
    label, steps, _s, _c = _position_steps(
        4.5, 4.5, 5.0, _calc(dispersion=0.50, odds=None), "")
    assert label == "轻仓 ≤5%" and steps == ["矩阵落位直接生效，无调节项触发"], steps
    print("OK 赔率 ∞ 地板分级调节链（硬地板上浮/软地板不上浮/无地板不上浮）")


def test_optimism_tax_gate():
    """v5.0 机制二（乐观税门禁）：base 净利 ÷ 一致预期 > 1.15 且非 A 档 → 中枢分封顶 6
    重算总分；A 档解封；缺 consensus_np 跳过（tax=None）；过程卡三态标注。"""
    calc = R.compute_valuation(minimal_fill())   # base 情景 profit=100
    inputs = {"pe_ttm": 11, "pe_band": [10, 12], "div_yield": 2, "risk_free": 1.7}
    # ratio = 100/80 = 1.25 > 1.15，gap_tier=B → 中枢 7.0 封顶 6 → 总分 6×.4+3.5×.25+5×.25+6×.1=5.1
    vc = R.compute_valuation_score(calc, dict(inputs, consensus_np=80), gap_tier="B")
    assert vc["tax"]["capped"] is True and vc["tax"]["exempt"] is False
    assert abs(vc["tax"]["ratio"] - 1.25) < 1e-9
    assert vc["central_s"] == 6.0 and vc["score"] == 5.1
    # A 档解封（去空格大写判定）：不封顶，分数回 5.5
    vc_a = R.compute_valuation_score(calc, dict(inputs, consensus_np=80), gap_tier=" a ")
    assert vc_a["tax"]["exempt"] is True and vc_a["tax"]["capped"] is False
    assert vc_a["central_s"] == 7.0 and vc_a["score"] == 5.5
    # ratio ≤ 1.15 不触发（1.10 → 不封不免注）
    vc_lo = R.compute_valuation_score(calc, dict(inputs, consensus_np=91), gap_tier="B")
    assert vc_lo["tax"]["capped"] is False and vc_lo["central_s"] == 7.0
    # 缺 consensus_np → tax=None 跳过
    vc_n = R.compute_valuation_score(calc, inputs)
    assert vc_n["tax"] is None and vc_n["score"] == 5.5
    # F16：consensus_np 键存在但 ≤0（亏损预期）→ legend 单列，与「无卖方覆盖」区分
    card_neg = R.build_valuation_process_card(calc, vc_n, dict(inputs, consensus_np=-5))
    assert "一致预期为负/零，乐观税不适用" in card_neg and "无卖方覆盖" not in card_neg
    card_zero = R.build_valuation_process_card(calc, vc_n, dict(inputs, consensus_np=0))
    assert "一致预期为负/零，乐观税不适用" in card_zero
    # 过程卡标注三态
    card = R.build_valuation_process_card(calc, vc, dict(inputs, consensus_np=80))
    assert "乐观税封顶 6" in card and "1.25" in card and "A 档" in card
    card_a = R.build_valuation_process_card(calc, vc_a, dict(inputs, consensus_np=80))
    assert "乐观税已检" in card_a and "A 档解封" in card_a
    card_n = R.build_valuation_process_card(calc, vc_n, inputs)
    assert "乐观税未检：无卖方覆盖" in card_n
    # mcap 口径：base 无 profit → tax=None，legend 标市值口径
    mcalc = {"central": 0.05, "central_raw": 0.05, "odds": 1.0, "dispersion": 0.5,
             "mode": "mcap", "horizon": "12个月",
             "rows": [{"key": "pess", "low": 7.0}, {"key": "base", "profit": None}]}
    vc_m = R.compute_valuation_score(mcalc, dict(inputs, consensus_np=80), gap_tier="B")
    assert vc_m["tax"] is None
    assert "乐观税未检：市值口径无净利可比" in R.build_valuation_process_card(mcalc, vc_m, inputs)
    print("OK 乐观税门禁（>1.15 封顶 6 / A 档解封 / 未触发 / 缺一致预期跳过 / 卡三态标注）")


def test_floor_uplift_grading():
    """v5.0 机制三（估值分侧）：赔率 ∞ 上浮分级——net_cash 硬地板 max(score,8.0)；
    dividend 软地板 +1 封顶 7.5（保送不减分）；floor 缺失不上浮；过程卡赔率行与 legend 标注。"""
    inputs = {"pe_ttm": 11, "pe_band": [10, 12], "div_yield": 2, "risk_free": 1.7}
    # 底分：中枢 5%→6.0×0.4 + 赔率∞→10×0.25 + 合理倍数 5.0×0.25 + 股息 6.0×0.1 = 6.75→6.8
    base_calc = {"central": 0.05, "central_raw": 0.05, "odds": None, "dispersion": 0.5,
                 "horizon": "12个月",
                 "rows": [{"key": "pess", "low": 10.5}, {"key": "base", "profit": 100}]}
    vc = R.compute_valuation_score(
        dict(base_calc, pess_floor={"type": "net_cash", "value": 12.5,
                                    "evidence": "净现金125亿÷总股本10亿"}), inputs)
    assert vc["score"] == 8.0
    assert vc["floor_uplift"] == {"type": "net_cash", "before": 6.8, "after": 8.0}
    vc2 = R.compute_valuation_score(
        dict(base_calc, pess_floor={"type": "dividend", "value": 10.6,
                                    "evidence": "保底分红0.7元/股×15年折现"}), inputs)
    assert vc2["score"] == 7.5 and vc2["floor_uplift"]["type"] == "dividend"
    vc3 = R.compute_valuation_score(base_calc, inputs)
    assert vc3["score"] == 6.8 and vc3["floor_uplift"] is None
    # 过程卡赔率分行地板信息 + legend 上浮说明（软地板注明调节链不上浮）
    calc_hard = dict(base_calc, pess_floor={"type": "net_cash", "value": 12.5,
                                            "evidence": "净现金125亿÷总股本10亿"})
    calc_soft = dict(base_calc, pess_floor={"type": "dividend", "value": 10.6,
                                            "evidence": "保底分红0.7元/股×15年折现"})
    card = R.build_valuation_process_card(calc_hard, vc, inputs)
    assert "悲观下限 10.5 ≥ 现价" in card and "硬地板=净现金/股 12.5：净现金125亿÷总股本10亿" in card
    assert "上浮至 8" in card
    card2 = R.build_valuation_process_card(calc_soft, vc2, inputs)
    assert "软地板=保底分红折现/股 10.6" in card2 and "调节链不上浮" in card2
    # F14：floor.type 空白/大小写归一（compute_valuation 透传层，三处消费口径同源）
    f_nc = minimal_fill()
    f_nc["valuation"]["scenarios"][0]["floor"] = {"type": " Net_Cash ", "value": 6.5,
                                                  "evidence": "净现金65亿÷总股本10亿"}
    assert R.compute_valuation(f_nc)["pess_floor"]["type"] == "net_cash"
    # F15：floor.evidence / metric_label 进过程卡前逐段 _esc（不双重转义、不裸注入）
    ev = '净现金 A&B <实测> "引号"'
    calc_ev = dict(base_calc, pess_floor={"type": "net_cash", "value": 12.5, "evidence": ev})
    card_ev = R.build_valuation_process_card(calc_ev, vc, inputs)
    assert "A&amp;B &lt;实测&gt; &quot;引号&quot;" in card_ev and ev not in card_ev, \
        "evidence 应转义一次且不双重转义"
    card_ml = R.build_valuation_process_card(base_calc, vc3, dict(inputs, metric_label="PE<b>"))
    assert "PE&lt;b&gt;" in card_ml
    print("OK 赔率 ∞ 估值分地板分级（硬地板到 8 / 软地板 +1 封顶 7.5 / 无地板不上浮 / 卡标注）")


def test_odds_floor_validate():
    """v5.0 机制三（校验侧 _check_odds_floor）：悲观下限 ≥ 现价（赔率 ∞）时——无 floor 拒 /
    type 非法拒 / evidence 空拒 / floor.value < 下限×0.99 拒 / 合规硬软地板过；
    赔率有限时 floor 软告警（无作用可删）。"""
    def odds_inf_fill(floor=None):
        f = minimal_fill()
        # 悲观下限 = 110×9.5/100 = 10.45 ≥ 现价 10；中枢 11 ≤ base 中枢 11，不触倒挂
        f["valuation"]["scenarios"][0] = {"key": "pess", "label": "悲观", "trigger": "下行",
                                          "profit": 110, "pe": [9.5, 10.5]}
        if floor:
            f["valuation"]["scenarios"][0]["floor"] = floor
        f["thesis_html"] = f["thesis_html"].replace(
            '<span class="scenario-pess">7.2</span>', '<span class="scenario-pess">11</span>')
        return f
    expect_valueerror(odds_inf_fill(), "赔率 ∞ 无地板应拒渲染")
    expect_valueerror(odds_inf_fill({"type": "净资产", "value": 11, "evidence": "x"}),
                      "floor.type 非法应拒")
    expect_valueerror(odds_inf_fill({"type": "net_cash", "value": 11, "evidence": ""}),
                      "floor.evidence 空应拒")
    expect_valueerror(odds_inf_fill({"type": "net_cash", "value": 10.0,
                                     "evidence": "净现金100亿÷总股本10亿"}),
                      "地板值 10.0 < 悲观下限 10.45×0.99 应拒")
    ok = odds_inf_fill({"type": "net_cash", "value": 10.5, "evidence": "净现金105亿÷总股本10亿"})
    R.validate_content(ok, R.compute_valuation(ok))   # 硬地板合规 → 过
    ok2 = odds_inf_fill({"type": "dividend", "value": 10.5, "evidence": "保底分红0.7元/股×15年折现"})
    R.validate_content(ok2, R.compute_valuation(ok2))  # 软地板合规 → 过
    # 赔率有限（下限 < 现价）+ floor → 软告警不拒
    f = minimal_fill()
    f["valuation"]["scenarios"][0]["floor"] = {"type": "net_cash", "value": 6.5,
                                               "evidence": "净现金65亿÷总股本10亿"}
    out = validate_stderr(f)
    assert "floor" in out and "无作用" in out, "赔率有限时 floor 应软告警"
    # F17：floor 写在 base/opt → 软告警不拒（floor 是悲观情景子键，写错位置不生效）
    f = minimal_fill()
    f["valuation"]["scenarios"][1]["floor"] = {"type": "net_cash", "value": 6.5,
                                               "evidence": "净现金65亿÷总股本10亿"}
    out = validate_stderr(f)
    assert "floor" in out and "写错位置不生效" in out, "floor 写错位置应软告警"
    # F17：相等边界（悲观下限 == 现价）报错文案用「不低于（≥）」而非「高于」
    f_eq = minimal_fill()
    f_eq["valuation"]["scenarios"][0] = {"key": "pess", "label": "悲观", "trigger": "下行",
                                         "profit": 100, "pe": [10, 11]}  # 下限=100×10÷100=10 == 现价
    f_eq["thesis_html"] = f_eq["thesis_html"].replace(
        '<span class="scenario-pess">7.2</span>', '<span class="scenario-pess">10.5</span>')
    try:
        R.validate_content(f_eq, R.compute_valuation(f_eq))
        raise AssertionError("下限等于现价且无地板应拒")
    except ValueError as e:
        assert "不低于" in str(e) and "≥" in str(e), f"文案应改「不低于（≥）」，实际 {e}"
    print("OK 赔率 ∞ 地板校验（无地板拒/非法拒/空证据拒/托不住拒/软硬地板过/有限时软告警）")


def test_consensus_np_cross_check():
    """v5.0 机制二（校验侧 _check_consensus_np）：valuation_inputs.consensus_np 照抄落盘
    consensus_np.np_avg——一致过 / 偏差 >1% 拒 / fill 有值落盘无键拒（手估嫌疑）/
    落盘有 fill 无软告警（漏抄，乐观税未检）/ 双向皆缺过。"""
    with tempfile.TemporaryDirectory() as d:
        ref = write_fill({"price": 10.0, "pe_ttm": 11.0,
                          "consensus_np": {"year": 2026, "np_avg": 100.0, "orgs": 12}},
                         d, name="em_ref.json")
        q = {"source_file": ref, "date": "2026-08-27"}
        f = minimal_fill(quote=q)
        f["valuation_inputs"]["consensus_np"] = 100.5   # 0.5% 偏差 → 过
        R.validate_content(f, R.compute_valuation(f))
        f = minimal_fill(quote=q)
        f["valuation_inputs"]["consensus_np"] = 105.0   # 5% 偏差 → 拒
        expect_valueerror(f, "consensus_np 与落盘偏差>1% 应拒")
        # fill 有值落盘无键 → 拒（手估嫌疑）
        ref2 = write_fill({"price": 10.0, "pe_ttm": 11.0}, d, name="em_ref2.json")
        f = minimal_fill(quote={"source_file": ref2, "date": "2026-08-27"})
        f["valuation_inputs"]["consensus_np"] = 100.0
        expect_valueerror(f, "落盘无 consensus_np 键而 fill 手填应拒")
        # 落盘有 fill 无 → 软告警（漏抄，乐观税未检）
        out = validate_stderr(minimal_fill(quote=q))
        assert "consensus_np" in out and "漏抄" in out, "落盘有 fill 无应软告警"
        # 双向皆缺 → 通过且无告警
        out2 = validate_stderr(minimal_fill(quote={"source_file": ref2, "date": "2026-08-27"}))
        assert "consensus_np" not in out2, "双向皆缺不应告警"
    print("OK consensus_np 交叉校验（一致过/偏差拒/手估拒/漏抄告警/双缺过）")


def test_edge_upgrade_rows():
    """v5.0 机制一：build_edge_upgrade_rows 输出——每条临界轨一条 pending 灰态 trig
    （升档路径 + 复核证据），块首 section-tag；空 crit 返回空串。"""
    crit, q_eff, v_eff = _edge_info(7.2, 8.5)
    assert len(crit) == 1 and q_eff < 7.0 and v_eff == 8.5
    html = build_edge_upgrade_rows(crit)
    assert "档位临界升档路径（脚本生成）" in html
    assert "档位临界升档复核：质量分 7.20（距 7.0 边界 0.20）" in html
    assert "复核期质量分 ≥7.31" in html and "复核证据" in html
    assert 'trig-dot pending' in html and '<span class="trig-status pending">待验证</span>' in html
    assert build_edge_upgrade_rows([]) == ""
    # 下侧临界（6.8 距 7.0 为 0.2）：有效分压边界下侧但档位归属不变（行为等价孰低）
    crit2, q_eff2, _v2 = _edge_info(6.8, 5.0)
    assert len(crit2) == 1 and crit2[0]["bound"] == 7.0
    assert 6.8 < q_eff2 < 7.0
    assert "质量分 6.80（距 7.0 边界 0.20）" in build_edge_upgrade_rows(crit2)
    print("OK 临界升档路径行（结构/文案/空串/下侧临界）")


def test_position_card_edge_badge():
    """v5.0 机制一：三轨判定卡临界轨 sub 追加「档位临界」橙徽章 + 距离说明；非临界不带。"""
    html = R.build_position_card(minimal_fill(), quality=7.2, valuation=8.5,
                                 timing=5.0, calc=_calc(), red_flag="")
    assert '<span class="badge badge-orange">档位临界</span>' in html
    assert "距 7.0 边界 0.20，按降档执行" in html
    assert "标准仓 ≤10%" in html, "临界降档应落中上·好价格 10 档"
    html2 = R.build_position_card(minimal_fill(), quality=7.5, valuation=8.5,
                                  timing=5.0, calc=_calc(), red_flag="")
    assert "档位临界" not in html2, "非临界不应带徽章"
    html3 = R.build_position_card(minimal_fill(), quality=6.0, valuation=8.2,
                                  timing=5.0, calc=_calc(), red_flag="")
    assert "距 8.0 边界 0.20，按降档执行" in html3, "估值轨临界徽章"
    print("OK 仓位卡临界徽章（质量轨/估值轨/非临界对照）")


def test_edge_upgrade_mounted_in_ch14():
    """v5.0 机制一：升档路径行挂 14 章跟踪仪表盘（TRIGGERS_HTML 拼接）；红灯熔断时不挂
    （仓位未走矩阵）。minimal_fill 质量分恰 7.00（dist 0）→ 渲染必出临界行。"""
    html = render_fill(minimal_fill())
    s14 = html.split('id="s14"', 1)[1]
    assert "档位临界升档路径（脚本生成）" in s14
    assert "档位临界升档复核：质量分 7.00（距 7.0 边界 0.00）" in s14
    f = minimal_fill(red_flag="测试红灯占位",
                     position_html="<p>不建议参与。" + "时机判定与决策逻辑。" * 12 + "</p>")
    html2 = render_fill(f)
    assert "档位临界升档路径" not in html2, "红灯熔断时不得挂临界升档行"
    print("OK 临界升档行 14 章挂载（常挂/红灯不挂）")


def test_period_charts_negative_domain():
    """F1/F2 负值域修复（v5.0.1 适配）：子弹图——归母亏损（有参照）/全负/零值/负一致预期渲染
    不炸且语义正确（负值条自零轴左伸、负分母不画节奏带且图注标不适用、域退化兜底不除零、
    累计或分母 ≤0 不标完成度）；单季双联——双负（减亏/增亏季）/单负（最新季负）不炸、
    柱体在 viewBox 内。"""
    import re as _re
    from charts_period import build_period_bullets, build_period_sqplot
    # ① 归母亏损（np<0，有经营目标参照）：不炸；负值条标签存在；正值分母刻度与节奏带照常
    pt = {"np": -2.0, "np_yoy": "转亏", "goal_np": 100.0, "consensus_np": 165.0,
          "band_np": [39.9, 52.1], "verdict_np": "滞后"}
    b = build_period_bullets(pt)
    assert b and 'aria-label="报告期进度子弹图"' in b
    assert "-2 亿" in b and "转亏" in b, "负值条与文字同比应渲染"
    assert "一致预期 165 亿" in b and "节奏带（按" in b, "分母刻度与节奏带不受影响"
    # ② 全行负值（有参照才画）：域含 0、条自零轴左伸（不夹成 2px 细条钉零位）、不除零
    b2 = build_period_bullets({"np": -50.0, "goal_np": 100.0})
    assert b2, "负值应渲染"
    assert "-50 亿" in b2 and 'width="2.0"' not in b2, "负值条不得被夹成 2px 细条"
    # ③ 零值：域退化兜底 lo+1.0，不炸
    b3 = build_period_bullets({"np": 0.0, "goal_np": 100.0})
    assert b3 and 'aria-label="报告期进度子弹图"' in b3
    # ④ 负一致预期：节奏带不画、图注标「分母为负…节奏带不适用」；负刻度在画布内
    b4 = build_period_bullets({"np": -5.0, "consensus_np": -50.0, "band_np": [40.0, 55.0]})
    assert "分母为负" in b4 and "节奏带不适用" in b4, "负分母应出图注"
    assert "节奏带（按" not in b4, "负分母不得换算节奏带"
    assert "一致预期 -50 亿" in b4, "负一致预期刻度应在负域内画出"
    # 累计或分母 ≤0 → 完成度无意义不标
    assert "已完成" not in b and "已完成" not in b4, "累计/分母 ≤0 不标完成度"
    # F2：双负（增亏/减亏季）与单负（最新季负）不炸、所有 rect 在 viewBox 内
    sq1 = build_period_sqplot({"sq_label": "2026Q2", "sq_rev": -10.0, "sq_np": -3.0,
                               "sq_prev_label": "2025Q2", "sq_prev_rev": -8.0,
                               "sq_prev_np": -5.0, "sq_np_yoy": "减亏"})
    assert sq1 and "减亏" in sq1, "双负季应渲染"
    sq2 = build_period_sqplot({"sq_label": "2026Q2", "sq_rev": 100.0, "sq_np": -3.0,
                               "sq_prev_label": "2025Q2", "sq_prev_rev": 90.0,
                               "sq_prev_np": 5.0, "sq_np_yoy": "转亏"})
    assert sq2 and "转亏" in sq2
    for svg, W, H in ((sq1, 1000, 268), (sq2, 1000, 268)):
        for m in _re.finditer(r'<rect x="([\d.-]+)" y="([\d.-]+)" width="([\d.-]+)" '
                              r'height="([\d.-]+)"', svg):
            x, y, w, h = (float(m.group(i)) for i in (1, 2, 3, 4))
            assert -1 <= x and x + w <= W + 1, f"rect 横向越界: {m.group(0)}"
            assert -1 <= y and y + h <= H + 1, f"rect 纵向越界: {m.group(0)}"
    print("OK 负值域（子弹图归母亏损/全负/零值/负一致预期/负值不标完成度 + 单季双联双负/单负）")


def test_net_cash_floor_edge_exemption():
    """F3 机制碰撞修复：net_cash 硬地板上浮恰落 8.0 → 估值轨豁免临界判定（落点是机制产物
    非测量噪声）——票面 8.0 不挂临界徽章、矩阵按 8.0 落 ≥8 列、赔率 ∞ 上浮不冻结；
    对照：不传 floor_uplift 旧行为仍判临界；dividend 软地板落 7.5 行为不变；
    质量轨临界+估值轨豁免组合只质量降档。"""
    calc = _calc(dispersion=0.50, odds=None, floor_type="net_cash")
    fu = {"type": "net_cash", "before": 6.8, "after": 8.0}
    # 底分 6.8 上浮 8.0 + 质量 7.5 → 矩阵直落「好公司·好价格」重仓，crit 空、无徽章
    label, steps, slot, crit = _position_steps(7.5, 8.0, 5.0, calc, "", floor_uplift=fu)
    assert label == "重仓 ≤20%" and crit == [], f"豁免后应直落重仓，实际 {label}/{crit}"
    assert "档位临界" not in slot
    # 对照：不传 floor_uplift（旧行为）→ 恰落 8.0 判临界，降档 10 档 + 上浮冻结
    label2, steps2, slot2, crit2 = _position_steps(7.5, 8.0, 5.0, calc, "")
    assert label2 == "标准仓 ≤10%" and [c["track"] for c in crit2] == ["估值"]
    assert "估值分 8.00 距 8.0 边界 0.00" in slot2
    # 质量轨临界 + 估值轨豁免 → 只质量降档（中上·好价格 10 档）
    label3, _s3, slot3, crit3 = _position_steps(7.2, 8.0, 5.0, calc, "", floor_uplift=fu)
    assert label3 == "标准仓 ≤10%" and [c["track"] for c in crit3] == ["质量"]
    assert "估值分 8.00 距" not in slot3, "估值轨豁免后不挂临界说明"
    # dividend 软地板落 7.5 → 不豁免（本就不临界），落 6-7.9 列行为不变
    fu_d = {"type": "dividend", "before": 6.8, "after": 7.5}
    label4, _s4, _sl4, crit4 = _position_steps(7.5, 7.5, 5.0, _calc(odds=None, floor_type="dividend"),
                                               "", floor_uplift=fu_d)
    assert label4 == "标准仓 ≤10%" and crit4 == []
    # 赔率 ∞ 上浮生效轨迹（不被没收）：质量 4.5 落轻仓 → 硬地板上浮标准仓
    label5, steps5, _sl5, _c5 = _position_steps(4.5, 8.0, 5.0, calc, "", floor_uplift=fu)
    assert label5 == "标准仓 ≤10%"
    assert any("赔率调节" in s and "上浮一档" in s for s in steps5), f"上浮轨迹应出现：{steps5}"
    # _edge_info 直测：豁免后 crit 空且有效分保持 8.0（矩阵按 ≥8 列落位）
    crit_e, _q_e, v_eff_e = _edge_info(7.5, 8.0, fu)
    assert crit_e == [] and v_eff_e == 8.0
    # 卡片口径（build_position_card 透传 floor_uplift）：票面 8.0 无临界徽章、落重仓
    html = R.build_position_card(minimal_fill(), quality=7.5, valuation=8.0,
                                 timing=5.0, calc=calc, red_flag="", floor_uplift=fu)
    assert "档位临界" not in html and "重仓 ≤20%" in html
    print("OK 净现金硬地板临界豁免（重仓直落/徽章不挂/上浮不冻结/对照组不变）")


def test_scenario_dup_key_rejected():
    """F6：valuation.scenarios key 重复即拒渲染——双 pess 曾绕过地板门禁
    （next() 首个 vs by_key 末个口径分裂）；重复 key 没有合法语义。"""
    f = minimal_fill()
    f["valuation"]["scenarios"].append({"key": "PESS", "label": "悲观B", "trigger": "x",
                                        "profit": 70, "pe": [7, 9]})
    try:
        R.validate_content(f, R.compute_valuation(f))
        raise AssertionError("双 pess 应拒但未拒")
    except ValueError as e:
        assert "key 重复" in str(e), f"应报 key 重复，实际: {e}"
    print("OK scenarios 重复 key 拒渲染（双 pess 门禁绕过修复）")


def test_position_edge_true_min():
    """临界孰低必须两侧实算（热核审计发现）：矩阵质量 5.5 行非单调（v<6 时上侧=观察池、
    下侧=质地一般 5），只算压边界一侧会把观察池抬成轻仓——违反「降档不抬档」。"""
    # 5.5 边界 + v<6：原落位观察池，压边界后 5 → 孰低=观察池（修复前误抬轻仓）
    label, steps, slot, crit = _position_steps(5.6, 5.0, 5.0, None, "")
    assert label == "观察池" and "中上·差价格" in slot and "观察池" in slot, \
        f"孰低应保观察池，实际 {label}/{slot}"
    assert [c["track"] for c in crit] == ["质量"] and "孰低" in slot
    # 同边界 + v≥8：原 10、压边界 5 → 孰低=5（正常降档方向不受影响）
    label2, _s2, _sl2, _c2 = _position_steps(5.6, 8.5, 5.0, None, "")
    assert label2 == "轻仓 ≤5%", f"实际 {label2}"
    # 下侧临界（6.8 近 7.0）：两侧同行，落位不变
    label3, _s3, _sl3, crit3 = _position_steps(6.8, 8.5, 5.0, None, "")
    assert label3 == "标准仓 ≤10%" and [c["track"] for c in crit3] == ["质量"]
    # 4.0 边界上侧（4.15）：原轻仓 5、压边界 0 → 孰低=不建议参与（设计内陡降，钉住）
    label4, _s4, _sl4, _c4 = _position_steps(4.15, 5.0, 5.0, None, "")
    assert label4 == "不建议参与", f"实际 {label4}"
    # 非临界对照（5.9 距 5.5 为 0.4）：观察池、无临界
    label5, _s5, _sl5, crit5 = _position_steps(5.9, 5.0, 5.0, None, "")
    assert label5 == "观察池" and crit5 == []
    print("OK 临界孰低两侧实算（5.5 行非单调不抬档 / 4.0 陡降钉住 / 下侧临界不变）")


def test_anchor_discipline():
    """v5.1.0 估值锚纪律门禁（增量证据锁死 + 回滚条款前置）。
    full_fill 合规形态：上版 base PE 11-13x ≠ 本版 10-12x，附基本面证据 → 通过。"""
    # 合规基线：full_fill 本身应通过（台账+证据清单渲染路径的 golden 覆盖）
    R.validate_content(full_fill(), R.compute_valuation(full_fill()))
    # ① 回测模式 prev.scenarios 缺失 → 拒
    f = full_fill()
    f["prev"] = {"date": "2026-08-08", "quality": 6.4, "valuation": 5.0, "timing": 4.8,
                 "target_range": "9-11"}
    expect_valueerror(f, "回测模式 prev.scenarios 缺失应拒")
    # ② PE 带移动但无 pe_band_evidence → 拒
    f = full_fill()
    del f["valuation"]["pe_band_evidence"]
    expect_valueerror(f, "PE 带移动但无增量证据应拒")
    # ③ 证据仅有价格类 → 拒（纯价格证据不构成移动理由）
    f = full_fill()
    f["valuation"]["pe_band_evidence"] = [{"type": "价格", "note": "股价一个月下跌 16.6%"}]
    expect_valueerror(f, "纯价格证据应拒")
    f["valuation"]["pe_band_evidence"] = [{"type": "卖方观点", "note": "券商集体下修目标价"}]
    expect_valueerror(f, "纯卖方观点应拒")
    # ④ type 非法 / note 空 → 拒
    f = full_fill()
    f["valuation"]["pe_band_evidence"] = [{"type": "直觉", "note": "感觉要跌"}]
    expect_valueerror(f, "非法 type 应拒")
    f["valuation"]["pe_band_evidence"] = [{"type": "基本面", "note": "  "}]
    expect_valueerror(f, "空 note 应拒")
    # ⑤ PE 带与上版一致：填了证据 → 拒（画蛇添足）；不填 → 过
    same_prev = [{"scenario": "悲观情景", "归母净利": "75 亿", "PE": "8-10x",
                  "目标价": "6-7.5 元"},
                 {"scenario": "基础情景", "归母净利": "95 亿", "PE": "10-12x",
                  "目标价": "9.5-11.4 元"},
                 {"scenario": "乐观情景", "归母净利": "110 亿", "PE": "12-14x",
                  "目标价": "13.2-15.4 元"}]
    f = full_fill(prev={"date": "2026-08-08", "quality": 6.4, "valuation": 5.0,
                        "timing": 4.8, "target_range": "9-11", "scenarios": same_prev})
    expect_valueerror(f, "PE 带与上版一致但填了证据应拒")
    f = full_fill(prev={"date": "2026-08-08", "quality": 6.4, "valuation": 5.0,
                        "timing": 4.8, "target_range": "9-11", "scenarios": same_prev})
    del f["valuation"]["pe_band_evidence"]
    R.validate_content(f, R.compute_valuation(f))   # 不抛即过
    # ⑥ 重构偏离 >15%：无 rollback_html → 拒；有 → 过
    f = full_fill()
    f["pe_history"]["p25"], f["pe_history"]["p75"] = 20.0, 30.0  # 中枢25 vs pe_band中枢11 → -56%
    expect_valueerror(f, "重构偏离 >15% 无 rollback_html 应拒")
    f = full_fill()
    f["pe_history"]["p25"], f["pe_history"]["p75"] = 20.0, 30.0
    f["valuation"]["rollback_html"] = "回滚条件：煤价中枢回升至 900 元/吨上方 → PE 带回滚至历史带"
    R.validate_content(f, R.compute_valuation(f))   # 不抛即过
    # ⑦ 首版（无 prev）与市值口径不受门禁约束
    R.validate_content(minimal_fill(), R.compute_valuation(minimal_fill()))
    print("OK 估值锚纪律门禁（prev.scenarios 必填 / 移动须基本面证据 / 未移动禁填 / "
          "重构须 rollback_html / 首版与市值口径豁免）")


def test_cycle_stages_period_warn():
    """v5.1.3：period 解析不出起止月份 → 软告警「季K图阶段分界不落该段」
    （与渲染同源 parse_stage_period；合法格式如 2023/01–2023/12、2023-01~2024-06 放行）。"""
    base = [{"name": "阶段一", "period": "2023/01–2023/12", "current": False},
            {"name": "阶段二", "period": "2024-01~2024-12", "current": False},
            {"name": "阶段三", "period": "2025/01-2025/12", "current": False},
            {"name": "阶段四", "period": "2026/01–至今", "current": True}]
    out = validate_stderr(minimal_fill(cycle_stages=base))
    assert "阶段分界不落该段" not in out, "合法 period 不应告警"
    bad = [dict(base[0], period="去年至今"), base[1],
           dict(base[2], period="2025/13–2026/01"), base[3]]   # 无数字/月份越界；current 在阶段四
    out2 = validate_stderr(minimal_fill(cycle_stages=bad))
    assert out2.count("阶段分界不落该段") == 2, "非法 period（无数字/月份越界）应各告警一条"
    print("OK period 格式软告警（合法放行 / 无数字与月份越界各告警）")


def test_typing_v2_stock_type_enum():
    """v5.3.0 判据 v2：stock_type 枚举标准化——标准值放行、旧名映射告警、无法映射拒渲染。"""
    assert "无法映射六型" not in validate_stderr(minimal_fill()), "默认值周期股应放行"
    s = validate_stderr(minimal_fill(stock_type="稳健成长股"))
    assert "旧名" in s and "成长型" in s, "稳健成长股应映射成长型并告警旧名"
    s2 = validate_stderr(minimal_fill(stock_type="快速成长（强周期属性）"))
    assert "旧名" in s2 and "high" in s2, "快速成长应映射成长型·high 层"
    expect_valueerror(minimal_fill(stock_type="烟蒂股"), "无法映射六型")


def test_typing_v2_layer_share_mismatch():
    """型↔层占比对账（首版软约束）：稳定价值填 70:30 → 告警；85:15 → 不告警。"""
    f = minimal_fill(stock_type="稳定价值/金融（银行）", layer_share={"L1": 70, "L3": 30})
    assert "映射 85:15 不符" in validate_stderr(f), "稳定价值 70:30 应告警占比不符"
    f2 = minimal_fill(stock_type="稳定价值/金融（银行）", layer_share={"L1": 85, "L3": 15})
    assert "映射 85:15 不符" not in validate_stderr(f2), "85:15 不应告警"
    f3 = minimal_fill(stock_type="成熟/停滞", layer_share={"L1": 70, "L3": 30})
    assert "映射 80:20 不符" in validate_stderr(f3), "成熟/停滞 70:30 应告警占比不符"


def test_typing_v2_growth_tier_cagr():
    """成长层 CAGR 对账（v5.4.0 改扣非口径）：按 fin_trend 扣非柱复算，跨层（缓冲带 ±5pct 外）
    → 告警；归母柱不再作对账基准。"""
    # 默认扣非柱 [75,79,83,86,88]，CAGR≈4.1%：high 声明 → 告警；mid 声明 → 不告警（4.1% 近中速层下沿）
    f_high = minimal_fill(stock_type="成长型", growth_tier="high")
    assert "分层与财务事实不符" in validate_stderr(f_high), "扣非 CAGR 4.1% 声明 high 应告警"
    f_mid = minimal_fill(stock_type="成长型", growth_tier="mid")
    assert "应归高速层" not in validate_stderr(f_mid), "扣非 CAGR 4.1% 声明 mid 不应告警归高速层"
    # 扣非柱改 [10,15,22,33,50]（CAGR≈49.5%）：mid 声明 → 告警应归高速层
    f_fast = minimal_fill(stock_type="成长型", growth_tier="mid")
    f_fast["fin_trend"]["panels"][1]["bars"][1]["values"] = [10, 15, 22, 33, 50]
    assert "应归高速层" in validate_stderr(f_fast), "扣非 CAGR 49.5% 声明 mid 应告警归高速层"
    # 归母柱改飞不再影响对账（扣非柱未动 → 不告警）
    f_rm = minimal_fill(stock_type="成长型", growth_tier="mid")
    f_rm["fin_trend"]["panels"][1]["bars"][0]["values"] = [10, 15, 22, 33, 50]
    assert "应归高速层" not in validate_stderr(f_rm), "归母柱不再作对账基准"
    # 扣非 CAGR 20.4%（中速层缓冲带内：5-25% +5pct）→ 不告警
    f_in = minimal_fill(stock_type="成长型", growth_tier="mid")
    f_in["fin_trend"]["panels"][1]["bars"][1]["values"] = [100, 120, 145, 175, 210]
    assert "应归高速层" not in validate_stderr(f_in), "扣非 CAGR 20.4% 在中速层缓冲带内应放行"
    # 扣非 CAGR 30.5%（>30% 上沿）→ 告警应归高速层
    f_over = minimal_fill(stock_type="成长型", growth_tier="mid")
    f_over["fin_trend"]["panels"][1]["bars"][1]["values"] = [100, 130, 170, 220, 290]
    assert "应归高速层" in validate_stderr(f_over), "扣非 CAGR 30.5% 越中速层上沿应告警"


def test_typing_v2_evidence_keys():
    """typing_evidence 按型必填键（首版软约束）：缺失 → 告警；填齐 → 不告警。"""
    assert "typing_evidence 缺键" in validate_stderr(minimal_fill()), "未填 typing_evidence 应告警"
    te = {"commodity_link": "利润随电解铝价格波动（归因：商品价格）",
          "volatility_fact": "峰谷回撤 63%", "comparable_periods": "2015-2016 底部、2021-2022 顶部"}
    assert "typing_evidence 缺键" not in validate_stderr(minimal_fill(typing_evidence=te)), "周期股三键齐全不应告警"


def test_typing_v2_clash_whitelist():
    """撞车白名单：周期股×成长型可声明共存（cross_check ≥30 字）；其他对拒渲染。"""
    f = minimal_fill(stock_type="成长型", growth_tier="mid",
                     typing_clash={"with": "周期股", "primary_reason": "量增主导",
                                   "cross_check": "对照方法目标价 20-24 元，与主型结论方向一致，差异在倍数选择。"})
    assert "非白名单共存对" not in validate_stderr(f), "白名单对应放行"
    expect_valueerror(minimal_fill(stock_type="成长型", growth_tier="mid",
                                   typing_clash={"with": "困境反转", "cross_check": "x" * 40}),
                      "非白名单共存对")
    f3 = minimal_fill(stock_type="周期股", typing_clash={"with": "成长型", "cross_check": "太短"})
    assert "cross_check <30 字" in validate_stderr(f3), "cross_check 不足 30 字应告警"


def test_typing_v2_weights_half_filled():
    """weights 半填拒渲染（冰轮实证）：L1/L3 只填一层 → 拒；两层同填 → 放行。"""
    expect_valueerror(minimal_fill(weights={"1A": 12, "1B": 12, "1C": 20, "1D": 16, "1E": 20, "1F": 20}),
                      "weights 半填")
    f = minimal_fill(weights={"1A": 12, "1B": 12, "1C": 20, "1D": 16, "1E": 20, "1F": 20,
                              "3A": 40, "3B": 35, "3C": 25})
    assert "weights 半填" not in validate_stderr(f), "两层同填不应告警"
    print("OK typing v2 校验组（枚举/占比/分层/证据键/撞车/权重完整性）")


def test_hist_cagr_guard():
    """P0-2（v5.4.0 审计）：_hist_cagr 的扣非柱值必须与 years 等长且全可解析，否则 None——
    zip 静默截断会把 CAGR 窗口算错，而本数驱动拒渲染门禁（明细缺失即拒）。"""
    from validate import _hist_cagr
    assert _hist_cagr(minimal_fill()) is not None    # 夹具扣非柱 [75,79,83,86,88] / 5 年
    short = minimal_fill()
    short["fin_trend"]["panels"][1]["bars"][1]["values"] = [75, 79]           # 短柱
    assert _hist_cagr(short) is None, "柱短于 years 应 None（不得截断算窗口）"
    long_ = minimal_fill()
    long_["fin_trend"]["panels"][1]["bars"][1]["values"] = [75, 79, 83, 86, 88, 90]   # 长柱
    assert _hist_cagr(long_) is None, "柱长于 years 应 None"
    bad = minimal_fill()
    bad["fin_trend"]["panels"][1]["bars"][1]["values"] = [75, 79, 83, "—", 88]       # 含非数字
    assert _hist_cagr(bad) is None, "含非数字应 None"
    neg = minimal_fill()
    neg["fin_trend"]["panels"][1]["bars"][1]["values"] = [75, -5, 83, 86, 88]         # 含非正值
    assert _hist_cagr(neg) is None, "含非正值（跨亏年）应 None"
    few = minimal_fill()
    few["fin_trend"]["years"] = ["2024", "2025"]
    few["fin_trend"]["panels"] = [{"title": "x", "bars": [{"name": "扣非净利", "values": [80, 88]}],
                                   "lines": [{"name": "净利率", "values": [1, 2]}]} for _ in range(3)]
    assert _hist_cagr(few) is None, "<3 年应 None"
    print("OK _hist_cagr 守卫（短柱/长柱/非数字/非正值/不足 3 年 → None）")


def test_typing_v2_cagr_negative_skips():
    """v5.4.0 拆分（P1-7：原用例走的是明细分支，属假绿）：
    a helper 级不可用 → None（见 test_hist_cagr_guard）；
    b 含非正值 + 有明细 → 人工判定（不复算、不出跨层告警）；
    c 含非正值 + 无明细 → 拒渲染（例外 b 触发）。"""
    # b 有明细 → 人工判定
    f = minimal_fill(stock_type="成长型", growth_tier="high",
                     typing_evidence={"cagr_hist": "近5年 CAGR 中枢 18%",
                                      "cagr_adjustments": [{"year": 2022, "item": "资产减值",
                                                            "amount": -5, "reason": "一次性减值剔除"}]})
    f["fin_trend"]["panels"][1]["bars"][1]["values"] = [80, -5, 90, 95, 100]
    out = validate_stderr(f)
    assert "分层与财务事实不符" not in out, "含负值序列应跳过对账、不得告警"
    assert "人工判定" in out, "有明细应标人工判定"
    # c 无明细 → 拒渲染
    f2 = minimal_fill(stock_type="成长型", growth_tier="high")
    f2["fin_trend"]["panels"][1]["bars"][1]["values"] = [80, -5, 90, 95, 100]
    expect_valueerror(f2, "扣非跨亏年无明细应拒", kw="扣非柱不可用")


def test_typing_v2_mature_not_stagnation():
    """v5.3.0 热核修正：裸「成熟」别名已删——「成熟成长股」应映射成长型而非成熟/停滞。"""
    s = validate_stderr(minimal_fill(stock_type="成熟成长股"))
    assert "无法映射六型" not in s, "成熟成长股应可映射（成长型）"
    assert "growth_tier 缺失" in s, "应按成长型分支处理（缺 growth_tier 告警）"
    print("OK 热核修正回归（非正值跳过 / 裸成熟不误吞）")


# ---------------- v5.4.0 A1 双尺锚纪律 / 校准锚（calib） ----------------

def test_anchor_dual_ruler_gate():
    """v5.4.0 双尺门禁：合理带（valuation_inputs.pe_band）与基础情景带（base 情景 pe）任一
    中枢偏离 pe_history P25-P75 中枢 >15% → rollback_html 必填（**首版无 prev 同样生效**）；
    一尺越界一尺不越、或两尺越界但异号 → 拒渲染（引「纪律四：禁止评分用旧尺、目标价用新尺」）；
    两尺同向同越界 = 一致重构，补回滚条款即放行。"""
    rb = "回滚条件：连续两季扣非同比转正 → PE 带回滚至历史带"
    # 首版双尺同向同越界（中枢 11 vs 25 → −56%）+ 无回滚条款 → 拒
    f = minimal_fill()
    f["pe_history"] = {"p25": 20.0, "p75": 30.0}
    expect_valueerror(f, "首版重构偏离无 rollback_html 应拒", kw="rollback_html 缺失")
    f["valuation"]["rollback_html"] = rb
    R.validate_content(f, R.compute_valuation(f))   # 补回滚条款 → 过
    # 双尺混用①：一尺越界一尺不越 → 拒（历史中枢 12；合理带中枢 24 → +100%；基础情景中枢 11 → −8%）
    f = minimal_fill()
    f["pe_history"] = {"p25": 11.0, "p75": 13.0}
    f["valuation_inputs"]["pe_band"] = [22, 26]
    expect_valueerror(f, "一尺越界一尺不越应拒", kw="纪律四")
    # 双尺混用②：两尺都越界但偏离异号 → 拒（历史中枢 15；合理带 +60%、基础情景 −27%）
    f = minimal_fill()
    f["pe_history"] = {"p25": 14.0, "p75": 16.0}
    f["valuation_inputs"]["pe_band"] = [22, 26]
    expect_valueerror(f, "双尺异号应拒", kw="方向相反")
    # 两尺皆可算但都不越界 → 放行（合理带与基础情景中枢同为 11，历史中枢 12 → −8.3%）
    f = minimal_fill()
    f["pe_history"] = {"p25": 11.0, "p75": 13.0}
    R.validate_content(f, R.compute_valuation(f))
    # 一尺可算一尺不可算：可算的越界 → 拒（未越界的那把尺不参与判定，文案注明「不可算」）
    f = minimal_fill()
    f["pe_history"] = {"p25": 20.0, "p75": 30.0}
    f["valuation_inputs"]["pe_band"] = []      # 合理带尺输入缺失
    expect_valueerror(f, "单尺越界应拒", kw="不可算")
    # 一尺可算（未越界）一尺不可算：不判混用、不要求回滚
    f = minimal_fill()
    f["pe_history"] = {"p25": 11.0, "p75": 13.0}
    f["valuation_inputs"]["pe_band"] = []
    R.validate_content(f, R.compute_valuation(f))
    # 15% 边界：dev = 4.6/4−1 = 14.999…%（浮点恰不越界）→ 放行；略高一线（4.7/4−1 = 17.5%）→ 拒
    f = minimal_fill()
    f["price"], f["mcap"] = "30", "3000"
    f["pe_history"] = {"p25": 4.0, "p75": 4.0}
    f["valuation_inputs"]["pe_band"] = [4.5, 4.7]
    for sc, pe in zip(f["valuation"]["scenarios"], ([2.5, 2.7], [4.5, 4.7], [7.3, 7.5])):
        sc["pe"] = pe
    f["thesis_html"] = ('测试论点与关键证据。三情景目标价 '
                        '<span class="scenario-pess">2.08</span>/'
                        '<span class="scenario-base">4.6</span>/'
                        '<span class="scenario-opt">8.88</span> 元，结论：观察。')
    R.validate_content(f, R.compute_valuation(f))
    f2 = minimal_fill()
    f2["price"], f2["mcap"] = "30", "3000"
    f2["pe_history"] = {"p25": 4.0, "p75": 4.0}
    f2["valuation_inputs"]["pe_band"] = [4.6, 4.8]
    for sc, pe in zip(f2["valuation"]["scenarios"], ([2.5, 2.7], [4.6, 4.8], [7.3, 7.5])):
        sc["pe"] = pe
    expect_valueerror(f2, "越界须配回滚条款", kw="rollback_html 缺失")
    # 市值口径（metric_label + mcap 情景）双尺皆不可算 → 豁免
    R.validate_content(mcap_fill(), R.compute_valuation(mcap_fill()))
    # 尺子声明文案点名偏离的尺：两尺 → 「两者」；单尺 → 只点该尺
    from scoring import build_regime_note
    f = minimal_fill()
    f["pe_history"] = {"p25": 20.0, "p75": 30.0}
    note = build_regime_note(f)
    assert "合理带与基础情景带两者" in note and "下移 56%" in note, f"实际：{note}"
    f_band = minimal_fill()
    f_band["pe_history"] = {"p25": 11.0, "p75": 13.0}
    f_band["valuation_inputs"]["pe_band"] = [22, 26]
    n_band = build_regime_note(f_band)
    assert "合理带中枢" in n_band and "基础情景带" not in n_band, f"实际：{n_band}"
    f_base = minimal_fill()
    f_base["pe_history"] = {"p25": 11.0, "p75": 13.0}
    f_base["valuation_inputs"]["pe_band"] = [11, 13]
    f_base["valuation"]["scenarios"][1]["pe"] = [9.5, 10.5]
    n_base = build_regime_note(f_base)
    assert "基础情景带中枢" in n_base and "合理带" not in n_base, f"实际：{n_base}"
    assert build_regime_note(minimal_fill()) == "", "两尺皆无输入 → 空串"
    print("OK 双尺锚纪律（首版越界拒 / rollback 放行 / 混用拒 / 异号拒 / 不越界放行 / mcap 豁免）")


def test_anchor_blind_fly_warn():
    """v5.4.0 校验盲飞：依赖历史 PE 时段锚的四型（周期/稳定价值/困境反转/成长·中速层）
    既无 metric_label 又缺 p25/p75 → 告警要求写明降级取数路径；有分位 / 行业口径 / 非四型 → 不告警。"""
    assert "校验盲飞" in validate_stderr(minimal_fill()), "周期股缺 p25/p75 应告警"
    assert "校验盲飞" not in validate_stderr(minimal_fill(pe_history={"p25": 10, "p75": 12}))
    assert "校验盲飞" not in validate_stderr(mcap_fill()), "市值口径 metric_label → 豁免"
    for st, gt in (("成熟/停滞", None), ("成长型", "high"), ("未盈利/管线", None)):
        f = minimal_fill(stock_type=st) if gt is None else minimal_fill(stock_type=st, growth_tier=gt)
        assert "校验盲飞" not in validate_stderr(f), f"{st}/{gt} 不属四型，不应告警"
    assert "校验盲飞" in validate_stderr(minimal_fill(stock_type="成长型", growth_tier="mid")), \
        "成长型·中速层属四型，缺分位应告警"
    assert "校验盲飞" in validate_stderr(minimal_fill(stock_type="稳定价值/金融（银行）"))
    assert "校验盲飞" in validate_stderr(minimal_fill(stock_type="困境反转"))
    print("OK 校验盲飞告警（四型缺分位告警 / 行业口径与非四型豁免）")


# ---------------- v5.4.0 A1 校准锚（calib）三校验 ----------------

_CALIB_MONTHS = [{"m": f"2021-{m:02d}", "close": 10.0, "pe": float(10 + m)} for m in range(1, 13)]


def _calib_fill(stages, **over):
    """calib 用例夹具：price_history 窗口 2021-01..2021-12（pe 11..22）+ cycle_html 在位。"""
    return minimal_fill(cycle_html="<p>周期分析。</p>",
                        price_history={"label": "近1年", "series": _CALIB_MONTHS},
                        cycle_stages=stages, **over)


_CALIB_STAGE = {"name": "校准段", "period": "2021/01–2021/12", "pe": "11–22x", "calib": True,
                "similarity": "增速 20%、渗透率低（可比）", "discount": "规模相当，无折价"}


def test_calib_keys_and_count_warn():
    """v5.4.0 校准锚①②：calib:true 缺 similarity/discount → 告警；四型 calib <2 → 告警；
    四型 calib ≥2 且键齐、窗口内对账通过 → 三条 calib 校验全不告警。"""
    stages = [dict(_CALIB_STAGE),  # 仅 1 个 calib
              {"name": "当前段", "period": "2022/01–至今", "current": True},
              {"name": "过渡段", "period": "2022/01–2022/06"}]
    out = validate_stderr(_calib_fill(stages))
    assert "校准锚（calib:true）仅 1 个" in out, "四型 calib <2 应告警"
    assert "缺 similarity" not in out, "键齐不应告警"
    bad = [dict(_CALIB_STAGE, similarity="", discount=None), stages[1], stages[2]]
    out2 = validate_stderr(_calib_fill(bad))
    assert "缺 similarity/discount" in out2, "缺两键应告警"
    # 非四型（成熟/停滞）calib 仅 1 个 → 不告警数量
    out3 = validate_stderr(_calib_fill(stages, stock_type="成熟/停滞"))
    assert "校准锚（calib:true）仅 1 个" not in out3, "非四型不受 ≥2 约束"
    # 正例：四型 calib=2、键齐、窗口内对账通过 → 三条校验全不告警
    good = [_CALIB_STAGE,
            dict(_CALIB_STAGE, name="校准段二", period="2021/06–2021/12", pe="16–22x"),
            {"name": "当前段", "period": "2022/01–至今", "current": True}]
    out4 = validate_stderr(_calib_fill(good))
    assert ("校准锚（calib:true）仅" not in out4 and "缺 similarity" not in out4
            and "端点偏差" not in out4 and "声明未核验" not in out4), f"正例不应告警：{out4}"
    for st in ("稳定价值/金融（银行）", "困境反转", "成长型"):
        over = {"growth_tier": "mid"} if st == "成长型" else {}
        out5 = validate_stderr(_calib_fill(good, stock_type=st, **over))
        assert "校准锚（calib:true）仅" not in out5, f"{st} calib=2 不应告警数量"
    # v5.4.1：四型零标记不再静默豁免（0 个 → 独立文案）；非四型 0 个 → 不告警
    zero = [{"name": "段一", "period": "2021/01–2021/12"}, stages[1], stages[2]]
    out6 = validate_stderr(_calib_fill(zero))
    assert "未标注校准锚（calib）" in out6, "四型 0 个 calib 应告警"
    assert "校准锚（calib:true）仅" not in out6, "0 个走专用文案"
    out7 = validate_stderr(_calib_fill(zero, stock_type="成熟/停滞"))
    assert "未标注校准锚" not in out7 and "校准锚（calib:true）仅" not in out7, "非四型 0 个不应告警"
    print("OK calib 键与数量校验（缺键告警 / 四型 0 与 1 个告警 / ≥2 正例放行 / 非四型豁免）")


def test_calib_window_recon_warn():
    """v5.4.0 校准锚③：calib 时段落在 price_history 窗口内 → 声明区间与窗口实测 PE 极值
    端点偏差 >25% 告警（上限方向同）；恰 25% 边界放行；未写 pe 键/窗口外 → 跳过；
    全部未核验 → 「声明未核验」汇总告警一条。"""
    cur = {"name": "当前段", "period": "2022/01–至今", "current": True}
    other = {"name": "过渡段", "period": "2022/01–2022/06"}
    ok = [dict(_CALIB_STAGE, pe="10–24x"), cur, other]          # 实测 11–22 → 容差内
    out = validate_stderr(_calib_fill(ok))
    assert "端点偏差 >25%" not in out and "声明未核验" not in out, f"容差内不应告警：{out}"
    off = [dict(_CALIB_STAGE, pe="30–40x"), cur, other]         # 实测 11 → 下限偏差 63%
    out2 = validate_stderr(_calib_fill(off))
    assert "端点偏差 >25%" in out2 and "下限 30x vs 实测最低 11x" in out2
    up = [dict(_CALIB_STAGE, pe="10–12x"), cur, other]          # 实测最高 22 → 上限偏差 83%
    out3 = validate_stderr(_calib_fill(up))
    assert "上限 12x vs 实测最高 22x" in out3, "上限方向同样要对账"
    # 恰 25%：|11−8.8|/8.8 = 0.25、|22−17.6|/17.6 = 0.25（浮点恰不越界）→ 放行
    edge = [dict(_CALIB_STAGE, pe="8.8–17.6x"), cur, other]
    out4 = validate_stderr(_calib_fill(edge))
    assert "端点偏差" not in out4 and "声明未核验" not in out4, f"恰 25% 应放行：{out4}"
    # 未写 pe 键 → 跳过对账（不计已核验 → 汇总告警）
    nope_pe = [dict(_CALIB_STAGE, pe=""), cur, other]
    out5 = validate_stderr(_calib_fill(nope_pe))
    assert "端点偏差" not in out5 and "声明未核验" in out5
    # 窗口外（2020 年不在序列内）→ 全部未核验
    outwin = [dict(_CALIB_STAGE, period="2020/01–2020/12"), cur, other]
    out6 = validate_stderr(_calib_fill(outwin))
    assert "均在取数窗口外" in out6 and "声明未核验" in out6
    # 无 pe 序列（price_history 缺 pe）→ 同样未核验
    nope = minimal_fill(cycle_html="<p>x</p>",
                        price_history={"label": "近1年",
                                       "series": [{"m": m["m"], "close": m["close"]}
                                                  for m in _CALIB_MONTHS]},
                        cycle_stages=[_CALIB_STAGE, cur, other])
    assert "均在取数窗口外" in validate_stderr(nope), "窗口内无 pe → 未核验"
    # 年份守卫（热核审计 P2）：pe 含四位年份不得吞为区间端点（「2021 年 10–24x」按 10–24 解析）
    yr = [dict(_CALIB_STAGE, pe="2021 年 10–24x"), cur, other]
    out7 = validate_stderr(_calib_fill(yr))
    assert "端点偏差" not in out7, f"年份不得吞为区间端点：{out7}"
    print("OK calib 窗口对账（上下限偏差告警 / 恰 25% 放行 / 未写 pe 跳过 / 窗口外汇总告警 / 年份守卫）")


# ---------------- v5.4.0 A2 口径收口（cagr_adjustments / 扣非对账） ----------------

def test_cagr_adjustments_gate():
    """v5.4.0 A2：三条例外（a 港股 5 位代码 / b 扣非柱不可用 / c cagr_hist 含调整词）任一
    命中且 cagr_adjustments 非空四键明细缺失 → 拒渲染；三条例外均不成立却填写 → 软告警。"""
    ok = [{"year": 2024, "item": "处置子公司股权收益", "amount": -6.2, "reason": "一次性损益剔除"}]
    te = {"cagr_hist": "近5年 CAGR 中枢 18%", "driver_nature": "量增", "shock_history": "无"}
    # a 港股 5 位代码
    f = minimal_fill(stock_type="成长型", growth_tier="mid", code="06082", typing_evidence=dict(te))
    expect_valueerror(f, "港股缺 cagr_adjustments 应拒", kw="港股 5 位代码")
    f["typing_evidence"]["cagr_adjustments"] = ok
    R.validate_content(f, R.compute_valuation(f))   # 补齐明细 → 过
    # b 扣非柱不可用（删扣非柱）
    f = minimal_fill(stock_type="成长型", growth_tier="mid", typing_evidence=dict(te))
    del f["fin_trend"]["panels"][1]["bars"][1]
    expect_valueerror(f, "扣非柱不可用应拒", kw="扣非柱不可用")
    # c cagr_hist 含口径调整词
    f = minimal_fill(stock_type="成长型", growth_tier="mid",
                     typing_evidence=dict(te, cagr_hist="近5年 CAGR 中枢 18%（剔除一次性损益后）"))
    expect_valueerror(f, "cagr_hist 调整词触发应拒", kw="口径调整词")
    # 结构不全（缺 reason）→ 同拒
    f = minimal_fill(stock_type="成长型", growth_tier="mid", code="06082",
                     typing_evidence=dict(te, cagr_adjustments=[
                         {"year": 2024, "item": "处置收益", "amount": -6.2}]))
    expect_valueerror(f, "四键不全应拒", kw="结构不全")
    # 成熟/停滞 同样要求 cagr_hist 键 → 同规则生效
    f = minimal_fill(stock_type="成熟/停滞", code="06082",
                     typing_evidence={"growth_narrative": "叙事消亡", "three_exclusions": "三条均成立",
                                      "cagr_hist": "近5年 CAGR 2%"})
    expect_valueerror(f, "成熟/停滞港股缺明细应拒", kw="港股 5 位代码")
    # c 关键词收窄（P1-5）：含「目标价调整」不触发门禁，无明细也放行
    f = minimal_fill(stock_type="成长型", growth_tier="mid",
                     typing_evidence=dict(te, cagr_hist="近5年 CAGR 中枢 18%（目标价调整后）"))
    R.validate_content(f, R.compute_valuation(f))
    # [{}] 残件 + 无例外命中 → 既不判「多填」（ok_adj=False）、也不拒；且不对账静默关掉
    f = minimal_fill(stock_type="成长型", growth_tier="mid",
                     typing_evidence=dict(te, cagr_adjustments=[{}]))
    out = validate_stderr(f)
    assert "均不成立" not in out, "残件不得走「多填」软告警"
    f["fin_trend"]["panels"][1]["bars"][1]["values"] = [10, 15, 22, 33, 50]
    assert "应归高速层" in validate_stderr(f), "残件不得静默关掉复算对账"
    # [{}] 残件 + 例外命中（港股）→ 拒（结构不全），而非「多填」告警
    f = minimal_fill(stock_type="成长型", growth_tier="mid", code="06082",
                     typing_evidence=dict(te, cagr_adjustments=[{}]))
    expect_valueerror(f, "残件应拒", kw="结构不全")
    # 三条例外均不成立却填明细 → 软告警（防口径漂移）
    f = minimal_fill(stock_type="成长型", growth_tier="mid",
                     typing_evidence=dict(te, cagr_adjustments=ok))
    assert "均不成立" in validate_stderr(f), "无例外却填明细应软告警"
    print("OK cagr_adjustments 强制校验（港股/扣非不可用/口径词拒，四键不全拒，多填告警）")


def test_growth_tier_cagr_adjustments_manual():
    """v5.4.0 A2 ①：cagr_adjustments 非空 → 按声明调整口径（人工判定），脚本不复算
    ——扣非 CAGR 再离谱也不出跨层告警。"""
    f = minimal_fill(stock_type="成长型", growth_tier="mid",
                     typing_evidence={"cagr_hist": "近5年 CAGR 中枢 18%（含并购口径调整）",
                                      "cagr_adjustments": [{"year": 2022, "item": "并购摊销",
                                                            "amount": -3, "reason": "口径调整"}]})
    f["fin_trend"]["panels"][1]["bars"][1]["values"] = [10, 15, 22, 33, 50]   # 扣非 CAGR 49.5%
    out = validate_stderr(f)
    assert "应归高速层" not in out, "有调整明细应跳过脚本复算"
    assert "人工判定" in out, "应标注人工判定"
    # 无明细时同一序列 → 跨层告警（对账基准=扣非柱）
    f2 = minimal_fill(stock_type="成长型", growth_tier="mid")
    f2["fin_trend"]["panels"][1]["bars"][1]["values"] = [10, 15, 22, 33, 50]
    assert "应归高速层" in validate_stderr(f2), "无明细须复算并告警"
    print("OK 成长层对账口径①（有明细 → 人工判定跳过；无明细 → 扣非复算告警）")


# ---------------- v5.4.0 A3 peer 选取硬化 ----------------

_PEER_PLOT_CLEAN = [{"name": "测试股份", "roe": 14, "pe": 11, "target": True},
                    {"name": "同业甲", "roe": 12, "pe": 18}]
_PEERS_META_OK = "同行业（煤化工）、同规模（市值 800-1,500 亿）筛选；同业丙口径不一剔出"
# 仅 matrix-table 的 peers_html（九宫格兜底形态：行=ROE 档、公司名在单元格里）
_MATRIX_ONLY_HTML = ('<div class="table-scroll"><table class="matrix-table">'
                     '<tr><th>PE 低</th><th>PE 中</th><th>PE 高</th></tr>'
                     '<tr><th>ROE 高</th><td>测试股份(14%/11x)</td><td>—</td><td>—</td></tr>'
                     '<tr><th>ROE 中</th><td>—</td><td>同业甲(12%/18x)</td><td>同业丙(15%/20x)</td></tr>'
                     '<tr><th>ROE 低</th><td>—</td><td>—</td><td>—</td></tr></table></div>'
                     '<span class="source">数据来源：测试</span>')


def test_peers_table_plot_consistency():
    """v5.4.0 ⑨表图一致（拒渲染）：散点图非 target 点必须在 peers_html **非 matrix-table 表**的
    行首格内（名字归一后精确相等），或在 peers_meta 点名声明；未声明 → 拒渲染；target 点豁免。
    审计 P0-1：matrix-table 九宫格行首格是 ROE 档位名、公司名在单元格里——不作名字来源；
    peers_html 只剩 matrix-table 时整条跳过（渲染器反正会删手写九宫格）。"""
    pts = _PEER_PLOT_CLEAN + [{"name": "同业丙", "roe": 15, "pe": 20}]
    expect_valueerror(minimal_fill(peers_plot={"points": pts}),
                      "表外同业未声明应拒", kw="表图一致")
    f = minimal_fill(peers_meta=_PEERS_META_OK, peers_plot={"points": pts})
    R.validate_content(f, R.compute_valuation(f))   # peers_meta 声明后者 → 过
    # 表内同业（同业甲）无需声明；target 点豁免
    f2 = minimal_fill(peers_meta=_PEERS_META_OK, peers_plot={"points": _PEER_PLOT_CLEAN})
    R.validate_content(f2, R.compute_valuation(f2))
    # P0-1：plot + matrix-table 同存（无普通指标表）→ 整条跳过，不误拒
    f3 = minimal_fill(peers_html=_MATRIX_ONLY_HTML, peers_plot={"points": pts})
    R.validate_content(f3, R.compute_valuation(f3))
    # 同存且另有普通表 → 普通表才是名字来源：只出现在九宫格里的同业丙仍拒
    f4 = minimal_fill(peers_html=_MATRIX_ONLY_HTML + minimal_fill()["peers_html"],
                      peers_plot={"points": pts})
    expect_valueerror(f4, "九宫格不作名字来源", kw="表图一致")
    # P1-12：名字归一后精确相等（括号注可去，「比亚迪」≠「比亚迪电子」——近似名仍拒）
    f5 = minimal_fill(peers_meta=_PEERS_META_OK,
                      peers_plot={"points": _PEER_PLOT_CLEAN
                                  + [{"name": "同业甲（A股）", "roe": 12, "pe": 18}]})
    R.validate_content(f5, R.compute_valuation(f5))   # 括号注归一后 = 表内「同业甲」→ 过
    tbl = minimal_fill()["peers_html"].replace("同业甲", "比亚迪电子")
    f6 = minimal_fill(peers_html=tbl, peers_meta=_PEERS_META_OK,
                      peers_plot={"points": _PEER_PLOT_CLEAN + [{"name": "比亚迪", "roe": 15, "pe": 20}]})
    expect_valueerror(f6, "近似名不得互相放行", kw="表图一致")
    # 交易所标记归一：表内「百济神州-U」≡ 图内「百济神州」（恒瑞 2026-09-19 存量实证）
    tbl7 = minimal_fill()["peers_html"].replace("同业甲", "百济神州-U")
    f7 = minimal_fill(peers_html=tbl7, peers_meta=_PEERS_META_OK,
                      peers_plot={"points": [_PEER_PLOT_CLEAN[0],
                                             {"name": "百济神州", "roe": 5, "pe": 38}]})
    R.validate_content(f7, R.compute_valuation(f7))
    print("OK peers 表图一致（未声明拒渲染 / 声明放行 / 九宫格不误拒 / 括号注归一 / 近似名仍拒 / -U 后缀归一）")


def test_peers_ruler_consistency_warn():
    """v5.4.0 ⑩尺子一致：target 点 ROE 与 fin_trend ROE 线末值绝对差 >3pct 且
    peers_meta 无「口径词+点名目标」双命中 → 告警；双命中注明 → 放行；
    裸口径词不点名目标 → 仍告警（热核审计 P2：堵万能逃生口）。"""
    meta_plain = "同行业（煤化工）、同规模（市值 800-1,500 亿）筛选；纯焦化标的排除"
    pts = [{"name": "测试股份", "roe": 20, "pe": 11, "target": True},
           {"name": "同业甲", "roe": 12, "pe": 18}]
    out = validate_stderr(minimal_fill(peers_meta=meta_plain, peers_plot={"points": pts}))
    assert "> 3pct" in out and "fin_trend ROE 线末值" in out, "ROE 两处口径差应告警"
    out2 = validate_stderr(minimal_fill(peers_meta=meta_plain + "；目标公司 ROE 取加权口径",
                                        peers_plot={"points": pts}))
    assert "> 3pct" not in out2, "口径词+点名目标应放行"
    out3 = validate_stderr(minimal_fill(peers_meta=meta_plain + "；ROE 取加权口径",
                                        peers_plot={"points": pts}))
    assert "> 3pct" in out3, "裸口径词不点名目标不放行"
    # 数据缺（fin_trend 无 ROE 线）→ 跳过
    f = minimal_fill(peers_meta=meta_plain, peers_plot={"points": pts})
    f["fin_trend"]["panels"][1]["lines"] = f["fin_trend"]["panels"][1]["lines"][:1]
    assert "> 3pct" not in validate_stderr(f), "无 ROE 参照应跳过"
    print("OK peers 尺子一致（差 >3pct 告警 / 双命中注明放行 / 裸口径词不放行 / 数据缺跳过）")


def test_peers_min_three_warn():
    """v5.4.0 ⑪peer ≥3：非 target 有效点 <3 → 告警；peers_meta 已写明凑不齐原因
    （含「仅/凑不齐/可比公司不足」）→ 抑制（与「meta 注明后可忽略」惯例一致）。"""
    assert "有效同业点仅 1 家" in validate_stderr(
        minimal_fill(peers_meta=_PEERS_META_OK, peers_plot={"points": _PEER_PLOT_CLEAN}))
    # 写明凑不齐 → 抑制
    assert "有效同业点仅" not in validate_stderr(
        minimal_fill(peers_meta=_PEERS_META_OK + "；可比公司仅 2 家（凑不齐 3 家）",
                     peers_plot={"points": _PEER_PLOT_CLEAN}))
    # 未写原因（哪怕 meta 完整）→ 仍告警
    assert "有效同业点仅" in validate_stderr(
        minimal_fill(peers_meta="同行业、同规模筛选；纯焦化标的排除",
                     peers_plot={"points": _PEER_PLOT_CLEAN}))
    pts = _PEER_PLOT_CLEAN + [{"name": "同业丙", "roe": 15, "pe": 20},
                              {"name": "同业丁", "roe": 16, "pe": 21}]
    meta = _PEERS_META_OK + "；同业丁未选（业务结构差异大）"
    assert "有效同业点仅" not in validate_stderr(
        minimal_fill(peers_meta=meta, peers_plot={"points": pts}))
    print("OK peer ≥3 告警（两点告警 / 凑不齐说明抑制 / 三点放行）")


def test_peers_rationale_warn():
    """v5.4.0 ⑫rationale：有 peer 章节实体（peers_plot 或非占位 peers_meta）时即检查——
    须含「同行业/同规模/同商业模式」≥2 种 + 排除语（排除/未选/剔出），缺一告警；
    占位「—」/空 meta 且无 peers_plot → 交给占位告警，不重复报 rationale。"""
    assert "选取理由不完整" in validate_stderr(minimal_fill(peers_meta="同行业筛选"))
    assert "选取理由不完整" in validate_stderr(minimal_fill(peers_meta="同行业、同规模筛选"))
    assert "选取理由不完整" not in validate_stderr(
        minimal_fill(peers_meta="同行业、同规模筛选；纯焦化标的排除"))
    # 默认态（meta="—"、无 peers_plot）：只有占位告警，不出现 rationale 告警
    default_out = validate_stderr(minimal_fill())
    assert "peers_meta 缺失或为占位符" in default_out and "选取理由不完整" not in default_out
    # 有 peers_plot 但 meta 占位 → rationale 不再静默失效（此前 `if meta:` 直接跳过）
    assert "选取理由不完整" in validate_stderr(
        minimal_fill(peers_plot={"points": _PEER_PLOT_CLEAN}))
    print("OK peers rationale 告警（依据不足/缺排除语告警，默认占位态不重复报）")


def test_peers_pe_cross_warn():
    """v5.4.0 ⑬PE 交叉（软告警）：valuation 基础情景 PE 下限 > 全部非 target 点 PE → 溢价论证提醒。"""
    low = [{"name": "测试股份", "roe": 14, "pe": 11, "target": True},
           {"name": "同业甲", "roe": 12, "pe": 8}]
    assert "高于全部同业" in validate_stderr(
        minimal_fill(peers_meta=_PEERS_META_OK, peers_plot={"points": low}))
    high = [{"name": "测试股份", "roe": 14, "pe": 11, "target": True},
            {"name": "同业甲", "roe": 12, "pe": 30}]
    assert "高于全部同业" not in validate_stderr(
        minimal_fill(peers_meta=_PEERS_META_OK, peers_plot={"points": high}))
    print("OK peers PE 交叉告警（基础带高于全部同业告警，低于则放行）")


def test_period_track_hk_deadend_message():
    """v5.5.1 F1：港股（5 位代码）period_track 硬拒点文案。港股 em_fetch 依赖 tushare
    hk_income 权限，无权限时 period_track 永不落盘，报错须指向「删除 fill 的 period_track」
    而非重跑 em_fetch（小米 01810 2026-10-07 实证：拦得对、文案误导）。
    拒渲染本身不变（防伪链不动），A 股文案保持原样。"""
    with tempfile.TemporaryDirectory() as d:
        ref = write_fill({"price": 10.0, "pe_ttm": 11.0}, d, name="em_ref.json")
        q = {"source_file": ref, "date": "2026-08-27"}
        # A 股：既有文案（重跑 em_fetch --out 落盘 或 删除 fill 的 period_track）
        f = period_fill(quote=q)
        try:
            R.validate_content(f, R.compute_valuation(f))
            raise AssertionError("A 股落盘无 period_track 键应拒渲染")
        except ValueError as e:
            assert "重跑 em_fetch --out 落盘" in str(e), f"A 股文案应保持原样，实际: {e}"
            assert "港股" not in str(e), f"A 股文案不应提港股，实际: {e}"
        # 港股：仍拒渲染（防伪链不动），文案改指港股真实出路
        fh = minimal_fill(code="01810", quote=q,
                          period_track={"period": "2026中报", "rev": 100.0})
        try:
            R.validate_content(fh, R.compute_valuation(fh))
            raise AssertionError("港股落盘无 period_track 键仍应拒渲染（防伪链不动）")
        except ValueError as e:
            m = str(e)
            assert "hk_income" in m and "删除" in m, f"港股文案应指向删字段，实际: {m}"
            assert "勿重跑" in m, f"港股文案应劝止重跑 em_fetch，实际: {m}"
    print("OK 港股 period_track 死路文案（仍拒渲染，文案分派港股）")


def test_gap_plot_street_source_gate():
    """v5.5.1 F2：gap_plot.street 落盘第二照抄源（首版软告警，不拒）——港股 street 非空而
    无 source_file → 告警（E5 对港股无逐机构明细，防手填）；source_file 读不到 / 结构非法 /
    数值对不上 → 告警；数值对得上 → 静默；A 股无 source_file 不告警（存量合法用法=
    street 直接照抄 E5「净利明细/目标价明细」行）。"""
    dims = [{"name": "2026E 出货量（万台）", "ours": 1800, "consensus": 1750,
             "street": [{"org": "国泰海通", "v": 1830}]},
            {"name": "2026E 均价（元）", "ours": 1150, "consensus": 1120,
             "street": [{"org": "花旗", "v": 1180}]}]
    # 港股无 source_file → 告警（指向 _street_ 落盘路径）
    out = validate_stderr(minimal_fill(code="01810", gap_plot={"dims": dims}))
    assert "gap_plot.street 无落盘源" in out and "_street_" in out, "港股 street 无源应告警"
    # A 股无 source_file → 静默（不误伤存量照抄 E5 行的合法用法）
    assert "gap_plot.street 无落盘源" not in validate_stderr(
        minimal_fill(code="600000", gap_plot={"dims": dims})), "A 股 street 无源不应告警"
    with tempfile.TemporaryDirectory() as d:
        ok = write_fill(
            {"source": "2026-10-07 六家机构电话调研纪要",
             "dims": {"2026E 出货量（万台）": [{"org": "国泰海通", "v": 1830,
                                                "date": "2026-09-28"}],
                      "2026E 均价（元）": [{"org": "花旗", "v": 1180, "date": "2026-10-01"}]}},
            d, name="_street_01810_10-07.json")
        # 数值对得上 → 静默
        out = validate_stderr(minimal_fill(code="01810",
                                           gap_plot={"dims": dims, "source_file": ok}))
        assert "无对应记录" not in out and "读取失败" not in out and "结构非法" not in out \
            and "四要素" not in out, "street 数值可在落盘源中找到时不应告警"
        # 数值对不上 → 告警（文案须写明真实容差口径）
        bad = [dict(dims[0], street=[{"org": "国泰海通", "v": 1500}]), dims[1]]
        out = validate_stderr(minimal_fill(code="01810",
                                           gap_plot={"dims": bad, "source_file": ok}))
        assert "无对应记录" in out, "street 数值与落盘源对不上应告警"
        assert "容差" in out and "0.005" in out, "告警文案应写明容差口径（1%，下限 0.005）"
        # 维度在落盘源中缺键 → 告警
        one = write_fill({"source": "调研", "dims": {}}, d, name="_street_01810_10-08.json")
        out = validate_stderr(minimal_fill(code="01810",
                                           gap_plot={"dims": dims, "source_file": one}))
        assert "无对应维度记录" in out, "落盘源缺维度键应告警"
        # 结构非法（缺 dims 对象）→ 告警
        bad_struct = write_fill([{"org": "花旗", "v": 1180}], d, name="_street_bad.json")
        out = validate_stderr(minimal_fill(code="01810",
                                           gap_plot={"dims": dims, "source_file": bad_struct}))
        assert "结构非法" in out, "落盘源缺 dims 对象应告警"
        # 记录缺机构名/日期（四要素不全）→ 告警
        noorg = write_fill(
            {"source": "调研", "dims": {"2026E 出货量（万台）": [{"v": 1830}],
                                        "2026E 均价（元）": [{"org": "花旗", "v": 1180,
                                                              "date": "2026-10-01"}]}},
            d, name="_street_01810_10-09.json")
        out = validate_stderr(minimal_fill(code="01810",
                                           gap_plot={"dims": dims, "source_file": noorg}))
        assert "四要素" in out, "记录缺机构名/日期应告警"
        # 落盘源缺 source（文件级来源说明）→ 告警
        nosrc = write_fill(
            {"dims": {"2026E 出货量（万台）": [{"org": "国泰海通", "v": 1830,
                                               "date": "2026-09-28"}],
                      "2026E 均价（元）": [{"org": "花旗", "v": 1180, "date": "2026-10-01"}]}},
            d, name="_street_01810_10-10.json")
        out = validate_stderr(minimal_fill(code="01810",
                                           gap_plot={"dims": dims, "source_file": nosrc}))
        assert "缺 source" in out, "落盘源缺 source（来源说明）应告警"
        # 文件读不到 → 告警不拒
        out = validate_stderr(minimal_fill(
            code="01810",
            gap_plot={"dims": dims, "source_file": os.path.join(d, "不存在.json")}))
        assert "gap_plot.source_file 读取失败" in out, "source_file 读不到应告警"
        # 图下注释：注明基名（不露本地全路径），无 source_file 则保持 E5 口径（存量 A 股）
        html = render_fill(minimal_fill(code="01810",
                                        gap_plot={"dims": dims, "source_file": ok}))
        assert "调研落盘" in html and os.path.basename(ok) in html, \
            "有 source_file 时图注应注明实际来源"
        assert ok not in html, "图注不得暴露本地全路径（只显示 basename）"
    assert "E5 逐研报明细回填" in render_fill(minimal_fill(gap_plot={"dims": dims})), \
        "无 source_file 时图注保持 E5 口径"
    print("OK gap_plot street 落盘源软校验（无源告警/对账/读不到/结构/四要素，A 股不误伤）")


def test_gap_plot_street_org_match():
    """v5.5.1 P1-2：street 对账按机构名匹配（防张冠李戴）——fill 写「摩根士丹利 1830」而落盘
    是「国泰海通 1830」→ 告警（数值相同也不算）；同 org 对得上 → 静默；同 org 多条任一命中
    → 静默（同机构取最新口径）；org 缺失（未具名点）→ 退全池数值比对。"""
    dims = [{"name": "2026E 出货量（万台）", "ours": 1800, "consensus": 1750,
             "street": [{"org": "国泰海通", "v": 1830}]},
            {"name": "2026E 均价（元）", "ours": 1150, "consensus": 1120,
             "street": [{"org": "花旗", "v": 1180}]}]
    with tempfile.TemporaryDirectory() as d:
        src = write_fill(
            {"source": "调研", "dims": {
                "2026E 出货量（万台）": [{"org": "国泰海通", "v": 1830, "date": "2026-09-28"},
                                        {"org": "国泰海通", "v": 1810, "date": "2026-08-15"},
                                        {"org": "中金", "v": 1850, "date": "2026-09-20"}],
                "2026E 均价（元）": [{"org": "花旗", "v": 1180, "date": "2026-10-01"}]}},
            d, name="_street_org.json")
        # 张冠李戴：数值与落盘中某条相同，但署名机构对不上 → 告警
        wrong = [dict(dims[0], street=[{"org": "摩根士丹利", "v": 1830}]), dims[1]]
        out = validate_stderr(minimal_fill(code="01810",
                                           gap_plot={"dims": wrong, "source_file": src}))
        assert "无对应记录" in out and "摩根士丹利" in out, \
            "机构名对不上应告警（数值相同也不能算对账成功）"
        # 同 org 命中（同机构多条取其一）→ 静默
        same = [dict(dims[0], street=[{"org": "国泰海通", "v": 1810}]), dims[1]]
        assert "无对应记录" not in validate_stderr(
            minimal_fill(code="01810", gap_plot={"dims": same, "source_file": src})), \
            "同机构数值命中应静默"
        # org 缺失（未具名点）→ 退全池数值比对，不误报
        noorg = [dict(dims[0], street=[{"v": 1830}]), dims[1]]
        assert "无对应记录" not in validate_stderr(
            minimal_fill(code="01810", gap_plot={"dims": noorg, "source_file": src})), \
            "未具名点应退全池数值比对"
    print("OK gap_plot street 机构名匹配（张冠李戴告警/同 org 命中/未具名退全池）")


def test_is_hk_code_single_source():
    """v5.5.1 P1-3：港股判定收单源 `_is_hk_code`（5 位数字）——period_track 硬拒文案、
    gap_plot street 无源门、cagr_adjustments 例外三处共用同一判定。"""
    assert _is_hk_code({"code": "01810"}) and _is_hk_code({"code": " 00700 "})
    for code in ("600000", "000001", "830799", "399001", "0181", "018100", None, ""):
        assert not _is_hk_code({"code": code}), f"{code!r} 不应判为港股"
    print("OK 港股判定单源（5 位数字，A 股/指数/缺失不命中）")


def test_prev_charts_structure_warn():
    """v5.5.1 F3：复盘模式「旧有新无」结构对照（软告警）——prev.charts 缺失提醒回填；
    gap_plot 旧有本无 / fin_trend 有效面板变少 / growth_plot.fcst 年少 / pe_history 有→无
    逐项各一条（文案要求 review_html 写明减配理由）；本版补齐 → 该项静默；无 prev → 静默。"""
    # prev 无 charts → 提醒回填；无 prev → 全程静默
    f_no = full_fill()
    del f_no["prev"]["charts"]
    assert "prev.charts 未填" in validate_stderr(f_no), "prev 有而 charts 缺失应告警提醒回填"
    assert "prev.charts" not in validate_stderr(minimal_fill()), "无 prev 应全程静默"
    # 上版 gap_plot 已生成、本版无 → 告警；本版补齐（有效维度 ≥2）→ 该项静默
    dims = [{"name": "2026E 出货量（万台）", "ours": 1800, "consensus": 1750},
            {"name": "2026E 均价（元）", "ours": 1150, "consensus": 1120}]
    f = full_fill()
    f["prev"]["charts"] = {"gap_plot": True}
    out = validate_stderr(f)
    assert "复盘减配" in out and "gap_plot" in out and "review_html" in out, "上版有图本版无应告警"
    f2 = full_fill()
    f2["prev"]["charts"] = {"gap_plot": True}
    f2["gap_plot"] = {"dims": dims}
    assert "复盘减配" not in validate_stderr(f2), "本版补齐图后该项应静默"
    # fin_trend 有效面板 4 → 3
    f = full_fill()
    f["prev"]["charts"] = {"fin_trend_panels": 4}
    f["fin_trend"]["panels"] = f["fin_trend"]["panels"][:3]
    out = validate_stderr(f)
    assert "复盘减配" in out and "fin_trend" in out and "4" in out and "3" in out, \
        "面板变少应告警"
    # growth_plot.fcst 有效年 2 → 1
    f = full_fill()
    f["prev"]["charts"] = {"growth_fcst_years": 2}
    out = validate_stderr(f)
    assert "复盘减配" in out and "fcst" in out, "预测年少应告警"
    # pe_history 有 → 无
    f = full_fill()
    f["prev"]["charts"] = {"pe_history": True}
    del f["pe_history"]
    out = validate_stderr(f)
    assert "复盘减配" in out and "pe_history" in out, "pe_history 有→无应告警"
    # 本版比上版「变多」→ 静默（只报减配，不报增配）
    f = full_fill()
    f["prev"]["charts"] = {"fin_trend_panels": 2, "growth_fcst_years": 1}
    assert "复盘减配" not in validate_stderr(f), "本版比上版图多不应告警"
    # 四项齐平（本版与上版一致）→ 无减配告警
    f = full_fill()
    f["prev"]["charts"] = {"gap_plot": False, "fin_trend_panels": 4,
                           "growth_fcst_years": 1, "pe_history": True}
    assert "复盘减配" not in validate_stderr(f), "与上版齐平不应告警"
    print("OK prev.charts 结构对照（缺字段提醒/四项减配逐条/补齐与变多静默/无 prev 静默）")


def test_prev_charts_pe_history_keys():
    """v5.5.1 P1-1：prev.charts.pe_history 判定与渲染同源（charts_cycle._pe_band_ok 单源）——
    本版 pe_history 只剩 hist_lo（缺 hist_hi，build_pe_band 不落图）而 prev.charts.pe_history=true
    → 告警（此前只看字段非空，缺键减配漏检）；hist_lo/hist_hi + valuation_inputs 的
    pe_ttm/pe_band 五键齐备 → 静默。"""
    f = full_fill()
    f["prev"]["charts"] = {"pe_history": True}
    f["pe_history"] = {"hist_lo": 13.7}          # 缺 hist_hi → 图不生成
    out = validate_stderr(f)
    assert "复盘减配" in out and "pe_history" in out, "pe_history 缺键导致图不生成应告警"
    f2 = full_fill()
    f2["prev"]["charts"] = {"pe_history": True}
    assert "复盘减配" not in validate_stderr(f2), "五键齐备应静默"
    print("OK prev.charts.pe_history 与渲染同源（缺键告警/齐备静默）")
