#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""monthly_checkup.py — 月度体检：到期复盘提醒 + 评分校准复跑（v4.9 方向三落地）

用法:
    python monthly_checkup.py [报告目录]     # 默认 D:\\个股深度分析
    python monthly_checkup.py --cal          # 同时复跑 score_calibration（联网取行情）
    python monthly_checkup.py --disclosure   # 到期/临近标的加查财报披露计划（联网 tushare，
                                             # 复用 em_fetch.fetch_disclosure 的 E1 同款口径）

离线主流程：扫描报告目录 → parse_report_name 文件名解析（三代命名：新命名/带「-复盘-」回测版/
pre-v4.0 旧 _ 分隔命名，港股 5 位代码正常识别）+ 正文抓「下次审查：YYYY-MM-DD」
→ 同代码取最新一份 → 按到期紧急度输出待办清单。
纪律：本脚本只输出待办与统计，不做投资判断；复盘由主模型按 backtest.md 流程执行。
"""
import os
import re
import subprocess
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_review import parse_report_name  # 文件名解析唯一 owner（extract_review.py）

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DEFAULT_DIR = r"D:\个股深度分析"
DUE_SOON_DAYS = 7   # 未来 7 天内到期算「临近」

_NEXT_REVIEW_RE = re.compile(r"下次审查[：:]\s*(?:</span>)?\s*(\d{4}-\d{2}-\d{2})")


def scan_reports(directory: str) -> list:
    """扫报告目录 → 每代码最新一份的锚点字典列表。
    文件名口径 = extract_review.parse_report_name（三代命名；分数为 float，旧 _ 命名
    无估值分则 valuation=None）。"""
    latest = {}
    for fn in sorted(os.listdir(directory)):
        info = parse_report_name(fn)
        if not info:
            continue
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
        if info["code"] not in latest or info["date"] > latest[info["code"]]["date"]:
            latest[info["code"]] = {"company": info["company"], "code": info["code"],
                                    "date": info["date"], "quality": info["quality"],
                                    "valuation": info["valuation"],
                                    "next_review": nxt, "file": fn}
    return list(latest.values())


def _fmt_score(v) -> str:
    """分数显示：None（旧 _ 命名无估值分等）→ —；float 去尾零。"""
    return "—" if v is None else f"{v:g}"


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
    overdue.sort(key=lambda t: t[0])   # 只看审查日：并列时比到 dict 会 TypeError
    due_soon.sort(key=lambda t: t[0])

    print(f"月度体检 {today} ｜ 报告目录 {directory} ｜ 覆盖 {len(rows)} 只标的")
    print("=" * 72)
    if overdue:
        print(f"\n■ 已到期（{len(overdue)}）——应进入回测复盘流程（SKILL.md 同股再分析）")
        for nd, r in overdue:
            print(f"  {r['company']}（{r['code']}）报告 {r['date']} ｜ 质量 {_fmt_score(r['quality'])} / "
                  f"估值 {_fmt_score(r['valuation'])} ｜ 审查日 {nd} 已过期 {(today - nd).days} 天")
    if due_soon:
        print(f"\n■ {DUE_SOON_DAYS} 天内临近（{len(due_soon)}）")
        for nd, r in due_soon:
            print(f"  {r['company']}（{r['code']}）报告 {r['date']} ｜ 质量 {_fmt_score(r['quality'])} / "
                  f"估值 {_fmt_score(r['valuation'])} ｜ 审查日 {nd}（{(nd - today).days} 天后）")
    if no_anchor:
        print(f"\n□ 缺下次审查锚点（{len(no_anchor)}）——旧版报告或提取失败")
        for r in no_anchor:
            print(f"  {r['company']}（{r['code']}）报告 {r['date']} ｜ {r['file']}")
    if not overdue and not due_soon:
        print("\n（无到期/临近标的）")
    if not overdue and not due_soon and not rows:
        print("目录内无符合命名规范的报告文件。")

    if "--disclosure" in flags and (overdue or due_soon):
        # tushare disclosure_date 拉财报披露计划，复用 em_fetch.fetch_disclosure
        # （E1 同款口径：to_ts_code 市场映射 6 位→.SH/.SZ、北交所 43/83/87/88/92→.BJ；
        # 按报告期倒序，优先取未实际披露且有计划日期的最近报告期）
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        try:
            import em_fetch as em
            print("\n■ 财报披露计划（到期/临近标的）")
            for nd, r in overdue + due_soon:
                if len(r["code"]) == 5:
                    print(f"  {r['company']}（{r['code']}）港股：tushare disclosure_date "
                          f"仅覆盖沪深，跳过（请按港交所披露易手工查）")
                    continue
                try:
                    disc = em.fetch_disclosure(r["code"])
                    if disc and disc.get("实际披露"):
                        print(f"  {r['company']}（{r['code']}）{disc['报告期']} "
                              f"已于 {disc['实际披露']} 实际披露（计划 {disc.get('计划披露') or '—'}）")
                    elif disc:
                        print(f"  {r['company']}（{r['code']}）{disc['报告期']} "
                              f"计划披露 {disc['计划披露']}（未披露）")
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
