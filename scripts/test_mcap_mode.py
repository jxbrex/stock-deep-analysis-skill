"""render_report.py 市值口径（mcap / metric_label）冒烟自检。
运行：python test_mcap_mode.py
覆盖：PE 经典模式回归（输出不变）、mcap 模式（目标市值行 + 行业倍数标签）、
口径混用 / 同情景双填 / mcap 区间非法 / 缺口径 四种拒绝。"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_report

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))


def _fixture(valuation, valuation_inputs, thesis_prices):
    pess, base, opt = thesis_prices
    dim = ('<div class="dim-block"><p>测试维度论据：行业规模与增速数据支撑，竞争格局稳定，'
           '龙头份额持续提升；财务趋势向上，现金含量充足，负债率可控；治理记录良好，分红稳定，'
           '关键假设已列基准值与验证日期。给予中性评分。</p></div>')
    return {
        "company": "冒烟测试", "code": "000001", "date": "2026-08-19",
        "subtitle": "测试行业 · 冒烟夹具",
        "scores": {"1A": 6, "1B": 6, "1C": 6, "1D": 6, "1E": 6, "1F": 6,
                   "3A": 6, "3B": 6, "3C": 6},
        "timing_scores": {"筹码面": 5, "技术面": 5},
        "yellow_deductions": [],
        "valuation_inputs": valuation_inputs,
        "valuation": valuation,
        "price": "10", "mcap": "1,000", "pe_ttm": "10",
        "price_sub_html": "现价", "mcap_sub": "总市值", "pe_sub": "PE",
        "horizon": "12个月", "target_range": "10-12", "target_sub_html": "目标价区间",
        "thesis_html": (f'冒烟结论：测试标的质地中上、价格合理，关键证据与数据已列明（夹具示例），'
                        f'悲观有支撑、乐观有弹性；三情景目标价 <span class="scenario-pess">{pess}</span> / '
                        f'<span class="scenario-base">{base}</span> / '
                        f'<span class="scenario-opt">{opt}</span> 元，年化中枢为正——标准仓。'),
        "conclusion_html": (
            "<p><strong>关键优势：</strong>" + "优势带数据 6.0；" * 15 + "</p>"
            "<p><strong>关键弱点：</strong>" + "弱点带数据 5.0；" * 15 + "</p>"
            "<p><strong>当前市场认知：</strong>" + "卖方假设来源 2026-01；" * 10 + "</p>"
            "<p><strong>核心投资逻辑：</strong>" + "论点加证伪条件；" * 10 + "</p>"),
        "p0_html": "<p>P0 关键驱动测试。</p>",
        "l1_html": dim * 6,
        "l3_html": dim * 3,
        "l4_html": "<p>红黄灯测试。</p>",
        "valuation_method": "PE历史时段匹配法", "stock_type": "周期股",
        "valuation_html": "<p>估值方法说明。</p>",
        "gap_tier": "B", "gap_html": "<p>预期差测试。</p>",
        "peers_meta": "同业", "peers_html": (
            '<div class="table-scroll"><table><tr><td>同业A</td></tr></table></div>'
            '<span class="source">数据来源：冒烟</span>'),
        "peers_plot": {"points": [{"name": "冒烟测试", "roe": 10, "pe": 10, "target": True},
                                  {"name": "同业A", "roe": 12, "pe": 15}]},
        "next_review": "2026-11-19", "dash_html": "<p>仪表盘测试。</p>",
        "position_html": "<p>时机判定小表与决策逻辑与触发条件。</p>" * 8,
        # v4.9 必填图字段（夹具最小值）
        "fin_trend": {"years": ["2023", "2024", "2025"], "panels": [
            {"title": "营收 × 毛利率",
             "bars": [{"name": "营收", "unit": "亿", "values": [90, 95, 100]}],
             "lines": [{"name": "毛利率", "pct": True, "values": [30, 31, 32]}]},
            {"title": "归母净利 × 净利率",
             "bars": [{"name": "归母净利", "unit": "亿", "values": [8, 9, 10]}],
             "lines": [{"name": "净利率", "pct": True, "values": [8.9, 9.5, 10]}]},
            {"title": "经营现金流 × 现金含量",
             "bars": [{"name": "经营现金流", "unit": "亿", "values": [9, 10, 11]}],
             "lines": [{"name": "现金含量", "values": [1.0, 1.1, 1.1], "threshold": 0.7}]},
        ]},
        "growth_plot": {"hist": [{"y": "2023", "rev": 5.0, "np": 12.5},
                                 {"y": "2024", "rev": 5.6, "np": 12.5},
                                 {"y": "2025", "rev": 5.3, "np": 11.1}],
                        "fcst": [{"y": "2026E", "np_lo": 5, "np_hi": 9, "np_consensus": 7.0}]},
    }


def _render(fixture, tmp):
    path = os.path.join(tmp, "_fill_smoke.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fixture, f, ensure_ascii=False)
    out = render_report.render(path)
    with open(out, encoding="utf-8") as f:
        return f.read()


def _expect_error(fixture, tmp, fragment):
    path = os.path.join(tmp, "_fill_smoke_bad.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fixture, f, ensure_ascii=False)
    try:
        render_report.render(path)
    except ValueError as e:
        assert fragment in str(e), f"报错文案不含「{fragment}」: {e}"
        return
    raise AssertionError(f"应拒绝渲染（{fragment}）但未拒绝")


def main():
    pe_inputs = {"pe_ttm": 10, "pe_band": [9, 12], "div_yield": 2, "risk_free": 1.7}
    pe_val = {"shares": 100, "horizon": "12个月", "scenarios": [
        {"key": "pess", "label": "悲观", "trigger": "下行", "profit": 80, "pe": [8, 10]},
        {"key": "base", "label": "基础", "trigger": "中性", "profit": 100, "pe": [10, 12]},
        {"key": "opt", "label": "乐观", "trigger": "上行", "profit": 120, "pe": [12, 14]}]}
    nav_inputs = {"pe_ttm": 0.5, "pe_band": [0.4, 0.6], "div_yield": 0,
                  "risk_free": 1.7, "metric_label": "P/NAV"}
    nav_val = {"shares": 100, "horizon": "12个月", "scenarios": [
        {"key": "pess", "label": "悲观", "trigger": "折让扩大", "mcap": [600, 800]},
        {"key": "base", "label": "基础", "trigger": "折让中性", "mcap": [1000, 1200]},
        {"key": "opt", "label": "乐观", "trigger": "折让收敛", "mcap": [1400, 1800]}]}

    with tempfile.TemporaryDirectory() as tmp:
        # 1. PE 经典模式回归
        html = _render(_fixture(pe_val, pe_inputs, (7.2, 11, 15.6)), tmp)
        assert "归母净利" in html and "PE(TTM) 10x vs 合理带 9-12x" in html
        assert "目标市值" not in html
        print("OK PE 经典模式：归母净利/EPS/PE 行与 PE(TTM) 标签保持原样")

        # 2. mcap 模式（NAV 口径 + metric_label）
        html = _render(_fixture(nav_val, nav_inputs, (7, 11, 16)), tmp)
        assert "目标市值" in html and "1,000-1,200 亿" in html
        assert "P/NAV 0.5x vs 合理带 0.4-0.6x" in html
        # v4.9：增长图/图墙caption 自带「归母净利」字样，断言收窄到情景表本体
        import re as _re
        tbl = _re.search(r'<table class="scenario-table">.*?</table>', html, _re.S).group(0)
        assert "归母净利" not in tbl and "EPS" not in tbl
        print("OK mcap 模式：情景表显示目标市值行，过程卡显示 P/NAV 标签")

        # 3. 口径混用（三情景不统一）→ 拒渲染
        bad = _fixture({**pe_val, "scenarios": [
            pe_val["scenarios"][0], pe_val["scenarios"][1], nav_val["scenarios"][2]]},
            pe_inputs, (7.2, 11, 15.6))
        _expect_error(bad, tmp, "口径混用")
        # 4. 同情景双填 profit + mcap → 拒渲染
        bad = _fixture({**pe_val, "scenarios": [
            {**pe_val["scenarios"][0], "mcap": [600, 800]},
            pe_val["scenarios"][1], pe_val["scenarios"][2]]}, pe_inputs, (7.2, 11, 15.6))
        _expect_error(bad, tmp, "口径冲突")
        # 5. mcap 区间非法（高 < 低）→ 拒渲染
        bad = _fixture({**nav_val, "scenarios": [
            {**nav_val["scenarios"][0], "mcap": [800, 600]},
            nav_val["scenarios"][1], nav_val["scenarios"][2]]}, nav_inputs, (7, 11, 16))
        _expect_error(bad, tmp, "mcap 区间非法")
        # 6. 既无 profit 也无 mcap → 拒渲染
        bad = _fixture({**pe_val, "scenarios": [
            {"key": "pess", "label": "悲观", "trigger": "空"},
            pe_val["scenarios"][1], pe_val["scenarios"][2]]}, pe_inputs, (7.2, 11, 15.6))
        _expect_error(bad, tmp, "缺净利假设")
        print("OK 四种非法口径均被拒渲染（口径混用/双填/区间非法/缺口径）")

    print("全部冒烟断言通过。")


if __name__ == "__main__":
    main()
