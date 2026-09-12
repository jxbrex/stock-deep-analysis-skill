#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
em_market.py — 行情 / 月K 取数族（stock-deep-analysis skill 取数分块之一，v4.10.3 自 em_data 拆分）

职责：E1 行情（tushare daily_basic 优先、东财 push2 兜底）、E2 月线（tushare 前复权 / 港股日线
聚合，东财 kline 兜底）、PE/PB 历史分位带、时机素材（MA60/MA120/52 周高低）。进程内日线序列
缓存 _HK_DAILY_CACHE/_A_DAILY_CACHE 随本块持有（E1 与 E2 共用同一次拉取）。

与其他块的边界（重要）：
- 只依赖 em_core.py，绝不 import 其他取数块（em_finance/em_owner/em_misc 同理）。
- 传输函数一律以 `_C.ts_call` / `_C.get` 模块属性形式调用（迟绑定——测试按 em_core 命名空间
  rebind 传输函数与缓存配置须即时传导）；静态 from-import 只用于无 rebind 依赖的纯工具
  （代码映射 / 格式化 / 取数窗口）与跨块共享 helper。
"""
import sys
from bisect import bisect_right
from datetime import date

import em_core as _C
from em_core import (to_ts_code, memo, _r2, _fmt_date, _daily_basic_latest, _win_days, _win_years)


_HK_DAILY_CACHE = {}
_A_DAILY_CACHE = {}  # A股日线序列缓存：fetch_quote(单日涨跌) 与 fetch_timing_material(430天MA) 共用一次拉取


def _hk_daily_series(ts_code: str, years: int = 6) -> list:
    """港股日线序列（按 trade_date 升序）。hk_daily 限流实测 1次/小时（会员级，2026-09-06 复测），单次拉全量缓存复用：
    E1 取最新价、E2 聚合月线共用同一次调用，避免同脚本内二次调用被限流。
    tushare 返回倒序（新→旧），缓存前统一升序——timing 的 MA/52 周窗口依赖尾部切片。
    失败写空哨兵：1次/小时限流下同进程重试必撞墙，消费方命中哨兵即走各自降级。"""
    def _load():
        beg, end = _win_years(years)
        try:
            rows = _C.ts_call("hk_daily", {"ts_code": ts_code, "start_date": beg, "end_date": end})
        except Exception:
            rows = []
        return sorted((r for r in rows if r.get("trade_date")), key=lambda x: x["trade_date"])
    rows = memo(_HK_DAILY_CACHE, ts_code, _load)
    if not rows:
        raise RuntimeError("hk_daily 空返回或已失败（哨兵）")
    return rows


def _a_daily_series(ts_code: str, days: int = 430) -> list:
    """A股日线序列（近 days 天）。fetch_quote 单日 pct_chg 与 fetch_timing_material 的
    MA60/MA120/52周高低都出自本序列：E1 内 quote 先于 timing 执行，由 quote 首拉、timing 复用，
    原单日+430天两次请求合一。默认字段拉取（daily 全字段含 pct_chg，不传 fields）。"""
    def _load():
        beg, end = _win_days(days)
        rows = _C.ts_call("daily", {"ts_code": ts_code, "start_date": beg, "end_date": end})
        if not rows:
            raise RuntimeError("daily 空返回")
        return rows
    return memo(_A_DAILY_CACHE, ts_code, _load)


def _em_quote(secid: str, is_hk: bool = False) -> dict:
    fields = "f43,f57,f58,f116,f162,f167,f168,f170"
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields={fields}"
    d = _C.get(url).get("data") or {}
    # 实测缩放差异：A股 价格÷100 比率÷100；港股 价格÷1000 比率÷100（f162=0 表示PE缺失非真0）
    price_div = 1000 if is_hk else 100
    ratio_div = 100
    div_p = lambda v: None if v in (None, "-") else v / price_div
    div_r = lambda v: None if v in (None, "-") else v / ratio_div
    pe = div_r(d.get("f162"))
    name = d.get("f58") or ""
    # 陈旧档拦截：已切换/退市标的东财返回零值（价格 0 + 市值 0），直接报错给可操作建议，
    # 避免零值静默流入报告（北交所旧代码 832982 实测返回「锦波生物(已切换)」全零，2026-08-30）
    if "已切换" in name or (not div_p(d.get("f43")) and not d.get("f116")):
        raise ValueError(
            f"东财行情显示 {name or secid} 已切换代码或已退市（无有效报价）："
            f"北交所旧代码（43/83/87/88 段）2025-10 起已切换 920 段新代码，请改用新代码重试；"
            f"其他情形请人工核查证券状态")
    return {
        "名称": d.get("f58"), "代码": d.get("f57"),
        "最新价": div_p(d.get("f43")), "涨跌幅%": div_r(d.get("f170")),
        "总市值亿": f"{(d.get('f116') or 0) / 1e8:,.1f}" if d.get("f116") else None,
        "PE_TTM": None if pe == 0 else pe,   # 港股 f162=0 = 缺失
        "PB": div_r(d.get("f167")),
        "换手率%": div_r(d.get("f168")),
    }


def fetch_pe_pb_band(code: str, years: int = 5) -> dict:
    """A股 PE(TTM)/PB 历史分位（tushare daily_basic）。失败返回 None。"""
    try:
        beg, end = _win_years(years)
        # fields 必须走第三参（塞 params 会被键归一化剔除→缓存键与 E2 月末PE回填不一致、
        # 且请求全字段拉 5 年，v4.8.3 修复实证）
        rows = _C.ts_call("daily_basic", {"ts_code": to_ts_code(code),
                                       "start_date": beg, "end_date": end},
                       fields="ts_code,trade_date,pe_ttm,pb")
        if not rows:
            raise RuntimeError("daily_basic 空返回")
        # 行按日期倒序只排一次：pe/pb 派生与 latest 扫描共用 rows_desc（原三处遍历各自 sorted）；
        # pe/pb 的数值升序为分位/bisect 所必需，与日期序无法合并
        rows_desc = sorted(rows, key=lambda x: x.get("trade_date") or "", reverse=True)
        pes = sorted(float(r["pe_ttm"]) for r in rows_desc
                     if r.get("pe_ttm") is not None and float(r["pe_ttm"]) > 0)
        pbs = sorted(float(r["pb"]) for r in rows_desc
                     if r.get("pb") is not None and float(r["pb"]) > 0)
        if len(pes) < 20:
            raise RuntimeError(f"daily_basic 有效样本不足({len(pes)})")
        latest_pe, latest_pb = None, None
        for r in rows_desc:  # 已按日期倒序，最先遇见的有效值即最新
            if latest_pe is None and r.get("pe_ttm") and float(r["pe_ttm"]) > 0:
                latest_pe = float(r["pe_ttm"])
            if latest_pb is None and r.get("pb") and float(r["pb"]) > 0:
                latest_pb = float(r["pb"])
            if latest_pe and latest_pb:
                break
        def pctile(vals, cur):
            if cur is None:
                return None
            return round(bisect_right(vals, cur) / len(vals) * 100)
        # 分位点（v4.8：供 pe_history 图 P25-P75 分位区；索引取 (n-1)*q 整部位）
        n = len(pes)
        pe_p25, pe_p75 = pes[int((n - 1) * 0.25)], pes[int((n - 1) * 0.75)]
        return {"n": n, "years": years,
                "pe_min": pes[0], "pe_max": pes[-1], "pe_cur": latest_pe, "pe_pct": pctile(pes, latest_pe),
                "pe_p25": pe_p25, "pe_p75": pe_p75,
                "pb_min": pbs[0], "pb_max": pbs[-1], "pb_cur": latest_pb, "pb_pct": pctile(pbs, latest_pb)}
    except Exception:
        return None


def fetch_quote(secid: str, is_hk: bool = False) -> dict:
    """E1 行情。tushare 优先（PE 为标准 TTM 口径，东财 f162 动态口径失真问题规避），东财兜底。"""
    code = secid.split(".")[-1]
    if is_hk:
        # tushare 港股只有价格（hk_daily 无估值字段）：价格取缓存序列最新值，市值/PB/换手取东财
        price, chg, td = None, None, None
        try:
            rows = _hk_daily_series(f"{code}.HK")
            r = max(rows, key=lambda x: x.get("trade_date") or "")
            price, chg = r.get("close"), r.get("pct_chg")
            td = r.get("trade_date")
        except Exception:
            pass
        try:
            base = _em_quote(secid, True)
        except Exception:
            base = {"名称": code, "代码": code, "最新价": None, "涨跌幅%": None,
                    "总市值亿": None, "PE_TTM": None, "PB": None, "换手率%": None}
        return {"名称": base.get("名称") or code, "代码": code,
                "最新价": price if price is not None else base.get("最新价"),
                "涨跌幅%": chg if chg is not None else base.get("涨跌幅%"),
                "总市值亿": base.get("总市值亿"), "PE_TTM": base.get("PE_TTM"),
                "PB": base.get("PB"), "换手率%": base.get("换手率%"),
                "数据日期": td or "东财实时"}
    try:
        ts = to_ts_code(code)
        r = _daily_basic_latest(code)
        name = code
        try:
            sb = _C.ts_call("stock_basic", {"ts_code": ts, "fields": "ts_code,name"})
            if sb:
                name = sb[0].get("name") or code
        except Exception:
            pass
        chg = None
        try:
            # 单日 pct_chg 取自 430 天日线序列缓存（fetch_timing_material 同源），
            # 免单独发单日 daily 请求（同一 E1 段内 quote→timing 先后触发，两请求合一）
            row = {x.get("trade_date"): x for x in _a_daily_series(ts)}.get(r["trade_date"]) or {}
            chg = row.get("pct_chg")
        except Exception:
            pass
        return {"名称": name, "代码": code, "最新价": r.get("close"), "涨跌幅%": _r2(chg),
                "总市值亿": (f"{(r.get('total_mv') or 0) / 1e4:,.1f}" if r.get("total_mv") else None),  # 万元→亿
                "PE_TTM": _r2(r.get("pe_ttm")), "PB": _r2(r.get("pb")),
                "换手率%": _r2(r.get("turnover_rate")), "数据日期": r.get("trade_date")}
    except Exception:
        return _em_quote(secid, False)


# ---------------- E2 月线 ----------------
def _em_kline_url(secid: str, klt: int, beg: str, end: str) -> str:
    """push2his K线 URL 拼装（klt=周期：101 日 / 103 月；fqt=1 前复权）——
    _em_kline_monthly 与 score_calibration._em_kline_daily 共用，口径唯一。"""
    return (f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}"
            f"&fields1=f1,f2,f3&fields2=f51,f53&klt={klt}&fqt=1&beg={beg}&end={end}")


def _em_kline_monthly(secid: str, years: int, is_hk: bool = False) -> list:
    beg, end = _win_years(years, "20991231")
    url = _em_kline_url(secid, 103, beg, end)
    d = _C.get(url).get("data") or {}
    out = []
    # 换算差异（实测）：A股K线 ×100（2331=23.31）；港股K线为真实价（53.600），无需换算
    div = 1 if is_hk else 100
    for k in (d.get("klines") or []):
        p = k.split(",")
        out.append({"date": p[0], "close": float(p[1]) / div})
    # 缩放校准：push2his 返回缩放行为不稳定（两次实测：×100 与原始价都出现过），
    # 用 E1 最新价反推——偏差>50% 且 ×100 后吻合则补救
    try:
        ref = fetch_quote(secid, is_hk).get("最新价")
        if ref and out:
            latest = out[-1]["close"]
            if latest and abs(latest - ref) / ref > 0.5 and abs(latest * 100 - ref) / ref < 0.2:
                out = [{**k, "close": round(k["close"] * 100, 2)} for k in out]
    except Exception:
        pass
    return out


def fetch_kline_monthly(secid: str, years: int, is_hk: bool = False) -> list:
    """E2 月线（前复权）。tushare 优先（monthly+adj_factor 复权；港股 hk_daily 聚合），东财兜底。"""
    code = secid.split(".")[-1]
    try:
        ts = to_ts_code(code)
        beg, end = _win_years(years)
        if is_hk:
            # 港股无月线接口：缓存日线按 YYYYMM 聚合（取每月最后交易日收盘），港股不做复权
            rows = _hk_daily_series(ts)
            cutoff = f"{date.today().year - years}01"
            last_of_month = {}
            for r in rows:
                if r["trade_date"][:6] >= cutoff:
                    last_of_month[r["trade_date"][:6]] = r  # 同月后写覆盖先写
            if not last_of_month:
                raise RuntimeError("hk_daily 聚合为空")
            out = [{"date": _fmt_date(r["trade_date"]), "close": round(float(r["close"]), 3)}
                   for _, r in sorted(last_of_month.items())]
            return out
        rows = _C.ts_call("monthly", {"ts_code": ts, "start_date": beg, "end_date": end})
        if not rows:
            raise RuntimeError("monthly 空返回")
        fac = _C.ts_call("adj_factor", {"ts_code": ts, "start_date": beg, "end_date": end})
        if not fac:
            raise RuntimeError("adj_factor 空返回，无法前复权，兜底东财")
        fmap = {f["trade_date"]: float(f["adj_factor"]) for f in fac if f.get("adj_factor")}
        latest_f = fmap[max(fmap)]
        out = []
        for r in sorted(rows, key=lambda x: x["trade_date"]):
            c = float(r["close"])
            f = fmap.get(r["trade_date"])
            if f and latest_f:
                c = c * f / latest_f   # 前复权
            out.append({"date": _fmt_date(r["trade_date"]), "close": round(c, 2)})
        # v4.8.1：月度 PE(TTM) 回填（供 price_history 图，替代模型手工「月收×总股本÷TTM净利」）。
        # 与 fetch_pe_pb_band 同参同字段（kline-years=5 时窗口亦同），命中透明缓存不增发请求；
        # 失败静默跳过（仅 close，图降级单线）
        try:
            pe_map = {r["trade_date"]: float(r["pe_ttm"])
                      for r in _C.ts_call("daily_basic", {"ts_code": ts, "start_date": beg, "end_date": end},
                                       fields="ts_code,trade_date,pe_ttm,pb")
                      if r.get("trade_date") and r.get("pe_ttm") and float(r["pe_ttm"]) > 0}
            for k, r in zip(out, sorted(rows, key=lambda x: x["trade_date"])):
                pe = pe_map.get(r["trade_date"])
                if pe:
                    k["pe"] = round(pe, 1)
        except Exception:
            pass
        return out
    except Exception:
        return _em_kline_monthly(secid, years, is_hk)


def fetch_timing_material(code: str, is_hk: bool = False):
    """时机分素材（v4.8，技术面六信号数据源唯一化——神华事故里假 MA60/假月线的产生环节
    正是「模型手拼」，与 quote 防伪同源）：现价/MA60/MA120/52 周高低，全部出自日线序列
    （A股 tushare daily 近 430 天；港股复用 hk_daily 缓存）。失败返回 None。"""
    try:
        if is_hk:
            rows = _hk_daily_series(f"{code}.HK")
            closes = [float(r["close"]) for r in rows
                      if r.get("close") is not None and r.get("trade_date")]
        else:
            # 与 fetch_quote 同源，统一走 _a_daily_series（v4.10.3 Step 5）：命中即省一发，
            # miss 则现拉并回填 _A_DAILY_CACHE——同进程再读不再重拉（旧实现只读不回填）
            rows = _a_daily_series(to_ts_code(code), 430)
            rows = sorted((r for r in rows if r.get("trade_date") and r.get("close") is not None),
                          key=lambda x: x["trade_date"])
            closes = [float(r["close"]) for r in rows]
        if len(closes) < 60:
            return None

        def _ma(n):
            return round(sum(closes[-n:]) / n, 2) if len(closes) >= n else None
        win = closes[-250:]  # 52 周 ≈ 250 个交易日
        return {"price": round(closes[-1], 2), "ma60": _ma(60), "ma120": _ma(120),
                "high_52w": round(max(win), 2), "low_52w": round(min(win), 2),
                "n": len(closes)}
    except Exception as e:
        print(f"⚠️ fetch_timing_material({code}): {e}", file=sys.stderr)
        return None
