#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
em_fetch.py — 批量取数脚本（stock-deep-analysis skill 专用，v4.8.3 起拆分为多模块）

模块分工：
    em_fetch.py   宿主：E7 定性站内搜索与输出组装（search_e7/red_flags/_sec_*/summarize/main/CLI）。
                 传输/缓存/映射/格式化由 em_core.py 提供，取数函数族从四个取数块 re-export
                 供宿主函数体与测试按名访问（em_fetch 是取数能力的唯一汇总出口）。
    em_core.py   传输/缓存/映射/格式化核心层（ts_call/get + 磁盘缓存状态与统计、代码映射、
                 格式化与取数窗口工具、跨块共享 helper）。测试按 em_core 命名空间 rebind
                 传输函数与缓存配置。
    em_market.py E1 行情 / E2 月线 / PE-PB 分位带 / 时机素材（日线序列缓存随块持有）。
    em_finance.py E3 财务年表与季度指标（F10 缓存随块持有）+ 审计意见 / 无风险利率 / TTM 股息率
                 / 有息负债 + 盈利质量红旗 forensic。
    em_owner.py  E4 股东户数 / E5 一致预期 / E6 主营构成。
    em_misc.py   业绩预告快报 / 治理包 / 披露计划。
    em_cache.py  磁盘缓存参数化原语（原子写/TTL/键路径）与 TTL/tier 常量。
    （四个取数块只依赖 em_core.py，彼此不 import；传输层一律以 `em_core.X` 模块属性形式调用）

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
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import em_core as _C
# 兼容性 re-export：外部按 em_fetch.X 按名访问（score_calibration / monthly_checkup / 测试），
# 均为本模块原有的模块级名字；内部调用一律走 _C.<name>，此处名字不参与内部解析。
from em_core import (  # noqa: F401
    UA, CURL_UA, TIMEOUT, TS_API,
    RateLimitError, HttpStatusError,
    _MKT_MAP, _MKT_SZ, _MKT_HK, _mkt_of, secid_of, to_ts_code,
    _tushare_token,
    _TS_CACHE, _TS_LOCKS, _TS_DEBUG, _STATS, _STATS_LOCK, _stat, _CACHE_DIR, _NO_CACHE,
    ts_call, _fin_rng, _get_via_curl, _get_via_urllib, get,
    yi, _r2, pct, _yoy, yoy_text, _fmt_date, _ttm_cutoff,
)

# Windows 控制台默认 GBK 编码，打印中文/货币符号会 UnicodeEncodeError —— 强制 UTF-8
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# E1 落盘捕获：_sec_e1 成功路径填充，main() 的 --out 把它写成 JSON（现价防伪通道的源头）
_E1_CAPTURE: dict = {}


# ---------------- 取数函数族 re-export（四个取数块，v4.10.3 Step 3 起） ----------------
# 从取数块 re-export 供宿主函数体与 score_calibration（import em_fetch as em 按名访问）
# 实际消费的名字，历史上面向"全量门面"的纯挂名已收窄；em_fetch 是唯一汇总出口。
# 传输函数不是内部解析路径：宿主一律走 _C.<name>（迟绑定），em_fetch.ts_call 只是 em_core
# 的兼容别名——rebind 目标是 em_core 命名空间（约定见 em_core.py 文件头）。
from em_market import (  # noqa: E402,F401
    _em_quote, _em_kline_url,
    fetch_pe_pb_band, fetch_quote, fetch_kline_monthly, fetch_timing_material,
)
from em_finance import (  # noqa: E402,F401
    _em_f10, _ts_annual_rows, _ts_latest_quarter, _ts_hk_annual_rows,
    fetch_annual_rows, fetch_latest_quarter,
    fetch_forensic, fetch_audit, fetch_risk_free, fetch_div_yield, fetch_debt,
)
from em_owner import (  # noqa: E402,F401
    fetch_holders, fetch_consensus, fetch_mainop,
)
from em_misc import (  # noqa: E402,F401
    fetch_forecast_express, fetch_governance, fetch_disclosure,
)


# ---------------- E7 定性站内搜索（东财，走 em_core.get 统一管线） ----------------

def search_e7(keyword: str, types: list = None, page_size: int = 8) -> dict:
    """E7 东方财富站内搜索。types: cmsArticleWebOld(新闻), cmsResearchWeb(研报) 等。
    返回 {'ok': bool, 'raw_head': str, 'items': [...]}。失败时 raw_head 含原始返回前 500 字符。
    传输走 em_core.get(url, raw=True)（jsonp 需原始文本）：重试/429 硬停/_stat/磁盘判定与
    其余取数同规；RateLimitError 原样上抛（由 main 限流硬停），其他传输/解析失败转 ok=False。"""
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
        raw = _C.get(url, raw=True)
    except RateLimitError:
        raise  # 429/5xx 硬停纪律：E7 不再把限流降级成 ok=False
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
        # fill 时机判定小表的技术面信号一律取自本行，禁止手估（神华假 MA60 同源修复）；
        # 月收序列不在此重复——归 E2 月线输出（月度收盘/月末PE，price_history 的 pe 字段照抄 E2）
        tm = fetch_timing_material(pure, is_hk)
        if tm:
            _E1_CAPTURE["timing"] = tm
            out.append(f"时机素材: 现价{tm['price']} | MA60 {tm.get('ma60')} / "
                       f"MA120 {tm.get('ma120') or '—'} | 52周高低 {tm['high_52w']}/{tm['low_52w']}"
                       f"（{tm['n']}个交易日，日线序列计算——技术面信号一律取自本行，禁止手估；"
                       f"月收序列见 E2，勿在本行重建口径）\n")
        else:
            out.append("时机素材: [未获取到（日线序列失败或不足60个交易日），"
                       "技术面信号须注明手工口径与来源；月收序列仍以 E2 月线输出为准]\n")
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
        out.append(f"## E3 财务年表\n[未获取到港股财务年表（tushare 无 hk_income 权限: {e}），"
                   f"请降级：**优先妙想 MCP mx_hk_finance_data 直查**（模型直调，实测可用）；"
                   f"次兜底：data-sources.md 港股手册 curl RPT_HKF10_FN_MAININDICATOR"
                   f"（字段映射见手册）]\n")
    return out


def _sec_e3(pure: str, secucode: str) -> tuple:
    """E3 财务年表段（A股分支）：年表、最新报告期、capex、有息负债；返回 (out, annual)。
    两条降级链（tushare 年报序列 / 最新季度 → 东财 F10）已下沉数据层 fetch_annual_rows /
    fetch_latest_quarter（v4.10.3 Step 4），本段只消费返回值。"""
    out = []
    annual = fetch_annual_rows(pure, secucode)
    q1 = fetch_latest_quarter(pure, secucode)
    if not annual:
        out.append("## E3 财务年表\n[tushare 与东财均失败，按降级链走妙想 mx_ashare_finance_data 直查]\n")
    else:
        out.append("## E3 财务年表（年报）\n"
                   "报告期 | 营收亿 | 归母净利亿 | 扣非净利亿 | 同比% | ROE% | 毛利率% | 净利率% | 负债率% | 经营现金流亿 | 现金含量")
        for r in annual:
            out.append(f"{r.get('REPORT_DATE_NAME')} | {yi(r.get('TOTALOPERATEREVE'))} | "
                       f"{yi(r.get('PARENTNETPROFIT'))} | {yi(r.get('KCFJCXSYJLR'))} | "
                       f"{yoy_text(r.get('PARENTNETPROFITTZ'))} | "
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
    # 周转天数逐年行（旧→新，v4.9.1）：fin_trend 应收/存货周转天数面板照抄本行
    def _d0(v):
        return str(round(v)) if v is not None else "—"
    turnover_bits = [f"{r['REPORT_DATE_NAME']} 应收{_d0(r.get('YSZKZZTS'))}/存货{_d0(r.get('CHZZTS'))}"
                     for r in reversed(annual)
                     if r.get("YSZKZZTS") is not None or r.get("CHZZTS") is not None]
    if turnover_bits:
        out.append("周转天数（应收/存货，天；旧→新，fin_trend 周转天数面板照抄本行）: "
                   + " ｜ ".join(turnover_bits) + "\n")
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
    except Exception as e:
        if not any(l.startswith("## E6") for l in out):
            out.append("## E6 主营构成")
        out.append(f"[失败: {e}]\n")
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

    # E1 并入并发池（v4.8.3 评估）：原「E1 先跑供 K 线缩放校准」的理由不成立——E2 东财兜底
    # _em_kline_monthly 在函数内自调 fetch_quote 取价校准，不依赖 E1 先行；_E1_CAPTURE 仅
    # _sec_e1 写入、main 在线程池 join（with 块退出）后才读，无时序竞态；map 保序使 E1 输出
    # 仍居首。E1 入池后其串行的 6 个取数与其余章节并行，缩短整段等待；同冷键并发由
    # ts_call per-key 锁兜底（quote 先拉 430 天 daily、timing 同 E1 job 内串行复用不受影响）。
    # 唯一新增并发面：tushare 全失败降级东财时 E2 校准的 fetch_quote 与 E1 东财 quote 同 URL，
    # 罕见且 get 有 2h 磁盘缓存兜底，可接受。
    jobs = [lambda: _sec_e1(secid, is_hk, pure)]
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
    if not _C._tushare_token():
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


def _debug_summary() -> None:
    """EM_FETCH_DEBUG=1：运行末尾 stderr 打一行汇总（请求数/缓存命中/重试等待）。
    逐请求 [net]/[cache-hit]/[disk-hit] 行仍保留供单点诊断，本行为整体效率画像。"""
    if not _TS_DEBUG:
        return
    print(f"[em_fetch stats] tushare请求 {_STATS['ts_net']} | 进程缓存命中 {_STATS['ts_mem']} | "
          f"磁盘缓存命中(ts {_STATS['ts_disk']} / em {_STATS['em_disk']}) | "
          f"东财网络 {_STATS['em_net']} | 网络重试等待 {_STATS['wait']} 次", file=sys.stderr)


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
    finally:
        _debug_summary()
