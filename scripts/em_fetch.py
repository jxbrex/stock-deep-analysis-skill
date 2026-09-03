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
    python em_fetch.py 600989 --out=_em_600989_quote.json  # E1 源头数字落盘（fill.quote 防伪引用）

输出: 紧凑 Markdown 摘要到 stdout（实测约 3.5KB/股），原始 JSON 不落盘不进上下文。
覆盖: E1 行情估值 / E2 月线 / E3 F10 主要指标 / E4 股东户数 / E5 一致预期 / E6 主营构成
      / 盈利质量红旗四项 / 审计意见（tushare fina_audit，独立行，供 L4 红灯 a 项判定）
      / 有息负债（tushare balancesheet）
"""
import json
import hashlib
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.parse
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from functools import lru_cache

# Windows 控制台默认 GBK 编码，打印中文/货币符号会 UnicodeEncodeError —— 强制 UTF-8
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

UA = {"User-Agent": "Mozilla/5.0"}
CURL_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
TIMEOUT = 15
TS_API = "https://api.tushare.pro"

# E1 落盘捕获：_sec_e1 成功路径填充，main() 的 --out 把它写成 JSON（现价防伪通道的源头）
_E1_CAPTURE: dict = {}


class RateLimitError(RuntimeError):
    """HTTP 429/5xx：触发限流或服务端错误，硬停——禁止同 URL 原样重试。"""


class HttpStatusError(RuntimeError):
    """其他 HTTP 4xx 错误响应（属服务端明确拒绝，非网络层错误，不重试）。"""


# 代码→市场映射表（secid_of / to_ts_code 共用，保证两边口径一致）：
# 前缀 → (tushare 后缀, 东财 secid 前缀, 是否港股)
# 注意顺序：北交所两位前缀必须先于沪B的单字符 "9" 判定（92 开头是北交所，不是沪B）
# 北交所东财 secid 前缀 0. 已实测验证（920982 全链路通过，2026-08-30）；
# 83/43 等旧代码 2025-10 起已切换 920 段，东财返回零值陈旧档，由 _em_quote 拦截报错
_MKT_MAP = [
    (("43", "83", "87", "88", "92"), "BJ", "0", False),   # 北交所
    (("60", "68", "9"), "SH", "1", False),                # 沪市主板/科创板/沪B
]
_MKT_SZ = ("SZ", "0", False)   # 其余 6 位默认深市（00/30 深主板/创业板、20 深B）
_MKT_HK = ("HK", "116", True)  # 5 位纯数字 = 港股


def _mkt_of(code: str):
    """纯数字代码 → (tushare后缀, 东财secid前缀, 是否港股)。
    只接受 6 位（A股/北交所/B股）或 5 位（港股）纯数字，其他直接报错，不静默按深市处理。"""
    if not code.isdigit() or len(code) not in (5, 6):
        raise ValueError(f"无法识别的证券代码 {code!r}：期望 6 位纯数字（A股/北交所/B股）"
                         f"或 5 位纯数字（港股），可带 .SH/.SZ/.BJ/.HK 后缀")
    if len(code) == 5:
        return _MKT_HK
    for prefixes, sfx, sec, hk in _MKT_MAP:
        if code.startswith(prefixes):
            return sfx, sec, hk
    return _MKT_SZ


def secid_of(code: str):
    """返回 (secid, secucode, is_hk)。港股：5位数字（如 06082/01880）→ 116. 前缀"""
    code = code.strip().upper().replace(".SH", "").replace(".SZ", "").replace(".BJ", "").replace(".HK", "")
    sfx, sec, hk = _mkt_of(code)
    return f"{sec}.{code}", f"{code}.{sfx}", hk


def to_ts_code(code: str) -> str:
    """tushare 代码：600989→600989.SH，000528→000528.SZ，06082→06082.HK"""
    code = code.strip().upper()
    if "." in code:
        return code
    sfx, _, _ = _mkt_of(code)
    return code + "." + sfx


# ---------------- tushare 传输层 ----------------

@lru_cache(maxsize=1)
def _tushare_token():
    """token 自动发现：环境变量 TUSHARE_TOKEN 优先，其次 ZCode MCP 配置（不落盘不打印）。
    lru_cache：此前每次请求都重新读文件+解析 JSON（20 请求 = 20 次重复发现）。"""
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


# tushare 透明缓存：同一进程内相同 (api, 归一化参数) 只发一次网络请求（会员限流保护）
_TS_CACHE: dict = {}
_TS_DEBUG = os.environ.get("EM_FETCH_DEBUG") == "1"

# ---------------- 磁盘缓存（跨进程，P0-B） ----------------
# 每份报告是一个新进程、每股 15-20 请求，同日重跑/check 修复循环/peers 批量全量重发，
# 痛点是 tushare 限流额度消耗（report_rc 等接口 1次/分钟）与东财野生端点封禁风险。
# TTL 分档：行情 2h / 财务 12h / 治理 24h（均远小于数据自身更新周期，陈旧风险可控）；
# EM_FETCH_NO_CACHE=1 全旁路。缓存读写任何失败都静默忽略，绝不阻断取数。
_CACHE_DIR = os.path.join(tempfile.gettempdir(), "em_fetch_cache")
_NO_CACHE = os.environ.get("EM_FETCH_NO_CACHE") == "1"
_TTL_QUOTE = 2 * 3600    # 行情（日线收盘级，2h 内唯一风险是盘中跑+收盘后 1h 内重跑，可识别）
_TTL_FIN = 12 * 3600     # 财务（季度更新）
_TTL_GOV = 24 * 3600     # 治理（公告/事件级更新）
_TS_TIER_QUOTE = {"daily", "daily_basic", "adj_factor", "hk_daily", "weekly", "monthly",
                  "index_daily", "stk_factor"}
_TS_TIER_GOV = {"pledge_stat", "stk_holdertrade", "repurchase", "fina_audit", "stock_basic",
                "disclosure_date", "namechange", "stk_holdernumber",
                "top10_holders", "top10_floatholders"}


def _dc_path(tag: str, key: str) -> str:
    return os.path.join(_CACHE_DIR, f"{tag}_{hashlib.md5(key.encode('utf-8')).hexdigest()[:16]}.json")


def _dc_read(path: str, ttl: int):
    """命中且未过期返回解析值，否则 None。"""
    if _NO_CACHE:
        return None
    try:
        if time.time() - os.path.getmtime(path) > ttl:
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _dc_write(path: str, val) -> None:
    """先写临时文件再 replace，避免并发读到写了一半的文件。"""
    if _NO_CACHE:
        return
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(val, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass


def ts_call(api_name: str, params: dict = None, fields: str = "") -> list:
    """tushare HTTP API。返回 list[dict]（fields↔items 对齐）。失败抛异常由调用方兜底。
    缓存键归一化：params 里的 "fields" 是 no-op（tushare 只认 payload 顶层 fields），剔除后参与键。"""
    norm = dict(params or {})
    norm.pop("fields", None)
    key = (api_name, tuple(sorted(norm.items())), fields)
    if key in _TS_CACHE:
        if _TS_DEBUG:
            print(f"[cache-hit] {api_name} {dict(norm)}", file=sys.stderr)
        return _TS_CACHE[key]
    # 磁盘缓存（跨进程）：行情 2h / 财务 12h / 治理 24h
    tier = _TTL_QUOTE if api_name in _TS_TIER_QUOTE else _TTL_GOV if api_name in _TS_TIER_GOV else _TTL_FIN
    dp = _dc_path("ts", repr(key))
    cached = _dc_read(dp, tier)
    if cached is not None:
        _TS_CACHE[key] = cached
        if _TS_DEBUG:
            print(f"[disk-hit] {api_name} {dict(norm)}", file=sys.stderr)
        return cached
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
    rows = [dict(zip(flds, row)) for row in (data.get("items") or [])]
    _TS_CACHE[key] = rows
    _dc_write(dp, rows)
    if _TS_DEBUG:
        print(f"[net] {api_name} {dict(norm)} -> {len(rows)} rows", file=sys.stderr)
    return rows


def _fin_rng() -> dict:
    """财务三表/指标的统一取数窗口（当年-7 起，覆盖 forensic 7 年/年表 5 年/最新季度 2 年三处需求），
    配合 ts_call 缓存：income/cashflow/balancesheet/fina_indicator 每股只发 1 次请求。"""
    return {"start_date": f"{date.today().year - 7}0101",
            "end_date": date.today().strftime("%Y%m%d")}


# ---------------- 东财传输层（兜底） ----------------

def _get_via_curl(url: str) -> bytes:
    """curl 传输：push2 域对 Python urllib 的 TLS 指纹间歇限流，curl 不受限（实测验证）。
    -w 捕获 HTTP 状态码：429/5xx → RateLimitError（限流硬停）；其他 4xx → HttpStatusError。"""
    r = subprocess.run(
        ["curl", "-s", "--max-time", str(TIMEOUT), "-H", f"User-Agent: {CURL_UA}",
         "-w", "\n%{http_code}", url],
        capture_output=True, timeout=TIMEOUT + 5,
    )
    if r.returncode != 0 or not r.stdout:
        raise ConnectionError(f"curl rc={r.returncode} {r.stderr[:100]!r}")
    body, _, status = r.stdout.rpartition(b"\n")
    code = int(status) if status.isdigit() else 0
    if code == 429 or code >= 500:
        raise RateLimitError(f"HTTP {code}（限流/服务端错误，硬停不重试）: {url[:80]}")
    if code >= 400:
        raise HttpStatusError(f"HTTP {code}: {url[:80]}")
    return body


def _get_via_urllib(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 429 or e.code >= 500:
            raise RateLimitError(f"HTTP {e.code}（限流/服务端错误，硬停不重试）: {url[:80]}") from e
        raise HttpStatusError(f"HTTP {e.code}: {url[:80]}") from e


def get(url: str, retries: int = 1) -> dict:
    """curl 优先、urllib 兜底（TLS 指纹规避），失败重试 1 次。返回解析后的 JSON dict。
    重试仅限网络层错误（超时/连接失败/异常响应体）；HTTP 错误响应（4xx/5xx）不重试、
    不换传输层重打，429/5xx 抛 RateLimitError 由 main 限流硬停。
    磁盘缓存：push2/push2his 行情 2h、datacenter 数据 12h（跨进程去重），其余 URL 不缓存。"""
    tier = _TTL_QUOTE if "push2" in url else _TTL_FIN if "datacenter" in url else 0
    dp = _dc_path("em", url) if tier else None
    if dp:
        cached = _dc_read(dp, tier)
        if cached is not None:
            return cached
    last_err = None
    for attempt in range(retries + 1):
        for transport in (_get_via_curl, _get_via_urllib):
            try:
                raw = transport(url)
                d = json.loads(raw.decode("utf-8"))
                if dp:
                    _dc_write(dp, d)
                return d
            except (RateLimitError, HttpStatusError):
                raise  # HTTP 错误响应：原样抛出，不重试
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


def _yoy(cur, pre):
    """同比%：分母 pre≤0 时百分比失真，按符号组合返回文字（扭亏/转亏/减亏/增亏）。
    pre>0 且 cur<0 → 转亏；pre<0 且 cur>0 → 扭亏；cur/pre 任一缺失 → None。"""
    if cur is None or pre is None:
        return None
    if pre > 0:
        return "转亏" if cur < 0 else (cur / pre - 1) * 100
    if pre < 0:
        if cur > 0:
            return "扭亏"
        return "减亏" if cur > pre else "增亏"
    return None  # pre == 0：基数为零，同比无意义


def yoy_text(v):
    """同比显示：数值→百分比，文字（扭亏/转亏…）→原样，None→—"""
    return v if isinstance(v, str) else pct(v)


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
    fields = "f43,f57,f58,f116,f162,f167,f168,f170"
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields={fields}"
    d = get(url).get("data") or {}
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


# ---------------- A 级增强：PE/PB 分位 / 业绩预告快报 / 治理包 / 披露日期 ----------------

def _daily_basic_latest(code: str) -> dict:
    """daily_basic 最近一行（15 日窗口 + 最小字段）。fetch_quote / _ts_latest_quarter 共用，
    替代两处无窗口全量拉取（拉十年全量只为 max 最新行的浪费）；空日期行过滤后再 max（None 陷阱）。"""
    end = date.today().strftime("%Y%m%d")
    beg = (date.today() - timedelta(days=15)).strftime("%Y%m%d")
    rows = ts_call("daily_basic",
                   {"ts_code": to_ts_code(code), "start_date": beg, "end_date": end},
                   fields="ts_code,trade_date,close,pe_ttm,pb,total_mv,turnover_rate,total_share")
    rows = [r for r in rows if r.get("trade_date")]
    if not rows:
        raise RuntimeError("daily_basic 空返回")
    return max(rows, key=lambda x: x["trade_date"])


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


def fetch_forecast_express(code: str) -> list:
    """业绩预告 + 业绩快报（tushare forecast/express，按报告期合并去重，新→旧最多4条）。"""
    try:
        out = []
        for r in ts_call("forecast", {"ts_code": to_ts_code(code)}):
            lo, hi = r.get("net_profit_min"), r.get("net_profit_max")
            rng = (f"{float(lo)/1e4:,.1f}~{float(hi)/1e4:,.1f}亿"  # forecast 净利单位：万元→亿
                   if lo is not None and hi is not None else None)
            chg_raw = (r.get("p_change_min"), r.get("p_change_max"))
            chg = (f"{chg_raw[0]:.0f}%~{chg_raw[1]:.0f}%"
                   if all(v is not None and abs(v) < 10000 for v in chg_raw) else None)  # 源数据异常值（如 1e9%）直接丢弃
            # 摘要只留原因短语（change_reason）；净利区间已单独列示，不再重复原文长句
            reason = (r.get("change_reason") or "").strip()
            if reason:
                summ = reason[:50]
            else:
                summ = ""  # 净利区间已列示，不再重复原文长句
            out.append({"类型": "预告", "报告期": r.get("end_date"), "披露": r.get("ann_date"),
                        "预告类型": r.get("type"), "净利区间": rng, "变动幅度": chg,
                        "摘要": summ})
        for r in ts_call("express", {"ts_code": to_ts_code(code)}):
            yoyv = r.get("yoy_net_profit")
            out.append({"类型": "快报", "报告期": r.get("end_date"), "披露": r.get("ann_date"),
                        "净利": yi(r.get("n_income")),
                        "同比": pct(yoyv) if isinstance(yoyv, (int, float)) and abs(yoyv) < 10000 else "—（源数据异常）",
                        "营收": yi(r.get("revenue"))})
        # 按报告期新→旧，同报告期快报优先（快报晚于预告、数据更实）
        out.sort(key=lambda x: (x.get("报告期") or "", 1 if x["类型"] == "快报" else 0), reverse=True)
        dedup = {}
        for r in out:
            dedup.setdefault(r.get("报告期"), r)
        return [dedup[k] for k in sorted(dedup, reverse=True)][:4]
    except Exception:
        return []


def fetch_forensic(code: str) -> list:
    """财报可信度初判（A股，tushare）：应计比率 + Beneish M-Score + 审计意见 → A/B/C/D。
    金融股（comp_type 2/3/4）不适用 M-Score，输出说明。单项计算失败跳过不报错。
    方法细节见 references/forensic-accounting.md。"""
    try:
        ts = to_ts_code(code)
        rng = _fin_rng()
        inc = _pick_latest_per_period(
            [r for r in ts_call("income", {"ts_code": ts, **rng})
             if (r.get("end_date") or "").endswith("1231") and str(r.get("report_type")) == "1"])[:2]
        if len(inc) < 2:
            return []
        bs = _pick_latest_per_period(
            [r for r in ts_call("balancesheet", {"ts_code": ts, **rng})
             if (r.get("end_date") or "").endswith("1231") and str(r.get("report_type")) == "1"])
        bs_map = {r["end_date"]: r for r in bs}
        cf_map = {r["end_date"]: r for r in ts_call("cashflow", {"ts_code": ts, **rng})
                  if (r.get("end_date") or "").endswith("1231")}
        t, t1 = inc[0], inc[1]
        b, b1 = bs_map.get(t["end_date"]) or {}, bs_map.get(t1["end_date"]) or {}
        c, c1 = cf_map.get(t["end_date"]) or {}, cf_map.get(t1["end_date"]) or {}
        if not b or not b1:
            return []

        def g(src, k):
            v = src.get(k)
            return float(v) if v is not None else None

        rev, rev1 = g(t, "total_revenue"), g(t1, "total_revenue")
        ni, ni1 = g(t, "n_income"), g(t1, "n_income")
        ocf, ocf1 = g(c, "n_cashflow_act"), g(c1, "n_cashflow_act")
        ta, ta1 = g(b, "total_assets"), g(b1, "total_assets")
        lines = []
        # 应计比率（Sloan）：(净利润−经营现金流) ÷ 平均总资产
        if None not in (ni, ocf, ta, ta1) and (ta + ta1):
            acc = (ni - ocf) / ((ta + ta1) / 2)
            acc_note = "<0 优 / 0-5% 正常 / >10% 红旗"
            lines.append(f"应计比率: {acc * 100:.1f}%（{acc_note}）")
        else:
            acc = None
        # 现金含量连续两年 <0.7（与红旗第1项同口径，供评级用；
        # 净利润为负时 ocf/ni 无意义，ni≤0 的年份跳过判定，不计入连续 2 年计数）
        nco_bad = False
        if None not in (ni, ni1, ocf, ocf1) and ni > 0 and ni1 > 0:
            nco_bad = (ocf / ni < 0.7) and (ocf1 / ni1 < 0.7)
        # M-Score（金融股不适用）
        m = None
        comp = str(t.get("comp_type") or "1")
        if comp != "1":
            lines.append(f"M-Score: 不适用（金融/保险/证券类公司，改查拨备/准备金/Level3 占比，"
                         f"替代项见 references/industry-financials.md 财报可信度替代项章节）")
        else:
            try:
                ar, ar1 = g(b, "accounts_receiv"), g(b1, "accounts_receiv")
                ca, ca1 = g(b, "total_cur_assets"), g(b1, "total_cur_assets")
                ppe, ppe1 = g(b, "fix_assets"), g(b1, "fix_assets")
                dep, dep1 = g(c, "depr_fa_coga_dpba"), g(c1, "depr_fa_coga_dpba")
                sga = (g(t, "sell_exp") or 0) + (g(t, "admin_exp") or 0)
                sga1 = (g(t1, "sell_exp") or 0) + (g(t1, "admin_exp") or 0)
                tl, tl1 = g(b, "total_liab"), g(b1, "total_liab")
                gm = g(t, "grossprofit_margin")  # income 无毛利率，从 fina_indicator 补
                gm1 = g(t1, "grossprofit_margin")
                if gm is None or gm1 is None:
                    ind = {r["end_date"]: r for r in ts_call(
                        "fina_indicator", {"ts_code": ts, **rng,
                                           "fields": "ts_code,end_date,grossprofit_margin"})}
                    gm = gm if gm is not None else g(ind.get(t["end_date"]) or {}, "grossprofit_margin")
                    gm1 = gm1 if gm1 is not None else g(ind.get(t1["end_date"]) or {}, "grossprofit_margin")
                vals = [rev, rev1, ar, ar1, ca, ca1, ppe, ppe1, dep, dep1, tl, tl1, ta, ta1,
                        ni, ocf, gm, gm1]
                if any(v is None for v in vals) or 0 in (rev, rev1, ta, ta1):
                    raise ValueError("字段不全")
                if gm <= 0 or gm1 <= 0:
                    raise ValueError("毛利率≤0，GMI 失真")
                dsri = (ar / rev) / (ar1 / rev1)
                gmi = gm1 / gm
                aq = lambda bb: 1 - (bb[0] + bb[1]) / bb[2]
                aqi = aq((ca, ppe, ta)) / aq((ca1, ppe1, ta1))
                sgi = rev / rev1
                depi = (dep1 / (ppe1 + dep1)) / (dep / (ppe + dep))
                sgai = (sga / rev) / (sga1 / rev1)
                tata = (ni - ocf) / ta
                lvgi = (tl / ta) / (tl1 / ta1)
                m = (-4.84 + 0.92 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi
                     + 0.115 * depi - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi)
                lines.append(f"M-Score: {m:.2f}（阈值 -1.78，低于它安全；越高越可疑）")
            except ValueError as e:
                lines.append(f"M-Score: 无法计算（{e}）")
            except Exception:
                lines.append("M-Score: 数据不足无法计算（字段缺失）")
        # 审计意见
        audit_bad = False
        try:
            aud = fetch_audit(code)
            audit_bad = bool(aud) and "标准无保留" not in str(aud.get("audit_result") or "")
        except Exception:
            pass
        # 初评
        serious = []
        if m is not None and m > -1.78:
            serious.append("M-Score 越限")
        if acc is not None and acc > 0.10:
            serious.append(f"应计比率 {acc * 100:.0f}%>10%")
        if nco_bad:
            serious.append("现金含量连续2年<0.7")
        if audit_bad:
            rating = "D"
        elif len(serious) >= 2:
            rating = "D"
        elif serious:
            rating = "C"
        elif (acc is not None and acc > 0.05) or (m is not None and m > -2.0):
            rating = "B"
        else:
            rating = "A"
        basis = ("审计意见非标" if audit_bad else ("；".join(serious) if serious else "无红旗项"))
        lines.append(f"初评: {rating}（{basis}）——C → 黄灯 d 类至少扣 0.5 且 00 章警示；"
                     f"D → 红灯回避，估值仅供参考")
        return lines
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
    except OSError:
        pass  # 网络层错误静默走降级
    except RuntimeError as e:  # token 未配置/接口报错必须可见，不再静默吞掉（神华事故教训）
        print(f"⚠️ fetch_governance pledge_stat: {e}", file=sys.stderr)
    try:
        rows = ts_call("stk_holdertrade", {"ts_code": ts})
        rows = [r for r in rows if r.get("ann_date")]
        rows.sort(key=lambda x: x.get("ann_date") or "", reverse=True)
        for r in rows[:6]:
            g["trades"].append({"披露": r.get("ann_date"), "股东": (r.get("holder_name") or "")[:12],
                                "方向": "增持" if r.get("in_de") == "IN" else "减持",
                                "数量万股": r.get("change_vol")})
    except OSError:
        pass  # 网络层错误静默走降级
    except RuntimeError as e:
        print(f"⚠️ fetch_governance stk_holdertrade: {e}", file=sys.stderr)
    try:
        rows = ts_call("repurchase", {"ts_code": ts})
        rows = [r for r in rows if r.get("ann_date")]
        rows.sort(key=lambda x: x.get("ann_date") or "", reverse=True)
        for r in rows[:3]:
            g["buyback"].append({"披露": r.get("ann_date"), "金额": yi(r.get("amount")) + "亿"
                                 if r.get("amount") else None, "进度": r.get("proc")})
    except OSError:
        pass  # 网络层错误静默走降级
    except RuntimeError as e:
        print(f"⚠️ fetch_governance repurchase: {e}", file=sys.stderr)
    return g


def fetch_disclosure(code: str) -> dict:
    """下一次财报披露计划（tushare disclosure_date）。失败返回 None。"""
    try:
        rows = ts_call("disclosure_date", {"ts_code": to_ts_code(code)})
        rows = [r for r in rows if r.get("end_date")]
        rows.sort(key=lambda x: x.get("end_date") or "", reverse=True)
        for r in rows:
            # 找尚未实际披露、且有计划日期的最近报告期
            if not r.get("actual_date") and r.get("pre_date"):
                return {"报告期": r.get("end_date"), "计划披露": r.get("pre_date")}
        # 全部已披露 → 返回最近一条实际披露供参考
        if rows:
            r = rows[0]
            return {"报告期": r.get("end_date"), "计划披露": r.get("pre_date"),
                    "实际披露": r.get("actual_date")}
    except OSError:
        pass  # 网络层错误静默走降级
    except RuntimeError as e:
        print(f"⚠️ fetch_disclosure: {e}", file=sys.stderr)
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
                "换手率%": _r2(r.get("turnover_rate")), "数据日期": r.get("trade_date")}
    except Exception:
        return _em_quote(secid, False)


# ---------------- E2 月线 ----------------

def _em_kline_monthly(secid: str, years: int, is_hk: bool = False) -> list:
    end = "20991231"
    beg = f"{date.today().year - years}0101"
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
        # v4.8.1：月度 PE(TTM) 回填（供 price_history 图，替代模型手工「月收×总股本÷TTM净利」）。
        # 与 fetch_pe_pb_band 同参同字段，命中透明缓存不增发请求；失败静默跳过（仅 close，图降级单线）
        try:
            pe_map = {r["trade_date"]: float(r["pe_ttm"])
                      for r in ts_call("daily_basic", {"ts_code": ts, "start_date": beg, "end_date": end},
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


def _ts_annual_rows(code: str, n_years: int = 5, secucode: str = None) -> list:
    """A股年报主要指标（新→旧），映射为东财 F10 同构键名，供年表与红旗共用。
    周转天数优先 tushare fina_indicator 换算；缺失期次用东财 F10 直接字段
    YSZKZZTS/CHZZTS 补齐（tushare 对部分个股该字段覆盖不全，中芯国际实证）。"""
    ts = to_ts_code(code)
    rng = _fin_rng()  # 统一窗口：与 forensic/最新季度共享缓存（本地过滤，n_years 由切片控制）
    inc = []
    ind = []
    cf = []
    try:
        inc = [r for r in ts_call("income", {"ts_code": ts, **rng})
               if (r.get("end_date") or "").endswith("1231") and str(r.get("report_type")) == "1"]
    except Exception:
        pass
    try:
        ind = [r for r in ts_call("fina_indicator", {"ts_code": ts, **rng})
               if (r.get("end_date") or "").endswith("1231")]
    except Exception:
        pass
    try:
        cf = [r for r in ts_call("cashflow", {"ts_code": ts, **rng})
              if (r.get("end_date") or "").endswith("1231")]
    except Exception:
        pass
    if not inc:
        raise RuntimeError("tushare income 无年报数据")
    ind_map = {r["end_date"]: r for r in ind}
    cf_map = {r["end_date"]: r for r in cf}
    # 东财 F10 直接字段映射（按报告期年份索引），补齐 tushare 缺失的周转天数
    em_map = {}
    if secucode:
        try:
            for r in _em_f10(secucode, size=n_years, annual_only=True) or []:
                key = (r.get("REPORT_DATE_NAME") or r.get("REPORT_DATE") or "")[:4]
                if key.isdigit():
                    em_map[key] = r
        except Exception:
            pass
    rows = []
    for r in _pick_latest_per_period(inc)[:n_years]:
        ed = r["end_date"]
        f = ind_map.get(ed) or {}
        c = cf_map.get(ed) or {}
        em = em_map.get(ed[:4]) or {}
        ocf = c.get("n_cashflow_act")
        if ocf is None:
            ocf = em.get("NETCASH_OPERATE_PK")
        ni = r.get("n_income")  # 净利润（含少数股东），与东财现金含量口径一致
        # 周转天数换算：fina_indicator 只给周转率——应收天数=360/ar_turn；
        # 存货天数=turn_days(营业周期)−应收天数（营业周期=存货+应收周转天数）
        ar_days = (360 / f["ar_turn"]) if f.get("ar_turn") else None
        inv_days = (f["turn_days"] - ar_days) if (f.get("turn_days") is not None
                                                  and ar_days is not None) else None
        if ar_days is None:
            ar_days = em.get("YSZKZZTS")
        if inv_days is None:
            inv_days = em.get("CHZZTS")
        rows.append({
            "REPORT_DATE_NAME": f"{ed[:4]}年报",
            "TOTALOPERATEREVE": r.get("total_revenue"),
            "PARENTNETPROFIT": r.get("n_income_attr_p"),
            "PARENTNETPROFITTZ": None,  # 同比在 summarize 外另算（需相邻期，见下）
            # 财务指标同样按字段级 fallback：tushare fina_indicator 缺期次时用东财 F10 补齐
            "ROEJQ": f.get("roe") if f.get("roe") is not None else em.get("ROEJQ"),
            "XSMLL": f.get("grossprofit_margin") if f.get("grossprofit_margin") is not None
            else em.get("XSMLL"),
            "XSJLL": f.get("netprofit_margin") if f.get("netprofit_margin") is not None
            else em.get("XSJLL"),
            "ZCFZL": f.get("debt_to_assets") if f.get("debt_to_assets") is not None
            else em.get("ZCFZL"),
            "NETCASH_OPERATE_PK": ocf,
            # 净利润为负时 ocf/ni 无意义：ni≤0 的年份置 None，不计入红旗连续 2 年 <0.7 计数
            "NCO_NETPROFIT": (ocf / ni if (ocf is not None and ni is not None and ni > 0) else None),
            "CAPEX": c.get("c_pay_acq_const_fiolta"),  # 购建固定资产/无形资产等支付现金（DCF capex 输入）
            "YSZKZZTS": ar_days,
            "CHZZTS": inv_days,
        })
    # 归母净利同比：与上一年比（分母≤0 时走 _yoy 文字化，不出失真百分比）
    by_ed = {r["REPORT_DATE_NAME"][:4]: r for r in rows}
    for r in rows:
        prev = by_ed.get(str(int(r["REPORT_DATE_NAME"][:4]) - 1))
        cur, pre = r.get("PARENTNETPROFIT"), (prev or {}).get("PARENTNETPROFIT")
        r["PARENTNETPROFITTZ"] = _yoy(cur, pre)
    return rows


def _ts_latest_quarter(code: str, secucode: str = None) -> dict:
    """A股最新报告期摘要（东财键名同构）：净利/同比/总股本/ROIC。
    ROIC/总股本缺失时用东财 F10 字段级补齐（tushare fina_indicator/daily_basic 覆盖不全）。"""
    ts = to_ts_code(code)
    rng = _fin_rng()  # 统一窗口：与 forensic/年表共享缓存（本地取最新报告期）
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
            yoy = _yoy(cur.get("n_income_attr_p"), r.get("n_income_attr_p"))
            break
    em = {}
    if secucode:
        try:
            f10 = _em_f10(secucode, size=1)
            if f10:
                em = f10[0]
        except Exception:
            pass
    roic = None
    try:
        ind = [r for r in ts_call("fina_indicator", {"ts_code": ts, **rng})
               if r.get("end_date") == cur["end_date"]]
        if ind:
            roic = ind[0].get("roic")
    except Exception:
        pass
    if roic is None:
        roic = em.get("ROIC")
    total_share = None
    try:
        total_share = _daily_basic_latest(code).get("total_share")
        total_share = total_share * 1e4 if total_share else None  # 万股→股
    except Exception:
        pass
    if total_share is None:
        total_share = em.get("TOTAL_SHARE")
    ed = cur.get("end_date") or ""
    qname = {"0331": "一季", "0630": "中报", "0930": "三季", "1231": "年报"}.get(ed[4:], ed)
    return {"REPORT_DATE_NAME": f"{ed[:4]}{qname}",
            "PARENTNETPROFIT": cur.get("n_income_attr_p"),
            "PARENTNETPROFITTZ": yoy,
            "TOTAL_SHARE": total_share,
            "ROIC": roic}


def _ts_hk_annual_rows(code: str, n_years: int = 4) -> list:
    """港股年报主要指标（新→旧）。tushare hk_income/hk_fina_indicator 优先（权限开放时）；
    失败或为空时走东财 RPT_HKF10_FN_MAININDICATOR 兜底（字段映射见 data-sources.md §港股支持矩阵）。"""
    ts = to_ts_code(code)
    y0 = date.today().year - n_years - 1
    rng = {"start_date": f"{y0}0101", "end_date": date.today().strftime("%Y%m%d")}
    try:
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
    except Exception:
        pass
    return _em_hkf10_annual_rows(code, n_years)


def _em_hkf10_annual_rows(code: str, n_years: int = 4) -> list:
    """东财港股 HKF10 主要指标兜底（RPT_HKF10_FN_MAININDICATOR，columns=ALL）。
    只取年报；营收/归母净利为元，yi() 转亿；比率字段已是百分比数值。"""
    flt = urllib.parse.quote(f'(SECUCODE="{code}.HK")', safe="()")
    url = (f"https://datacenter.eastmoney.com/securities/api/data/v1/get"
           f"?reportName=RPT_HKF10_FN_MAININDICATOR&columns=ALL&filter={flt}"
           f"&pageNumber=1&pageSize={max(20, n_years * 6)}&sortTypes=-1&sortColumns=REPORT_DATE")
    try:
        data = get(url).get("result") or {}
    except Exception:
        return []
    items = data.get("data") or []
    rows = []
    seen = set()
    for r in items:
        rt = str(r.get("REPORT_TYPE") or "")
        if "年报" not in rt:
            continue
        year = rt[:4]
        if not year.isdigit() or year in seen:
            continue
        seen.add(year)
        rows.append({
            "期": f"{year}年报",
            "营收亿": yi(r.get("OPERATE_INCOME")),
            "归母净利亿": yi(r.get("HOLDER_PROFIT")),
            "ROE%": pct(r.get("ROE_AVG")),
            "毛利率%": pct(r.get("GROSS_PROFIT_RATIO")),
            "净利率%": pct(r.get("NET_PROFIT_RATIO")),
        })
        if len(rows) >= n_years:
            break
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
        # 单次循环聚合：按预测年度的净利/EPS（quarter 形如 2026Q4 → 2026）、目标价区间、评级分布
        years, prices, ratings = {}, [], {}
        for r in recent:
            q = str(r.get("quarter") or "")
            yr = q[:4] if len(q) >= 4 else ""
            if yr.isdigit():
                slot = years.setdefault(yr, {"np": [], "eps": []})
                if r.get("np") is not None:
                    slot["np"].append(float(r["np"]) / 1e4)  # report_rc np 单位万元 → 亿
                if r.get("eps") is not None:
                    slot["eps"].append(float(r["eps"]))
            if r.get("min_price") and r.get("max_price"):
                prices.append((float(r["min_price"]), float(r["max_price"])))
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


def _mainop_norm_em(rows: list) -> list:
    """东财 E6 原始行补 GROSS_PROFIT（毛利额，元）：优先原始字段 MAIN_BUSINESS_RPOFIT，
    缺失用 收入×毛利率 折算（GROSS_RPOFIT_RATIO 为小数口径，见 data-sources.md E6 节）。
    同收入同毛利率的重复条目（同源改名残留）一并去重，留先发行。"""
    seen = set()
    deduped = []
    for r in rows:
        sig = (r.get("MAIN_BUSINESS_INCOME"), r.get("GROSS_RPOFIT_RATIO"))
        if sig in seen:
            continue
        seen.add(sig)
        deduped.append(r)
    rows = deduped
    for r in rows:
        gp = r.get("MAIN_BUSINESS_RPOFIT")
        if gp is None:
            inc, gpr = r.get("MAIN_BUSINESS_INCOME"), r.get("GROSS_RPOFIT_RATIO")
            if inc is not None and gpr is not None:
                try:
                    r["GROSS_PROFIT"] = float(inc) * float(gpr)
                except (TypeError, ValueError):
                    pass
            continue
        try:
            r["GROSS_PROFIT"] = float(gp)
        except (TypeError, ValueError):
            pass
    return rows


def fetch_mainop(secucode: str) -> list:
    """E6 主营构成（东财键名同构）。tushare fina_mainbz 优先（产品P→行业D次序），东财兜底。
    v4.8 起各分部带 GROSS_PROFIT（毛利额，元）：tushare 取 bz_profit（缺则 收入−成本），
    东财取 MAIN_BUSINESS_RPOFIT（缺则 收入×毛利率 折算）。分部净利润无公开数据源，
    业务构成图的利润口径一律为毛利。"""
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
        # 源头重复条目去重（2026-09-02 宝丰实证：fina_mainbz 会同时返回「烯烃产品」与「烯烃」两行，
        # 收入/成本完全一致——同源改名跟踪残留。签名=（收入,成本）全等即同一条业务线，留先发行）
        seen_sig, deduped = set(), []
        for r in items:
            sig = (r.get("bz_sales"), r.get("bz_cost"))
            if sig in seen_sig:
                continue
            seen_sig.add(sig)
            deduped.append(r)
        if len(deduped) < len(items):
            print(f"注：fina_mainbz 重复条目已去重 {len(items)}→{len(deduped)}"
                  f"（同收入同成本，同源改名残留）", file=sys.stderr)
        items = deduped
        total = sum(float(r["bz_sales"]) for r in items if r.get("bz_sales")) or None
        out = []
        for r in items:
            sales = float(r["bz_sales"]) if r.get("bz_sales") else None
            cost = float(r["bz_cost"]) if r.get("bz_cost") else None
            gp = None
            if r.get("bz_profit") is not None:
                gp = float(r["bz_profit"])
            elif sales is not None and cost is not None:
                gp = sales - cost
            out.append({
                "REPORT_DATE": _fmt_date(latest_ed),
                "REPORT_NAME": f"{latest_ed[:4]}年报" if latest_ed.endswith("1231") else latest_ed,
                "MAINOP_TYPE": mainop_type,
                "ITEM_NAME": r.get("bz_item"),
                "MAIN_BUSINESS_INCOME": sales,
                "MBI_RATIO": (sales / total if (sales and total) else None),
                "GROSS_RPOFIT_RATIO": ((sales - cost) / sales if (sales and cost is not None) else None),
                "GROSS_PROFIT": gp,
            })
        return out
    except Exception:
        return _mainop_norm_em(_em_mainop(secucode))


# ---------------- 审计意见（供 L4 红灯 a 项判定，不计入 1D 红旗） ----------------

def fetch_audit(code: str):
    """tushare fina_audit 最新年报审计意见。失败/无数据返回 None。"""
    try:
        rows = ts_call("fina_audit", {"ts_code": to_ts_code(code)})
        if rows:
            rows.sort(key=lambda x: x.get("end_date") or "", reverse=True)
            return rows[0]
    except OSError:
        pass  # 网络层错误静默走降级
    except RuntimeError as e:
        print(f"⚠️ fetch_audit: {e}", file=sys.stderr)
    return None


_RF_CACHE: dict = {}  # 无风险利率按日期缓存：peers 场景每股重复请求同一端点（P1-C）


def fetch_risk_free():
    """中债 10 年期国债到期收益率（东财 RPTA_WEB_TREASURYYIELD；列编码 EMM00166466=10年，
    同页 EMM00588704=2年 / EMM00166462=5年 / EMM00166469=30年）。
    返回 (日期, 收益率%) 或 None。valuation_inputs.risk_free 的直接来源。
    模块级按当日缓存：同进程 peers 批量时只请求一次。"""
    today = date.today().isoformat()
    if today in _RF_CACHE:
        return _RF_CACHE[today]
    try:
        d = get("https://datacenter-web.eastmoney.com/api/data/v1/get?reportName="
                "RPTA_WEB_TREASURYYIELD&columns=ALL&pageSize=1&pageNumber=1")
        row = ((d.get("result") or {}).get("data") or [{}])[0]
        y = row.get("EMM00166466")
        res = ((row.get("SOLAR_DATE") or "")[:10], round(float(y), 2)) if y is not None else None
    except Exception:
        res = None
    _RF_CACHE[today] = res
    return res


def _ttm_cutoff(today: date = None) -> str:
    """近 12 个月窗口起点（YYYYMMDD）。用 today-365 天而非 replace(year-1)，
    避免今天恰好是 2/29 时 replace 崩溃（闰日）。"""
    return ((today or date.today()) - timedelta(days=365)).strftime("%Y%m%d")


def fetch_div_yield(code: str, price: float):
    """TTM 税前股息率（tushare dividend）：只计 div_proc=实施 且除息日在近 12 个月内的
    每股派息合计 ÷ 现价；同除息日多条记录去重。返回 (每股派息, 股息率%, 明细) 或 None。
    valuation_inputs.div_yield 的税前基准（AH/港股按规则自行折税后）。"""
    try:
        rows = ts_call("dividend", {"ts_code": to_ts_code(code),
                                    "fields": "ts_code,end_date,div_proc,cash_div_tax,ex_date"})
        cutoff = _ttm_cutoff()
        by_ex = {}
        for r in rows:
            if (r.get("div_proc") == "实施" and r.get("ex_date") and r.get("cash_div_tax")
                    and r["ex_date"] >= cutoff):
                by_ex.setdefault(r["ex_date"], float(r["cash_div_tax"]))
        if not by_ex or not price:
            return None
        per_share = sum(by_ex.values())
        items = sorted(by_ex.items(), reverse=True)
        return per_share, per_share / price * 100, items
    except Exception:
        return None


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
            end = date.today().strftime("%Y%m%d")
            beg = (date.today() - timedelta(days=430)).strftime("%Y%m%d")
            rows = ts_call("daily", {"ts_code": to_ts_code(code), "start_date": beg, "end_date": end},
                           fields="ts_code,trade_date,close")
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
    except Exception:
        return None


def fetch_debt(code: str):
    """最新报告期有息负债与货币资金（tushare balancesheet）。
    返回 dict（st_borr/non_cur_liab_due_1y/lt_borr/bond_payable/money_cap，单位元）或 None。"""
    try:
        rows = ts_call("balancesheet", {"ts_code": to_ts_code(code), **_fin_rng()})
        rows = [r for r in rows if str(r.get("report_type")) == "1"]
        if not rows:
            return None
        return _pick_latest_per_period(rows)[0]
    except OSError:
        return None  # 网络层错误静默走降级
    except RuntimeError as e:
        print(f"⚠️ fetch_debt: {e}", file=sys.stderr)
        return None


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
        try:
            raw = _get_via_curl(url).decode("utf-8", errors="replace")
        except Exception:
            raw = _get_via_urllib(url).decode("utf-8", errors="replace")
    except Exception as e:
        return {"ok": False, "raw_head": f"[curl/urllib均失败: {e}]", "items": []}
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

def red_flags(annual: list) -> list:
    """盈利质量红旗四项检查（现金含量/应收/存货/毛利率；审计意见已挪出，单独一行输出）。
    annual: 年报列表（新→旧，东财键名同构）。
    三态输出：✓=真通过（有数据且未恶化）/ ✗=真恶化 / △=数据不足——数据缺失显示△，
    绝不显示✓（"✓ API未触发"是虚假通过，芯原股份实证）。"""
    flags = []
    annual = annual[:3]

    # 1. 利润现金含量（经营现金流/净利润 <0.7 视为不达标；数值为倍数如 1.48=148%；
    #    口径：净利润为负的年份该比率无意义，上游已置 None 跳过，不计入连续年数）
    vals = [r.get("NCO_NETPROFIT") for r in annual if r.get("NCO_NETPROFIT") is not None]
    if len(vals) >= 2:
        bad_n = sum(1 for v in vals if v < 0.7)
        if bad_n >= 2:
            flags.append(f"✗ 利润现金含量 连续{bad_n}年<0.7（仅计净利润>0年份）")
        else:
            flags.append(f"✓ 利润现金含量（最低{round(min(vals), 2)}，仅计净利润>0年份）")
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

    return flags


# ---------------- 汇总输出 ----------------

def _sec_e1(secid: str, is_hk: bool, pure: str) -> list:
    """E1 行情估值段：报价、PE/PB 带、披露计划、无风险利率、TTM股息率。"""
    out = []
    try:
        q = fetch_quote(secid, is_hk)
        _E1_CAPTURE.update({"code": q.get("代码"), "name": q.get("名称"),
                            "market": "港股" if is_hk else "A股",
                            "price": q.get("最新价"), "pe_ttm": q.get("PE_TTM"),
                            "pb": q.get("PB"), "mcap_yi": q.get("总市值亿"),
                            "trade_date": q.get("数据日期")})
        cur_s = "HK$" if is_hk else "¥"  # 港股用港元符号，不再硬编码 ¥
        pe_s = "—（缺失，可价格÷EPS手工算）" if q["PE_TTM"] is None else f"{q['PE_TTM']}x"
        out.append(f"## E1 行情估值\n{q['名称']}({q['代码']}) 价{cur_s}{q['最新价']} "
                   f"涨跌{q['涨跌幅%']}% | 市值{q['总市值亿']}亿 | "
                   f"PE(TTM){pe_s} PB{q['PB']}x | 换手{q['换手率%']}%\n")
        if not is_hk:
            band = fetch_pe_pb_band(pure)
            if band:
                _E1_CAPTURE["pe_band"] = [band["pe_min"], band["pe_max"]]
                _E1_CAPTURE["pe_pct"] = band["pe_pct"]
                _E1_CAPTURE["pe_p25"] = band.get("pe_p25")
                _E1_CAPTURE["pe_p75"] = band.get("pe_p75")
                out.append(f"PE(TTM) {band['years']}年带: {band['pe_min']:.1f}~{band['pe_max']:.1f}x，"
                           f"当前分位{band['pe_pct']}% | PB 带: {band['pb_min']:.2f}~{band['pb_max']:.2f}x，"
                           f"当前分位{band['pb_pct']}%（n={band['n']}交易日）\n"
                           f"PE 分位区 P25-P75: {band.get('pe_p25'):.1f}~{band.get('pe_p75'):.1f}x"
                           f"（pe_history 图分位段直接引用）\n")
            else:
                out.append("PE/PB 历史分位带: [未获取到（tushare daily_basic 无数据或样本<20）]"
                           "——请降级：EM 月线×总股本÷TTM净利手工推算分位，或妙想 MCP 直查；"
                           "此带是估值分中枢分核心输入，禁止静默跳过\n")
            disc = fetch_disclosure(pure)
            if disc:
                if disc.get("实际披露"):
                    out.append(f"财报披露: {disc['报告期']} 已于{disc['实际披露']}实际披露"
                               f"（计划{disc.get('计划披露') or '—'}）\n")
                else:
                    out.append(f"财报披露: {disc['报告期']} 计划披露日 {disc['计划披露']}（未披露）\n")
            else:
                out.append("财报披露: [未获取到披露计划，请降级：妙想 MCP mx_finance_search_notice 或交易所官网查证]\n")
        rf = fetch_risk_free()
        if rf:
            _E1_CAPTURE["risk_free"] = rf[1]
            out.append(f"无风险利率（中债10Y）: {rf[1]}%（{rf[0]}，东财国债收益率）"
                       f"——valuation_inputs.risk_free 直接引用此值\n")
        else:
            out.append("无风险利率（中债10Y）: [未获取到（东财国债收益率端点失败），"
                       "请降级：WebSearch 中债 10 年期收益率最近公开值并标估算]\n")
        if not is_hk:
            dy = fetch_div_yield(pure, q.get("最新价"))
            if dy:
                _E1_CAPTURE["div_yield"] = round(dy[1], 2)
                detail = " + ".join(f"{v:g}({d})" for d, v in dy[2])
                out.append(f"TTM股息率（税前）: {dy[1]:.2f}%（近12月每股派息{dy[0]:g}元＝{detail} "
                           f"÷ 现价{q.get('最新价')}，tushare dividend 实施口径）"
                           f"——valuation_inputs.div_yield 税前基准，需税后口径时自行折算\n")
            else:
                out.append("TTM股息率: [近12个月无实施分红记录或 tushare dividend 失败；"
                           "若公司确有分红请手工核查并标注路径]\n")
        # 时机分素材（v4.8）：现价/MA60/MA120/52周高低出自日线序列，随 --out 落盘，
        # fill 时机判定小表的技术面信号一律取自本行，禁止手估（神华假 MA60 同源修复）
        tm = fetch_timing_material(pure, is_hk)
        if tm:
            _E1_CAPTURE["timing"] = tm
            out.append(f"时机素材: 现价{tm['price']} | MA60 {tm.get('ma60')} / "
                       f"MA120 {tm.get('ma120') or '—'} | 52周高低 {tm['high_52w']}/{tm['low_52w']}"
                       f"（{tm['n']}个交易日，日线序列计算——技术面信号一律取自本行，禁止手估）\n")
        else:
            out.append("时机素材: [未获取到（日线序列失败或不足60个交易日），"
                       "技术面信号须注明手工口径与来源]\n")
    except Exception as e:
        out.append(f"## E1 行情估值\n[失败: {e}]\n")
    return out


def _sec_e3_hk(pure: str) -> list:
    """E3 财务年表段（港股分支）。"""
    out = []
    try:
        hk_rows = _ts_hk_annual_rows(pure)
        out.append("## E3 财务年表（年报，tushare hk_income → 东财 HKF10 兜底）")
        out.append("报告期 | 营收亿 | 归母净利亿 | ROE% | 毛利率% | 净利率%")
        for r in hk_rows:
            out.append(f"{r['期']} | {r['营收亿']} | {r['归母净利亿']} | "
                       f"{r['ROE%']} | {r['毛利率%']} | {r['净利率%']}")
        out.append("\n## 盈利质量红旗\n[港股：现金含量/应收/存货周转天数港股接口不提供，按缺失处理；"
                   "毛利率用上表对照同业；审计意见走必查项手工查证]\n")
        out.append("有息负债: [港股分支跳过（tushare balancesheet 不覆盖港股），"
                   "请降级：东财F10资产负债表]\n")
    except Exception as e:
        out.append(f"## E3 财务年表\n[tushare 港股无 hk_income 权限。**优先：妙想 MCP "
                   f"mx_hk_finance_data 直查**（模型直调，实测可用）；次兜底：data-sources.md "
                   f"港股手册 curl RPT_HKF10_FN_MAININDICATOR（字段映射见手册）。tushare 报错: {e}]\n")
    return out


def _sec_e3(pure: str, secucode: str) -> tuple:
    """E3 财务年表段（A股分支）：年表、最新报告期、capex、有息负债；返回 (out, annual)。"""
    out = []
    try:
        annual = _ts_annual_rows(pure, secucode=secucode)
        if not annual:
            raise RuntimeError("tushare 年报序列为空")
    except Exception:
        annual = _em_f10(secucode, size=5, annual_only=True)
    try:
        q1 = _ts_latest_quarter(pure, secucode=secucode) or {}
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
                       f"{yi(r.get('PARENTNETPROFIT'))} | {yoy_text(r.get('PARENTNETPROFITTZ'))} | "
                       f"{pct(r.get('ROEJQ'))} | {pct(r.get('XSMLL'))} | {pct(r.get('XSJLL'))} | "
                       f"{pct(r.get('ZCFZL'))} | {yi(r.get('NETCASH_OPERATE_PK'))} | "
                       f"{(str(round(r['NCO_NETPROFIT'], 2)) if r.get('NCO_NETPROFIT') is not None else '—')}")
    out.append(f"\n最新报告期: {q1.get('REPORT_DATE_NAME')} 净利{yi(q1.get('PARENTNETPROFIT'))}亿 "
               f"同比{yoy_text(q1.get('PARENTNETPROFITTZ'))} | 总股本{yi(q1.get('TOTAL_SHARE'), 2)}亿 | "
               f"ROIC {pct(q1.get('ROIC'))}（{q1.get('REPORT_DATE_NAME')}累计，未年化，季报口径远小于全年，勿直接与 ROE 比）\n")
    capex_bits = [f"{r['REPORT_DATE_NAME']} {yi(r.get('CAPEX'))}亿" for r in annual[:3]
                  if r.get("CAPEX") is not None]
    if capex_bits:
        out.append("资本开支（购建固定资产/无形资产等支付现金，DCF capex 直接取此口径）: "
                   + " ｜ ".join(capex_bits) + "\n")
    # 有息负债（tushare balancesheet 最新报告期；短债=短期借款+一年内到期非流动负债，
    # 长债=长期借款+应付债券；短债覆盖=货币资金÷短债，分母 0 显示「无短债」）
    debt = fetch_debt(pure)
    if debt:
        def _f0(v):
            try:
                return float(v or 0)
            except (TypeError, ValueError):
                return 0.0
        st_debt = _f0(debt.get("st_borr")) + _f0(debt.get("non_cur_liab_due_1y"))
        lt_debt = _f0(debt.get("lt_borr")) + _f0(debt.get("bond_payable"))
        mc = debt.get("money_cap")
        if st_debt <= 0:
            cover = "无短债"
        elif mc is None:
            cover = "—"
        else:
            cover = f"{float(mc) / st_debt:.2f}"
        out.append(f"有息负债 {yi(st_debt + lt_debt)}亿（短债 {yi(st_debt)}亿 / 长债 {yi(lt_debt)}亿）"
                   f"｜货币资金 {yi(mc)}亿｜短债覆盖 {cover}\n")
    else:
        out.append("有息负债: 未获取（tushare balancesheet 失败），请降级：东财F10资产负债表\n")
    return out, annual


def _sec_quality(pure: str, annual: list) -> list:
    """盈利质量红旗 + 审计意见 + 财报可信度（A股，紧跟 E3 年表）。"""
    out = []
    out.append("## 盈利质量红旗\n" + "\n".join(red_flags(annual)) + "\n")
    # 审计意见独立行：供 L4 红灯 a 项判定，不计入 1D 红旗
    audit = fetch_audit(pure)
    if audit:
        out.append(f"审计意见: {(audit.get('audit_result') or '').strip()}"
                   f"（{(audit.get('end_date') or '')[:4]}年报，tushare fina_audit）"
                   f"——供 L4 红灯 a 项判定，不计入 1D 红旗\n")
    else:
        out.append("审计意见: 未获取（tushare fina_audit 失败），请按 SKILL.md Step 1.1 手工查证年报"
                   "——供 L4 红灯 a 项判定，不计入 1D 红旗\n")
    forensic = fetch_forensic(pure)
    if forensic:
        out.append("## 财报可信度（初判）\n" + "\n".join(forensic) + "\n")
    else:
        out.append("## 财报可信度（初判）\n△ 数据不足（tushare 三表缺字段，应计比率/M-Score 无法计算）"
                   "——请降级：东财 F10 补应计/M-Score 输入，或妙想 MCP 直查；"
                   "此评级是 MANDATORY（C→黄灯扣分、D→红灯），禁止静默跳过\n")
    return out


def _sec_e2(secid: str, years: int, is_hk: bool) -> list:
    """E2 月线段：区间、最低/最高/最新、近12月收盘/月末PE(TTM)序列。"""
    out = []
    try:
        kl = fetch_kline_monthly(secid, years, is_hk)
        if kl:
            closes = [k["close"] for k in kl]
            out.append(f"## E2 月线（{len(kl)}期）\n"
                       f"区间 {kl[0]['date']}~{kl[-1]['date']} | "
                       f"最低{min(closes)} 最高{max(closes)} 最新{closes[-1]}\n"
                       f"近12月: " + " ".join(f"{k['close']}/{k['pe']}" if k.get("pe") else str(k['close'])
                                             for k in kl[-12:]) + "\n"
                       f"（近12月格式=月收盘/月末PE(TTM)，无 PE 时仅收盘；price_history 的 pe 字段照抄本序列，"
                       f"不再手工按「月收×总股本÷TTM净利」推算）\n")
    except Exception as e:
        out.append(f"## E2 月线\n[失败: {e}]\n")
    return out


def _sec_e4(pure: str, is_hk: bool) -> list:
    """E4 股东户数段。"""
    out = []
    try:
        h = fetch_holders(pure)
        if h:
            out.append("## E4 股东户数")
            for r in h[:6]:
                num = r.get("HOLDER_NUM")
                num_s = f"{num:,}" if isinstance(num, (int, float)) else "—"
                ratio = r.get("HOLDER_NUM_RATIO")
                # HOLDER_NUM_RATIO 为 None 时不出「变动」段（避免 变动None% 字面量）
                chg_s = f" (变动{round(ratio, 1)}%)" if isinstance(ratio, (int, float)) else ""
                out.append(f"{(r.get('END_DATE') or '')[:10]}: {num_s}户{chg_s}")
            out.append("")
        elif is_hk:
            out.append("## E4 股东户数\n[港股不支持，跳过]\n")
    except Exception as e:
        out.append(f"## E4 股东户数\n[失败: {e}]\n")
    return out


def _sec_forecast(pure: str) -> list:
    """业绩预告/快报段（A股）。"""
    out = []
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
    else:
        out.append("## 业绩预告/快报\n[未获取到（tushare forecast/express 无数据），"
                   "请降级：东财业绩预告公开端点或妙想 MCP 直查；L3 催化剂判断缺少近期业绩信号]\n")
    return out


def _sec_gov(pure: str) -> list:
    """1E 治理段（A股）：质押、增减持、回购。"""
    out = []
    g = fetch_governance(pure)
    glines = []
    if g.get("pledge"):
        p = g["pledge"]
        glines.append(f"质押: 质押比例{p.get('质押比例%')}%（截至{p.get('日期')}）")
    if g.get("trades"):
        t_s = "；".join(f"{t['披露']}{t['股东']}{t['方向']}" for t in g["trades"][:4])
        latest = str(g["trades"][0].get("披露") or "")
        try:  # 最新增减持记录超过 24 个月视为陈旧，提示另行核查近 12 个月
            stale = (date.today() - date(int(latest[:4]), int(latest[4:6]), int(latest[6:8]))).days > 730
        except (ValueError, IndexError):
            stale = False
        if stale:
            t_s += f"（⚠️ 最新记录止于 {latest}，已超 24 个月——近 12 个月增减持须另行核查并标注路径）"
        glines.append(f"增减持: {t_s}")
    if g.get("buyback"):
        b_s = "；".join(f"{b['披露']}回购{b.get('金额') or ''}{b.get('进度') or ''}" for b in g["buyback"][:2])
        glines.append(f"回购: {b_s}")
    if glines:
        out.append("## 1E 治理（tushare）\n" + "\n".join(glines) + "\n")
    else:
        out.append("## 1E 治理\n[未获取到质押/增减持/回购数据，请降级：10jqka event.html 或巨潮手工查，"
                   "或妙想 MCP mx_finance_search_notice 直查；禁止在无数据时给 1E 满分锚定]\n")
    return out


def _sec_e5(pure: str, is_hk: bool) -> list:
    """E5 一致预期段。"""
    out = []
    try:
        c = fetch_consensus(pure)
        if c.get("_src") == "tushare":
            lines = [f"## E5 一致预期（tushare 券商研报，近180天{c['orgs']}家/{c['n_reports']}份）"]
            if not c.get("years"):
                lines.append("[未获取到年度净利预测（report_rc quarter 字段缺失或空），"
                             "预期差拆解档位 B 缺核心输入；请降级：妙想 MCP 直查或东财 RPT_WEB_RESPREDICT 手工 curl]")
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
    return out


def _sec_e6(secucode: str, is_hk: bool) -> list:
    """E6 主营构成段。"""
    out = []
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
            # 毛利占比分母：各分部毛利额合计（v4.8 业务构成图用；分部净利无公开数据，口径=毛利）
            gp_total = sum(float(r["GROSS_PROFIT"]) for r in items if r.get("GROSS_PROFIT")) or None
            out.append(f"## E6 主营构成（{latest}，按{'产品' if typed.get('2') else '行业/地区'}）")
            for r in items:
                ratio = r.get("MBI_RATIO")
                gpr = r.get("GROSS_RPOFIT_RATIO")
                gp = r.get("GROSS_PROFIT")
                gp_pct = (float(gp) / gp_total * 100) if (gp is not None and gp_total) else None
                out.append(f"{r.get('ITEM_NAME')}: 收入{yi(r.get('MAIN_BUSINESS_INCOME'))}亿 "
                           f"占比{ratio is not None and f'{ratio*100:.1f}%' or '—'} "
                           f"毛利率{gpr is not None and f'{gpr*100:.1f}%' or '—'} "
                           f"毛利{yi(gp) if gp is not None else '—'}亿"
                           f"{f'（毛利占比{gp_pct:.1f}%）' if gp_pct is not None else ''}")
            out.append("")
        elif is_hk:
            out.append("## E6 主营构成\n[港股不支持（tushare/东财均无港股主营构成接口），定性搜索补]\n")
        else:
            out.append("## E6 主营构成\n[未获取到主营构成数据，请降级：妙想 MCP 直查或年报定性搜索；"
                       "1B/1C 评分缺核心输入]\n")
    except Exception:
        pass
    return out


def _sec_e7(searches: list) -> list:
    """E7 定性站内搜索段（可选）。"""
    out = []
    # E7 定性站内搜索（可选；tushare news 无权限，保持东财 E7）
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
    return out


def summarize(code: str, years: int, searches: list = None) -> str:
    secid, secucode, is_hk = secid_of(code)
    pure = secucode.split(".")[0]
    mkt = "港股" if is_hk else "A股"
    out = [f"# {pure} 数据摘要（{mkt}）\n"]

    # E1 先跑（K 线缩放校准依赖 E1 的东财报价），其余章节并发（单请求最坏路径约 60s，
    # 串行叠加单股可达分钟级）；max_workers 克制在 4，避免触发限流
    out.extend(_sec_e1(secid, is_hk, pure))

    jobs = []
    if is_hk:
        jobs.append(lambda: _sec_e3_hk(pure))
    else:
        def _e3_and_quality():  # quality 依赖 e3 的 annual，两节绑为一个并发单元
            e3_out, annual = _sec_e3(pure, secucode)
            return e3_out + _sec_quality(pure, annual)
        jobs.append(_e3_and_quality)
    jobs.append(lambda: _sec_e2(secid, years, is_hk))
    jobs.append(lambda: _sec_e4(pure, is_hk))
    if not is_hk:
        jobs.append(lambda: _sec_forecast(pure))
        jobs.append(lambda: _sec_gov(pure))
    jobs.append(lambda: _sec_e5(pure, is_hk))
    jobs.append(lambda: _sec_e6(secucode, is_hk))
    if searches:
        jobs.append(lambda: _sec_e7(searches))

    with ThreadPoolExecutor(max_workers=4) as ex:
        for res in ex.map(lambda f: f(), jobs):  # map 保序：输出章节顺序与串行版一致
            out.extend(res)

    return "\n".join(out)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = {}
    for a in sys.argv[1:]:
        if not a.startswith("--"):
            continue
        if "=" not in a:
            # --peers 这类不带 = 的参数原样会被静默忽略，改为明确报错+用法提示
            print(f"错误：参数 {a} 需要「=值」形式（如 --peers=600309,002001）\n\n用法:{__doc__}",
                  file=sys.stderr)
            sys.exit(2)
        k, v = a[2:].split("=", 1)
        opts[k] = v
    if not args:
        print(__doc__)
        sys.exit(1)
    if not _tushare_token():
        # 硬告警不硬停（东财兜底仍可出报告）：token 缺失时 ts_call 的 RuntimeError 曾被
        # 各 fetch 的裸 except 静默吞掉 → 治理/审计全部输出「未获取到」，agent 白走降级链
        print("⚠️ 硬告警：tushare token 未配置（TUSHARE_TOKEN 环境变量与 ZCode mcp 配置均无）"
              "——PE分位带/财务年表/治理/审计将静默降级或失败，建议先配置再跑", file=sys.stderr)
    try:
        years = int(opts.get("kline-years", "5"))
        if years < 1:
            raise ValueError
    except ValueError:
        print(f"错误：--kline-years 需为正整数，收到 {opts.get('kline-years')!r}", file=sys.stderr)
        sys.exit(2)
    searches = None
    if opts.get("search"):
        searches = [s.strip() for s in opts["search"].split(",") if s.strip()]
    print(summarize(args[0], years, searches))
    if opts.get("out"):
        # E1 落盘：现价/PE/分位带等源头数字写 JSON，fill 的 quote.source_file 引用它，
        # render 时比对 price/pe_ttm 防手填造假（神华 601088 事故修复，偏差>1% 拒渲染）
        if not _E1_CAPTURE:
            print("警告：--out 已指定但 E1 捕获为空（E1 取数失败？），未落盘", file=sys.stderr)
        else:
            _E1_CAPTURE["fetched_at"] = date.today().isoformat()
            _E1_CAPTURE["source"] = "em_fetch.py"
            with open(opts["out"], "w", encoding="utf-8") as f:
                json.dump(_E1_CAPTURE, f, ensure_ascii=False, indent=2)
            print(f"[E1 已落盘] {opts['out']}（fill 的 quote.source_file 引用此文件）",
                  file=sys.stderr)
    for peer in (opts.get("peers") or "").split(","):
        peer = peer.strip()
        if peer:
            print("\n---\n")
            print(summarize(peer, years))


if __name__ == "__main__":
    try:
        main()
    except RateLimitError as e:
        # 限流硬停：不重试，提示稍后重跑，非零退出码供调用方识别
        print(f"[限流硬停] {e}——已停止，请隔几分钟再重跑（频繁请求会触发东财封禁）",
              file=sys.stderr)
        sys.exit(2)
    except ValueError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(2)
