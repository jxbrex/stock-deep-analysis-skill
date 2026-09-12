#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_render_e2e.py — render_report 端到端回归（无网络，直接 python 运行）

覆盖 render() 全流程产物：千位符归一、BOM fill 解析、币种替换、回测模式章节、
字面 {{KEY}} 实体化、低价股目标价精度、渲染后归档。
拆分自 test_render_core.py（v4.10.2），断言逐字沿用。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_report as R
from conftest import minimal_fill, render_fill, render_workspace, write_fill


def test_fmt_thousands():
    """Hero 金额卡千位符归一：裸数字补逗号，已有逗号幂等，<1000/非数字不动，price 类不走此路。"""
    assert R._fmt_thousands("10330.7") == "10,330.7"
    assert R._fmt_thousands("10,330.7") == "10,330.7"
    assert R._fmt_thousands("999.9") == "999.9"
    assert R._fmt_thousands("188153") == "188,153"
    assert R._fmt_thousands("—") == "—"
    assert R._fmt_thousands("23.34万") == "23.34万"  # 带单位不归一
    print("OK 千位符归一（补逗号 / 幂等 / <1000 不动 / 非数字不动）")


def test_bom_fill_loads():
    """带 BOM 的 UTF-8 fill JSON 必须可解析。"""
    with render_workspace() as d:
        p = write_fill(minimal_fill(), d, name="_fill_t.json", encoding="utf-8-sig")  # 写带 BOM
        fill = R._load_fill(p)
    assert fill["company"] == "测试股份"


def test_currency_hkd():
    """currency="港元"：输出 HTML 含「港元」，情景表目标价行不用默认「元」。"""
    html = render_fill(minimal_fill(currency="港元"))
    assert "港元" in html, "输出应含「港元」"
    assert "10-12 港元" in html, "情景表目标价行应用港元"
    assert "{{CUR}}" not in html, "{{CUR}} 必须被替换"


def test_review_dumbbell():
    """回测模式：prev 填了才出三轨哑铃图；回测章=第 12 章（v4.8.1 起提前，在跟踪仪表盘之前）。"""
    fill = minimal_fill(prev={"date": "2026-08-08", "quality": 7.0, "valuation": 5.5,
                              "timing": 5.0, "target_range": "10-12"},
                        review_html='<table><tr><td>假设变更对比</td></tr></table>'
                                    '<span class="source">数据来源：测试</span>'
                                    '<span class="rev">甲</span><span class="rev">乙</span><span class="rev">丙</span>')
    html = render_fill(fill)
    assert 'aria-label="三轨分新旧对比"' in html, "回测模式应生成哑铃图"
    assert 'id="s12"' in html and "回测复盘" in html, "回测章节应出现（v4.8.1 起为第 12 章）"
    assert html.find('id="s12"') < html.find('id="s13"'), "回测复盘应排在跟踪仪表盘（s13）之前"


def test_fill_literal_mustache_survives():
    """v4.9 fill 片段含字面 {{KEY}} 不被模板占位符替换误吞（实体化原样显示，渲染通过）。"""
    f = minimal_fill()
    # position_html 里带一段「模板占位符示例」文本
    f["position_html"] = ("<p>模板占位符示例 {{DATE}} 与 {{COMPANY}} 是字面量，时机判定与决策逻辑如下。"
                          + "时机判定与决策逻辑。" * 6 + "</p>")
    html = render_fill(f)
    assert "{{DATE}}" not in html, "字面 {{DATE}} 不应被替换为实际日期（误吞）"
    assert "&#123;&#123;DATE}}" in html and "&#123;&#123;COMPANY}}" in html, "字面 {{}} 应实体化原样显示"
    print("OK fill 字面 {{KEY}} 实体化（不误吞、不残留报错）")


def test_low_price_precision():
    """v4.10：低价股目标价区间两位小数（_fmt_px，<10 元）——工行「6-6/8-8/9-9」被整数
    格式化压没区间的实证修复；目标价行/Hero 区间卡/走廊图标签统一精度，≥10 元仍整数。"""
    fill = minimal_fill(
        price="7.94", pe_ttm="7.56",
        valuation_inputs={"pe_ttm": 7.56, "pe_band": [6.5, 7.8],
                          "div_yield": 3.9, "risk_free": 1.7},
        valuation={"shares": 3564, "horizon": "12个月", "scenarios": [
            {"key": "pess", "label": "悲观", "trigger": "息差续降", "profit": 3500, "pe": [6, 6.6]},
            {"key": "base", "label": "基础", "trigger": "息差企稳", "profit": 3795, "pe": [7.1, 7.5]},
            {"key": "opt", "label": "乐观", "trigger": "息差回升", "profit": 3950, "pe": [7.8, 8.4]},
        ]},
        thesis_html=('银行论点与关键证据。三情景目标价 '
                     '<span class="scenario-pess">6.19</span>/'
                     '<span class="scenario-base">7.77</span>/'
                     '<span class="scenario-opt">8.98</span> 元，结论：回避当前价。'),
    )
    html = render_fill(fill)
    # 3500/3564×6=5.89、×6.6=6.48；3795/3564×7.1=7.56、×7.5=7.99（base 区间 → Hero 区间卡）
    assert "5.89-6.48 元" in html, "悲观目标价应为两位小数区间"
    assert "7.56-7.99" in html, "Hero 目标价区间卡应为 base 两位小数区间"
    assert ">6-6 元<" not in html and ">8-8 元<" not in html, "整数压没区间的旧形态不得复现"
    print("OK 低价股目标价两位小数（区间不再被整数格式化压没）")


def test_archive_after_render():
    """v4.10 B-min 归档：渲染成功后 _fill_/_em_ 前缀文件移入 _archive/ 并追加 _index.jsonl；
    非 _fill_ 命名的 fill（fixture/存量文件）不动；归档在渲染成功之后（防伪链不断）。"""
    with render_workspace() as d:
        quote_path = write_fill({"price": 10, "pe_ttm": 11}, d, name="_em_600000_quote.json")
        fill = minimal_fill(quote={"source_file": quote_path, "date": "2026-08-27"})
        p = write_fill(fill, d)
        R.render(p, out_path=os.path.join(d, "out.html"))
        arch = os.path.join(d, "_archive")
        assert not os.path.exists(p), "fill 应被移走"
        assert not os.path.exists(quote_path), "quote 落盘应被移走"
        assert os.path.exists(os.path.join(arch, "fill_测试股份_600000_2026-08-27.json")), "fill 归档命名"
        assert os.path.exists(os.path.join(arch, "em_600000_quote_2026-08-27.json")), "quote 归档命名"
        row = json.loads(open(os.path.join(arch, "_index.jsonl"), encoding="utf-8").read().strip())
        assert row["company"] == "测试股份" and row["code"] == "600000", "索引行公司/代码"
        assert row["html"] == "out.html" and row["renderer"] == R.RENDERER_VERSION, "索引行 html/渲染器版本"
        p2 = write_fill(minimal_fill(), d, name="keep.json")
        R.render(p2, out_path=os.path.join(d, "out2.html"))
        assert os.path.exists(p2), "非 _fill_ 前缀 fill 不得被移动"
        n = len(open(os.path.join(arch, "_index.jsonl"), encoding="utf-8").read().strip().splitlines())
        assert n == 2, "每次渲染追加一行索引"
    print("OK 渲染后归档（fill+quote 移入 _archive、索引追加、非 _fill_ 不动）")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"全部 {len(tests)} 项测试通过")
