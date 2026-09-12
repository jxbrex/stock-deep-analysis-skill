#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_render_gate.py — render_report 门禁/校验回归（无网络，直接 python 运行）

覆盖：拒渲染（负扣分 / PE 倒挂 / timing 缺维 / 黄灯缺键 / date 非法）、quote 四件套防伪、
写作纪律与内容告警、L4 形态硬门禁、仓位决策链（_position_steps）纯函数分支。
拆分自 test_render_core.py（v4.10.2），断言逐字沿用。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_report as R
from scoring import _position_steps, _quality_verdict, _valuation_verdict
from conftest import (
    minimal_fill, _dim, _calc, expect_valueerror,
    capture_stderr, validate_stderr, render_workspace, write_fill,
)


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
    with render_workspace() as d:
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
    """v4.7.1 写作纪律告警：四拍挤段 / 三年并排 / pe_history 无第 10 章承载。"""
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
    # pe_history 与第 10 章绑定：cycle_html 缺失 → 告警；填了 → 不告警
    ph = {"hist_lo": 13.7, "hist_hi": 83.2}
    assert "cycle_html 缺失" in validate_stderr(minimal_fill(pe_history=ph)), "pe_history 无第 10 章承载应告警"
    fill_ok = minimal_fill(pe_history=ph, cycle_html='<p>周期阶段分析正文，非空即渲染整章。</p>')
    assert "cycle_html 缺失" not in validate_stderr(fill_ok), "cycle_html 已填不应告警"


def test_quote_four_piece():
    """v4.8 防伪链四件套扩展：valuation_inputs.pe_ttm 偏差>1% 拒；pe_band 完全越界历史带拒；
    risk_free 偏差>0.3pct 告警不拒；港股 div_yield 不比对。"""
    with render_workspace() as d:
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
    （红灯熔断 / 中枢为负 / 直落重仓 / 上浮封顶 / 0 兜底 / 观察池下调）。"""
    # 红灯熔断：后续调节不再适用
    label, steps, slot = _position_steps(7.2, 8.5, 7.0, _calc(odds=None), "财务造假嫌疑")
    assert label == "不建议参与" and slot is None and "红灯熔断" in steps[0]
    # 中枢为负拦截器（不落矩阵）
    label, steps, slot = _position_steps(7.2, 8.5, 7.0, _calc(), "")
    assert label == "重仓 ≤20%" and "矩阵落位" in slot, "无红灯无负中枢应走矩阵直落"
    label, steps, slot = _position_steps(7.2, 8.5, 7.0, {"central_raw": -0.1, "central": -0.1}, "")
    assert label == "回避（中枢为负，等价格）" and slot is None and "中枢为负" in steps[0]
    # 上浮封顶：质地一般轻仓 + 时机/离散/赔率三连浮仍止步标准仓
    label, steps, slot = _position_steps(4.27, 4.3, 7.0, _calc(dispersion=0.30, odds=None), "")
    assert label == "标准仓 ≤10%" and "上浮封顶" in "".join(steps)
    # 下调 0 兜底：两次下调不得回卷
    label, steps, slot = _position_steps(4.27, 4.3, 3.5, _calc(dispersion=0.95), "")
    assert label == "不建议参与" and "重仓" not in "".join(steps)
    # 观察池：中上质地 + 差价格；时机差 → 下调不建议参与
    label, steps, slot = _position_steps(5.8, 5.0, 5.0, None, "")
    assert label == "观察池" and "观察池" in slot
    label, steps, slot = _position_steps(5.8, 5.0, 3.0, None, "")
    assert label == "不建议参与" and "观察池下调" in "".join(steps)
    # 与卡片渲染同源：build_position_card 输出含同一结论（行为零变更冒烟）
    html = R.build_position_card(minimal_fill(), 4.27, 4.3, 7.0,
                                 _calc(dispersion=0.30, odds=None), "")
    assert "标准仓 ≤10%" in html
    print("OK _position_steps 直接单测（红灯/负中枢/直落/封顶/兜底/观察池）")


def test_try_up_wording_nailed():
    """v4.10.2 热核审计钉死：try_up 三条上浮路径的轨迹文案逐字断言。
    背景：try_up 收敛曾把赔率分支「）→ 上浮一档」（无空格）归一为「） → 上浮一档」
    （有空格）——1 字节漂移，因该分支零断言零快照覆盖而溜过。此处把三条路径
    （时机/离散度/赔率）的成功上浮文案逐字钉死，上浮分支统一「detail → 上浮一档」写法。"""
    # 时机分上浮成功（落轻仓 → 标准仓）
    label, steps, _ = _position_steps(4.27, 4.3, 6.5, _calc(), "")
    assert label == "标准仓 ≤10%"
    assert steps == ["时机分调节：时机分 6.50 ≥ 6 → 上浮一档（轻仓 ≤5%→标准仓 ≤10%）"], steps
    # 离散度上浮成功
    label, steps, _ = _position_steps(4.27, 4.3, 5.0, _calc(dispersion=0.30), "")
    assert label == "标准仓 ≤10%"
    assert steps == ["离散度调节：离散度 30.0% < 40% → 上浮一档（轻仓 ≤5%→标准仓 ≤10%）"], steps
    # 赔率 ∞ 上浮成功（归一化前此分支无空格，本轮有意归一——见 handoff 审计修补段）
    label, steps, _ = _position_steps(4.27, 4.3, 5.0, _calc(dispersion=0.50, odds=None), "")
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
    无 p25/p75 支撑 / 极性矛盾 → 告警；概念齐备且无矛盾 → 不告警。"""
    # 引「分位」但 pe_history 无 p25/p75 → 告警（数据支撑缺失）
    out = validate_stderr(minimal_fill(pe_sub="PE 处近 5 年低分位"))
    assert "分位" in out and "未填 p25/p75" in out, "引用分位而缺 p25/p75 应告警"
    # 有 p25/p75 但极性矛盾：现价 PE 高于 P75 却说低分位
    ph = {"hist_lo": 5, "hist_hi": 30, "p25": 8, "p75": 10, "label": "近5年"}
    out = validate_stderr(minimal_fill(pe_sub="现价 PE 处于低分位", pe_history=ph))
    assert "低分位" in out and "矛盾" in out, "低分位说法与高于 P75 的现价应告警"
    # 极性正确（现价 < P25 说低分位）→ 不告警
    out = validate_stderr(minimal_fill(pe_sub="现价 PE 处于低分位", pe_history={"p25": 20, "p75": 30}))
    assert "分位" not in out, "低分位说法与低于 P25 的现价不应告警"
    # 引用历史带但 pe_history 无 hist_lo/hist_hi → 告警
    out = validate_stderr(minimal_fill(pe_sub="PE 高于历史带上沿", pe_history={"p25": 8, "p75": 10}))
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

    four = ('<div class="concl-grid">' + card("关键优势", '<a href="#s3">3 公司本质</a>')
            + card("关键弱点", '<a href="#s5">5 风险评估</a>')
            + card("当前市场认知", '<a href="#s8">8 市场预期差</a>')
            + card("核心投资逻辑", '<a href="#s7">7 估值与安全边际</a>') + '</div>')
    assert "缺卡" not in validate_stderr(minimal_fill(conclusion_html=four)), "四卡齐全不应告警"
    three = four.replace(card("当前市场认知", '<a href="#s8">8 市场预期差</a>'), "")
    out = validate_stderr(minimal_fill(conclusion_html=three))
    assert "缺卡" in out and "当前市场认知" in out, "缺卡应告警并点名缺失卡头"
    mixed = ('<div class="concl-grid">' + card("核心投资逻辑", "7") + card("关键优势", "3")
             + card("关键弱点", "5") + card("当前市场认知", "8") + '</div>')
    out = validate_stderr(minimal_fill(conclusion_html=mixed))
    assert "顺序错误" in out, "四卡乱序应告警"
    print("OK conclusion 四卡结构（齐全放行 / 缺卡点名 / 乱序告警）")


def test_review_miss_diagnostics_warns():
    """v4.9 复盘「未命中」缺诊断方向：含未命中而无规律/反例字样 → 告警。"""
    prev = {"date": "2026-08-08", "quality": 7.0, "valuation": 5.5,
            "timing": 5.0, "target_range": "10-12"}
    tbl = '<table><tr><td>假设</td></tr></table><span class="source">数据来源：测试</span>'
    miss_key = "未提「规律/反例」"  # 告警文案关键字（与用户正文的「规律/反例」区分）
    out = validate_stderr(minimal_fill(prev=prev, review_html=tbl + "判定：未命中"))
    assert miss_key in out, "含未命中而无规律/反例字样应告警"
    out2 = validate_stderr(minimal_fill(prev=prev,
                                        review_html=tbl + "判定：未命中——本次属原规律失效的现场反例"))
    assert miss_key not in out2, "已写明规律失效/反例方向不应告警"
    print("OK 复盘未命中诊断告警（无规律/反例措辞告警，已写失效方向放行）")


def test_peers_roe_outlier_warns():
    """v4.9 peers_plot ROE 量级倒挂：目标点 ROE 脱离同业量级 → 告警；同量级 → 不告警。"""
    # 目标 ROE 2% vs 同业 12-15% → 倒挂告警
    fill = minimal_fill(peers_plot={"points": [
        {"name": "测试股份", "roe": 2, "pe": 11, "target": True},
        {"name": "同业甲", "roe": 12, "pe": 18},
        {"name": "同业乙", "roe": 15, "pe": 20}]})
    out = validate_stderr(fill)
    assert "ROE" in out and "脱离同业量级" in out, "目标 ROE 明显低于同业应告警"
    # 目标 ROE 34 vs 同业 12-15 → 倒挂告警
    fill = minimal_fill(peers_plot={"points": [
        {"name": "测试股份", "roe": 34, "pe": 11, "target": True},
        {"name": "同业甲", "roe": 12, "pe": 18},
        {"name": "同业乙", "roe": 15, "pe": 20}]})
    assert "脱离同业量级" in validate_stderr(fill)
    # 目标 14 vs 同业 12-15 → 不告警
    fill = minimal_fill(peers_plot={"points": [
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
    """v4.9.1 补充修订二：3.5 治理块单行化——trig-strip 块内 <p> 恰为 2（判词+评分）→ 不告警；
    trig 行后另起 <p> 正文（>2 个 <p>）→ 告警；3.5 未用 trig-strip 的存量写法 → 不打扰。"""

    def l1_with_35(inner):
        dims = [('<div class="dim-block"><p>该维度分析：公司基本面稳健，数据支撑充分，'
                 '论据详实可靠，行业地位稳固，具备长期参考价值。</p></div>')] * 5
        return "".join(dims) + ('<div class="dim-block"><div class="dim-header">'
                                '<span class="dim-name">3.5 治理与资本配置</span></div>'
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

    # 补充修订四：3.3 护城河 / 4.3 催化剂同款 <p> 恰为 2 规则
    def dim_with(name, inner):
        return ('<div class="dim-block"><div class="dim-header">'
                f'<span class="dim-name">{name}</span></div>' + inner + '</div>')
    dims5 = [('<div class="dim-block"><p>该维度分析：公司基本面稳健，数据支撑充分，'
              '论据详实可靠，行业地位稳固，具备长期参考价值。</p></div>')] * 5
    assert "恰为 2" not in validate_stderr(minimal_fill(
        l1_html="".join(dims5) + dim_with("3.3 商业模式与护城河", compact))), "3.3 紧凑形态不应告警"
    assert "恰为 2" in validate_stderr(minimal_fill(
        l1_html="".join(dims5) + dim_with("3.3 商业模式与护城河", loose))), "3.3 另起正文应告警"
    l3_43 = ("".join(dims5[:2]) + dim_with("4.3 催化剂", loose))
    assert "恰为 2" in validate_stderr(minimal_fill(l3_html=l3_43)), "4.3 另起正文应告警"
    print("OK 3.5 治理块单行化（紧凑放行 / 另起正文告警 / 存量不打扰 / 3.3+4.3 同款覆盖）")


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
    print("OK peers 最优/最差标注缺失告警（零标注告警 / 自带放行）")


def test_price_history_pe_warn():
    """v4.10：price_history 的 pe 过半缺失 → PE 折线不生成，告警提示照抄 E2 月末 PE
    （工行 09-11 报告 12 点全缺、图只剩股价线实证）。"""
    ph = {"label": "近12个月", "series": [{"m": f"2025-{m:02d}", "close": 7.5} for m in range(1, 13)]}
    assert "月末 PE" in validate_stderr(minimal_fill(price_history=ph)), "pe 全缺应告警"
    ph2 = {"label": "近12个月",
           "series": [{"m": f"2025-{m:02d}", "close": 7.5, "pe": 7.6} for m in range(1, 13)]}
    assert "月末 PE" not in validate_stderr(minimal_fill(price_history=ph2)), "pe 齐全不应告警"
    print("OK price_history pe 缺失告警（全缺告警 / 齐全放行）")


def test_l4_form_gates():
    """v4.10：L4 固定形态硬门禁——缺 pm-grid 三联卡拒渲染（旧 danger-card 单段形态打回）；
    黄灯扣分明细表行数 ≠ yellow_deductions 条数拒渲染（工行 09-11 照抄旧形态实证）。"""

    def expect_reject(fill, needle):
        try:
            R.validate_content(fill, R.compute_valuation(fill))
        except ValueError as e:
            assert needle in str(e), f"拒绝理由应含「{needle}」，实际：{e}"
            return
        raise AssertionError(f"应拒渲染但未拒（期待理由含「{needle}」）")

    f = minimal_fill()
    f["l4_html"] = ('<div class="danger-card"><strong>损失预演：</strong>单段长文旧形态，'
                    '故事与重合度与清单外风险糊在一个段落里。</div>')
    expect_reject(f, "损失预演三联卡")
    f2 = minimal_fill(yellow_deductions=[{"label": "x", "points": 0.5},
                                         {"label": "y", "points": 0.5}])
    f2["l4_html"] = (f2["l4_html"] + '<div class="table-scroll"><table><tbody>'
                     '<tr><td>a 交易与股东行为</td><td>无</td><td>0</td></tr>'
                     '<tr><td>b 行业与政策环境</td><td>x</td><td class="num">0.5</td></tr>'
                     '<tr><td>c 盈利与财务质量</td><td>y</td><td class="num">0.5</td></tr>'
                     '<tr><td>d 经营与公司治理</td><td>无</td><td>0</td></tr>'
                     '</tbody></table></div><span class="source">数据来源：测试</span>')
    expect_reject(f2, "只列 points>0")
    f3 = minimal_fill(yellow_deductions=[{"label": "x", "points": 0.5}])
    f3["l4_html"] = (f3["l4_html"] + '<div class="table-scroll"><table><tbody>'
                     '<tr><td>b 行业与政策环境</td><td>x</td><td class="num">0.5</td></tr>'
                     '</tbody></table></div><span class="source">数据来源：测试</span>')
    R.validate_content(f3, R.compute_valuation(f3))  # 匹配形态不拒即通过
    print("OK L4 形态门禁（旧形态拒 / 零扣分行拒 / 合规放行）")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"全部 {len(tests)} 项测试通过")
