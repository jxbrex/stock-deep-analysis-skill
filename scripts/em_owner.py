#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
em_owner.py — E4-E6 股东/预期/主营取数族（stock-deep-analysis skill 取数分块之一，v4.10.3 自 em_data 拆分）

职责：E4 股东户数（tushare stk_holdernumber 优先，东财兜底）、E5 一致预期（tushare report_rc
研报聚合 / 东财 RPT_WEB_RESPREDICT 兜底）、E6 主营构成（tushare fina_mainbz 产品优先取，
东财兜底）。

与其他块的边界（重要）：
- 只依赖 em_core.py，绝不 import 其他取数块（em_market/em_finance/em_misc 同理）。
- 传输函数一律以 `_C.ts_call` / `_C.get` 模块属性形式调用（迟绑定——测试按 em_core 命名空间
  rebind 传输函数与缓存配置须即时传导）；静态 from-import 只用于无 rebind 依赖的纯工具
  （代码映射 / 格式化 / 取数窗口）与跨块共享 helper。
"""
import sys
from datetime import date

import em_core as _C
from em_core import (to_ts_code, _fmt_date, _em_dc, _win_years, yi)


# ---------------- E4 股东户数 ----------------
def _em_holders(code: str) -> list:
    return _em_dc("RPT_HOLDERNUMLATEST", f'(SECURITY_CODE="{code}")', 8)


def fetch_holders(code: str) -> list:
    """E4 股东户数（东财键名同构）。tushare stk_holdernumber 优先（变动比自算），东财兜底。"""
    try:
        rows = _C.ts_call("stk_holdernumber", {"ts_code": to_ts_code(code)})
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
        rows = _C.ts_call("report_rc", {"ts_code": to_ts_code(code)})
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
# fina_mainbz 维度合计行的 bz_item 取值（v4.10.3）：除产品/行业/地区三大维度名外，
# 兼容「合计」「主营业务」两种可能的表头写法。
_MAINBZ_TOTAL_NAMES = {"产品", "行业", "地区", "合计", "主营业务"}


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
    业务构成图的利润口径一律为毛利。v4.10.3 起剔除 fina_mainbz 的维度合计行（见下）。"""
    code, _ = secucode.split(".")
    try:
        ts = to_ts_code(code)
        beg, end = _win_years(2)
        rng = {"start_date": beg, "end_date": end}
        rows = None
        mainop_type = None
        for tp, mt in (("P", "2"), ("D", "1")):  # 产品优先，地区当行业位展示
            got = _C.ts_call("fina_mainbz", {"ts_code": ts, "type": tp, **rng})
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
        # 维度合计行剔除（v4.10.3，2026-09-12 香农芯创 300475 实证）：fina_mainbz 在明细行之外
        # 额外返回一行 bz_item=维度名（产品/行业/地区）的合计行——留在分母里会让所有 MBI_RATIO
        # 腰斩（香农芯创占比 46.8% 实为 93.7%）。分母取**该合计行金额**：合计行=维度汇总，经
        # income.total_revenue 交叉验证精确等于营业收入；扁平 payload 它恰为其余行之和，但层级
        # payload（父级小计与子级明细并存，东方电气 1.86x / 工商银行 3.66x / 山东黄金 1.13x 实证）
        # sum(明细) 会重复计数，故不能用明细和当初数。
        dropped = [r for r in items if str(r.get("bz_item") or "").strip() in _MAINBZ_TOTAL_NAMES]
        if dropped:
            items = [r for r in items
                     if str(r.get("bz_item") or "").strip() not in _MAINBZ_TOTAL_NAMES]
            desc = "；".join(f'{str(r.get("bz_item") or "").strip()}，{yi(r.get("bz_sales"))} 亿'
                            for r in dropped)
            print(f"注：fina_mainbz 已剔除维度合计行（{desc}，其值作分母）", file=sys.stderr)
            total = max((float(r["bz_sales"]) for r in dropped if r.get("bz_sales")), default=None)
        else:
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
