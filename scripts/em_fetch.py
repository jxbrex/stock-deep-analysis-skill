#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
em_fetch.py — 批量取数脚本（stock-deep-analysis skill 专用）

数据源优先级：tushare（官方API，口径规范，会员限流保护）优先，东方财富公开接口兜底。
tushare token 自动发现：环境变量 TUSHARE_TOKEN > ZCode config.json 的 mcp.servers.tushare.url。
tushare 不可用时自动回落东财野生端点（curl 传输，防 TLS 指纹限流）。

用法:
    python em_fetch.py 600989                    # 目标公司全量取数
    python em_fetch.py 600989 --peers=600309,002001   # 目标 + 可比公司
    python em_fetch.py 600989 --kline-years=5    # 月K线回溯年数（默认5）
    python em_fetch.py 600989 --search="收购,减持,新华三"  # E7 定性站内搜索（可多关键词，逗号分隔）

输出: 紧凑 Markdown 摘要到 stdout（约 2KB），原始 JSON 不落盘不进上下文。
覆盖: E1 行情估值 / E2 月线 / E3 F10 主要指标 / E4 股东户数 / E5 一致预期 / E6 主营构成
      / 盈利质量红旗（审计意见 tushare fina_audit 自动填）
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.parse
from datetime import date

UA = {"User-Agent": "Mozilla/5.0"}
CURL_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
TIMEOUT = 15
TS_API = "https://api.tushare.pro"


def secid_of(code: str):
    """返回 (secid, secucode, is_hk)。港股：5位数字（如 06082/01880）→ 116. 前缀"""
    code = code.strip().upper().replace(".SH", "").replace(".SZ", "").replace(".BJ", "").replace(".HK", "")
    if code.startswith(("60", "68")):
        return f"1.{code}", f"{code}.SH", False
    if code.isdigit() and len(code) == 5:
        return f"116.{code}", f"{code}.HK", True
    return f"0.{code}", f"{code}.SZ", False


def to_ts_code(code: str) -> str:
    """tushare 代码：600989→600989.SH，000528→000528.SZ，06082→06082.HK"""
    code = code.strip().upper()
    if "." in code:
        return code
    if code.isdigit() and len(code) == 5:
        return code + ".HK"
    if code.startswith(("60", "68", "9")):
        return code + ".SH"
    if code.startswith(("43", "83", "87", "88", "92")):
        return code + ".BJ"
    return code + ".SZ"


# ---------------- tushare 传输层 ----------------

def _tushare_token():
    """token 自动发现：环境变量 TUSHARE_TOKEN 优先，其次 ZCode MCP 配置（不落盘不打印）。"""
    tok = os.environ.get("TUSHARE_TOKEN")
    if tok:
        return tok.strip()
    cfg = os.path.expanduser(os.path.join("~", ".zcode", "cli", "config.json"))
    try:
        with open(cfg, encoding="utf-8") as f:
            url = json.load(f)["mcp"]["servers"]["tushare"]["url"]
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        tok = (qs.get("token") or [None])[0]
        return tok.strip() if tok else None
    except Exception:
        return None


def ts_call(api_name: str, params: dict = None, fields: str = "") -> list:
    """tushare HTTP API。返回 list[dict]（fields↔items 对齐）。失败抛异常由调用方兜底。"""
    tok = _tushare_token()
    if not tok:
        raise RuntimeError("tushare token 未配置（TUSHARE_TOKEN 环境变量或 ZCode mcp 配置）")
    payload = {"api_name": api_name, "token": tok, "params": params or {}, "fields": fields}
    req = urllib.request.Request(
        TS_API, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **UA}, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        d = json.loads(r.read().decode("utf-8"))
    if d.get("code") != 0:
        raise RuntimeError(f"tushare {api_name}: {d.get('msg')}")
    data = d.get("data") or {}
    flds = data.get("fields") or []
    return [dict(zip(flds, row)) for row in (data.get("items") or [])]


# ---------------- 东财传输层（兜底） ----------------

def _get_via_curl(url: str) -> bytes:
    """curl 传输：push2 域对 Python urllib 的 TLS 指纹间歇限流，curl 不受限（实测验证）。"""
    r = subprocess.run(
        ["curl", "-s", "--max-time", str(TIMEOUT), "-H", f"User-Agent: {CURL_UA}", url],
        capture_output=True, timeout=TIMEOUT + 5,
    )
    if r.returncode != 0 or not r.stdout:
        raise ConnectionError(f"curl rc={r.returncode} {r.stderr[:100]!r}")
    return r.stdout


def _get_via_urllib(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def get(url: str, retries: int = 2) -> dict:
    """curl 优先、urllib 兜底、失败重试。返回解析后的 JSON dict。"""
    last_err = None
    for attempt in range(retries + 1):
        for transport in (_get_via_curl, _get_via_urllib):
            try:
                raw = transport(url)
                return json.loads(raw.decode("utf-8"))
            except Exception as e:
                last_err = e
        if attempt < retries:
            time.sleep(1.5)
    raise last_err


def yi(x, digits=1):
    """元 -> 亿（≥1000 带千位符）"""
    if x is None:
        return "—"
    try:
        return f"{float(x) / 1e8:,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _r2(x):
    """两位小数格式化（None 安全），用于 PE/PB/换手率等比率"""
    return round(x, 2) if isinstance(x, (int, float)) else None


def pct(x, digits=1):
    if x is None:
        return "—"
    try:
        return f"{float(x):.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_date(yyyymmdd: str) -> str:
    """YYYYMMDD -> YYYY-MM-DD"""
    s = str(yyyymmdd or "")
    return f"{s[:4]}-{s[4:6]}-{s[6:]}" if len(s) == 8 else s


# ---------------- E1 行情估值 ----------------

_HK_DAILY_CACHE = {}


def _hk_daily_series(ts_code: str, years: int = 6) -> list:
    """港股日线序列。hk_daily 限流实测 1次/分钟（会员级），单次拉全量缓存复用：
    E1 取最新价、E2 聚合月线共用同一次调用，避免同脚本内二次调用被限流。"""
    if ts_code not in _HK_DAILY_CACHE:
        end = date.today().strftime("%Y%m%d")
        beg = f"{date.today().year - years}0101"
        rows = ts_call("hk_daily", {"ts_code": ts_code, "start_date": beg, "end_date": end})
        if not rows:
            raise RuntimeError("hk_daily 空返回")
        _HK_DAILY_CACHE[ts_code] = rows
    return _HK_DAILY_CACHE[ts_code]


def _em_quote(secid: str, is_hk: bool = False) -> dict:
    fields = "f43,f44,f45,f46,f57,f58,f60,f116,f117,f162,f167,f168,f169,f170"
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields={fields}"
    d = get(url).get("data") or {}
    # 实测缩放差异：A股 价格÷100 比率÷100；港股 价格÷1000 比率÷100（f162=0 表示PE缺失非真0）
    price_div = 1000 if is_hk else 100
    ratio_div = 100
    div_p = lambda v: None if v in (None, "-") else v / price_div
    div_r = lambda v: None if v in (None, "-") else v / ratio_div
    pe = div_r(d.get("f162"))
    return {
        "名称": d.get("f58"), "代码": d.get("f57"),
        "最新价": div_p(d.get("f43")), "涨跌幅%": div_r(d.get("f170")),
        "总市值亿": f"{(d.get('f116') or 0) / 1e8:,.1f}" if d.get("f116") else None,
        "PE_TTM": None if pe == 0 else pe,   # 港股 f162=0 = 缺失
        "PB": div_r(d.get("f167")),
        "换手率%": div_r(d.get("f168")),
    }


# ---------------- A 级增强：PE/PB 分位 / 业绩预告快报 / 治理包 / 披露日期 ----------------

def fetch_pe_pb_band(code: str, years: int = 5) -> dict:
    """A股 PE(TTM)/PB 历史分位（tushare daily_basic）。失败返回 None。"""
    try:
        end = date.today().strftime("%Y%m%d")
        beg = f"{date.today().year - years}0101"
        rows = ts_call("daily_basic", {"ts_code": to_ts_code(code),
                                       "start_date": beg, "end_date": end,
                                       "fields": "ts_code,trade_date,pe_ttm,pb"})
        if not rows:
            raise RuntimeError("daily_basic 空返回")
        pes = sorted(float(r["pe_ttm"]) for r in rows
                     if r.get("pe_ttm") is not None and float(r["pe_ttm"]) > 0)
        pbs = sorted(float(r["pb"]) for r in rows
                     if r.get("pb") is not None and float(r["pb"]) > 0)
        if len(pes) < 20:
            raise RuntimeError(f"daily_basic 有效样本不足({len(pes)})")
        latest_pe, latest_pb = None, None
        for r in sorted(rows, key=lambda x: x.get("trade_date") or "", reverse=True):
            if latest_pe is None and r.get("pe_ttm") and float(r["pe_ttm"]) > 0:
                latest_pe = float(r["pe_ttm"])
            if latest_pb is None and r.get("pb") and float(r["pb"]) > 0:
                latest_pb = float(r["pb"])
            if latest_pe and latest_pb:
                break
        def pctile(vals, cur):
            if cur is None:
                return None
            return round(sum(1 for v in vals if v <= cur) / len(vals) * 100)
        return {"n": len(pes), "years": years,
                "pe_min": pes[0], "pe_max": pes[-1], "pe_cur": latest_pe, "pe_pct": pctile(pes, latest_pe),
                "pb_min": pbs[0], "pb_max": pbs[-1], "pb_cur": latest_pb, "pb_pct": pctile(pbs, latest_pb)}
    except Exception:
        return None


def fetch_forecast_express(code: str) -> list:
    """业绩预告 + 业绩快报（tushare forecast/express，按报告期合并去重，新→旧最多4条）。"""
    try:
        out = []
        for r in ts_call("forecast", {"ts_code": to_ts_code(code)}):
            lo, hi = r.get("net_profit_min"), r.get("net_profit_max")
            rng = (f"{float(lo)/1e4:,.1f}~{float(hi)/1e4:,.1f}亿"  # forecast 净利单位：万元→亿
                   if lo is not None and hi is not None else None)
            chg = (f"{r['p_change_min']:.0f}%~{r['p_change_max']:.0f}%"
                   if r.get("p_change_min") is not None and r.get("p_change_max") is not None else None)
            # 摘要清洗：剥离数字句子（净利区间已单独列示），只留原因短语；无原因则用 change_reason
            raw = (r.get("summary") or "").replace("\n", " ")
            reason = (r.get("change_reason") or "").strip()
            if reason:
                summ = reason[:50]
            else:
                summ = ""  # 净利区间已列示，不再重复原文长句
            out.append({"类型": "预告", "报告期": r.get("end_date"), "披露": r.get("ann_date"),
                        "预告类型": r.get("type"), "净利区间": rng, "变动幅度": chg,
                        "摘要": summ})
        for r in ts_call("express", {"ts_code": to_ts_code(code)}):
            out.append({"类型": "快报", "报告期": r.get("end_date"), "披露": r.get("ann_date"),
                        "净利": yi(r.get("n_income")), "同比": pct(r.get("yoy_net_profit")),
                        "营收": yi(r.get("revenue"))})
        # 按报告期新→旧，同报告期快报优先（快报晚于预告、数据更实）
        out.sort(key=lambda x: (x.get("报告期") or "", 1 if x["类型"] == "快报" else 0), reverse=True)
        dedup = {}
        for r in out:
            dedup.setdefault(r.get("报告期"), r)
        return [dedup[k] for k in sorted(dedup, reverse=True)][:4]
    except Exception:
        return []


def fetch_governance(code: str) -> dict:
    """1E 治理包（tushare）：质押统计 / 增减持 / 回购。各项独立失败返回空，不影响其他项。"""
    ts = to_ts_code(code)
    g = {"pledge": None, "trades": [], "buyback": []}
    try:
        rows = ts_call("pledge_stat", {"ts_code": ts})
        if rows:
            r = max(rows, key=lambda x: x.get("end_date") or "")
            g["pledge"] = {"日期": r.get("end_date"), "质押比例%": r.get("pledge_ratio")}
    except Exception:
        pass
    try:
        rows = ts_call("stk_holdertrade", {"ts_code": ts})
        rows = [r for r in rows if r.get("ann_date")]
        rows.sort(key=lambda x: x.get("ann_date") or "", reverse=True)
        for r in rows[:6]:
            g["trades"].append({"披露": r.get("ann_date"), "股东": (r.get("holder_name") or "")[:12],
                                "方向": "增持" if r.get("in_de") == "IN" else "减持",
                                "数量万股": r.get("change_vol")})
    except Exception:
        pass
    try:
        rows = ts_call("repurchase", {"ts_code": ts})
        rows = [r for r in rows if r.get("ann_date")]
        rows.sort(key=lambda x: x.get("ann_date") or "", reverse=True)
        for r in rows[:3]:
            g["buyback"].append({"披露": r.get("ann_date"), "金额": yi(r.get("amount")) + "亿"
                                 if r.get("amount") else None, "进度": r.get("proc")})
    except Exception:
        pass
    return g


def fetch_disclosure(code: str) -> dict:
    """下一次财报披露计划（tushare disclosure_date）。失败返回 None。"""
    try:
        rows = ts_call("disclosure_date", {"ts_code": to_ts_code(code)})
        rows = [r for r in rows if r.get("end_date")]
        rows.sort(key=lambda x: x.get("end_date") or "", reverse=True)
        today = date.today().strftime("%Y%m%d")
        for r in rows:
            # 找尚未实际披露、且有计划日期的最近报告期
            if not r.get("actual_date") and r.get("pre_date"):
                return {"报告期": r.get("end_date"), "计划披露": r.get("pre_date")}
        # 全部已披露 → 返回最近一条实际披露供参考
        if rows:
            r = rows[0]
            return {"报告期": r.get("end_date"), "计划披露": r.get("pre_date"),
                    "实际披露": r.get("actual_date")}
    except Exception:
        pass
    return None


def fetch_quote(secid: str, is_hk: bool = False) -> dict:
    """E1 行情。tushare 优先（PE 为标准 TTM 口径，东财 f162 动态口径失真问题规避），东财兜底。"""
    code = secid.split(".")[-1]
    if is_hk:
        # tushare 港股只有价格（hk_daily 无估值字段）：价格取缓存序列最新值，市值/PB/换手取东财
        price, chg = None, None
        try:
            rows = _hk_daily_series(f"{code}.HK")
            r = max(rows, key=lambda x: x.get("trade_date") or "")
            price, chg = r.get("close"), r.get("pct_chg")
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
                "PB": base.get("PB"), "换手率%": base.get("换手率%")}
    try:
        ts = to_ts_code(code)
        db = ts_call("daily_basic", {"ts_code": ts})
        if not db:
            raise RuntimeError("daily_basic 空返回")
        r = max(db, key=lambda x: x.get("trade_date") or "")
        name = code
        try:
            sb = ts_call("stock_basic", {"ts_code": ts, "fields": "ts_code,name"})
            if sb:
                name = sb[0].get("name") or code
        except Exception:
            pass
        chg = None
        try:
            dy = ts_call("daily", {"ts_code": ts, "start_date": r["trade_date"],
                                   "end_date": r["trade_date"]})
            if dy:
                chg = dy[0].get("pct_chg")
        except Exception:
            pass
        return {"名称": name, "代码": code, "最新价": r.get("close"), "涨跌幅%": _r2(chg),
                "总市值亿": (f"{(r.get('total_mv') or 0) / 1e4:,.1f}" if r.get("total_mv") else None),  # 万元→亿
                "PE_TTM": _r2(r.get("pe_ttm")), "PB": _r2(r.get("pb")),
                "换手率%": _r2(r.get("turnover_rate"))}
    except Exception:
        return _em_quote(secid, False)


# ---------------- E2 月线 ----------------

def _em_kline_monthly(secid: str, years: int, is_hk: bool = False) -> list:
    end = "20991231"
    beg = f"{int(__import__('datetime').date.today().year) - years}0101"
    url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}"
           f"&fields1=f1,f2,f3&fields2=f51,f53&klt=103&fqt=1&beg={beg}&end={end}")
    d = get(url).get("data") or {}
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
        end = date.today().strftime("%Y%m%d")
        beg = f"{date.today().year - years}0101"
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
        rows = ts_call("monthly", {"ts_code": ts, "start_date": beg, "end_date": end})
        if not rows:
            raise RuntimeError("monthly 空返回")
        fac = ts_call("adj_factor", {"ts_code": ts, "start_date": beg, "end_date": end})
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
        return out
    except Exception:
        return _em_kline_monthly(secid, years, is_hk)


# ---------------- E3 财务（年报序列） ----------------

def _em_f10(secucode: str, size: int = 12, annual_only: bool = False) -> list:
    if annual_only:
        flt = urllib.parse.quote(f'(SECUCODE="{secucode}")(REPORT_TYPE="年报")', safe="()")
    else:
        flt = urllib.parse.quote(f'(SECUCODE="{secucode}")', safe="()")
    url = (f"https://datacenter.eastmoney.com/securities/api/data/v1/get"
           f"?reportName=RPT_F10_FINANCE_MAINFINADATA&columns=ALL&filter={flt}"
           f"&pageNumber=1&pageSize={size}&sortTypes=-1&sortColumns=REPORT_DATE")
    return (get(url).get("result") or {}).get("data") or []


def _pick_latest_per_period(rows: list) -> list:
    """同一报告期多次公告时取第一条（tushare 按公告日倒序返回），按报告期倒序。"""
    seen = {}
    for r in sorted(rows, key=lambda x: (x.get("end_date") or "", x.get("ann_date") or ""), reverse=True):
        seen.setdefault(r.get("end_date"), r)
    return [seen[k] for k in sorted(seen, reverse=True)]


def _ts_annual_rows(code: str, n_years: int = 5) -> list:
    """A股年报主要指标（新→旧），映射为东财 F10 同构键名，供年表与红旗共用。"""
    ts = to_ts_code(code)
    y0 = date.today().year - n_years - 1
    rng = {"start_date": f"{y0}0101", "end_date": date.today().strftime("%Y%m%d")}
    inc = [r for r in ts_call("income", {"ts_code": ts, **rng})
           if (r.get("end_date") or "").endswith("1231") and str(r.get("report_type")) == "1"]
    ind = [r for r in ts_call("fina_indicator", {"ts_code": ts, **rng,
                              "fields": "ts_code,end_date,roe,grossprofit_margin,netprofit_margin,"
                                        "debt_to_assets,ar_turn,turn_days"})
           if (r.get("end_date") or "").endswith("1231")]
    cf = [r for r in ts_call("cashflow", {"ts_code": ts, **rng})
          if (r.get("end_date") or "").endswith("1231")]
    if not inc:
        raise RuntimeError("tushare income 无年报数据")
    ind_map = {r["end_date"]: r for r in ind}
    cf_map = {r["end_date"]: r for r in cf}
    rows = []
    for r in _pick_latest_per_period(inc)[:n_years]:
        ed = r["end_date"]
        f = ind_map.get(ed) or {}
        c = cf_map.get(ed) or {}
        ocf = c.get("n_cashflow_act")
        ni = r.get("n_income")  # 净利润（含少数股东），与东财现金含量口径一致
        # 周转天数换算：fina_indicator 只给周转率——应收天数=360/ar_turn；
        # 存货天数=turn_days(营业周期)−应收天数（营业周期=存货+应收周转天数）
        ar_days = (360 / f["ar_turn"]) if f.get("ar_turn") else None
        inv_days = (f["turn_days"] - ar_days) if (f.get("turn_days") is not None
                                                  and ar_days is not None) else None
        rows.append({
            "REPORT_DATE_NAME": f"{ed[:4]}年报",
            "TOTALOPERATEREVE": r.get("total_revenue"),
            "PARENTNETPROFIT": r.get("n_income_attr_p"),
            "PARENTNETPROFITTZ": None,  # 同比在 summarize 外另算（需相邻期，见下）
            "ROEJQ": f.get("roe"),
            "XSMLL": f.get("grossprofit_margin"),
            "XSJLL": f.get("netprofit_margin"),
            "ZCFZL": f.get("debt_to_assets"),
            "NETCASH_OPERATE_PK": ocf,
            "NCO_NETPROFIT": (ocf / ni if (ocf is not None and ni) else None),
            "YSZKZZTS": ar_days,
            "CHZZTS": inv_days,
        })
    # 归母净利同比：与上一年比
    by_ed = {r["REPORT_DATE_NAME"][:4]: r for r in rows}
    for r in rows:
        prev = by_ed.get(str(int(r["REPORT_DATE_NAME"][:4]) - 1))
        cur, pre = r.get("PARENTNETPROFIT"), (prev or {}).get("PARENTNETPROFIT")
        if cur is not None and pre:
            r["PARENTNETPROFITTZ"] = (cur / pre - 1) * 100
    return rows


def _ts_latest_quarter(code: str) -> dict:
    """A股最新报告期摘要（东财键名同构）：净利/同比/总股本/ROIC。"""
    ts = to_ts_code(code)
    y0 = date.today().year - 2
    rng = {"start_date": f"{y0}0101", "end_date": date.today().strftime("%Y%m%d")}
    inc = [r for r in ts_call("income", {"ts_code": ts, **rng})
           if str(r.get("report_type")) == "1"]
    if not inc:
        return {}
    inc = _pick_latest_per_period(inc)
    cur = inc[0]
    yoy = None
    for r in inc[1:]:
        # 找去年同期（end_date 月日相同、年份-1）
        if (r.get("end_date") or "")[4:] == (cur.get("end_date") or "")[4:]:
            pre = r.get("n_income_attr_p")
            if pre:
                yoy = (cur["n_income_attr_p"] / pre - 1) * 100
            break
    roic = None
    try:
        ind = ts_call("fina_indicator", {"ts_code": ts, "period": cur["end_date"]})
        if ind:
            roic = ind[0].get("roic")
    except Exception:
        pass
    total_share = None
    try:
        db = ts_call("daily_basic", {"ts_code": ts, "fields": "ts_code,trade_date,total_share"})
        if db:
            total_share = max(db, key=lambda x: x.get("trade_date") or "").get("total_share")
            total_share = total_share * 1e4 if total_share else None  # 万股→股
    except Exception:
        pass
    ed = cur.get("end_date") or ""
    qname = {"0331": "一季", "0630": "中报", "0930": "三季", "1231": "年报"}.get(ed[4:], ed)
    return {"REPORT_DATE_NAME": f"{ed[:4]}{qname}",
            "PARENTNETPROFIT": cur.get("n_income_attr_p"),
            "PARENTNETPROFITTZ": yoy,
            "TOTAL_SHARE": total_share,
            "ROIC": roic}


def _ts_hk_annual_rows(code: str, n_years: int = 4) -> list:
    """港股年报主要指标（新→旧）。tushare hk_income/hk_fina_indicator，字段缺失显示 —。"""
    ts = to_ts_code(code)
    y0 = date.today().year - n_years - 1
    rng = {"start_date": f"{y0}0101", "end_date": date.today().strftime("%Y%m%d")}
    inc = [r for r in ts_call("hk_income", {"ts_code": ts, **rng})
           if (r.get("end_date") or "").endswith("1231")]
    if not inc:
        raise RuntimeError("tushare hk_income 无年报数据")
    try:
        ind = {r["end_date"]: r for r in ts_call("hk_fina_indicator", {"ts_code": ts, **rng})
               if (r.get("end_date") or "").endswith("1231")}
    except Exception:
        ind = {}
    rows = []
    for r in _pick_latest_per_period(inc)[:n_years]:
        ed = r["end_date"]
        f = ind.get(ed) or {}
        rows.append({
            "期": f"{ed[:4]}年报",
            "营收亿": yi(r.get("total_revenue") or r.get("revenue")),
            "归母净利亿": yi(r.get("n_income_attr_p") or r.get("parent_netprofit")),
            "ROE%": pct(f.get("roe")),
            "毛利率%": pct(f.get("grossprofit_margin") or f.get("gross_margin")),
            "净利率%": pct(f.get("netprofit_margin")),
        })
    return rows


# ---------------- E4 股东户数 ----------------

def _em_holders(code: str) -> list:
    flt = urllib.parse.quote(f'(SECURITY_CODE="{code}")', safe="()")
    url = (f"https://datacenter.eastmoney.com/securities/api/data/v1/get"
           f"?reportName=RPT_HOLDERNUMLATEST&columns=ALL&filter={flt}&pageNumber=1&pageSize=8")
    return (get(url).get("result") or {}).get("data") or []


def fetch_holders(code: str) -> list:
    """E4 股东户数（东财键名同构）。tushare stk_holdernumber 优先（变动比自算），东财兜底。"""
    try:
        rows = ts_call("stk_holdernumber", {"ts_code": to_ts_code(code)})
        rows = [r for r in rows if r.get("holder_num")]
        if not rows:
            raise RuntimeError("stk_holdernumber 空返回")
        rows.sort(key=lambda x: x.get("end_date") or "")  # 旧→新算变动比
        out = []
        prev = None
        for r in rows:
            num = r.get("holder_num")
            ratio = round((num / prev - 1) * 100, 1) if (prev and num) else None
            out.append({"END_DATE": r.get("end_date"), "HOLDER_NUM": num,
                        "HOLDER_NUM_RATIO": ratio})
            prev = num
        return list(reversed(out))[:8]
    except Exception:
        return _em_holders(code)


# ---------------- E5 一致预期 ----------------

def _em_consensus(code: str) -> dict:
    flt = urllib.parse.quote(f'(SECURITY_CODE="{code}")', safe="()")
    url = (f"https://datacenter.eastmoney.com/securities/api/data/v1/get"
           f"?reportName=RPT_WEB_RESPREDICT&columns=ALL&filter={flt}&pageNumber=1&pageSize=1")
    data = (get(url).get("result") or {}).get("data") or []
    return data[0] if data else {}


def fetch_consensus(code: str) -> dict:
    """E5 一致预期。tushare report_rc（券商盈利预测明细）优先；东财 RPT_WEB_RESPREDICT 兜底。
    返回带 _src 标记的 dict。tushare 返回近180天研报聚合：家数/分年度净利与EPS均值/目标价区间。"""
    try:
        rows = ts_call("report_rc", {"ts_code": to_ts_code(code)})
        if not rows:
            raise RuntimeError("report_rc 空返回")
        cutoff = date.today().toordinal() - 180
        recent = []
        for r in rows:
            try:
                rd = date(int(r["report_date"][:4]), int(r["report_date"][4:6]), int(r["report_date"][6:8]))
                if rd.toordinal() >= cutoff:
                    recent.append(r)
            except Exception:
                continue
        if not recent:
            raise RuntimeError("report_rc 近180天无研报")
        orgs = {r.get("org_name") for r in recent if r.get("org_name")}
        # 按预测年度聚合（quarter 形如 2026Q4 → 2026）
        years = {}
        for r in recent:
            q = str(r.get("quarter") or "")
            yr = q[:4] if len(q) >= 4 else ""
            if not yr.isdigit():
                continue
            slot = years.setdefault(yr, {"np": [], "eps": []})
            if r.get("np") is not None:
                slot["np"].append(float(r["np"]) / 1e4)  # report_rc np 单位万元 → 亿
            if r.get("eps") is not None:
                slot["eps"].append(float(r["eps"]))
        prices = [(float(r["min_price"]), float(r["max_price"])) for r in recent
                  if r.get("min_price") and r.get("max_price")]
        ratings = {}
        for r in recent:
            rt = (r.get("rating") or "").strip()
            if rt:
                ratings[rt] = ratings.get(rt, 0) + 1
        return {"_src": "tushare", "orgs": len(orgs), "n_reports": len(recent),
                "years": years,
                "aim": (min(p[0] for p in prices), max(p[1] for p in prices)) if prices else None,
                "ratings": ratings}
    except Exception:
        d = _em_consensus(code)
        if d:
            d["_src"] = "em"
        return d


# ---------------- E6 主营构成 ----------------

def _em_mainop(secucode: str) -> list:
    flt = urllib.parse.quote(f'(SECUCODE="{secucode}")', safe="()")
    url = (f"https://datacenter.eastmoney.com/securities/api/data/v1/get"
           f"?reportName=RPT_F10_FN_MAINOP&columns=ALL&filter={flt}"
           f"&pageNumber=1&pageSize=20&sortTypes=-1&sortColumns=REPORT_DATE")
    try:
        return (get(url).get("result") or {}).get("data") or []
    except Exception:
        return []


def fetch_mainop(secucode: str) -> list:
    """E6 主营构成（东财键名同构）。tushare fina_mainbz 优先（产品P→行业D次序），东财兜底。"""
    code, _ = secucode.split(".")
    try:
        ts = to_ts_code(code)
        y0 = date.today().year - 2
        rng = {"start_date": f"{y0}0101", "end_date": date.today().strftime("%Y%m%d")}
        rows = None
        mainop_type = None
        for tp, mt in (("P", "2"), ("D", "1")):  # 产品优先，地区当行业位展示
            got = ts_call("fina_mainbz", {"ts_code": ts, "type": tp, **rng})
            if got:
                rows, mainop_type = got, mt
                break
        if not rows:
            raise RuntimeError("fina_mainbz 空返回")
        latest_ed = max(r.get("end_date") or "" for r in rows)
        items = [r for r in rows if r.get("end_date") == latest_ed]
        total = sum(float(r["bz_sales"]) for r in items if r.get("bz_sales")) or None
        out = []
        for r in items:
            sales = float(r["bz_sales"]) if r.get("bz_sales") else None
            cost = float(r["bz_cost"]) if r.get("bz_cost") else None
            out.append({
                "REPORT_DATE": _fmt_date(latest_ed),
                "REPORT_NAME": f"{latest_ed[:4]}年报" if latest_ed.endswith("1231") else latest_ed,
                "MAINOP_TYPE": mainop_type,
                "ITEM_NAME": r.get("bz_item"),
                "MAIN_BUSINESS_INCOME": sales,
                "MBI_RATIO": (sales / total if (sales and total) else None),
                "GROSS_RPOFIT_RATIO": ((sales - cost) / sales if (sales and cost is not None) else None),
            })
        return out
    except Exception:
        return _em_mainop(secucode)


# ---------------- 审计意见（红旗第五项） ----------------

def fetch_audit(code: str):
    """tushare fina_audit 最新年报审计意见。失败/无数据返回 None（红旗显示 △ 手工查证）。"""
    try:
        rows = ts_call("fina_audit", {"ts_code": to_ts_code(code)})
        if rows:
            rows.sort(key=lambda x: x.get("end_date") or "", reverse=True)
            return rows[0]
    except Exception:
        pass
    return None


def _audit_flag(audit) -> str:
    if not audit:
        return "△ 审计意见（必查项：按 SKILL.md Step 1.1 查证年报后填写，禁止直接沿用本行）"
    r = (audit.get("audit_result") or "").strip()
    ed = (audit.get("end_date") or "")[:4]
    if "标准无保留" in r:
        return f"✓ 审计意见：{r}（{ed}年报，tushare fina_audit）"
    if any(k in r for k in ("无法表示", "否定", "保留")):
        return f"✗ 审计意见：{r}（{ed}年报，非标准意见=红旗）"
    return f"△ 审计意见：{r or '未取到'}（{ed}）"


# ---------------- E7 定性站内搜索（东财，保持不动） ----------------

def search_e7(keyword: str, types: list = None, page_size: int = 8) -> dict:
    """E7 东方财富站内搜索。types: cmsArticleWebOld(新闻), cmsResearchWeb(研报) 等。
    返回 {'ok': bool, 'raw_head': str, 'items': [...]}。失败时 raw_head 含原始返回前 500 字符。"""
    if types is None:
        types = ["cmsArticleWebOld"]
    p = {"uid": "", "keyword": keyword, "type": types,
         "client": "web", "clientType": "web", "clientVersion": "curr",
         "param": {t: {"searchScope": "default", "sort": "default",
                       "pageIndex": 1, "pageSize": page_size,
                       "preTag": "", "postTag": ""} for t in types}}
    url = ("https://search-api-web.eastmoney.com/search/jsonp?cb=cb&param="
           + urllib.parse.quote(json.dumps(p, ensure_ascii=False)))
    try:
        raw = _get_via_curl(url).decode("utf-8", errors="replace")
    except Exception as e:
        return {"ok": False, "raw_head": f"[curl失败: {e}]", "items": []}
    # 剥 jsonp 外壳
    try:
        start = raw.find("(") + 1
        end = raw.rfind(")")
        if start > 0 and end > start:
            d = json.loads(raw[start:end])
        else:
            d = json.loads(raw)
    except Exception:
        return {"ok": False, "raw_head": f"[解析失败] 原始返回前500字符: {raw[:500]}", "items": []}
    result = d.get("result") or {}
    items = []
    for t in types:
        blk = result.get(t) or {}
        # 兼容两种结构：{"list":[...]} 或直接 [...]
        if isinstance(blk, list):
            lst = blk
        else:
            lst = blk.get("list") or []
        for it in lst:
            items.append({
                "title": (it.get("title") or it.get("TITLE") or "").strip(),
                "date": (it.get("showTime") or it.get("SHOWTIME") or it.get("date") or "")[:10],
                "url": (it.get("url") or it.get("URL") or ""),
                "summary": (it.get("summary") or it.get("SUMMARY") or "")[:150],
                "source": (it.get("mediaName") or it.get("MEDIANAME") or ""),
            })
    if not items:
        return {"ok": True, "raw_head": f"[空结果] 原始返回前500字符: {raw[:500]}", "items": []}
    return {"ok": True, "raw_head": "", "items": items}


# ---------------- 盈利质量红旗 ----------------

def red_flags(annual: list, audit=None) -> list:
    """盈利质量红旗五项检查。annual: 年报列表（新→旧，东财键名同构）。
    三态输出：✓=真通过（有数据且未恶化）/ ✗=真恶化 / △=数据不足——数据缺失显示△，
    绝不显示✓（"✓ API未触发"是虚假通过，芯原股份实证）。审计意见 tushare 自动填。"""
    flags = []
    annual = annual[:3]

    # 1. 利润现金含量（经营现金流/净利润 <0.7 视为不达标；数值为倍数如 1.48=148%）
    vals = [r.get("NCO_NETPROFIT") for r in annual if r.get("NCO_NETPROFIT") is not None]
    if len(vals) >= 2:
        bad_n = sum(1 for v in vals if v < 0.7)
        if bad_n >= 2:
            flags.append(f"✗ 利润现金含量 连续{bad_n}年<0.7")
        else:
            flags.append(f"✓ 利润现金含量（最低{round(min(vals), 2)}）")
    else:
        flags.append(f"△ 利润现金含量 数据不足({len(vals)}期有效)")

    # 2/3. 应收/存货周转天数趋势（变长=恶化）
    def worsening(key, name):
        vals = [r.get(key) for r in annual if r.get(key) is not None]
        if len(vals) >= 3:
            if vals[0] > vals[-1] * 1.3:
                return f"✗ {name} 恶化（{vals[-1]:.0f}→{vals[0]:.0f}天）"
            return f"✓ {name}（{vals[0]:.0f}天，未恶化）"
        return f"△ {name} 数据不足({len(vals)}期有效)"
    flags.append(worsening("YSZKZZTS", "应收账款周转"))
    flags.append(worsening("CHZZTS", "存货周转"))

    # 4. 毛利率异常（需同业对照，此处仅列数值）
    if annual and annual[0].get("XSMLL") is not None:
        flags.append(f"△ 毛利率 {pct(annual[0].get('XSMLL'))}（待与同业对照）")
    else:
        flags.append("△ 毛利率 数据不足")

    # 5. 审计意见（tushare fina_audit 自动填；无数据回落手工查证提示）
    flags.append(_audit_flag(audit))
    return flags


# ---------------- 汇总输出 ----------------

def summarize(code: str, years: int, searches: list = None) -> str:
    secid, secucode, is_hk = secid_of(code)
    pure = secucode.split(".")[0]
    mkt = "港股" if is_hk else "A股"
    out = [f"# {pure} 数据摘要（{mkt}）\n"]

    try:
        q = fetch_quote(secid, is_hk)
        pe_s = "—（缺失，可价格÷EPS手工算）" if q["PE_TTM"] is None else f"{q['PE_TTM']}x"
        out.append(f"## E1 行情估值\n{q['名称']}({q['代码']}) 价¥{q['最新价']} "
                   f"涨跌{q['涨跌幅%']}% | 市值{q['总市值亿']}亿 | "
                   f"PE(TTM){pe_s} PB{q['PB']}x | 换手{q['换手率%']}%\n")
        if not is_hk:
            band = fetch_pe_pb_band(pure)
            if band:
                out.append(f"PE(TTM) {band['years']}年带: {band['pe_min']:.1f}~{band['pe_max']:.1f}x，"
                           f"当前分位{band['pe_pct']}% | PB 带: {band['pb_min']:.2f}~{band['pb_max']:.2f}x，"
                           f"当前分位{band['pb_pct']}%（n={band['n']}交易日）\n")
            disc = fetch_disclosure(pure)
            if disc:
                if disc.get("实际披露"):
                    out.append(f"财报披露: {disc['报告期']} 已于{disc['实际披露']}实际披露"
                               f"（计划{disc.get('计划披露') or '—'}）\n")
                else:
                    out.append(f"财报披露: {disc['报告期']} 计划披露日 {disc['计划披露']}（未披露）\n")
    except Exception as e:
        out.append(f"## E1 行情估值\n[失败: {e}]\n")

    if is_hk:
        try:
            hk_rows = _ts_hk_annual_rows(pure)
            out.append("## E3 财务年表（年报，tushare hk_income）")
            out.append("报告期 | 营收亿 | 归母净利亿 | ROE% | 毛利率% | 净利率%")
            for r in hk_rows:
                out.append(f"{r['期']} | {r['营收亿']} | {r['归母净利亿']} | "
                           f"{r['ROE%']} | {r['毛利率%']} | {r['净利率%']}")
            out.append("\n## 盈利质量红旗\n[港股：现金含量/应收/存货周转天数港股接口不提供，按缺失处理；"
                       "毛利率用上表对照同业；审计意见走必查项手工查证]\n")
        except Exception as e:
            out.append(f"## E3 财务年表\n[tushare 港股无 hk_income 权限。**优先：妙想 MCP "
                       f"mx_hk_finance_data 直查**（模型直调，实测可用）；次兜底：data-sources.md "
                       f"港股手册 curl RPT_HKF10_FN_MAININDICATOR（字段映射见手册）。tushare 报错: {e}]\n")
    else:
        try:
            annual = _ts_annual_rows(pure)
            if not annual:
                raise RuntimeError("tushare 年报序列为空")
        except Exception:
            annual = _em_f10(secucode, size=5, annual_only=True)
        try:
            q1 = _ts_latest_quarter(pure) or {}
        except Exception:
            q1 = {}
        if not q1:
            f10 = _em_f10(secucode, size=4)
            q1 = f10[0] if f10 else {}
        if not annual:
            out.append("## E3 财务年表\n[tushare 与东财均失败，按降级链走妙想 mx_ashare_finance_data 直查]\n")
        else:
            out.append("## E3 财务年表（年报）\n"
                       "报告期 | 营收亿 | 归母净利亿 | 同比% | ROE% | 毛利率% | 净利率% | 负债率% | 经营现金流亿 | 现金含量")
            for r in annual:
                out.append(f"{r.get('REPORT_DATE_NAME')} | {yi(r.get('TOTALOPERATEREVE'))} | "
                           f"{yi(r.get('PARENTNETPROFIT'))} | {pct(r.get('PARENTNETPROFITTZ'))} | "
                           f"{pct(r.get('ROEJQ'))} | {pct(r.get('XSMLL'))} | {pct(r.get('XSJLL'))} | "
                           f"{pct(r.get('ZCFZL'))} | {yi(r.get('NETCASH_OPERATE_PK'))} | "
                           f"{(str(round(r['NCO_NETPROFIT'], 2)) if r.get('NCO_NETPROFIT') is not None else '—')}")
        out.append(f"\n最新报告期: {q1.get('REPORT_DATE_NAME')} 净利{yi(q1.get('PARENTNETPROFIT'))}亿 "
                   f"同比{pct(q1.get('PARENTNETPROFITTZ'))} | 总股本{yi(q1.get('TOTAL_SHARE'), 2)}亿 | "
                   f"ROIC {pct(q1.get('ROIC'))}\n")
        out.append("## 盈利质量红旗\n" + "\n".join(red_flags(annual, fetch_audit(pure))) + "\n")

    try:
        kl = fetch_kline_monthly(secid, years, is_hk)
        if kl:
            closes = [k["close"] for k in kl]
            out.append(f"## E2 月线（{len(kl)}期）\n"
                       f"区间 {kl[0]['date']}~{kl[-1]['date']} | "
                       f"最低{min(closes)} 最高{max(closes)} 最新{closes[-1]}\n"
                       f"近12月: " + " ".join(str(k['close']) for k in kl[-12:]) + "\n")
    except Exception as e:
        out.append(f"## E2 月线\n[失败: {e}]\n")

    try:
        h = fetch_holders(pure)
        if h:
            out.append("## E4 股东户数")
            for r in h[:6]:
                num = r.get("HOLDER_NUM")
                num_s = f"{num:,}" if isinstance(num, (int, float)) else "—"
                out.append(f"{(r.get('END_DATE') or '')[:10]}: {num_s}户 "
                           f"(变动{r.get('HOLDER_NUM_RATIO') and round(r['HOLDER_NUM_RATIO'], 1)}%)")
            out.append("")
        elif is_hk:
            out.append("## E4 股东户数\n[港股不支持，跳过]\n")
    except Exception as e:
        out.append(f"## E4 股东户数\n[失败: {e}]\n")

    if not is_hk:
        fe = fetch_forecast_express(pure)
        if fe:
            out.append("## 业绩预告/快报（tushare）")
            for r in fe:
                period = r.get("报告期") or "—"
                period_s = f"{period[:4]}-{period[4:6]}-{period[6:]}" if len(str(period)) == 8 else period
                if r["类型"] == "快报":
                    out.append(f"[快报] {period_s}（披露{r.get('披露')}）: 营收{r.get('营收')}亿 "
                               f"归母净利{r.get('净利')}亿 同比{r.get('同比')}")
                else:
                    line = f"[预告] {period_s}（披露{r.get('披露')}）: {r.get('预告类型') or ''}"
                    if r.get("净利区间"):
                        line += f" 净利{r['净利区间']}"
                    if r.get("变动幅度"):
                        line += f" 变动{r['变动幅度']}"
                    if r.get("摘要"):
                        line += f" | {r['摘要']}"
                    out.append(line)
            out.append("")

        g = fetch_governance(pure)
        glines = []
        if g.get("pledge"):
            p = g["pledge"]
            glines.append(f"质押: 质押比例{p.get('质押比例%')}%（截至{p.get('日期')}）")
        if g.get("trades"):
            t_s = "；".join(f"{t['披露']}{t['股东']}{t['方向']}" for t in g["trades"][:4])
            glines.append(f"增减持: {t_s}")
        if g.get("buyback"):
            b_s = "；".join(f"{b['披露']}回购{b.get('金额') or ''}{b.get('进度') or ''}" for b in g["buyback"][:2])
            glines.append(f"回购: {b_s}")
        if glines:
            out.append("## 1E 治理（tushare）\n" + "\n".join(glines) + "\n")

    try:
        c = fetch_consensus(pure)
        if c.get("_src") == "tushare":
            lines = [f"## E5 一致预期（tushare 券商研报，近180天{c['orgs']}家/{c['n_reports']}份）"]
            for yr in sorted(c["years"]):
                slot = c["years"][yr]
                if slot["np"]:
                    np_avg = sum(slot["np"]) / len(slot["np"])
                    line = (f"{yr}E: 归母净利均值{np_avg:,.1f}亿"
                            f"(区间{min(slot['np']):,.1f}-{max(slot['np']):,.1f})")
                    if slot["eps"]:
                        line += f" EPS均值{sum(slot['eps'])/len(slot['eps']):.2f}"
                    lines.append(line)
            if c.get("aim"):
                lines.append(f"目标价区间: {c['aim'][0]:.1f}-{c['aim'][1]:.1f}元")
            if c.get("ratings"):
                lines.append("评级分布: " + " ".join(f"{k}{v}" for k, v in
                                                      sorted(c["ratings"].items(), key=lambda x: -x[1])))
            out.append("\n".join(lines) + "\n")
        elif c:
            out.append(f"## E5 一致预期\n"
                       f"覆盖{c.get('RATING_ORG_NUM')}家: 买入{c.get('RATING_BUY_NUM')} "
                       f"增持{c.get('RATING_ADD_NUM')} 中性{c.get('RATING_NEUTRAL_NUM') or 0} | "
                       f"目标价{c.get('DEC_AIMPRICEMIN')}-{c.get('DEC_AIMPRICEMAX')}\n"
                       f"EPS: {c.get('YEAR1')}{c.get('YEAR_MARK1')}={c.get('EPS1') and round(c['EPS1'], 2)} "
                       f"{c.get('YEAR2')}{c.get('YEAR_MARK2')}={c.get('EPS2') and round(c['EPS2'], 2)} "
                       f"{c.get('YEAR3')}{c.get('YEAR_MARK3')}={c.get('EPS3') and round(c['EPS3'], 2)}\n"
                       f"行业: {c.get('INDUSTRY_BOARD')} | 概念: {(c.get('CONCEPTINDEX_BOARD') or '')[:80]}\n")
        elif is_hk:
            out.append("## E5 一致预期\n[港股无覆盖（tushare report_rc/东财均空），预期差按档位C处理]\n")
    except Exception as e:
        out.append(f"## E5 一致预期\n[失败: {e}]\n")

    try:
        mo = fetch_mainop(secucode)
        # MAINOP_TYPE: 1=行业/地区 2=产品；优先展示按产品，其次按行业
        typed = {}
        for r in mo:
            t = r.get("MAINOP_TYPE")
            if t in ("1", "2"):
                typed.setdefault(t, []).append(r)
        items_all = (typed.get("2") or typed.get("1") or [])
        if items_all:
            latest_date = items_all[0].get("REPORT_DATE")
            items = [r for r in items_all if r.get("REPORT_DATE") == latest_date][:8]
            latest = (items_all[0].get("REPORT_NAME") or "")
            out.append(f"## E6 主营构成（{latest}，按{'产品' if typed.get('2') else '行业/地区'}）")
            for r in items:
                ratio = r.get("MBI_RATIO")
                gpr = r.get("GROSS_RPOFIT_RATIO")
                out.append(f"{r.get('ITEM_NAME')}: 收入{yi(r.get('MAIN_BUSINESS_INCOME'))}亿 "
                           f"占比{ratio is not None and f'{ratio*100:.1f}%' or '—'} "
                           f"毛利率{gpr is not None and f'{gpr*100:.1f}%' or '—'}")
            out.append("")
        elif is_hk:
            out.append("## E6 主营构成\n[港股不支持（tushare/东财均无港股主营构成接口），定性搜索补]\n")
    except Exception:
        pass

    # E7 定性站内搜索（可选；tushare news 无权限，保持东财 E7）
    if searches:
        out.append("## E7 定性站内搜索")
        for kw in searches:
            r = search_e7(kw)
            if r["ok"] and r["items"]:
                out.append(f"\n### 「{kw}」({len(r['items'])}条)")
                for it in r["items"][:8]:
                    line = f"- [{it['date']}] {it['title']}"
                    if it["source"]:
                        line += f" — {it['source']}"
                    out.append(line)
                    if it["summary"]:
                        out.append(f"  {it['summary'][:120]}")
            elif r["ok"]:
                out.append(f"\n### 「{kw}」: 空结果（已换词/换type后仍空→降级）")
                out.append(f"  诊断: {r['raw_head'][:300]}")
            else:
                out.append(f"\n### 「{kw}」: 调用失败")
                out.append(f"  诊断: {r['raw_head'][:300]}")
        out.append("")

    return "\n".join(out)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = {a.split("=")[0][2:]: a.split("=")[1] for a in sys.argv[1:] if a.startswith("--") and "=" in a}
    if not args:
        print(__doc__)
        sys.exit(1)
    years = int(opts.get("kline-years", "5"))
    searches = None
    if opts.get("search"):
        searches = [s.strip() for s in opts["search"].split(",") if s.strip()]
    print(summarize(args[0], years, searches))
    for peer in (opts.get("peers") or "").split(","):
        peer = peer.strip()
        if peer:
            print("\n---\n")
            print(summarize(peer, years))


if __name__ == "__main__":
    main()
