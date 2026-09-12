#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
em_core.py — 传输/缓存/映射/格式化核心层（stock-deep-analysis skill 专用，v4.10.3 自 em_fetch 拆出）

职责（以下能力的唯一持有者）：
- 传输：tushare ts_call（进程内缓存 + per-key 锁）与东财 get（curl 优先 / urllib 兜底）；
- 缓存状态与统计：_TS_CACHE/_CACHE_DIR/_NO_CACHE/_STATS（IO 原语与 TTL 常量在 em_cache.py）；
- 代码→市场映射（_mkt_of/secid_of/to_ts_code）与格式化/窗口工具（yi/pct/_yoy/yoy_text/…）。

拆出动机（v4.10.3 Step 1）：此前 em_fetch ↔ 取数模块（当时的 em_data.py）互相 import（取数模块
顶层 import em_fetch 并把 ts_call/get 包成转发 stub），导入顺序敏感——新解释器里先 import 取数
模块即 ImportError（partially initialized module）。破环后四个取数块（em_market/em_finance/
em_owner/em_misc）与 em_fetch 只单向依赖本模块，任意导入顺序均可用，也不再需要 sys.modules 引导；
Step 3 起原来被多块共用的 helper（_em_dc/_daily_basic_latest）也归位本模块，块间零横向 import。

rebind 约定：测试（test_em_fetch / test_monthly_checkup）按本模块命名空间直接赋值传输函数
与缓存配置（em_core.ts_call / em_core.get / em_core._CACHE_DIR / …）。消费方必须以
`em_core.X` 模块属性形式解析（各取数块内写 _C.X，em_fetch 内写 _C.X）；静态 from-import
是取值快照，会让 rebind 失效。

数据源优先级：tushare（官方API，口径规范，会员限流保护）优先，东方财富公开接口兜底。
tushare token 自动发现：环境变量 TUSHARE_TOKEN > ZCode config.json 的 mcp.servers.tushare.url。
tushare 不可用时自动回落东财野生端点（curl 传输，防 TLS 指纹限流）。
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from functools import lru_cache

from em_cache import (dc_path, dc_read, dc_write,
                      _TTL_QUOTE, _TTL_FIN, _TTL_GOV, _TS_TIER_QUOTE, _TS_TIER_GOV)


UA = {"User-Agent": "Mozilla/5.0"}
CURL_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
TIMEOUT = 15
TS_API = "https://api.tushare.pro"


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
_TS_LOCKS: dict = {}  # per-key 锁：线程池并发下同冷键只发一次（不同键仍并行）
_TS_DEBUG = os.environ.get("EM_FETCH_DEBUG") == "1"

# 运行统计（EM_FETCH_DEBUG=1 时 main 末尾打一行汇总）：请求数/缓存命中/重试等待。
# 线程池并发自增用锁保护（值只增不减，开销可忽略）。
_STATS = {"ts_net": 0, "ts_mem": 0, "ts_disk": 0, "em_net": 0, "em_disk": 0, "wait": 0}
_STATS_LOCK = threading.Lock()


def _stat(name: str) -> None:
    with _STATS_LOCK:
        _STATS[name] += 1


def memo(cache: dict, key, loader):
    """进程内 get-or-load 单语义（v4.10.3 Step 5 收编四套模块级 dict 缓存）：
    命中（key in cache）直接返回缓存值；未命中调 loader()，把返回值回填 cache 后返回。

    与各调用点原语义的对应关系（收编时逐处核对）：
    - loader 抛异常时不回填、异常原样外溢——即「失败不入缓存」，是否把失败当结果缓存由
      loader 自己决定（返回 []/None 就入缓存，抛异常就不入）；
    - 空值（[]/None）作为**合法缓存值**回填，不会因 falsy 被当作 miss 重取；
    - cache 容器由调用方持有，本函数不替换、不改名、不清理——测试直接捅这四个 dict
      （test_em_fetch 的 _TS_CACHE.clear() / _HK_DAILY_CACHE.pop()），容器身份不可变。"""
    if key in cache:
        return cache[key]
    val = loader()
    cache[key] = val
    return val


# ---------------- 磁盘缓存（跨进程，P0-B） ----------------
# 每份报告是一个新进程、每股 15-20 请求，同日重跑/check 修复循环/peers 批量全量重发，
# 痛点是 tushare 限流额度消耗（report_rc 等接口 1次/分钟）与东财野生端点封禁风险。
# TTL 分档与 IO 原语（原子写/TTL 判定/键路径）在 em_cache.py（参数化纯函数）；本模块持有
# 两个可 rebind 的配置状态（test_em_fetch 按 em_core 命名空间直接赋值），经参数传入原语。
_CACHE_DIR = os.path.join(tempfile.gettempdir(), "em_fetch_cache")
_NO_CACHE = os.environ.get("EM_FETCH_NO_CACHE") == "1"


def ts_call(api_name: str, params: dict = None, fields: str = "") -> list:
    """tushare HTTP API。返回 list[dict]（fields↔items 对齐）。失败抛异常由调用方兜底。
    缓存键归一化：params 里的 "fields" 是 no-op（tushare 只认 payload 顶层 fields），剔除后参与键。
    线程安全：per-key 锁保证同冷键（内存 miss + 磁盘 miss）只发一次网络；锁只覆盖单键，
    不同键在 4 worker 线程池下仍并行；第二线程等锁后命中先行者写入的内存缓存直接返回。"""
    norm = dict(params or {})
    norm.pop("fields", None)
    key = (api_name, tuple(sorted(norm.items())), fields)
    if key in _TS_CACHE:
        _stat("ts_mem")
        if _TS_DEBUG:
            print(f"[cache-hit] {api_name} {dict(norm)}", file=sys.stderr)
        return _TS_CACHE[key]
    with _TS_LOCKS.setdefault(key, threading.Lock()):
        if key in _TS_CACHE:  # 等锁期间同键已被其他线程拉取
            _stat("ts_mem")
            if _TS_DEBUG:
                print(f"[cache-hit] {api_name} {dict(norm)}", file=sys.stderr)
            return _TS_CACHE[key]
        # 磁盘缓存（跨进程）：行情 2h / 财务 12h / 治理 24h
        tier = (_TTL_QUOTE if api_name in _TS_TIER_QUOTE
                else _TTL_GOV if api_name in _TS_TIER_GOV else _TTL_FIN)
        dp = dc_path(_CACHE_DIR, "ts", repr(key))
        cached = dc_read(dp, tier, _NO_CACHE)
        if cached is not None:
            _TS_CACHE[key] = cached
            _stat("ts_disk")
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
        dc_write(dp, rows, _NO_CACHE, _CACHE_DIR)
        _stat("ts_net")
        if _TS_DEBUG:
            print(f"[net] {api_name} {dict(norm)} -> {len(rows)} rows", file=sys.stderr)
        return rows


def _ts_quiet(label: str, exc: Exception) -> None:
    """tushare 取数点的统一错误政策（v4.10.3 账本第 8 项，收编原六处成对 except）：
    OSError（网络层）静默走降级；RuntimeError（token 未配置/接口报错）打 ⚠️ 到 stderr
    后同样降级。神华事故教训：RuntimeError 曾被裸 except 整段静默吞掉，白走降级链。
    调用方固定写 `except (OSError, RuntimeError) as e: _ts_quiet(label, e)`——OSError 与
    RuntimeError 互不继承，合并捕获与原先两个顺序 except 完全等价；其余异常不在捕获
    范围内，照旧向上抛，本 helper 不吞任何原本会外溢的异常。"""
    if not isinstance(exc, OSError):
        print(f"⚠️ {label}: {exc}", file=sys.stderr)


def _win_days(n: int) -> tuple:
    """近 n 天请求窗口 (start_date, end_date)：end=今天、beg=今天-n 天（均 YYYYMMDD）。
    两个端点取自同一次 date.today()，不会跨午夜各取一次。"""
    today = date.today()
    return (today - timedelta(days=n)).strftime("%Y%m%d"), today.strftime("%Y%m%d")


def _win_years(n: int, end: str = None) -> tuple:
    """近 n 整年请求窗口 (start_date, end_date)：beg=今年-n 的 1 月 1 日，end 非空时
    原样使用、缺省为今天；东财月K线传 "20991231" 作无上界哨兵（非真实日期）。"""
    return f"{date.today().year - n}0101", end or date.today().strftime("%Y%m%d")


def _fin_rng() -> dict:
    """财务三表/指标的统一取数窗口（当年-7 起，覆盖 forensic 7 年/年表 5 年/最新季度 2 年三处需求），
    配合 ts_call 缓存：income/cashflow/balancesheet/fina_indicator 每股只发 1 次请求。"""
    beg, end = _win_years(7)
    return {"start_date": beg, "end_date": end}


def _daily_basic_latest(code: str) -> dict:
    """daily_basic 最近一行（15 日窗口 + 最小字段）。em_market.fetch_quote 与
    em_finance._ts_latest_quarter 共用，替代两处无窗口全量拉取（拉十年全量只为 max 最新行）；
    空日期行过滤后再 max（None 陷阱）。v4.10.3 Step 3 自 em_data 归位本模块——跨块共享，
    而块间只许依赖 em_core，故不能留在任一取数块。"""
    beg, end = _win_days(15)
    rows = ts_call("daily_basic",
                   {"ts_code": to_ts_code(code), "start_date": beg, "end_date": end},
                   fields="ts_code,trade_date,close,pe_ttm,pb,total_mv,turnover_rate,total_share")
    rows = [r for r in rows if r.get("trade_date")]
    if not rows:
        raise RuntimeError("daily_basic 空返回")
    return max(rows, key=lambda x: x["trade_date"])


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


def get(url: str, retries: int = 1, raw: bool = False):
    """curl 优先、urllib 兜底（TLS 指纹规避），失败重试 1 次。
    raw=False（缺省）返回解析后的 JSON dict；raw=True 返回解码后的原始文本（str），供 jsonp
    等非纯 JSON 端点（E7 站内搜索）共用同一条管线——重试、429/5xx 硬停、_stat 统计与磁盘
    缓存 tier 判定对两者一致。
    重试仅限网络层错误（超时/连接失败/异常响应体）；HTTP 错误响应（4xx/5xx）不重试、
    不换传输层重打，429/5xx 抛 RateLimitError 由 main 限流硬停。
    磁盘缓存：push2/push2his 行情 2h、datacenter 数据 12h（跨进程去重），其余 URL 不缓存。"""
    tier = _TTL_QUOTE if "push2" in url else _TTL_FIN if "datacenter" in url else 0
    dp = dc_path(_CACHE_DIR, "em", url) if tier else None
    if dp:
        cached = dc_read(dp, tier, _NO_CACHE)
        if cached is not None:
            _stat("em_disk")
            return cached
    last_err = None
    for attempt in range(retries + 1):
        for transport in (_get_via_curl, _get_via_urllib):
            try:
                text = transport(url).decode("utf-8")
                d = text if raw else json.loads(text)
                if dp:
                    dc_write(dp, d, _NO_CACHE, _CACHE_DIR)
                _stat("em_net")
                return d
            except (RateLimitError, HttpStatusError):
                raise  # HTTP 错误响应：原样抛出，不重试
            except Exception as e:
                last_err = e
        if attempt < retries:
            _stat("wait")
            time.sleep(1.5)
    raise last_err


def _em_dc(report_name: str, flt: str, page_size: int, sort_columns: str = None) -> list:
    """东财 datacenter 通用取数（securities/api/data/v1/get，columns=ALL，pageNumber=1）。
    flt 为未编码 filter 表达式（如 '(SECUCODE="600989.SH")'，内部统一 quote）；
    sort_columns 给出时按该列倒序（RPT 各表默认 sortTypes=-1）。返回 result.data 列表（可能为空）。
    原 F10 主指标/港股 HKF10/股东户数/一致预期/主营构成 五处重复 URL 拼接收敛于此。
    v4.10.3 Step 3 自 em_data 归位本模块：被 em_finance（F10/HKF10）与 em_owner（户数/预期/主营）
    两块共用，块间只许依赖 em_core。"""
    q = ("https://datacenter.eastmoney.com/securities/api/data/v1/get"
         f"?reportName={report_name}&columns=ALL"
         f"&filter={urllib.parse.quote(flt, safe='()')}&pageNumber=1&pageSize={page_size}")
    if sort_columns:
        q += f"&sortTypes=-1&sortColumns={sort_columns}"
    return (get(q).get("result") or {}).get("data") or []


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


def _ttm_cutoff(today: date = None) -> str:
    """近 12 个月窗口起点（YYYYMMDD）。用 today-365 天而非 replace(year-1)，
    避免今天恰好是 2/29 时 replace 崩溃（闰日）。"""
    return ((today or date.today()) - timedelta(days=365)).strftime("%Y%m%d")
