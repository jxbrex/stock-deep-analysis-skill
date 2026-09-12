#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_em_fetch.py — em_fetch.py 无网络单元测试（自包含、全 assert）

覆盖：
1. secid_of / to_ts_code 市场映射一致性（A股沪/深、北交所、B股、港股5位、非法输入报错）
2. 闰日路径：_ttm_cutoff 在 2/29 不炸
3. 同比文字化：_yoy 分母≤0 时返回 扭亏/转亏/减亏/增亏
4. 429 硬停：mock 掉 curl，断言 429 → RateLimitError 且不重试同一 URL、不回落 urllib

运行: python test_em_fetch.py（scripts 目录下）；或 pytest 收集（v4.10.2 起各区为独立 def test_* 用例）
"""
import os
import sys
import time
from datetime import date

import em_core
import em_fetch as em


def test_01_market_map():
    """1. 市场映射一致性"""

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



def test_02_leap_day():
    """2. 闰日路径"""

    # 2024-02-29 是闰日：旧写法 replace(year=2023) 会 ValueError，新写法必须正常
    assert em._ttm_cutoff(date(2024, 2, 29)) == "20230301"
    assert em._ttm_cutoff(date(2026, 8, 26)) == "20250826"
    print("2. 闰日路径 通过")



def test_03_yoy_text():
    """3. 同比文字化"""

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



def test_04_rate_limit_hardstop():
    """4. 429 硬停（无网络，mock curl/urllib）"""

    calls = {"curl": 0, "urllib": 0}


    class _FakeProc:
        """模拟 curl 返回 HTTP 429（-w 追加的状态码行）"""
        returncode = 0
        stdout = b'{"error": "too many requests"}\n429'
        stderr = b""


    _orig_run = em_core.subprocess.run
    _orig_urllib = em_core._get_via_urllib


    def _fake_run(*a, **k):
        calls["curl"] += 1
        return _FakeProc()


    def _fake_urllib(url):
        calls["urllib"] += 1
        return b"{}"


    em_core.subprocess.run = _fake_run
    em_core._get_via_urllib = _fake_urllib
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
        em_core.subprocess.run = lambda *a, **k: (calls.__setitem__("curl", calls["curl"] + 1), _Fake500())[1]
        try:
            em.get("http://example.invalid/y")
            raise AssertionError("502 应抛 RateLimitError")
        except em.RateLimitError:
            pass
        assert calls["curl"] == 1

        # 正常 200：去掉状态码行后返回 JSON
        class _Fake200(_FakeProc):
            stdout = b'{"data": {"x": 1}}\n200'

        em_core.subprocess.run = lambda *a, **k: _Fake200()
        assert em.get("http://example.invalid/ok") == {"data": {"x": 1}}

        # 网络层错误（连接失败）维持原逻辑：curl 失败 → urllib 兜底
        em_core.subprocess.run = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("mock 连接失败"))
        em_core._get_via_urllib = lambda url: b'{"ok": true}'
        assert em.get("http://example.invalid/net") == {"ok": True}
    finally:
        em_core.subprocess.run = _orig_run
        em_core._get_via_urllib = _orig_urllib
    print("4. 429 硬停 通过")



def test_05_stale_code_guard():
    """5. 陈旧档拦截（无网络，mock get）"""

    _orig_get = em_core.get
    try:
        # 北交所旧代码（已切换 920 段）：东财返回全零 + 名称含「已切换」→ 必须报错
        em_core.get = lambda url: {"data": {"f43": 0, "f57": "832982", "f58": "锦波生物(已切换)",
                                            "f116": 0, "f162": 0, "f167": 0, "f168": 0, "f170": 0}}
        try:
            em._em_quote("0.832982")
            raise AssertionError("已切换标的全零行情必须抛 ValueError")
        except ValueError as e:
            assert "920" in str(e), "报错应提示北交所 920 新代码段"
        # 正常标的：有价格有市值 → 不拦
        em_core.get = lambda url: {"data": {"f43": 12099, "f57": "920982", "f58": "锦波生物",
                                            "f116": 1.39e10, "f162": 2473, "f167": 683,
                                            "f168": 103, "f170": -14}}
        q = em._em_quote("0.920982")
        assert q["名称"] == "锦波生物" and q["最新价"] == 120.99
    finally:
        em_core.get = _orig_get
    print("5. 陈旧档拦截 通过")



def test_06_token_alarm():
    """6. token 缺失硬告警（无网络，mock ts_call）"""
    # 神华事故教训：RuntimeError（token 未配置/接口报错）曾被裸 except 静默吞掉 → 白走降级链。
    # 收窄后：OSError 静默、RuntimeError 必须打印 ⚠️ 到 stderr。
    import io
    import contextlib

    _orig_ts = em_core.ts_call
    try:
        def _boom(*a, **k):
            raise RuntimeError("tushare token 未配置（mock）")

        em_core.ts_call = _boom
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
        em_core.ts_call = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("mock 断网"))
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            assert em.fetch_audit("600989") is None
        assert "⚠️" not in buf.getvalue(), "网络层错误不应告警（静默走降级）"
    finally:
        em_core.ts_call = _orig_ts
    print("6. token 缺失硬告警 通过")



def test_07_disk_cache():
    """7. 磁盘缓存（无网络，mock urlopen + 临时目录）"""
    import json as _json
    import tempfile as _tmp

    _orig_dir, _orig_no = em_core._CACHE_DIR, em_core._NO_CACHE
    em_core._CACHE_DIR = _tmp.mkdtemp()
    em_core._NO_CACHE = False


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
    _orig_open = em_core.urllib.request.urlopen
    em_core.urllib.request.urlopen = lambda *a, **k: (_net.__setitem__("n", _net["n"] + 1),
                                                 _Resp({"code": 0, "data": {"fields": ["a"],
                                                                            "items": [[1]]}}))[1]
    try:
        params = {"ts_code": "600989.SH", "start_date": "20200101"}
        em_core._TS_CACHE.clear()
        r1 = em_core.ts_call("daily_basic", params)
        em_core._TS_CACHE.clear()  # 清进程缓存：第二发必须命中磁盘
        r2 = em_core.ts_call("daily_basic", params)
        assert r1 == r2 == [{"a": 1}]
        assert _net["n"] == 1, f"磁盘缓存应省去第二次网络请求，实际 {_net['n']} 次"

        # TTL 过期（行情档 2h）→ 重新请求
        f = os.listdir(em_core._CACHE_DIR)[0]
        stale = os.path.join(em_core._CACHE_DIR, f)
        old = time.time() - 3 * 3600
        os.utime(stale, (old, old))
        em_core._TS_CACHE.clear()
        em_core.ts_call("daily_basic", params)
        assert _net["n"] == 2, "过期缓存应重新取数"

        # EM_FETCH_NO_CACHE 旁路：新鲜缓存也不读
        em_core._NO_CACHE = True
        em_core._TS_CACHE.clear()
        em_core.ts_call("daily_basic", params)
        assert _net["n"] == 3, "NO_CACHE 旁路必须强制走网络"
    finally:
        em_core.urllib.request.urlopen = _orig_open
        em_core._CACHE_DIR, em_core._NO_CACHE = _orig_dir, _orig_no
        em_core._TS_CACHE.clear()
    print("7. 磁盘缓存（命中 / TTL 过期重取 / NO_CACHE 旁路）通过")



def test_08_mainbz_gross_profit():
    """8. E6 毛利额回填 + 维度合计行剔除（无网络，mock ts_call）"""
    # v4.8：fetch_mainop 各分部带 GROSS_PROFIT——tushare 取 bz_profit，缺则 收入−成本。
    # v4.10.3：fina_mainbz 额外返回的维度合计行（bz_item="产品"）必须剔除，且分母取该合计行金额
    # （=营业收入）——计入分母致占比腰斩（香农芯创 46.8% 实为 93.7%）；层级 payload 下用
    # sum(明细) 做分母会重复计数（东方电气 1.86x / 工商银行 3.66x 实证）。
    _orig_ts8 = em_core.ts_call
    try:
        em_core.ts_call = lambda api, params=None, fields="": [
            {"end_date": "20251231", "bz_item": "烯烃产品", "bz_sales": 1.5e10, "bz_cost": 9e9,
             "bz_profit": 6e9},
            {"end_date": "20251231", "bz_item": "焦化产品", "bz_sales": 5e9, "bz_cost": 4e9,
             "bz_profit": None},   # 缺 bz_profit → 应按 收入−成本 回填 1e9
            {"end_date": "20251231", "bz_item": "烯烃", "bz_sales": 1.5e10, "bz_cost": 9e9,
             "bz_profit": 6e9},   # 与第一行同收入同成本 → 同源改名残留，应去重
            {"end_date": "20251231", "bz_item": "产品", "bz_sales": 2e10, "bz_cost": 1.3e10,
             "bz_profit": None},  # 维度合计行（= 前两行之和）→ 应剔除、不入返回
        ] if api == "fina_mainbz" else []
        mo = em.fetch_mainop("600989.SH")
        assert len(mo) == 2, f"同收入同成本重复条目应去重且合计行应剔除，实际 {len(mo)} 行"
        assert all(x["ITEM_NAME"] != "产品" for x in mo), "维度合计行不得进入返回"
        assert mo[0]["GROSS_PROFIT"] == 6e9, "bz_profit 应直接透传"
        assert mo[1]["GROSS_PROFIT"] == 1e9, "缺 bz_profit 应按 收入−成本 回填"
        # 扁平 payload：合计行恰为其余行之和，占比 0.75/0.25（含合计行未剔除时 0.375/0.125）
        assert abs(mo[0]["MBI_RATIO"] - 0.75) < 1e-9, "占比=分部收入÷合计行金额"
        assert abs(mo[1]["MBI_RATIO"] - 0.25) < 1e-9

        # 层级 payload（审计 P0-1 真 bug）：父级小计行与子级明细并存时 sum(明细) ≠ 合计行——
        # 分母必须取被剔除的合计行（=营业收入），否则各占比被放大 sum(明细)/合计行 倍
        em_core.ts_call = lambda api, params=None, fields="": [
            {"end_date": "20251231", "bz_item": "能源装备制造", "bz_sales": 2e10,
             "bz_cost": 1.3e10, "bz_profit": 7e9},   # 父级小计（保留：展示层另案）
            {"end_date": "20251231", "bz_item": "烯烃产品", "bz_sales": 1.5e10,
             "bz_cost": 9e9, "bz_profit": 6e9},
            {"end_date": "20251231", "bz_item": "焦化产品", "bz_sales": 5e9,
             "bz_cost": 4e9, "bz_profit": 1e9},
            {"end_date": "20251231", "bz_item": "产品", "bz_sales": 2e10,
             "bz_cost": None, "bz_profit": None},        # 合计行=营业收入（分母）
        ] if api == "fina_mainbz" else []
        mo2 = em.fetch_mainop("600875.SH")
        assert len(mo2) == 3, f"层级 payload 应只剔合计行、保留父/子行，实际 {len(mo2)} 行"
        assert all(x["ITEM_NAME"] != "产品" for x in mo2), "维度合计行不得进入返回"
        ratios = {x["ITEM_NAME"]: x["MBI_RATIO"] for x in mo2}
        assert abs(ratios["能源装备制造"] - 1.0) < 1e-9, "父级小计÷合计行=1.0"
        assert abs(ratios["烯烃产品"] - 0.75) < 1e-9, "分母应为合计行 2e10（非 sum(明细)=4e10）"
        assert abs(ratios["焦化产品"] - 0.25) < 1e-9
    finally:
        em_core.ts_call = _orig_ts8
    print("8. E6 毛利额回填 通过")



def test_09_pe_band_timing():
    """9. PE 带 P25/P75 与时机素材（无网络，mock ts_call）"""
    _orig_ts9 = em_core.ts_call
    try:
        # 100 个交易日 pe_ttm = 1..100（单调，分位点可精确断言）
        rows_db = [{"trade_date": f"2025{(i // 28) + 1:02d}{(i % 28) + 1:02d}", "pe_ttm": float(i + 1),
                    "pb": 1.5} for i in range(100)]
        em_core.ts_call = lambda api, params=None, fields="": rows_db if api == "daily_basic" else []
        band = em.fetch_pe_pb_band("600989", years=5)
        assert band["pe_p25"] == 25.0 and band["pe_p75"] == 75.0, \
            f"P25/P75 应为 25/75，实际 {band['pe_p25']}/{band['pe_p75']}"
        assert band["pe_min"] == 1.0 and band["pe_max"] == 100.0

        # 时机素材：300 个交易日 close = 1..300（递增）→ MA60/MA120/52周高低可精确断言
        import em_market
        em_market._A_DAILY_CACHE.clear()  # 从 miss 起跑，断言不受其它用例残留影响
        _dcalls = []

        def _ts9_daily(api, params=None, fields=""):
            if api == "daily":
                _dcalls.append(params)
                return rows_d
            return []

        rows_d = [{"trade_date": f"2026{(i // 28) + 1:02d}{(i % 28) + 1:02d}", "close": float(i + 1)}
                  for i in range(300)]
        em_core.ts_call = _ts9_daily
        tm = em.fetch_timing_material("600989", False)
        assert tm["ma60"] == 270.5 and tm["ma120"] == 240.5, f"实际 {tm}"
        assert tm["high_52w"] == 300.0 and tm["low_52w"] == 51.0, "52周窗口=最后250个交易日"
        assert tm["n"] == 300
        # v4.10.3 Step 5：timing 走 _a_daily_series 后，首次 miss 回填 _A_DAILY_CACHE
        # （旧实现只读不回填），同进程二次调用命中缓存、不再发 daily
        assert len(_dcalls) == 1 and em_market._A_DAILY_CACHE.get("600989.SH") is not None
        em.fetch_timing_material("600989", False)
        assert len(_dcalls) == 1, f"二次调用应命中缓存，实际发 daily {len(_dcalls)} 次"
        # 数据不足 60 日 → None（新股不硬画）；须先清掉上面的回填才能走到该分支
        em_market._A_DAILY_CACHE.clear()
        em_core.ts_call = lambda api, params=None, fields="": rows_d[:30] if api == "daily" else []
        assert em.fetch_timing_material("600989", False) is None
    finally:
        em_core.ts_call = _orig_ts9
    print("9. PE 带 P25/P75 + 时机素材 通过")



def test_10_hk_daily_reversed():
    """9b. 港股日线倒序回归（v4.9.1 补充修订三）"""
    # tushare hk_daily 返回倒序（新→旧），_hk_daily_series 缓存前统一升序；否则 timing 的
    # MA60/52周窗口吃到最旧数据（美图 01357 实证：MA60/52周高低算在 2020 年数据上）。
    import em_market
    _orig_ts9b = em_core.ts_call
    try:
        # 300 个交易日 close=1..300 递增（日期升序时），按 tushare 真实形态倒序（新→旧）给出
        rows_hk = [{"trade_date": f"2026{(i // 28) + 1:02d}{(i % 28) + 1:02d}", "close": float(i + 1)}
                   for i in range(300)][::-1]
        em_core.ts_call = lambda api, params=None, fields="": rows_hk if api == "hk_daily" else []
        em_market._HK_DAILY_CACHE.pop("01357.HK", None)
        tm = em.fetch_timing_material("01357", True)
        assert tm["ma60"] == 270.5 and tm["ma120"] == 240.5, f"倒序未纠：实际 {tm}"
        assert tm["high_52w"] == 300.0 and tm["low_52w"] == 51.0, f"52周窗口=最新250个交易日，实际 {tm}"
        assert tm["price"] == 300.0 and tm["n"] == 300
        # 升序不破坏既有消费方：月线聚合仍取每月最后交易日收盘，输出升序
        km = em.fetch_kline_monthly("116.01357", 1, True)
        assert km[-1]["close"] == 300.0 and km[0]["date"] < km[-1]["date"], f"实际 {km[:1]}…{km[-1:]}"
        # 失败哨兵：ts_call 抛异常 → 进程内后续调用不再发网络（1次/小时限流下三连撞防护，
        # 2026-09-06 美图 01357 实测：首调限流后 E2/timing 重试全撞墙）
        calls = []
        def _boom(api, params=None, fields=""):
            calls.append(api)
            raise RuntimeError("频率超限")
        em_core.ts_call = _boom
        em_market._HK_DAILY_CACHE.pop("99999.HK", None)
        assert em.fetch_timing_material("99999", True) is None
        assert em.fetch_timing_material("99999", True) is None
        assert calls == ["hk_daily"], f"哨兵未生效：{calls}"
    finally:
        em_core.ts_call = _orig_ts9b
        em_market._HK_DAILY_CACHE.pop("01357.HK", None)
        em_market._HK_DAILY_CACHE.pop("99999.HK", None)
    print("9b. 港股日线倒序回归 + 失败哨兵 通过")



def test_11_monthly_pe_backfill():
    """10. E2 月线月末 PE(TTM) 回填（无网络，mock ts_call）"""
    # v4.8.1：fetch_kline_monthly A股 tushare 路径按月附 pe（月末交易日 pe_ttm，与 PE 带同参命中缓存）；
    # daily_basic 不可用 → 静默降级为仅 close（price_history 图自动只画股价线）
    _orig_ts10 = em_core.ts_call
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
        em_core.ts_call = _ts10
        kl = em.fetch_kline_monthly("1.600989", 1, False)
        assert [k.get("pe") for k in kl] == [15.0, 16.0, 17.0], f"月末 PE 应回填，实际 {kl}"

        def _ts10b(api, params=None, fields=""):
            if api in ("monthly", "adj_factor"):
                return {"monthly": rows_m, "adj_factor": rows_f}[api]
            raise RuntimeError("daily_basic 不可用")
        em_core.ts_call = _ts10b
        kl2 = em.fetch_kline_monthly("1.600989", 1, False)
        assert all("pe" not in k for k in kl2) and [k["close"] for k in kl2] == [10.0, 11.0, 12.0], \
            f"daily_basic 失败应静默降级为仅 close，实际 {kl2}"
    finally:
        em_core.ts_call = _orig_ts10
    print("10. E2 月线月末 PE(TTM) 回填 通过")



def test_12_fields_third_param():
    """11. fetch_pe_pb_band 的 fields 必须走第三参（v4.8.3 回归）"""
    # 实证背景：fetch_pe_pb_band 曾把 fields 塞进 params——ts_call 键归一化会剔除 params 里的
    # fields（键尾为空串），与 E2 月末 PE 回填（第三参、键尾为字段串）永远不同键，透明缓存
    # 失效→重复请求，且请求不带 fields→全字段拉 5 年 daily_basic。
    _calls11 = []
    _orig_ts11 = em_core.ts_call
    def _ts11(api, params=None, fields=""):
        _calls11.append((api, dict(params or {}), fields))
        return [{"trade_date": "20260102", "pe_ttm": 15.0, "pb": 1.2}] * 30
    em_core.ts_call = _ts11
    try:
        em.fetch_pe_pb_band("600989")
        db = [(p, f) for (a, p, f) in _calls11 if a == "daily_basic"]
        assert db, "fetch_pe_pb_band 应调用 daily_basic"
        (params11, fields11), = db
        assert "fields" not in params11, "fields 不得塞进 params（被键归一化剔除→缓存永不命中）"
        assert fields11 == "ts_code,trade_date,pe_ttm,pb", f"fields 应走第三参，实际 {fields11!r}"
    finally:
        em_core.ts_call = _orig_ts11
    print("11. fetch_pe_pb_band fields 归一化 通过")


if __name__ == "__main__":
    import traceback
    test_01_market_map()
    test_02_leap_day()
    test_03_yoy_text()
    test_04_rate_limit_hardstop()
    test_05_stale_code_guard()
    test_06_token_alarm()
    test_07_disk_cache()
    test_08_mainbz_gross_profit()
    test_09_pe_band_timing()
    test_10_hk_daily_reversed()
    test_11_monthly_pe_backfill()
    test_12_fields_third_param()
    print("全部断言通过")
