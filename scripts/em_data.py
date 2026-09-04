#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
em_data.py — 东财/tushare 取数函数族（em_fetch 拆分子模块之一，v4.8.3）

职责：E1-E6 与审计/治理/估值/时机等全部数据取数函数（fetch_*/_em_*/_ts_*）及随身的
东财端点工具 _em_dc 与序列缓存容器（_HK_DAILY_CACHE/_A_DAILY_CACHE/_EM_F10_CACHE/_RF_CACHE）。

与宿主 em_fetch.py 的边界（重要）：
- test_em_fetch.py 按 em_fetch 命名空间 rebind 传输函数（ts_call/get）与缓存配置
  （_CACHE_DIR/_NO_CACHE）。Python 函数体内自由名解析「定义模块」的 __dict__，若本模块
  静态 import ts_call/get，rebind 不会传导 → 第 6/8-11 段测试失效。故 ts_call/get 经下方
  转发 stub 动态读宿主属性；其余共享工具（映射/格式化/窗口等）无 rebind 依赖，静态绑定。
- 传输/缓存实现（ts_call/get/_dc_* 状态/统计）留在宿主：它们读取的缓存配置须与
  em_fetch 命名空间 rebind 同步，物理移出会破坏磁盘缓存测试语义。
"""

import sys
import urllib.parse
from bisect import bisect_right
from datetime import date, timedelta

import em_fetch as _H  # 宿主模块（循环 import：加载中途为半成品对象，属性延迟到函数运行时解析）

# ---- 动态转发（test_em_fetch 按 em_fetch 命名空间 rebind，须运行时解析宿主）----
def ts_call(api_name: str = None, params: dict = None, fields: str = ""):
    return _H.ts_call(api_name, params, fields)


def get(url: str = None, retries: int = 1):
    """转发宿主 get。只传 url 一个位置参：测试 mock 形如 em.get = lambda url: ...，
    多传 retries 会让单参 mock 报 TypeError。本模块内无多参 get 调用。"""
    return _H.get(url)


# ---- 共享工具静态绑定（无 rebind 依赖）----
from em_fetch import (to_ts_code, yi, pct, _yoy, _r2, _fmt_date, _fin_rng, _ttm_cutoff)  # noqa: E402


def _em_dc(report_name: str, flt: str, page_size: int, sort_columns: str = None) -> list:
    """东财 datacenter 通用取数（securities/api/data/v1/get，columns=ALL，pageNumber=1）。
    flt 为未编码 filter 表达式（如 '(SECUCODE="600989.SH")'，内部统一 quote）；
    sort_columns 给出时按该列倒序（RPT 各表默认 sortTypes=-1）。返回 result.data 列表（可能为空）。
    原 F10 主指标/港股 HKF10/股东户数/一致预期/主营构成 五处重复 URL 拼接收敛于此。"""
    q = ("https://datacenter.eastmoney.com/securities/api/data/v1/get"
         f"?reportName={report_name}&columns=ALL"
         f"&filter={urllib.parse.quote(flt, safe='()')}&pageNumber=1&pageSize={page_size}")
    if sort_columns:
        q += f"&sortTypes=-1&sortColumns={sort_columns}"
    return (get(q).get("result") or {}).get("data") or []


_HK_DAILY_CACHE = {}
_A_DAILY_CACHE = {}  # A股日线序列缓存：fetch_quote(单日涨跌) 与 fetch_timing_material(430天MA) 共用一次拉取


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


def _a_daily_series(ts_code: str, days: int = 430) -> list:
    """A股日线序列（近 days 天）。fetch_quote 单日 pct_chg 与 fetch_timing_material 的
    MA60/MA120/52周高低都出自本序列：E1 内 quote 先于 timing 执行，由 quote 首拉、timing 复用，
    原单日+430天两次请求合一。默认字段拉取（daily 全字段含 pct_chg，不传 fields）。"""
    if ts_code not in _A_DAILY_CACHE:
        end = date.today().strftime("%Y%m%d")
        beg = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
        rows = ts_call("daily", {"ts_code": ts_code, "start_date": beg, "end_date": end})
        if not rows:
            raise RuntimeError("daily 空返回")
        _A_DAILY_CACHE[ts_code] = rows
    return _A_DAILY_CACHE[ts_code]


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
        # fields 必须走第三参（塞 params 会被键归一化剔除→缓存键与 E2 月末PE回填不一致、
        # 且请求全字段拉 5 年，v4.8.3 修复实证）
        rows = ts_call("daily_basic", {"ts_code": to_ts_code(code),
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
        # 与 fetch_pe_pb_band 同参同字段（kline-years=5 时窗口亦同），命中透明缓存不增发请求；
        # 失败静默跳过（仅 close，图降级单线）
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
    rows = _EM_F10_CACHE.get(secucode)
    if rows is None:
        rows = _em_dc("RPT_F10_FINANCE_MAINFINADATA", f'(SECUCODE="{secucode}")',
                      _EM_F10_PAGE, "REPORT_DATE")
        _EM_F10_CACHE[secucode] = rows
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


# ---------------- E4 股东户数 ----------------

def _em_holders(code: str) -> list:
    return _em_dc("RPT_HOLDERNUMLATEST", f'(SECURITY_CODE="{code}")', 8)


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
    data = _em_dc("RPT_WEB_RESPREDICT", f'(SECURITY_CODE="{code}")', 1)
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
    try:
        return _em_dc("RPT_F10_FN_MAINOP", f'(SECUCODE="{secucode}")', 20, "REPORT_DATE")
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
            # E1 内 fetch_quote 先行已用 _a_daily_series 拉 430 天并回填缓存，此处命中即省一发；
            # 读不到（quote 走了东财降级等）才现拉——只读不回填，保持每次调用反映最新源数据
            rows = _A_DAILY_CACHE.get(to_ts_code(code))
            if rows is None:
                end = date.today().strftime("%Y%m%d")
                beg = (date.today() - timedelta(days=430)).strftime("%Y%m%d")
                rows = ts_call("daily", {"ts_code": to_ts_code(code), "start_date": beg, "end_date": end})
                if not rows:
                    raise RuntimeError("daily 空返回")
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
