#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
em_misc.py — 预告快报 / 治理 / 披露杂项取数族（stock-deep-analysis skill 取数分块之一，v4.10.3 自 em_data 拆分）

职责：业绩预告与快报（tushare forecast/express）、治理包（质押统计 / 增减持 / 回购）、下一次
财报披露计划。盈利质量红旗与审计意见归 em_finance.py（不在本块）。

与其他块的边界（重要）：
- 只依赖 em_core.py，绝不 import 其他取数块（em_market/em_finance/em_owner 同理）。
- 传输函数一律以 `_C.ts_call` / `_C.get` 模块属性形式调用（迟绑定——测试按 em_core 命名空间
  rebind 传输函数与缓存配置须即时传导）；静态 from-import 只用于无 rebind 依赖的纯工具
  （代码映射 / 格式化 / 取数窗口）与跨块共享 helper。
"""
import em_core as _C
from em_core import (to_ts_code, yi, pct, _ts_quiet)


def fetch_forecast_express(code: str) -> list:
    """业绩预告 + 业绩快报（tushare forecast/express，按报告期合并去重，新→旧最多4条）。"""
    try:
        out = []
        for r in _C.ts_call("forecast", {"ts_code": to_ts_code(code)}):
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
        for r in _C.ts_call("express", {"ts_code": to_ts_code(code)}):
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


def fetch_governance(code: str) -> dict:
    """1E 治理包（tushare）：质押统计 / 增减持 / 回购。各项独立失败返回空，不影响其他项。"""
    ts = to_ts_code(code)
    g = {"pledge": None, "trades": [], "buyback": []}
    try:
        rows = _C.ts_call("pledge_stat", {"ts_code": ts})
        if rows:
            r = max(rows, key=lambda x: x.get("end_date") or "")
            g["pledge"] = {"日期": r.get("end_date"), "质押比例%": r.get("pledge_ratio")}
    except (OSError, RuntimeError) as e:
        _ts_quiet("fetch_governance pledge_stat", e)
    try:
        rows = _C.ts_call("stk_holdertrade", {"ts_code": ts})
        rows = [r for r in rows if r.get("ann_date")]
        rows.sort(key=lambda x: x.get("ann_date") or "", reverse=True)
        for r in rows[:6]:
            g["trades"].append({"披露": r.get("ann_date"), "股东": (r.get("holder_name") or "")[:12],
                                "方向": "增持" if r.get("in_de") == "IN" else "减持",
                                "数量万股": r.get("change_vol")})
    except (OSError, RuntimeError) as e:
        _ts_quiet("fetch_governance stk_holdertrade", e)
    try:
        rows = _C.ts_call("repurchase", {"ts_code": ts})
        rows = [r for r in rows if r.get("ann_date")]
        rows.sort(key=lambda x: x.get("ann_date") or "", reverse=True)
        for r in rows[:3]:
            g["buyback"].append({"披露": r.get("ann_date"), "金额": yi(r.get("amount")) + "亿"
                                 if r.get("amount") else None, "进度": r.get("proc")})
    except (OSError, RuntimeError) as e:
        _ts_quiet("fetch_governance repurchase", e)
    return g


def fetch_disclosure(code: str) -> dict:
    """下一次财报披露计划（tushare disclosure_date）。失败返回 None。"""
    try:
        rows = _C.ts_call("disclosure_date", {"ts_code": to_ts_code(code)})
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
    except (OSError, RuntimeError) as e:
        _ts_quiet("fetch_disclosure", e)
    return None
