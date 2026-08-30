#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_calibration.py — score_calibration 纯函数回归测试（无网络，直接 python 运行）

覆盖：文件名两代命名解析、分桶边界、同股去重口径。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import score_calibration as sc

# 1. 文件名解析：- 分隔（含/不含复盘标记）、_ 分隔旧版、非报告文件
assert sc.parse_filename("万华化学-600309-6.74-7.4-复盘-2026-08-26.html") == ("600309", "2026-08-26")
assert sc.parse_filename("中兴通讯-000063-4.92-2.3-2026-08-24.html") == ("000063", "2026-08-24")
assert sc.parse_filename("腾讯控股-00700-6.93-8.2-复盘-2026-08-23.html") == ("00700", "2026-08-23")
assert sc.parse_filename("中国神华_601088_6.72_2026-08-07.html") == ("601088", "2026-08-07")
assert sc.parse_filename("随手笔记.html") is None
assert sc.parse_filename("无日期-600989-6.0-5.0.html") is None
print("OK parse_filename（两代命名 + 非报告排除）")

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
