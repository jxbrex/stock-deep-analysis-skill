#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_mcap_mode.py — 市值口径（mcap / metric_label）冒烟（无网络，直接 python 运行）

覆盖：PE 经典模式回归（输出不变）、mcap 模式（目标市值行 + 行业倍数标签）、
口径混用 / 同情景双填 / mcap 区间非法 / 缺口径 四种拒绝。
夹具全部走 conftest（minimal_fill / mcap_fill），不再自造平行 fill。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from conftest import minimal_fill, mcap_fill, render_fill, expect_valueerror


def test_pe_mode_regression():
    """PE 经典模式回归：归母净利/EPS/PE 行与 PE(TTM) 过程卡标签保持原样，无目标市值行。"""
    html = render_fill(minimal_fill())
    assert "归母净利" in html and "PE(TTM) 11x vs 合理带 10-12x" in html
    assert "目标市值" not in html


def test_mcap_mode_render():
    """mcap 模式（P/NAV 口径）：情景表显示目标市值行（无归母净利/EPS 行），过程卡显示 P/NAV 标签。"""
    html = render_fill(mcap_fill())
    assert "目标市值" in html and "1,000-1,200 亿" in html
    assert "P/NAV 0.55x vs 合理带 0.5-0.6x" in html
    # 增长图/图墙 caption 自带「归母净利」字样，断言收窄到情景表本体
    tbl = re.search(r'<table class="scenario-table">.*?</table>', html, re.S).group(0)
    assert "归母净利" not in tbl and "EPS" not in tbl


def test_mcap_mode_rejections():
    """四种非法口径均被拒渲染：口径混用 / 同情景双填 / mcap 区间非法 / 缺口径。"""
    f = minimal_fill()   # 口径混用：三情景 profit+pe 与 mcap 不统一
    f["valuation"]["scenarios"][2] = {"key": "opt", "label": "乐观", "trigger": "上行",
                                      "mcap": [1440, 1680]}
    expect_valueerror(f, kw="口径混用")
    f = minimal_fill()   # 同情景双填 profit + mcap
    f["valuation"]["scenarios"][0]["mcap"] = [640, 800]
    expect_valueerror(f, "双填", kw="口径冲突")
    f = mcap_fill()      # mcap 区间非法（高 < 低）
    f["valuation"]["scenarios"][0]["mcap"] = [800, 640]
    expect_valueerror(f, "区间非法", kw="mcap 区间非法")
    f = minimal_fill()   # 既无 profit 也无 mcap
    f["valuation"]["scenarios"][0] = {"key": "pess", "label": "悲观", "trigger": "空"}
    expect_valueerror(f, "缺口径", kw="缺净利假设")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"全部 {len(tests)} 项测试通过")
