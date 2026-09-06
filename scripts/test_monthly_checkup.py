#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_monthly_checkup.py — monthly_checkup 离线回归测试（无网络，直接 python 运行）

覆盖：合并解析口径后的 scan_reports（复盘版/旧 _ 命名/港股 5 位均识别、同代码取最新）、
--disclosure 的 ts_code 市场映射（rebind em_fetch.ts_call 拦截：6 位→.SH/.SZ、
北交所 92 段→.BJ、港股 5 位跳过不发查询；em_data 转发 stub 运行时解析宿主，rebind 传导）。
"""
import contextlib
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monthly_checkup as mc
import em_fetch as em


def _write(d, name, content):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return p


def test_scan_reports_merged_caliber():
    """合并口径：复盘版参与「同代码取最新」；旧 _ 命名与港股 5 位代码不再被漏掉。"""
    with tempfile.TemporaryDirectory() as d:
        # 同代码两份：复盘版日期更新，必须取复盘版（旧 _REPORT_RE 不认「-复盘-」段会漏）
        _write(d, "万华化学-600309-6.74-7.4-2026-08-01.html", "<html>下次审查：2026-08-10</html>")
        _write(d, "万华化学-600309-6.80-7.6-复盘-2026-08-26.html", "<html>下次审查：2026-09-26</html>")
        # 旧 _ 分隔命名（pre-v4.0 单轨分）：识别，valuation 为 None
        _write(d, "中国神华_601088_6.72_2026-08-07.html", "<html></html>")
        # 港股 5 位代码（旧代码段 {4,6} + 无复盘支持下的漏判样本）
        _write(d, "腾讯控股-00700-6.93-8.2-2026-08-23.html", "<html>下次审查：2026-09-01</html>")
        # 非报告文件忽略
        _write(d, "随手笔记.html", "<html></html>")
        rows = {r["code"]: r for r in mc.scan_reports(d)}
    assert set(rows) == {"600309", "601088", "00700"}, f"覆盖口径: {sorted(rows)}"
    assert rows["600309"]["date"] == "2026-08-26", f"应取复盘新版: {rows['600309']}"
    assert rows["600309"]["next_review"] == "2026-09-26"
    assert rows["601088"]["valuation"] is None and rows["601088"]["quality"] == 6.72
    assert rows["00700"]["next_review"] == "2026-09-01"
    print("OK scan_reports 合并口径（复盘取最新 / 旧 _ 命名 / 港股 5 位 / 非报告排除）")


def test_disclosure_ts_code_mapping():
    """--disclosure：ts_code 后缀走 to_ts_code 市场映射；港股跳过。全程 mock，禁网络。"""
    captured = []
    real_ts_call = em.ts_call

    def fake_ts_call(api_name, params=None, fields=""):
        captured.append((api_name, (params or {}).get("ts_code")))
        return [{"end_date": "20261231", "pre_date": "2026-10-30", "actual_date": None}]

    em.ts_call = fake_ts_call
    argv = sys.argv
    buf = io.StringIO()
    try:
        with tempfile.TemporaryDirectory() as d:
            anchor = "下次审查：2026-08-01"  # 恒过期（相对任何运行日）
            _write(d, "宝丰能源-600989-7.00-3.9-2026-08-01.html", f"<html>{anchor}</html>")
            _write(d, "中兴通讯-000063-4.92-2.3-2026-08-01.html", f"<html>{anchor}</html>")
            _write(d, "北证样本-920982-5.0-6.0-2026-08-01.html", f"<html>{anchor}</html>")
            _write(d, "腾讯控股-00700-6.93-8.2-2026-08-01.html", f"<html>{anchor}</html>")
            sys.argv = ["monthly_checkup.py", d, "--disclosure"]
            with contextlib.redirect_stdout(buf):
                mc.main()
        out = buf.getvalue()
    finally:
        em.ts_call = real_ts_call
        sys.argv = argv
    got = sorted(ts for api, ts in captured if api == "disclosure_date")
    assert got == ["000063.SZ", "600989.SH", "920982.BJ"], f"ts_code 市场映射错误: {got}"
    assert not any(ts and ts.endswith(".HK") for _, ts in captured), "港股不应发 disclosure_date 查询"
    assert "00700" in out and "港股" in out, f"港股应输出跳过说明:\n{out}"
    assert "计划披露 2026-10-30" in out, f"mock 计划披露日期应出现在输出:\n{out}"
    print("OK --disclosure ts_code 映射（SH/SZ/BJ + 港股跳过，mock 无网络）")


if __name__ == "__main__":
    test_scan_reports_merged_caliber()
    test_disclosure_ts_code_mapping()
    print("全部 2 项测试通过")
