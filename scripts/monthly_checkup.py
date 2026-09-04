#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""monthly_checkup.py — 月度体检：到期复盘提醒 + 评分校准复跑（v4.10 方向三落地）

用法:
    python monthly_checkup.py [报告目录]     # 默认 D:\\个股深度分析
    python monthly_checkup.py --cal          # 同时复跑 score_calibration（联网取行情）
    python monthly_checkup.py --disclosure   # 到期/临近标的加查财报披露计划（联网 tushare，口径待实测）

离线主流程：扫描报告目录 → 文件名解析（公司-代码-质量分-估值分-日期.html）+ 正文抓
「下次审查：YYYY-MM-DD」→ 同代码取最新一份 → 按到期紧急度输出待办清单。
纪律：本脚本只输出待办与统计，不做投资判断；复盘由主模型按 backtest.md 流程执行。
"""
import os
import re
import subprocess
import sys
from datetime import date, datetime

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DEFAULT_DIR = r"D:\个股深度分析"
DUE_SOON_DAYS = 7   # 未来 7 天内到期算「临近」

# 文件名：宝丰能源-600989-7.00-3.9-2026-09-02.html（公司-代码-质量分-估值分-报告日）
_REPORT_RE = re.compile(r"^(.+)-([0-9A-Z]{4,6})-([\d.]+)-([\d.]+)-(\d{4}-\d{2}-\d{2})\.html$",
                        re.I)
_NEXT_REVIEW_RE = re.compile(r"下次审查[：:]\s*(?:</span>)?\s*(\d{4}-\d{2}-\d{2})")


def scan_reports(directory: str) -> list:
    """扫报告目录 → 每代码最新一份的锚点字典列表。"""
    latest = {}
    for fn in sorted(os.listdir(directory)):
        m = _REPORT_RE.match(fn)
        if not m:
            continue
        company, code, quality, valuation, rdate = m.groups()
        path = os.path.join(directory, fn)
        nxt = None
        try:
            # 只读文件头尾各一段找「下次审查」（大文件免整读）
            size = os.path.getsize(path)
            with open(path, encoding="utf-8", errors="replace") as f:
                head = f.read(8192)
                if size > 8192:
                    f.seek(max(0, size - 8192))
                    head += f.read()
            mm = _NEXT_REVIEW_RE.search(head)
            if mm:
                nxt = mm.group(1)
        except OSError:
            pass
        if code not in latest or rdate > latest[code]["date"]:
            latest[code] = {"company": company, "code": code, "date": rdate,
                            "quality": quality, "valuation": valuation,
                            "next_review": nxt, "file": fn}
    return list(latest.values())


def _parse_d(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    directory = args[0] if args else DEFAULT_DIR
    if not os.path.isdir(directory):
        print(f"报告目录不存在: {directory}", file=sys.stderr)
        sys.exit(1)

    today = date.today()
    rows = scan_reports(directory)
    overdue, due_soon, no_anchor = [], [], []
    for r in rows:
        nd = _parse_d(r["next_review"])
        if nd is None:
            no_anchor.append(r)
        elif nd <= today:
            overdue.append((nd, r))
        elif (nd - today).days <= DUE_SOON_DAYS:
            due_soon.append((nd, r))
    overdue.sort()
    due_soon.sort()

    print(f"月度体检 {today} ｜ 报告目录 {directory} ｜ 覆盖 {len(rows)} 只标的")
    print("=" * 72)
    if overdue:
        print(f"\n■ 已到期（{len(overdue)}）——应进入回测复盘流程（SKILL.md 同股再分析）")
        for nd, r in overdue:
            print(f"  {r['company']}（{r['code']}）报告 {r['date']} ｜ 质量 {r['quality']} / "
                  f"估值 {r['valuation']} ｜ 审查日 {nd} 已过期 {(today - nd).days} 天")
    if due_soon:
        print(f"\n■ {DUE_SOON_DAYS} 天内临近（{len(due_soon)}）")
        for nd, r in due_soon:
            print(f"  {r['company']}（{r['code']}）报告 {r['date']} ｜ 质量 {r['quality']} / "
                  f"估值 {r['valuation']} ｜ 审查日 {nd}（{(nd - today).days} 天后）")
    if no_anchor:
        print(f"\n□ 缺下次审查锚点（{len(no_anchor)}）——旧版报告或提取失败")
        for r in no_anchor:
            print(f"  {r['company']}（{r['code']}）报告 {r['date']} ｜ {r['file']}")
    if not overdue and not due_soon:
        print("\n（无到期/临近标的）")
    if not overdue and not due_soon and not rows:
        print("目录内无符合命名规范的报告文件。")

    if "--disclosure" in flags and (overdue or due_soon):
        # 增量功能：tushare disclosure_date 拉财报披露计划（口径待实测校准）
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        try:
            import em_fetch as em
            print("\n■ 财报披露计划（到期/临近标的）")
            for nd, r in overdue + due_soon:
                ts = r["code"] + (".SH" if r["code"].startswith("6") else ".SZ")
                try:
                    rows_d = em.ts_call("disclosure_date", {"ts_code": ts,
                                                            "end_date": f"{today.year}1231"})
                    if rows_d:
                        latest = rows_d[0]
                        print(f"  {r['company']}（{r['code']}）计划披露 {latest.get('pre_date', '?')}"
                              f"（实际 {latest.get('actual_date') or '—'}）")
                    else:
                        print(f"  {r['company']}（{r['code']}）未查到披露计划")
                except Exception as e:
                    print(f"  {r['company']}（{r['code']}）查询失败：{e}")
        except Exception as e:
            print(f"\n披露计划查询不可用（{e}）——跳过", file=sys.stderr)

    if "--cal" in flags:
        print("\n■ 评分校准复跑（score_calibration.py）")
        cal = os.path.join(os.path.dirname(os.path.abspath(__file__)), "score_calibration.py")
        subprocess.run([sys.executable, cal, directory], check=False)
    else:
        print("\n提示：加 --cal 复跑评分校准（每月一次积累样本）；加 --disclosure 查到期标的披露计划")


if __name__ == "__main__":
    main()
