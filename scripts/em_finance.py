#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
em_finance.py — E3 财务取数族（stock-deep-analysis skill 取数分块之一，v4.10.3 自 em_data 拆分）

职责：年报/季报三表与财务指标（tushare income/cashflow/balancesheet/fina_indicator 优先，东财
F10 兜底）、港股年报、审计意见、无风险利率、TTM 股息率、有息负债，以及盈利质量红旗与
M-Score（forensic，7 年三表 + 审计意见）。进程内状态 _EM_F10_CACHE/_EM_F10_PAGE（F10 一次
拉取）与 _RF_CACHE（无风险利率按日）随本块持有。

与其他块的边界（重要）：
- 只依赖 em_core.py，绝不 import 其他取数块（em_market/em_owner/em_misc 同理）。
- 传输函数一律以 `_C.ts_call` / `_C.get` 模块属性形式调用（迟绑定——测试按 em_core 命名空间
  rebind 传输函数与缓存配置须即时传导）；静态 from-import 只用于无 rebind 依赖的纯工具
  （代码映射 / 格式化 / 取数窗口）与跨块共享 helper。
"""
from datetime import date

import em_core as _C
from em_core import (to_ts_code, yi, pct, memo, _yoy, _ts_quiet, _ttm_cutoff,
                     _daily_basic_latest, _em_dc, _fin_rng, _win_years)


# ---------------- E3 财务（年报序列） ----------------

# F10 主要指标进程内一次拉取：_ts_annual_rows(年报补齐)、_ts_latest_quarter(最新一期)、
# _sec_e3 两条兜底（年报5/最新4期）原各发一次东财请求（URL 因 pageSize/filter 各异互不命中缓存）。
# 合一：每 secucode 只拉一次 pageSize=20 无 filter 全量（含季报），各调用点本地过滤切片。
# pageSize=20 的由来：该表按报告期倒序、年报行每 4 期 1 个（实测 600989），
# 最新报告期落在 0331/0630/0930/1231 任一档时，20 行内均至少含 5 个年报行（5 行是最大需求）。
_EM_F10_CACHE: dict = {}
_EM_F10_PAGE = 20


def _f10_is_annual(r: dict) -> bool:
    """东财 F10 年报行判定：REPORT_DATE_NAME 以「年报」结尾（同 REPORT_TYPE="年报" 语义），
    缺失时退 REPORT_DATE（"2025-12-31 00:00:00" 格式）按 12-31 判定。"""
    n = str(r.get("REPORT_DATE_NAME") or "")
    d = str(r.get("REPORT_DATE") or "")
    return n.endswith("年报") or d[:10].endswith("-12-31")


def _em_f10(secucode: str, size: int = 12, annual_only: bool = False) -> list:
    """东财 F10 主要财务指标（按 REPORT_DATE 倒序）。进程内同 secucode 只发一次请求；
    annual_only → 过滤年报行后取前 size 行，否则取最近 size 行（混合报告期）。"""
    def _load():
        return _em_dc("RPT_F10_FINANCE_MAINFINADATA", f'(SECUCODE="{secucode}")',
                      _EM_F10_PAGE, "REPORT_DATE")
    rows = memo(_EM_F10_CACHE, secucode, _load)
    if annual_only:
        rows = [r for r in rows if _f10_is_annual(r)]
    return rows[:size]


def _pick_latest_per_period(rows: list) -> list:
    """同一报告期多次公告时取第一条（tushare 按公告日倒序返回），按报告期倒序。"""
    seen = {}
    for r in sorted(rows, key=lambda x: (x.get("end_date") or "", x.get("ann_date") or ""), reverse=True):
        seen.setdefault(r.get("end_date"), r)
    return [seen[k] for k in sorted(seen, reverse=True)]


def _ts_annual_fetch_3(code: str, rng: dict) -> tuple:
    """拉取并本地过滤三表年报行（income/fina_indicator/cashflow），各自独立失败静默返回空。
    income 额外要求 report_type="1"（防止与合并报表重复行）；ind/cf 沿用原口径不过滤。"""
    ts = to_ts_code(code)
    inc, ind, cf = [], [], []
    try:
        inc = [r for r in _C.ts_call("income", {"ts_code": ts, **rng})
               if (r.get("end_date") or "").endswith("1231") and str(r.get("report_type")) == "1"]
    except Exception:
        pass
    try:
        ind = [r for r in _C.ts_call("fina_indicator", {"ts_code": ts, **rng})
               if (r.get("end_date") or "").endswith("1231")]
    except Exception:
        pass
    try:
        cf = [r for r in _C.ts_call("cashflow", {"ts_code": ts, **rng})
              if (r.get("end_date") or "").endswith("1231")]
    except Exception:
        pass
    return inc, ind, cf


def _ts_annual_em_map(secucode: str, n_years: int) -> dict:
    """东财 F10 直接字段映射（按报告期年份索引），补齐 tushare 缺失的周转天数（中芯国际实证）。"""
    em_map = {}
    if not secucode:
        return em_map
    try:
        for r in _em_f10(secucode, size=n_years, annual_only=True) or []:
            key = (r.get("REPORT_DATE_NAME") or r.get("REPORT_DATE") or "")[:4]
            if key.isdigit():
                em_map[key] = r
    except Exception:
        pass
    return em_map


def _compose_annual_row(r: dict, ind: dict, cf: dict, em: dict) -> dict:
    """单期年报行组装（东财键名同构）。fina_indicator 缺失字段按字段级 fallback 到东财 F10：
    ROE/毛利率/净利率/负债率直接取，周转天数由 tushare 换算、缺期次用东财 YSZKZZTS/CHZZTS 补齐。"""
    ocf = cf.get("n_cashflow_act")
    if ocf is None:
        ocf = em.get("NETCASH_OPERATE_PK")
    ni = r.get("n_income")  # 净利润（含少数股东），与东财现金含量口径一致
    # 周转天数换算：fina_indicator 只给周转率——应收天数=360/ar_turn；
    # 存货天数=turn_days(营业周期)−应收天数（营业周期=存货+应收周转天数）
    ar_days = (360 / ind["ar_turn"]) if ind.get("ar_turn") else None
    inv_days = (ind["turn_days"] - ar_days) if (ind.get("turn_days") is not None
                                                and ar_days is not None) else None
    if ar_days is None:
        ar_days = em.get("YSZKZZTS")
    if inv_days is None:
        inv_days = em.get("CHZZTS")
    return {
        "REPORT_DATE_NAME": f"{r['end_date'][:4]}年报",
        "TOTALOPERATEREVE": r.get("total_revenue"),
        "PARENTNETPROFIT": r.get("n_income_attr_p"),
        "PARENTNETPROFITTZ": None,  # 同比在外层回填（需相邻期）
        # 扣非净利润：tushare fina_indicator profit_dedt 主源，缺期次东财 F10 KCFJCXSYJLR 兜底（v4.9.1）
        "KCFJCXSYJLR": ind.get("profit_dedt") if ind.get("profit_dedt") is not None
        else em.get("KCFJCXSYJLR"),
        # 财务指标字段级 fallback：tushare fina_indicator 缺期次时用东财 F10 补齐
        "ROEJQ": ind.get("roe") if ind.get("roe") is not None else em.get("ROEJQ"),
        "XSMLL": ind.get("grossprofit_margin") if ind.get("grossprofit_margin") is not None
        else em.get("XSMLL"),
        "XSJLL": ind.get("netprofit_margin") if ind.get("netprofit_margin") is not None
        else em.get("XSJLL"),
        "ZCFZL": ind.get("debt_to_assets") if ind.get("debt_to_assets") is not None
        else em.get("ZCFZL"),
        "NETCASH_OPERATE_PK": ocf,
        # 净利润为负时 ocf/ni 无意义：ni≤0 的年份置 None，不计入红旗连续 2 年 <0.7 计数
        "NCO_NETPROFIT": (ocf / ni if (ocf is not None and ni is not None and ni > 0) else None),
        "CAPEX": cf.get("c_pay_acq_const_fiolta"),  # 购建固定资产/无形资产等支付现金（DCF capex 输入）
        "YSZKZZTS": ar_days,
        "CHZZTS": inv_days,
    }


def _ts_annual_rows(code: str, n_years: int = 5, secucode: str = None) -> list:
    """A股年报主要指标（新→旧），映射为东财 F10 同构键名，供年表与红旗共用。
    周转天数优先 tushare fina_indicator 换算；缺失期次用东财 F10 直接字段
    YSZKZZTS/CHZZTS 补齐（tushare 对部分个股该字段覆盖不全，中芯国际实证）。"""
    rng = _fin_rng()  # 统一窗口：与 forensic/最新季度共享缓存（本地过滤，n_years 由切片控制）
    inc, ind, cf = _ts_annual_fetch_3(code, rng)
    if not inc:
        raise RuntimeError("tushare income 无年报数据")
    ind_map = {r["end_date"]: r for r in ind}
    cf_map = {r["end_date"]: r for r in cf}
    em_map = _ts_annual_em_map(secucode, n_years)
    rows = [_compose_annual_row(r, ind_map.get(r["end_date"]) or {},
                                cf_map.get(r["end_date"]) or {}, em_map.get(r["end_date"][:4]) or {})
            for r in _pick_latest_per_period(inc)[:n_years]]
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
    inc = [r for r in _C.ts_call("income", {"ts_code": ts, **rng})
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
        ind = [r for r in _C.ts_call("fina_indicator", {"ts_code": ts, **rng})
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
    beg, end = _win_years(n_years + 1)
    rng = {"start_date": beg, "end_date": end}
    try:
        inc = [r for r in _C.ts_call("hk_income", {"ts_code": ts, **rng})
               if (r.get("end_date") or "").endswith("1231")]
        if not inc:
            raise RuntimeError("tushare hk_income 无年报数据")
        try:
            ind = {r["end_date"]: r for r in _C.ts_call("hk_fina_indicator", {"ts_code": ts, **rng})
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
    try:
        items = _em_dc("RPT_HKF10_FN_MAININDICATOR", f'(SECUCODE="{code}.HK")',
                       max(20, n_years * 6), "REPORT_DATE")
    except Exception:
        return []
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


# E3 A股取数入口：tushare → 东财 F10 的降级链在此收口（v4.10.3 Step 4 自 _sec_e3 下沉），
# 宿主只消费返回值，不再就地 try/except 兜底。
def fetch_annual_rows(code: str, secucode: str) -> list:
    """E3 年表（A股）：tushare 年报序列优先；空序列或取数失败 → 东财 F10 年报行兜底
    （size=5, annual_only=True，与原 _sec_e3 就地降级同参同序）。返回 [] 表示两链皆空。"""
    try:
        annual = _ts_annual_rows(code, secucode=secucode)
        if not annual:
            raise RuntimeError("tushare 年报序列为空")
        return annual
    except Exception:
        return _em_f10(secucode, size=5, annual_only=True)


def fetch_latest_quarter(code: str, secucode: str) -> dict:
    """E3 最新报告期（A股）：tushare 最新季度优先；空返回或取数失败 → 东财 F10 最近一期兜底
    （size=4，与原 _sec_e3 就地降级同参同序）。返回 {} 表示两链皆空。"""
    try:
        q1 = _ts_latest_quarter(code, secucode=secucode) or {}
    except Exception:
        q1 = {}
    if q1:
        return q1
    f10 = _em_f10(secucode, size=4)
    return f10[0] if f10 else {}


# ---------------- 审计意见（供 L4 红灯 a 项判定，不计入 1D 红旗） ----------------
def fetch_audit(code: str):
    """tushare fina_audit 最新年报审计意见。失败/无数据返回 None。"""
    try:
        rows = _C.ts_call("fina_audit", {"ts_code": to_ts_code(code)})
        if rows:
            rows.sort(key=lambda x: x.get("end_date") or "", reverse=True)
            return rows[0]
    except (OSError, RuntimeError) as e:
        _ts_quiet("fetch_audit", e)
    return None


_RF_CACHE: dict = {}  # 无风险利率按日期缓存：peers 场景每股重复请求同一端点（P1-C）


def fetch_risk_free():
    """中债 10 年期国债到期收益率（东财 RPTA_WEB_TREASURYYIELD；列编码 EMM00166466=10年，
    同页 EMM00588704=2年 / EMM00166462=5年 / EMM00166469=30年）。
    返回 (日期, 收益率%) 或 None。valuation_inputs.risk_free 的直接来源。
    模块级按当日缓存：同进程 peers 批量时只请求一次。"""
    today = date.today().isoformat()

    def _load():
        try:
            d = _C.get("https://datacenter-web.eastmoney.com/api/data/v1/get?reportName="
                    "RPTA_WEB_TREASURYYIELD&columns=ALL&pageSize=1&pageNumber=1")
            row = ((d.get("result") or {}).get("data") or [{}])[0]
            y = row.get("EMM00166466")
            return ((row.get("SOLAR_DATE") or "")[:10], round(float(y), 2)) if y is not None else None
        except Exception:
            return None

    return memo(_RF_CACHE, today, _load)


def fetch_div_yield(code: str, price: float):
    """TTM 税前股息率（tushare dividend）：只计 div_proc=实施 且除息日在近 12 个月内的
    每股派息合计 ÷ 现价；同除息日多条记录去重。返回 (每股派息, 股息率%, 明细) 或 None。
    valuation_inputs.div_yield 的税前基准（AH/港股按规则自行折税后）。"""
    try:
        rows = _C.ts_call("dividend", {"ts_code": to_ts_code(code),
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


def fetch_debt(code: str):
    """最新报告期有息负债与货币资金（tushare balancesheet）。
    返回 dict（st_borr/non_cur_liab_due_1y/lt_borr/bond_payable/money_cap，单位元）或 None。"""
    try:
        rows = _C.ts_call("balancesheet", {"ts_code": to_ts_code(code), **_fin_rng()})
        rows = [r for r in rows if str(r.get("report_type")) == "1"]
        if not rows:
            return None
        return _pick_latest_per_period(rows)[0]
    except (OSError, RuntimeError) as e:
        _ts_quiet("fetch_debt", e)
        return None


# ---------------- 盈利质量红旗（forensic：7 年三表 + 审计意见） ----------------
def fetch_forensic(code: str) -> list:
    """财报可信度初判（A股，tushare）：应计比率 + Beneish M-Score + 审计意见 → A/B/C/D。
    金融股（comp_type 2/3/4）不适用 M-Score，输出说明。单项计算失败跳过不报错。
    方法细节见 references/forensic-accounting.md。"""
    try:
        ts = to_ts_code(code)
        rng = _fin_rng()
        inc = _pick_latest_per_period(
            [r for r in _C.ts_call("income", {"ts_code": ts, **rng})
             if (r.get("end_date") or "").endswith("1231") and str(r.get("report_type")) == "1"])[:2]
        if len(inc) < 2:
            return []
        bs = _pick_latest_per_period(
            [r for r in _C.ts_call("balancesheet", {"ts_code": ts, **rng})
             if (r.get("end_date") or "").endswith("1231") and str(r.get("report_type")) == "1"])
        bs_map = {r["end_date"]: r for r in bs}
        cf_map = {r["end_date"]: r for r in _C.ts_call("cashflow", {"ts_code": ts, **rng})
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
                    ind = {r["end_date"]: r for r in _C.ts_call(
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
