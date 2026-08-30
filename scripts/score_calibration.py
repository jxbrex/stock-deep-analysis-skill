#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""score_calibration.py — 评分统计校准：存量报告的三轨分 vs 报告日后实际收益（思考题①工具化）

用法:
    python score_calibration.py [报告目录]     # 默认 D:\\个股深度分析

流程：扫描目录 HTML 报告 → extract_review 提取锚点（代码/日期/质量分/估值分/时机分）
→ tushare 日线（前复权口径：close×adj_factor）算报告日收盘→最新收盘的收益与沪深300超额
（港股用 hk_daily 原始价、恒生指数基准，分红不调整，窗口短误差可接受，输出标注）
→ 按质量分/估值分分桶统计。

判读纪律（防过度解读，写在输出里）：
- 样本同源（同一市场 regime），超额收益只缓解不消除；同股多份报告窗口重叠，给去重口径。
- 持有期 <20 个交易日的观测标「短窗」，短窗收益主要是噪音，只看不评。
- 校准结论需要 30+ 独立样本且持有期对齐；本表是描述性起点，每月复跑一次积累样本。
"""
import os
import re
import sys
import time
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_review as E
import em_fetch as em

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DEFAULT_DIR = r"D:\个股深度分析"
SHORT_WINDOW = 20  # 交易日

# 分桶边界（与决策矩阵口径对齐：质量 <4 回避 / 4-5.5 一般 / 5.5-7 中上 / ≥7 好公司；
# 估值 <4 贵 / 4-6 合理 / 6-8 合理偏便宜 / ≥8 深度安全边际）
Q_BUCKETS = [(0, 4, "质量<4 回避"), (4, 5.5, "质量4-5.5 一般"),
             (5.5, 7, "质量5.5-7 中上"), (7, 11, "质量≥7 好公司")]
V_BUCKETS = [(0, 4, "估值<4 贵"), (4, 6, "估值4-6 合理"),
             (6, 8, "估值6-8 偏便宜"), (8, 11, "估值≥8 深度安全边际")]


def bucket_of(v, buckets):
    """分值 → 桶标签；None 不入桶。"""
    if v is None:
        return None
    for lo, hi, label in buckets:
        if lo <= v < hi:
            return label
    return None


def parse_filename(fn: str):
    """文件名兜底提取 (code, date)：支持 -分隔与 _ 分隔两代命名。无标记/旧版报告也能取到。"""
    m = re.search(r"-(\d{5,6})-[\d.]+-[\d.]+-(?:复盘-)?(\d{4}-\d{2}-\d{2})\.html$", fn)
    if m:
        return m.group(1), m.group(2)
    m = re.search(r"_(\d{5,6})_[\d.]+_(\d{4}-\d{2}-\d{2})\.html$", fn)
    if m:
        return m.group(1), m.group(2)
    return None


def collect_reports(directory: str) -> list:
    """扫描目录 → [{path, code, rep_date, quality, valuation, timing, price}]。提取失败的跳过并告警。"""
    reps = []
    for fn in sorted(os.listdir(directory)):
        if not fn.lower().endswith(".html"):
            continue
        fa = parse_filename(fn)
        if not fa:
            continue
        code, rep_date = fa
        path = os.path.join(directory, fn)
        try:
            ext = E.extract(path)
        except Exception as e:
            print(f"跳过 {fn}（提取失败: {e}）", file=sys.stderr)
            continue
        prev = ext.get("prev") or {}
        q, v = prev.get("quality"), prev.get("valuation")
        code = (ext.get("code") or code).split(".")[0]  # 归一：剥掉 .SH/.SZ 后缀
        if q is None and v is None:
            # 旧版单轨报告（pre-v4.0）：无三轨分——取文件名代码后第一个分数作质量分近似
            # （_ 分隔格式那是综合分，- 分隔双分格式第一个是质量分），入明细但不入桶
            m3 = re.search(r"[_-]\d{5,6}[_-]([\d.]+)(?:[_-][\d.]+)?[_-](?:复盘-)?"
                           r"\d{4}-\d{2}-\d{2}\.html$", fn)
            if not m3:
                print(f"跳过 {fn}（未提取到三轨分，旧版单轨报告）", file=sys.stderr)
                continue
            reps.append({"file": fn, "code": code,
                         "company": ext.get("company") or fn,
                         "rep_date": prev.get("date") or rep_date,
                         "quality": float(m3.group(1)), "valuation": None, "timing": None,
                         "price": ext.get("price"), "legacy": True})
            continue
        reps.append({"file": fn, "code": code,
                     "company": ext.get("company") or fn,
                     "rep_date": prev.get("date") or rep_date,
                     "quality": q, "valuation": v, "timing": prev.get("timing"),
                     "price": ext.get("price")})
    return reps


def _ts(api_name: str, params: dict) -> list:
    """ts_call 限流包装：tushare 分钟级频次限制（如 hk_daily 1次/分）命中时睡 62s 重试一次。"""
    try:
        return em.ts_call(api_name, params)
    except RuntimeError as e:
        if "频率超限" in str(e) or "频次" in str(e):
            print(f"  tushare 限流，62s 后重试 {api_name}...", file=sys.stderr)
            time.sleep(62)
            return em.ts_call(api_name, params)
        raise


def _em_kline_daily(secid: str, start: str, end: str) -> list:
    """东财日 K（klt=101, fqt=1 前复权）→ [{trade_date, adj_close}]。
    港股日线走此通道（tushare hk_daily 限 1次/小时，批量校准不可用）。"""
    url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}"
           f"&fields1=f1,f2,f3&fields2=f51,f53&klt=101&fqt=1&beg={start}&end={end}")
    d = em.get(url).get("data") or {}
    return [{"trade_date": k.split(",")[0].replace("-", ""), "adj_close": float(k.split(",")[1])}
            for k in (d.get("klines") or [])]


def _daily_adj_rows(code: str, start: str, end: str, is_hk: bool) -> list:
    """日线 + 复权因子合成前复权口径行 [{trade_date, adj_close}]（港股走东财前复权日 K）。"""
    if is_hk:
        return _em_kline_daily(em.secid_of(code)[0], start, end)
    ts = em.to_ts_code(code)
    rows = _ts("daily", {"ts_code": ts, "start_date": start, "end_date": end})
    adj = {r["trade_date"]: float(r["adj_factor"]) for r in
           _ts("adj_factor", {"ts_code": ts, "start_date": start, "end_date": end})
           if r.get("adj_factor") is not None}
    return [{"trade_date": r["trade_date"],
             "adj_close": float(r["close"]) * adj.get(r["trade_date"], 1.0)}
            for r in rows if r.get("close") is not None]


def fetch_return(code: str, rep_date: str, today: str) -> dict:
    """报告日收盘（≤报告日最近交易日）→ 最新收盘的前复权收益。
    单次宽窗口取数（前一月月初→今天），减少限流接口调用次数。
    返回 {entry_date, exit_date, ret, n_days}，失败抛异常。"""
    is_hk = len(code) == 5
    d0 = rep_date.replace("-", "")
    rows = _daily_adj_rows(code, f"{int(d0[:4])}{max(1, int(d0[4:6]) - 1):02d}01", today, is_hk)
    rows.sort(key=lambda r: r["trade_date"])  # tushare 返回倒序，统一升序
    if not rows:
        raise RuntimeError("日线空返回")
    entry = None
    for r in rows:
        if r["trade_date"] <= d0:
            entry = r  # ≤报告日最后一个交易日
    if entry is None:
        raise RuntimeError(f"报告日 {rep_date} 前无交易数据")
    exit_ = rows[-1]
    if exit_["trade_date"] <= entry["trade_date"]:
        raise RuntimeError("报告日后无新交易日（报告即最新）")
    return {"entry_date": entry["trade_date"], "exit_date": exit_["trade_date"],
            "ret": exit_["adj_close"] / entry["adj_close"] - 1,
            "n_days": sum(1 for r in rows if entry["trade_date"] < r["trade_date"])}


_INDEX_CACHE = {}


def fetch_index_return(market: str, start_td: str, end_td: str) -> float:
    """基准同期收益：A股→沪深300（前复权不需要，指数无分红调整口径），港股→恒生指数。"""
    key = (market, start_td, end_td)
    if key in _INDEX_CACHE:
        return _INDEX_CACHE[key]
    rows = None
    if market == "HK":
        # 恒生指数走东财日 K（指数无复权，fqt=0；tushare index_global 频次同样受限）
        rows = _em_kline_daily("100.HSI", start_td, end_td)
        rows = [{"trade_date": r["trade_date"], "close": r["adj_close"]} for r in rows]
    else:
        rows = _ts("index_daily", {"ts_code": "000300.SH",
                                   "start_date": start_td, "end_date": end_td})
    if not rows:
        raise RuntimeError("指数数据空返回")
    rows = sorted(rows, key=lambda r: r["trade_date"])
    base = rows[0]["close"]
    ret = None
    for r in rows:
        if r["trade_date"] <= start_td:
            base = r["close"]  # ≤报告日最后一个交易日收盘
    last = rows[-1]["close"]
    ret = last / base - 1
    _INDEX_CACHE[key] = ret
    return ret


def dedup_earliest(reps: list) -> list:
    """同股去重口径：每股只保留最早一份（窗口最长、相互独立）。"""
    seen = {}
    for r in reps:
        if r["code"] not in seen or r["rep_date"] < seen[r["code"]]["rep_date"]:
            seen[r["code"]] = r
    return list(seen.values())


def _bucket_table(reps: list, key: str, buckets, title: str) -> list:
    lines = [f"\n### {title}\n", "| 桶 | n | 平均收益 | 中位收益 | 胜率 | 平均超额 |",
             "|---|---|---|---|---|---|"]
    for lo, hi, label in buckets:
        members = [r for r in reps if bucket_of(r.get(key), buckets) == label]
        if not members:
            lines.append(f"| {label} | 0 | — | — | — | — |")
            continue
        rets = sorted(r["ret"] for r in members)
        exc = [r["excess"] for r in members if r.get("excess") is not None]
        n = len(members)
        med = rets[n // 2] if n % 2 else (rets[n // 2 - 1] + rets[n // 2]) / 2
        win = sum(1 for x in rets if x > 0) / n
        lines.append(f"| {label} | {n} | {sum(rets) / n:+.1%} | {med:+.1%} | "
                     f"{win:.0%} | {sum(exc) / len(exc):+.1%} |" if exc else
                     f"| {label} | {n} | {sum(rets) / n:+.1%} | {med:+.1%} | {win:.0%} | — |")
    return lines


def main():
    directory = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIR
    today = date.today().strftime("%Y%m%d")
    reps = collect_reports(directory)
    print(f"# 评分校准：{directory} 共 {len(reps)} 份有效报告（{today} 收盘口径）\n")

    ok, fail = [], 0
    for r in reps:
        try:
            fr = fetch_return(r["code"], r["rep_date"], today)
            r.update(fr)
            mkt = "HK" if len(r["code"]) == 5 else "A"
            try:
                r["excess"] = r["ret"] - fetch_index_return(mkt, fr["entry_date"], today)
            except Exception:
                r["excess"] = None
            ok.append(r)
        except Exception as e:
            fail += 1
            print(f"跳过 {r['file']}（收益计算失败: {e}）", file=sys.stderr)
    print(f"收益计算成功 {len(ok)} 份，失败 {fail} 份"
          f"（失败多为报告日即最新交易日/标的停牌）\n")

    print("## 明细（按报告日排序）\n")
    print("| 公司 | 代码 | 报告日 | 质量 | 估值 | 时机 | 持有交易日 | 收益 | 超额 | 备注 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(ok, key=lambda x: x["rep_date"]):
        note = "短窗(<20日)只看不评" if r["n_days"] < SHORT_WINDOW else ""
        if r.get("legacy"):
            note = (note + "；" if note else "") + "旧版单轨分近似，不入桶"
        exc = f"{r['excess']:+.1%}" if r.get("excess") is not None else "—"
        print(f"| {r['company']} | {r['code']} | {r['rep_date']} | {r['quality']} | "
              f"{r['valuation']} | {r['timing']} | {r['n_days']} | {r['ret']:+.1%} | {exc} | {note} |")

    ok_b = [r for r in ok if not r.get("legacy")]  # 入桶口径：排除旧版单轨近似
    for label, group in (("全口径（同股多份都计入，窗口有重叠）", ok_b),
                         ("去重口径（同股仅取最早一份，独立窗口）", dedup_earliest(ok_b))):
        print(f"\n## 分桶统计——{label}")
        for line in _bucket_table(group, "quality", Q_BUCKETS, "质量分 × 实际收益"):
            print(line)
        for line in _bucket_table(group, "valuation", V_BUCKETS, "估值分 × 实际收益"):
            print(line)

    print("\n---\n判读纪律：样本同 regime + 短窗为主，本表是描述性起点；"
          "显著性结论需 30+ 独立样本且持有期对齐，每月复跑积累。")


if __name__ == "__main__":
    main()
