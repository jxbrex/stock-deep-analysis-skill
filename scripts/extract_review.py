#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_review.py — 从旧版深度分析 HTML 报告提取复盘锚点（回测模式输入）

用法:
    python extract_review.py 旧报告.html

输出: 结构化 JSON（stdout）：
- prev：上版锚点（date/quality/valuation/timing/target_range），可直接拷入新 fill JSON 的 prev 字段
- scenarios：旧三情景假设（触发条件/净利/PE/目标价/较现价），供复盘四格表"当时预测"列引用
- dash_tables：旧跟踪仪表盘全部表格（关键指标/触发条件/预测登记），供"旧触发条件核对表"逐条核对
- review_tables：旧报告 R 复盘章节表格（若旧报告本身是复盘版）

纪律：本脚本只搬运结构化原文（数字+位置），不做总结判断；核对与归因由主模型完成。
"""
import json
import os
import re
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _txt(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


def _num(s):
    m = re.search(r"-?\d[\d,]*\.?\d*", str(s))
    return float(m.group(0).replace(",", "")) if m else None


def _sections(html: str) -> dict:
    """按 section 切块 → {章节标题: 块 html}"""
    out = {}
    for m in re.finditer(r'<div class="section">(.*?)(?=<div class="section">|<div class="disclaimer">)',
                         html, re.S):
        blk = m.group(1)
        t = re.search(r'<span class="section-title">(.*?)</span>', blk, re.S)
        if t:
            out[_txt(t.group(1))] = blk
    return out


def _tables(blk: str) -> list:
    """提取块内全部表格 → [{header: [...], rows: [[...]]}]（纯文本单元格）"""
    res = []
    for tm in re.finditer(r"<table\b[^>]*>(.*?)</table>", blk, re.S | re.I):
        tbl = tm.group(1)
        rows = []
        for trm in re.finditer(r"<tr\b[^>]*>(.*?)</tr>", tbl, re.S | re.I):
            cells = [_txt(c) for c in re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", trm.group(1), re.S | re.I)]
            if cells:
                rows.append(cells)
        if rows:
            res.append({"header": rows[0], "rows": rows[1:]})
    return res


def extract(path: str) -> dict:
    html = open(path, encoding="utf-8").read()
    out = {"source_file": os.path.basename(path)}

    # Hero 锚点
    m = re.search(r"<h1>(.*?)</h1>", html, re.S)
    if m:
        h1 = _txt(m.group(1))
        cm = re.match(r"(.+?)[（(]([\dA-Z.]+)[）)]", h1)
        if cm:
            out["company"], out["code"] = cm.group(1).strip(), cm.group(2).strip()
    m = re.search(r'topbar-tag active">([^<]+)<', html)
    if m:
        out["date"] = m.group(1).strip()

    def _hero_score(cls):
        m = re.search(r'hero-track %s">.*?s-value[^>]*>([\d.]+)<' % cls, html, re.S)
        return float(m.group(1)) if m else None

    quality, valuation = _hero_score("quality"), _hero_score("valuation")
    m = re.search(r'hero-timing-mini">时机分 <span class="tv">([\d.]+)<', html)
    timing = float(m.group(1)) if m else None
    # 目标价区间 / 现价（hero-data-strip）
    target_range = price = None
    for dm in re.finditer(r'<div class="d-item">(.*?)</div>\s*</div>', html, re.S):
        blk = dm.group(1)
        lab = _txt(re.search(r'<div class="d-label">(.*?)</div>', blk, re.S).group(1)) if re.search(
            r'<div class="d-label">', blk) else ""
        val = _txt(re.search(r'<div class="d-value">(.*?)</div>', blk, re.S).group(1)) if re.search(
            r'<div class="d-value">', blk) else ""
        if "目标价" in lab:
            target_range = val.replace(" 元", "").strip()
        elif "股价" in lab:
            price = _num(val)
    out["prev"] = {"date": out.get("date"), "quality": quality, "valuation": valuation,
                   "timing": timing, "target_range": target_range}
    out["price"] = price

    secs = _sections(html)
    # 旧三情景假设（scenario-table：指标在行、情景在列）
    for title, blk in secs.items():
        if "估值" not in title:
            continue
        for tb in _tables(blk):
            if not any("情景" in h for h in tb["header"]):
                continue
            scen = [{"scenario": h} for h in tb["header"][1:]]
            for row in tb["rows"]:
                if len(row) < 2:
                    continue
                for i, cell in enumerate(row[1:]):
                    if i < len(scen):
                        scen[i][row[0]] = cell
            out["scenarios"] = scen
            break
        break
    # 跟踪仪表盘 / 复盘章节表格
    for title, blk in secs.items():
        if "跟踪仪表盘" in title:
            out["dash_tables"] = _tables(blk)
        if "回测复盘" in title:
            out["review_tables"] = _tables(blk)
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    if not os.path.exists(sys.argv[1]):
        print(f"错误：文件不存在: {sys.argv[1]}\n"
              f"提示：旧报告若是会话附件，先把它保存到工作目录再运行本脚本",
              file=sys.stderr)
        sys.exit(1)
    print(json.dumps(extract(sys.argv[1]), ensure_ascii=False, indent=2))
