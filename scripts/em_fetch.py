#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
em_fetch.py — 东方财富公开接口批量取数脚本（stock-deep-analysis skill 专用）

用法:
    python em_fetch.py 600989                    # 目标公司全量取数
    python em_fetch.py 600989 --peers=600309,002001   # 目标 + 可比公司
    python em_fetch.py 600989 --kline-years=5    # 月K线回溯年数（默认5）
    python em_fetch.py 600989 --search="收购,减持,新华三"  # E7 定性站内搜索（可多关键词，逗号分隔）

输出: 紧凑 Markdown 摘要到 stdout（约 2KB），原始 JSON 不落盘不进上下文。
覆盖: E1 行情估值 / E2 月线 / E3 F10 主要指标 / E4 股东户数 / E5 一致预期 / E6 主营构成
"""
import json
import subprocess
import sys
import time
import urllib.request
import urllib.parse

UA = {"User-Agent": "Mozilla/5.0"}
CURL_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
TIMEOUT = 15


def secid_of(code: str):
    """返回 (secid, secucode, is_hk)。港股：5位数字（如 06082/01880）→ 116. 前缀"""
    code = code.strip().upper().replace(".SH", "").replace(".SZ", "").replace(".BJ", "").replace(".HK", "")
    if code.startswith(("60", "68")):
        return f"1.{code}", f"{code}.SH", False
    if code.isdigit() and len(code) == 5:
        return f"116.{code}", f"{code}.HK", True
    return f"0.{code}", f"{code}.SZ", False


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
    """元 -> 亿"""
    if x is None:
        return "—"
    try:
        return f"{float(x) / 1e8:.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def pct(x, digits=1):
    if x is None:
        return "—"
    try:
        return f"{float(x):.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def fetch_quote(secid: str, is_hk: bool = False) -> dict:
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
        "总市值亿": round((d.get("f116") or 0) / 1e8, 1),
        "PE_TTM": None if pe == 0 else pe,   # 港股 f162=0 = 缺失
        "PB": div_r(d.get("f167")),
        "换手率%": div_r(d.get("f168")),
    }


def fetch_kline_monthly(secid: str, years: int, is_hk: bool = False) -> list:
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
    return out


def fetch_f10(secucode: str, size: int = 12, annual_only: bool = False) -> list:
    if annual_only:
        flt = urllib.parse.quote(f'(SECUCODE="{secucode}")(REPORT_TYPE="年报")', safe="()")
    else:
        flt = urllib.parse.quote(f'(SECUCODE="{secucode}")', safe="()")
    url = (f"https://datacenter.eastmoney.com/securities/api/data/v1/get"
           f"?reportName=RPT_F10_FINANCE_MAINFINADATA&columns=ALL&filter={flt}"
           f"&pageNumber=1&pageSize={size}&sortTypes=-1&sortColumns=REPORT_DATE")
    return (get(url).get("result") or {}).get("data") or []


def fetch_holders(code: str) -> list:
    flt = urllib.parse.quote(f'(SECURITY_CODE="{code}")', safe="()")
    url = (f"https://datacenter.eastmoney.com/securities/api/data/v1/get"
           f"?reportName=RPT_HOLDERNUMLATEST&columns=ALL&filter={flt}&pageNumber=1&pageSize=8")
    return (get(url).get("result") or {}).get("data") or []


def fetch_consensus(code: str) -> dict:
    flt = urllib.parse.quote(f'(SECURITY_CODE="{code}")', safe="()")
    url = (f"https://datacenter.eastmoney.com/securities/api/data/v1/get"
           f"?reportName=RPT_WEB_RESPREDICT&columns=ALL&filter={flt}&pageNumber=1&pageSize=1")
    data = (get(url).get("result") or {}).get("data") or []
    return data[0] if data else {}


def fetch_mainop(secucode: str) -> list:
    flt = urllib.parse.quote(f'(SECUCODE="{secucode}")', safe="()")
    url = (f"https://datacenter.eastmoney.com/securities/api/data/v1/get"
           f"?reportName=RPT_F10_FN_MAINOP&columns=ALL&filter={flt}"
           f"&pageNumber=1&pageSize=20&sortTypes=-1&sortColumns=REPORT_DATE")
    try:
        return (get(url).get("result") or {}).get("data") or []
    except Exception:
        return []


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


def red_flags(annual: list) -> list:
    """盈利质量红旗五项检查。annual: 年报列表（新→旧）。
    三态输出：✓=真通过（有数据且未恶化）/ ✗=真恶化 / △=数据不足——数据缺失显示△，
    绝不显示✓（"✓ API未触发"是虚假通过，芯原股份实证）。审计意见为必查项（另走查证）。"""
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

    flags.append("△ 审计意见（必查项：按 SKILL.md Step 1.1 查证年报后填写，禁止直接沿用本行）")
    return flags


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
    except Exception as e:
        out.append(f"## E1 行情估值\n[失败: {e}]\n")

    if is_hk:
        # 港股：E3/E4/E5/E6 脚本不支持 → 提示走 data-sources.md 港股手册
        out.append("## E3 财务年表\n[港股：脚本不直接取数。按 data-sources.md 港股手册用 curl 调 "
                   "RPT_HKF10_FN_MAININDICATOR 取数（字段名与A股不同，见手册映射表）]\n")
        out.append("## 盈利质量红旗\n[港股：仅毛利率可用 HKF10 字段 GROSS_PROFIT_RATIO 手工核对；"
                   "现金含量/应收/存货周转天数港股接口不提供，按缺失处理，审计意见走必查项]\n")
    else:
        try:
            f10 = fetch_f10(secucode, size=4)
            annual = fetch_f10(secucode, size=5, annual_only=True)
            out.append("## E3 财务年表（年报）\n"
                       "报告期 | 营收亿 | 归母净利亿 | 同比% | ROE% | 毛利率% | 净利率% | 负债率% | 经营现金流亿 | 现金含量")
            for r in annual:
                out.append(f"{r.get('REPORT_DATE_NAME')} | {yi(r.get('TOTALOPERATEREVE'))} | "
                           f"{yi(r.get('PARENTNETPROFIT'))} | {pct(r.get('PARENTNETPROFITTZ'))} | "
                           f"{pct(r.get('ROEJQ'))} | {pct(r.get('XSMLL'))} | {pct(r.get('XSJLL'))} | "
                           f"{pct(r.get('ZCFZL'))} | {yi(r.get('NETCASH_OPERATE_PK'))} | "
                           f"{(str(round(r['NCO_NETPROFIT'], 2)) if r.get('NCO_NETPROFIT') is not None else '—')}")
            q1 = f10[0] if f10 else {}
            out.append(f"\n最新报告期: {q1.get('REPORT_DATE_NAME')} 净利{yi(q1.get('PARENTNETPROFIT'))}亿 "
                       f"同比{pct(q1.get('PARENTNETPROFITTZ'))} | 总股本{yi(q1.get('TOTAL_SHARE'), 2)}亿 | "
                       f"ROIC {pct(q1.get('ROIC'))}\n")
            out.append("## 盈利质量红旗\n" + "\n".join(red_flags(annual)) + "\n")
        except Exception as e:
            out.append(f"## E3 财务\n[失败: {e}]\n")

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
                out.append(f"{(r.get('END_DATE') or '')[:10]}: {r.get('HOLDER_NUM')}户 "
                           f"(变动{r.get('HOLDER_NUM_RATIO') and round(r['HOLDER_NUM_RATIO'], 1)}%)")
            out.append("")
        elif is_hk:
            out.append("## E4 股东户数\n[港股不支持，跳过]\n")
    except Exception as e:
        out.append(f"## E4 股东户数\n[失败: {e}]\n")

    try:
        c = fetch_consensus(pure)
        if c:
            out.append(f"## E5 一致预期\n"
                       f"覆盖{c.get('RATING_ORG_NUM')}家: 买入{c.get('RATING_BUY_NUM')} "
                       f"增持{c.get('RATING_ADD_NUM')} 中性{c.get('RATING_NEUTRAL_NUM') or 0} | "
                       f"目标价{c.get('DEC_AIMPRICEMIN')}-{c.get('DEC_AIMPRICEMAX')}\n"
                       f"EPS: {c.get('YEAR1')}{c.get('YEAR_MARK1')}={c.get('EPS1') and round(c['EPS1'], 2)} "
                       f"{c.get('YEAR2')}{c.get('YEAR_MARK2')}={c.get('EPS2') and round(c['EPS2'], 2)} "
                       f"{c.get('YEAR3')}{c.get('YEAR_MARK3')}={c.get('EPS3') and round(c['EPS3'], 2)}\n"
                       f"行业: {c.get('INDUSTRY_BOARD')} | 概念: {(c.get('CONCEPTINDEX_BOARD') or '')[:80]}\n")
        elif is_hk:
            out.append("## E5 一致预期\n[港股无东财覆盖（实测空返回），预期差按档位C处理]\n")
    except Exception as e:
        out.append(f"## E5 一致预期\n[失败: {e}]\n")

    try:
        mo = fetch_mainop(secucode)
        # MAINOP_TYPE: 1=行业 2=产品 3=地区；优先展示按产品，其次按行业
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
            out.append(f"## E6 主营构成（{latest}，按{'产品' if typed.get('2') else '行业'}）")
            for r in items:
                ratio = r.get("MBI_RATIO")
                gpr = r.get("GROSS_RPOFIT_RATIO")
                out.append(f"{r.get('ITEM_NAME')}: 收入{yi(r.get('MAIN_BUSINESS_INCOME'))}亿 "
                           f"占比{ratio is not None and f'{ratio*100:.1f}%' or '—'} "
                           f"毛利率{gpr is not None and f'{gpr*100:.1f}%' or '—'}")
            out.append("")
        elif is_hk:
            out.append("## E6 主营构成\n[港股不支持（RPT_HKF10_FN_MAINOP 不存在），定性搜索补]\n")
    except Exception:
        pass

    # E7 定性站内搜索（可选）
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
