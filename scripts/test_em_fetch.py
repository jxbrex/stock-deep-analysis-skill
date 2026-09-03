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
import os
import sys
import time
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

# ---------------- 5. 陈旧档拦截（无网络，mock get） ----------------

_orig_get = em.get
try:
    # 北交所旧代码（已切换 920 段）：东财返回全零 + 名称含「已切换」→ 必须报错
    em.get = lambda url: {"data": {"f43": 0, "f57": "832982", "f58": "锦波生物(已切换)",
                                   "f116": 0, "f162": 0, "f167": 0, "f168": 0, "f170": 0}}
    try:
        em._em_quote("0.832982")
        raise AssertionError("已切换标的全零行情必须抛 ValueError")
    except ValueError as e:
        assert "920" in str(e), "报错应提示北交所 920 新代码段"
    # 正常标的：有价格有市值 → 不拦
    em.get = lambda url: {"data": {"f43": 12099, "f57": "920982", "f58": "锦波生物",
                                   "f116": 1.39e10, "f162": 2473, "f167": 683,
                                   "f168": 103, "f170": -14}}
    q = em._em_quote("0.920982")
    assert q["名称"] == "锦波生物" and q["最新价"] == 120.99
finally:
    em.get = _orig_get
print("5. 陈旧档拦截 通过")

# ---------------- 6. token 缺失硬告警（无网络，mock ts_call） ----------------
# 神华事故教训：RuntimeError（token 未配置/接口报错）曾被裸 except 静默吞掉 → 白走降级链。
# 收窄后：OSError 静默、RuntimeError 必须打印 ⚠️ 到 stderr。
import io
import contextlib

_orig_ts = em.ts_call
_orig_token = em._tushare_token
try:
    def _boom(*a, **k):
        raise RuntimeError("tushare token 未配置（mock）")

    em.ts_call = _boom
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        assert em.fetch_audit("600989") is None
        assert em.fetch_debt("600989") is None
        g = em.fetch_governance("600989")
        assert g["pledge"] is None and g["trades"] == []
        assert em.fetch_disclosure("600989") is None
    err = buf.getvalue()
    assert err.count("⚠️") >= 5, f"4 函数 6 个取数点的 RuntimeError 应逐条告警，实际 {err.count('⚠️')} 条"
    assert "token 未配置" in err, "告警应含原因"

    # OSError（网络层）仍静默
    em.ts_call = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("mock 断网"))
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        assert em.fetch_audit("600989") is None
    assert "⚠️" not in buf.getvalue(), "网络层错误不应告警（静默走降级）"
finally:
    em.ts_call = _orig_ts
    em._tushare_token = _orig_token
print("6. token 缺失硬告警 通过")

# ---------------- 7. 磁盘缓存（无网络，mock urlopen + 临时目录） ----------------
import json as _json
import tempfile as _tmp

_orig_dir, _orig_no = em._CACHE_DIR, em._NO_CACHE
em._CACHE_DIR = _tmp.mkdtemp()
em._NO_CACHE = False


class _Resp:
    def __init__(self, payload):
        self._p = _json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._p


_net = {"n": 0}
_orig_open = em.urllib.request.urlopen
em.urllib.request.urlopen = lambda *a, **k: (_net.__setitem__("n", _net["n"] + 1),
                                             _Resp({"code": 0, "data": {"fields": ["a"],
                                                                        "items": [[1]]}}))[1]
try:
    params = {"ts_code": "600989.SH", "start_date": "20200101"}
    em._TS_CACHE.clear()
    r1 = em.ts_call("daily_basic", params)
    em._TS_CACHE.clear()  # 清进程缓存：第二发必须命中磁盘
    r2 = em.ts_call("daily_basic", params)
    assert r1 == r2 == [{"a": 1}]
    assert _net["n"] == 1, f"磁盘缓存应省去第二次网络请求，实际 {_net['n']} 次"

    # TTL 过期（行情档 2h）→ 重新请求
    f = os.listdir(em._CACHE_DIR)[0]
    stale = os.path.join(em._CACHE_DIR, f)
    old = time.time() - 3 * 3600
    os.utime(stale, (old, old))
    em._TS_CACHE.clear()
    em.ts_call("daily_basic", params)
    assert _net["n"] == 2, "过期缓存应重新取数"

    # EM_FETCH_NO_CACHE 旁路：新鲜缓存也不读
    em._NO_CACHE = True
    em._TS_CACHE.clear()
    em.ts_call("daily_basic", params)
    assert _net["n"] == 3, "NO_CACHE 旁路必须强制走网络"
finally:
    em.urllib.request.urlopen = _orig_open
    em._CACHE_DIR, em._NO_CACHE = _orig_dir, _orig_no
    em._TS_CACHE.clear()
print("7. 磁盘缓存（命中 / TTL 过期重取 / NO_CACHE 旁路）通过")

# ---------------- 8. E6 毛利额回填（无网络，mock ts_call） ----------------
# v4.8：fetch_mainop 各分部带 GROSS_PROFIT——tushare 取 bz_profit，缺则 收入−成本。
_orig_ts8 = em.ts_call
try:
    em.ts_call = lambda api, params=None, fields="": [
        {"end_date": "20251231", "bz_item": "烯烃产品", "bz_sales": 1.5e10, "bz_cost": 9e9,
         "bz_profit": 6e9},
        {"end_date": "20251231", "bz_item": "焦化产品", "bz_sales": 5e9, "bz_cost": 4e9,
         "bz_profit": None},   # 缺 bz_profit → 应按 收入−成本 回填 1e9
        {"end_date": "20251231", "bz_item": "烯烃", "bz_sales": 1.5e10, "bz_cost": 9e9,
         "bz_profit": 6e9},   # 与第一行同收入同成本 → 同源改名残留，应去重
    ] if api == "fina_mainbz" else []
    mo = em.fetch_mainop("600989.SH")
    assert len(mo) == 2, f"同收入同成本重复条目应去重，实际 {len(mo)} 行"
    assert mo[0]["GROSS_PROFIT"] == 6e9, "bz_profit 应直接透传"
    assert mo[1]["GROSS_PROFIT"] == 1e9, "缺 bz_profit 应按 收入−成本 回填"
    assert abs(mo[0]["MBI_RATIO"] - 0.75) < 1e-9, "占比=分部收入÷合计（去重后分母）"
finally:
    em.ts_call = _orig_ts8
print("8. E6 毛利额回填 通过")

# ---------------- 9. PE 带 P25/P75 与时机素材（无网络，mock ts_call） ----------------
_orig_ts9 = em.ts_call
try:
    # 100 个交易日 pe_ttm = 1..100（单调，分位点可精确断言）
    rows_db = [{"trade_date": f"2025{(i // 28) + 1:02d}{(i % 28) + 1:02d}", "pe_ttm": float(i + 1),
                "pb": 1.5} for i in range(100)]
    em.ts_call = lambda api, params=None, fields="": rows_db if api == "daily_basic" else []
    band = em.fetch_pe_pb_band("600989", years=5)
    assert band["pe_p25"] == 25.0 and band["pe_p75"] == 75.0, \
        f"P25/P75 应为 25/75，实际 {band['pe_p25']}/{band['pe_p75']}"
    assert band["pe_min"] == 1.0 and band["pe_max"] == 100.0

    # 时机素材：300 个交易日 close = 1..300（递增）→ MA60/MA120/52周高低可精确断言
    rows_d = [{"trade_date": f"2026{(i // 28) + 1:02d}{(i % 28) + 1:02d}", "close": float(i + 1)}
              for i in range(300)]
    em.ts_call = lambda api, params=None, fields="": rows_d if api == "daily" else []
    tm = em.fetch_timing_material("600989", False)
    assert tm["ma60"] == 270.5 and tm["ma120"] == 240.5, f"实际 {tm}"
    assert tm["high_52w"] == 300.0 and tm["low_52w"] == 51.0, "52周窗口=最后250个交易日"
    assert tm["n"] == 300
    # 数据不足 60 日 → None（新股不硬画）
    em.ts_call = lambda api, params=None, fields="": rows_d[:30] if api == "daily" else []
    assert em.fetch_timing_material("600989", False) is None
finally:
    em.ts_call = _orig_ts9
print("9. PE 带 P25/P75 + 时机素材 通过")

# ---------------- 10. E2 月线月末 PE(TTM) 回填（无网络，mock ts_call） ----------------
# v4.8.1：fetch_kline_monthly A股 tushare 路径按月附 pe（月末交易日 pe_ttm，与 PE 带同参命中缓存）；
# daily_basic 不可用 → 静默降级为仅 close（price_history 图自动只画股价线）
_orig_ts10 = em.ts_call
try:
    rows_m = [{"trade_date": "20260131", "close": 10.0},
              {"trade_date": "20260228", "close": 11.0},
              {"trade_date": "20260331", "close": 12.0}]
    rows_f = [{"trade_date": "20260131", "adj_factor": 1.0},
              {"trade_date": "20260228", "adj_factor": 1.0},
              {"trade_date": "20260331", "adj_factor": 1.0}]
    rows_db = [{"trade_date": "20260131", "pe_ttm": 15.0, "pb": 1.2},
               {"trade_date": "20260228", "pe_ttm": 16.0, "pb": 1.2},
               {"trade_date": "20260331", "pe_ttm": 17.0, "pb": 1.2}]

    def _ts10(api, params=None, fields=""):
        return {"monthly": rows_m, "adj_factor": rows_f, "daily_basic": rows_db}.get(api, [])
    em.ts_call = _ts10
    kl = em.fetch_kline_monthly("1.600989", 1, False)
    assert [k.get("pe") for k in kl] == [15.0, 16.0, 17.0], f"月末 PE 应回填，实际 {kl}"

    def _ts10b(api, params=None, fields=""):
        if api in ("monthly", "adj_factor"):
            return {"monthly": rows_m, "adj_factor": rows_f}[api]
        raise RuntimeError("daily_basic 不可用")
    em.ts_call = _ts10b
    kl2 = em.fetch_kline_monthly("1.600989", 1, False)
    assert all("pe" not in k for k in kl2) and [k["close"] for k in kl2] == [10.0, 11.0, 12.0], \
        f"daily_basic 失败应静默降级为仅 close，实际 {kl2}"
finally:
    em.ts_call = _orig_ts10
print("10. E2 月线月末 PE(TTM) 回填 通过")

print("\n全部断言通过", file=sys.stderr)
