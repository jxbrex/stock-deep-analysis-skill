#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_em_fetch.py — em_fetch.py 无网络单元测试（自包含、全 assert）

覆盖：
1. secid_of / to_ts_code 市场映射一致性（A股沪/深、北交所、B股、港股5位、非法输入报错）
2. 闰日路径：_ttm_cutoff 在 2/29 不炸
3. 同比文字化：_yoy 分母≤0 时返回 扭亏/转亏/减亏/增亏
4. 429 硬停：mock 掉 curl，断言 429 → RateLimitError 且不重试同一 URL、不回落 urllib

运行: python test_em_fetch.py（scripts 目录下）
"""
import sys
from datetime import date

import em_fetch as em

# ---------------- 1. 市场映射一致性 ----------------

# A股沪市（60/68 开头）
assert em.secid_of("600989") == ("1.600989", "600989.SH", False)
assert em.to_ts_code("600989") == "600989.SH"
assert em.secid_of("688981") == ("1.688981", "688981.SH", False)
# A股深市（00/30 开头，默认分支）
assert em.secid_of("000528") == ("0.000528", "000528.SZ", False)
assert em.to_ts_code("000528") == "000528.SZ"
assert em.secid_of("300750") == ("0.300750", "300750.SZ", False)
# 北交所（43/83/87/88/92 开头）：两边都必须是 BJ，secid 前缀 0.
for bj in ("430047", "830799", "871245", "880001", "920001"):
    assert em.secid_of(bj) == (f"0.{bj}", f"{bj}.BJ", False), bj
    assert em.to_ts_code(bj) == f"{bj}.BJ", bj
# B股（9 开头 → 沪市；200 开头深B → 深市默认分支）
assert em.secid_of("900901") == ("1.900901", "900901.SH", False)
assert em.to_ts_code("900901") == "900901.SH"
assert em.secid_of("200002") == ("0.200002", "200002.SZ", False)
# 港股 5 位
assert em.secid_of("06082") == ("116.06082", "06082.HK", True)
assert em.to_ts_code("06082") == "06082.HK"
assert em.secid_of("00700") == ("116.00700", "00700.HK", True)
# 带后缀输入：secid_of 剥后缀重判，to_ts_code 原样透传
assert em.secid_of("600989.SH") == ("1.600989", "600989.SH", False)
assert em.to_ts_code("600989.SH") == "600989.SH"
assert em.secid_of("06082.HK") == ("116.06082", "06082.HK", True)
# 非法输入：非纯数字或长度非 5/6 → 两边都报 ValueError，不静默按深市处理
for bad in ("abc", "12345x", "1234567", "", "123", "60098A"):
    for fn in (em.secid_of, em.to_ts_code):
        try:
            fn(bad)
            raise AssertionError(f"{fn.__name__}({bad!r}) 应报 ValueError")
        except ValueError:
            pass
print("1. 市场映射一致性 通过")

# ---------------- 2. 闰日路径 ----------------

# 2024-02-29 是闰日：旧写法 replace(year=2023) 会 ValueError，新写法必须正常
assert em._ttm_cutoff(date(2024, 2, 29)) == "20230301"
assert em._ttm_cutoff(date(2026, 8, 26)) == "20250826"
print("2. 闰日路径 通过")

# ---------------- 3. 同比文字化 ----------------

assert em._yoy(5, -3) == "扭亏"        # pre<0, cur>0
assert em._yoy(-5, 10) == "转亏"       # pre>0, cur<0
assert em._yoy(-3, -5) == "减亏"       # pre<0, 亏损收窄
assert em._yoy(-6, -5) == "增亏"       # pre<0, 亏损扩大
assert abs(em._yoy(110, 100) - 10.0) < 1e-9   # 正常正分母 → 数值百分比
assert em._yoy(5, 0) is None           # pre==0 无意义
assert em._yoy(None, 5) is None
assert em._yoy(5, None) is None
# 渲染：文字原样、数值走百分比
assert em.yoy_text("扭亏") == "扭亏"
assert em.yoy_text(10.0) == "10.0%"
assert em.yoy_text(None) == "—"
print("3. 同比文字化 通过")

# ---------------- 4. 429 硬停（无网络，mock curl/urllib） ----------------

calls = {"curl": 0, "urllib": 0}


class _FakeProc:
    """模拟 curl 返回 HTTP 429（-w 追加的状态码行）"""
    returncode = 0
    stdout = b'{"error": "too many requests"}\n429'
    stderr = b""


_orig_run = em.subprocess.run
_orig_urllib = em._get_via_urllib


def _fake_run(*a, **k):
    calls["curl"] += 1
    return _FakeProc()


def _fake_urllib(url):
    calls["urllib"] += 1
    return b"{}"


em.subprocess.run = _fake_run
em._get_via_urllib = _fake_urllib
try:
    # get() 遇到 429：抛 RateLimitError，且不重试同一 URL、不回落 urllib
    try:
        em.get("http://example.invalid/x")
        raise AssertionError("429 应抛 RateLimitError")
    except em.RateLimitError:
        pass
    assert calls["curl"] == 1, f"429 禁止同 URL 原样重试（curl 被调了 {calls['curl']} 次）"
    assert calls["urllib"] == 0, "429 不应回落 urllib 重打"

    # 5xx 同样硬停
    class _Fake500(_FakeProc):
        stdout = b"<html>bad gateway</html>\n502"

    calls["curl"] = 0
    em.subprocess.run = lambda *a, **k: (calls.__setitem__("curl", calls["curl"] + 1), _Fake500())[1]
    try:
        em.get("http://example.invalid/y")
        raise AssertionError("502 应抛 RateLimitError")
    except em.RateLimitError:
        pass
    assert calls["curl"] == 1

    # 正常 200：去掉状态码行后返回 JSON
    class _Fake200(_FakeProc):
        stdout = b'{"data": {"x": 1}}\n200'

    em.subprocess.run = lambda *a, **k: _Fake200()
    assert em.get("http://example.invalid/ok") == {"data": {"x": 1}}

    # 网络层错误（连接失败）维持原逻辑：curl 失败 → urllib 兜底
    em.subprocess.run = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("mock 连接失败"))
    em._get_via_urllib = lambda url: b'{"ok": true}'
    assert em.get("http://example.invalid/net") == {"ok": True}
finally:
    em.subprocess.run = _orig_run
    em._get_via_urllib = _orig_urllib
print("4. 429 硬停 通过")

print("\n全部断言通过", file=sys.stderr)
