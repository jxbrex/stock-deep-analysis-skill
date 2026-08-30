#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_review.py — 从旧版深度分析 HTML 报告提取复盘锚点（回测模式输入）

用法:
    python extract_review.py 旧报告.html        # 提取指定旧报告的复盘锚点
    python extract_review.py --find 600989      # 回测触发判定：在工作目录找同代码最新旧报告并直接提取

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
    # errors="replace" 兜底：非 UTF-8 文件（如 GBK 导出）不直接崩，但含替换字符时告警
    html = open(path, encoding="utf-8", errors="replace").read()
    if "\ufffd" in html:
        print(f"警告：{path} 含非 UTF-8 字节（已用替换字符  兜底），提取结果可能缺字/乱码",
              file=sys.stderr)
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
        lm = re.search(r'<div class="d-label">(.*?)</div>', blk, re.S)
        vm = re.search(r'<div class="d-value">(.*?)</div>', blk, re.S)
        lab = _txt(lm.group(1)) if lm else ""
        val = _txt(vm.group(1)) if vm else ""
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
    # 空结果告警：锚点全空且无任何章节表格 → 大概率模板结构已变更，避免静默输出空 JSON
    anchors_empty = all(out["prev"].get(k) is None for k in ("quality", "valuation", "timing",
                                                             "target_range"))
    if anchors_empty and not any(k in out for k in ("scenarios", "dash_tables", "review_tables")):
        print("警告：未提取到内容，可能是模板结构已变更（请核对 render_report.py 的 HTML 结构）",
              file=sys.stderr)
    return out


def find_prev_report(code: str, directory: str = ".") -> str:
    """回测模式触发的机械判定：在工作目录找同代码的最新旧报告。
    双条件：文件名含 -{code}- 且尾部带 YYYY-MM-DD 日期；文件内含
    "generated by render_report.py" 标记（排除手写绕行产物与无关 HTML）。
    返回最新一版路径；找不到返回 None。"""
    cands = []
    for fn in os.listdir(directory):
        if not fn.lower().endswith(".html") or f"-{code}-" not in fn:
            continue
        m = re.search(r"(\d{4}-\d{2}-\d{2})\.html$", fn)
        if not m:
            continue
        p = os.path.join(directory, fn)
        try:
            content = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if "generated by render_report.py" not in content:
            print(f"提示：{fn} 文件名匹配但无渲染器标记（手写绕行产物？），不计为旧报告",
                  file=sys.stderr)
            continue
        cands.append((m.group(1), p))
    if not cands:
        return None
    cands.sort()
    return cands[-1][1]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "--find":
        # 回测触发判定：找到 → 打印路径并直接输出提取结果；找不到 → 正常首次分析
        if len(sys.argv) < 3:
            print("用法: python extract_review.py --find [代码]", file=sys.stderr)
            sys.exit(1)
        prev = find_prev_report(sys.argv[2])
        if not prev:
            print(f"工作目录未找到 {sys.argv[2]} 的脚本生成旧报告 → 正常首次分析，不进入回测模式",
                  file=sys.stderr)
            sys.exit(0)
        print(f"发现同代码旧报告: {prev} → 进入回测模式（先独立取数打分，再读本报告）",
              file=sys.stderr)
        print(json.dumps(extract(prev), ensure_ascii=False, indent=2))
        sys.exit(0)
    if not os.path.exists(sys.argv[1]):
        print(f"错误：文件不存在: {sys.argv[1]}\n"
              f"提示：旧报告若是会话附件，先把它保存到工作目录再运行本脚本",
              file=sys.stderr)
        sys.exit(1)
    print(json.dumps(extract(sys.argv[1]), ensure_ascii=False, indent=2))
