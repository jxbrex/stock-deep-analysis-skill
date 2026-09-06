#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_calibration.py — score_calibration 纯函数回归测试（无网络，直接 python 运行）

覆盖：文件名解析接线（owner=extract_review.parse_report_name，两代命名）、分桶边界、同股去重口径。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import score_calibration as sc

# 1. 文件名解析已合并至 extract_review.parse_report_name（score_calibration 经 import 复用），
#    此处验证接线与两代命名口径（返回值由 (code, date) 元组改为 dict，断言随之改写）
r = sc.parse_report_name("万华化学-600309-6.74-7.4-复盘-2026-08-26.html")
assert r["code"] == "600309" and r["date"] == "2026-08-26" and r["is_review"] is True
r = sc.parse_report_name("中兴通讯-000063-4.92-2.3-2026-08-24.html")
assert r["code"] == "000063" and r["date"] == "2026-08-24" and r["is_review"] is False
r = sc.parse_report_name("腾讯控股-00700-6.93-8.2-复盘-2026-08-23.html")
assert r["code"] == "00700" and r["date"] == "2026-08-23"
r = sc.parse_report_name("中国神华_601088_6.72_2026-08-07.html")
assert r["code"] == "601088" and r["date"] == "2026-08-07"
assert r["valuation"] is None and r["quality"] == 6.72  # 旧 _ 命名：单轨综合分作质量分近似
assert sc.parse_report_name("随手笔记.html") is None
assert sc.parse_report_name("无日期-600989-6.0-5.0.html") is None
print("OK parse_report_name 接线（owner=extract_review，两代命名 + 非报告排除）")

# 2. 分桶边界：阈值点归属（与决策矩阵口径：左闭右开）
assert sc.bucket_of(3.99, sc.Q_BUCKETS) == "质量<4 回避"
assert sc.bucket_of(4.0, sc.Q_BUCKETS) == "质量4-5.5 一般"
assert sc.bucket_of(7.0, sc.Q_BUCKETS) == "质量≥7 好公司"
assert sc.bucket_of(8.0, sc.V_BUCKETS) == "估值≥8 深度安全边际"
assert sc.bucket_of(7.99, sc.V_BUCKETS) == "估值6-8 偏便宜"
assert sc.bucket_of(None, sc.V_BUCKETS) is None
print("OK bucket_of（边界左闭右开 / None 不入桶）")

# 3. 同股去重：取最早一份
reps = [{"code": "00700", "rep_date": "2026-08-23"},
        {"code": "00700", "rep_date": "2026-08-14"},
        {"code": "600989", "rep_date": "2026-08-19"}]
got = sc.dedup_earliest(reps)
assert len(got) == 2
assert next(r for r in got if r["code"] == "00700")["rep_date"] == "2026-08-14"
print("OK dedup_earliest（同股取最早，独立窗口）")

print("全部 3 项测试通过")
