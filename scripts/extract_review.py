#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_review.py — 从旧版深度分析 HTML 报告提取复盘锚点（回测模式输入）

用法:
    python extract_review.py 旧报告.html        # 提取指定旧报告的复盘锚点
    python extract_review.py --find 600989      # 回测触发判定：在扫描目录递归找同代码最新旧报告并直接提取
    python extract_review.py --find 00700 --include-unmarked
                                                # 宽松档：pre-v4.3 无渲染器标记的旧报告也参与匹配
    python extract_review.py --find 600989 --dir D:\个股深度分析
                                                # 代码可带 .SH/.SZ/.HK/.BJ 后缀或 sh/sz 前缀（norm_code 自动归一）；
                                                # --dir 指定扫描根目录（默认 "."，递归子目录）

输出: 结构化 JSON（stdout）：
- prev：上版锚点（date/quality/valuation/timing/target_range），可直接拷入新 fill JSON 的 prev 字段
- scenarios：旧三情景假设（触发条件/净利/PE/目标价/较现价），供复盘四格表"当时预测"列引用
- dash_tables：旧跟踪仪表盘全部表格（关键指标/触发条件/预测登记），供旧触发条件逐条核对
  （v4.9.1 起核对结果写 `triggers` 状态条，dash_html 不再手写旧触发条件核对表）
- review_tables：旧报告 R 复盘章节表格（若旧报告本身是复盘版）

纪律：本脚本只搬运结构化原文（数字+位置），不做总结判断；核对与归因由主模型完成。
"""
import json
import os
import re
import sys
from typing import NamedTuple

from scoring import _num

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _txt(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


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
    m = re.search(r'topbar-tag active">([^<]+)<', html)  # v4.7 前模板顶栏
    if not m:  # v4.7 起顶栏已删，日期在 Hero 副标题「｜报告日期：YYYY-MM-DD」
        m = re.search(r"报告日期：\s*(\d{4}-\d{2}-\d{2})", html)
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


def _head_tail_sniff(path: str) -> str:
    """只读文件头部+尾部各一段用于匹配判定（find_prev_report 只需查渲染器生成标记，
    该标记固定插在文件末尾 </body> 前）——避免为机械筛选而整读动辄 1-2MB 的大 HTML。
    ≤8KB 文件仍整读（小报告读整更简单）；截断若劈开多字节字符会以替换符垫底，
    不影响 ASCII 标记串的匹配。"""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if size <= 8192:
            return f.read().decode("utf-8", errors="replace")
        head = f.read(2048).decode("utf-8", errors="replace")
        f.seek(size - 4096)
        tail = f.read().decode("utf-8", errors="replace")
        return head + "\n" + tail


# 报告文件名三代命名（全仓唯一解析口径，score_calibration/monthly_checkup 复用本函数）：
#   新命名   公司-代码-质量分-估值分-YYYY-MM-DD.html       （render_report.py 自动命名）
#   回测版   公司-代码-质量分-估值分-复盘-YYYY-MM-DD.html  （同上，回测模式加「-复盘」段）
#   旧命名   公司_代码_综合分_YYYY-MM-DD.html              （pre-v4.0 单轨分，无估值分）
_NAME_DASH_RE = re.compile(
    r"^(.+)-(\d{5,6})-([\d.]+)-([\d.]+)-(复盘-)?(\d{4}-\d{2}-\d{2})\.html$", re.I)
_NAME_LEGACY_RE = re.compile(
    r"^(.+)_(\d{5,6})_([\d.]+)_(\d{4}-\d{2}-\d{2})\.html$", re.I)


def _score(s):
    """文件名分数字段 → float；脏数据（如 '7.'）返回 None 不抛出。"""
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def norm_code(code) -> str:
    """证券代码归一化（全仓唯一口径：CLI 入参 / 回测触发 / 校准统计共用）：
    去 sh/sz/hk/bj 前缀（不分大小写，限后接数字）、去 .SH/.SZ/.HK/.BJ 后缀、strip 空白。
    '600000.SH' / 'sh600000' / ' 600000 ' → '600000'；港股 5 位前导零保留（'00700.HK' → '00700'）。"""
    s = str(code or "").strip()
    s = re.sub(r"\.(SH|SZ|HK|BJ)$", "", s, flags=re.I)
    return re.sub(r"^(SH|SZ|HK|BJ)(?=\d)", "", s, flags=re.I).strip()


# 「像报告但文件名解析失败」判定（仅供跳过提示，不参与匹配）：.html 且含公司名特征或 5-6 位
# 数字代码（代码段与 _NAME_DASH_RE 的代码组同口径，公司名特征只取最常见的三种后缀词）。
_NAME_HINT_RE = re.compile(r"\d{5,6}|股份|集团|控股")


def _looks_like_report(fn: str) -> bool:
    """文件名「像报告」判定（供解析失败提示用；score_calibration 扫描侧同口径复用）。"""
    return fn.lower().endswith(".html") and bool(_NAME_HINT_RE.search(fn))


# find_prev_report 的结构化哨兵（v4.10.3 Step 7）：把「无候选 / 有候选但被严格档排除 /
# 代码不匹配」区分开，CLI 才能分别提示，而不是三种情形一律打印「正常首次分析」。
ST_FOUND = "found"                # 命中（path 非空）
ST_EXCLUDED = "excluded"          # 有同代码候选，但全被严格档排除（无渲染器标记）
ST_NO_CODE_MATCH = "no_code_match"  # 有可解析的报告文件，但没有同代码
ST_NO_CANDIDATES = "no_candidates"  # 扫描目录内没有可解析的报告文件


class PrevFind(NamedTuple):
    """find_prev_report 返回值：命中看 `path` 非空——**勿用真值判断**（命名元组恒为真）；
    path 为空时 `status` ∈ {ST_EXCLUDED, ST_NO_CODE_MATCH, ST_NO_CANDIDATES} 说明未命中原因。"""
    path: str = None
    status: str = ST_NO_CANDIDATES


def parse_report_name(path: str):
    """报告文件名/路径 → {company, code, quality, valuation, date, is_review}；不匹配返回 None。
    代码口径：6 位纯数字 = A股/北交所，5 位 = 港股（00700 前导零保留）。
    旧命名（_ 分隔）只有单轨综合分：填入 quality 作近似、valuation 为 None、
    is_review 恒 False——调用方要区分两代命名看 valuation is None 即可。"""
    fn = os.path.basename(path)
    m = _NAME_DASH_RE.match(fn)
    if m:
        return {"company": m.group(1), "code": m.group(2),
                "quality": _score(m.group(3)), "valuation": _score(m.group(4)),
                "date": m.group(6), "is_review": bool(m.group(5))}
    m = _NAME_LEGACY_RE.match(fn)
    if m:
        return {"company": m.group(1), "code": m.group(2),
                "quality": _score(m.group(3)), "valuation": None,
                "date": m.group(4), "is_review": False}
    return None


def find_prev_report(code: str, directory: str = ".", include_unmarked: bool = False) -> PrevFind:
    """回测模式触发的机械判定：在 directory（**递归子目录**，v4.10.3 起剪枝——不扫
    artifacts/ 与点/下划线开头目录（.venv/_archive）及 __pycache__/node_modules，
    避免仓库根下测试夹具误进回测模式）找同代码的最新旧报告。
    代码先经 norm_code 归一化，故 '600000' / '600000.SH' / 'sh600000' 等价。
    双条件：文件名通过 parse_report_name 解析且代码一致（三代命名均认，含旧 _ 分隔
    命名与港股 5 位代码）；文件内含 "generated by render_report.py" 标记
    （排除手写绕行产物与无关 HTML）。
    include_unmarked=True（宽松档）：无标记的 pre-v4.3 旧报告也参与匹配
    （同日期冲突时带标记者优先），匹配到时打印提示——旧模板结构可能不同，
    提取结果需人工核对。
    返回 PrevFind：命中 path=日期最新一版路径；未命中 path=None，status 说明原因
    （ST_EXCLUDED / ST_NO_CODE_MATCH / ST_NO_CANDIDATES）。文件名解析失败但「像报告」
    的文件打 [跳过: 文件名无法解析 …] 到 stderr，不再静默丢。"""
    code = norm_code(code)
    cands = []
    parsed_any = False
    excluded = False
    for root, dirs, files in os.walk(directory):
        # 剪枝（v4.10.3 审计）：CWD=仓库根时 artifacts/ 里的测试夹具会命中同名报告、误进回测模式；
        # 点/下划线开头（.venv/_archive）与依赖目录同样不扫。剪枝在 sort 之前，二者不改匹配语义。
        dirs[:] = [d for d in dirs if not d.startswith((".", "_"))
                   and d not in {"artifacts", "__pycache__", "node_modules"}]
        dirs.sort()  # os.walk 顺序未定义：排序保证「同日期同标记」时的取用稳定
        for fn in sorted(files):
            info = parse_report_name(fn)
            if not info:
                if _looks_like_report(fn):
                    print(f"[跳过: 文件名无法解析 {fn}]", file=sys.stderr)
                continue
            parsed_any = True
            if info["code"] != code:
                continue
            p = os.path.join(root, fn)
            try:
                content = _head_tail_sniff(p)
            except OSError:
                continue
            marked = "generated by render_report.py" in content
            if not marked and not include_unmarked:
                excluded = True
                print(f"提示：{fn} 文件名匹配但无渲染器标记（手写绕行产物？），不计为旧报告"
                      f"（如确为 pre-v4.3 旧报告，可加 --include-unmarked 宽松匹配）",
                      file=sys.stderr)
                continue
            if not marked:
                print(f"提示：{fn} 无渲染器标记（pre-v4.3 旧报告），宽松档计入；"
                      f"旧模板结构可能不同，提取结果请人工核对", file=sys.stderr)
            cands.append((info["date"], marked, p))
    if cands:
        cands.sort(key=lambda c: (c[0], c[1]))  # 同日期带标记者优先
        return PrevFind(cands[-1][2], ST_FOUND)
    if excluded:
        return PrevFind(None, ST_EXCLUDED)
    return PrevFind(None, ST_NO_CODE_MATCH if parsed_any else ST_NO_CANDIDATES)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "--find":
        # 回测触发判定：找到 → 打印路径并直接输出提取结果；未命中 → 按哨兵情形分别提示
        # （不再三种情形一律「正常首次分析」——被严格档排除/目录空都要能看见）
        args = sys.argv[2:]
        directory = "."
        if "--dir" in args:                       # --dir <路径>
            i = args.index("--dir")
            val = args[i + 1] if i + 1 < len(args) else None
            if not val or val.startswith("--"):   # 缺值 / 值是另一个 flag（曾静默回落 "."）
                print("错误：--dir 缺少目录参数（用法: extract_review.py --find [代码] --dir <目录>）",
                      file=sys.stderr)
                sys.exit(1)
            directory = val
            del args[i:i + 2]
        for a in list(args):                      # --dir=<路径>（兼容 = 形式）
            if a.startswith("--dir="):
                directory = a.split("=", 1)[1]
                if not directory:
                    print("错误：--dir= 后缺少目录参数（用法: extract_review.py --find [代码] --dir <目录>）",
                          file=sys.stderr)
                    sys.exit(1)
                args.remove(a)
        code = next((a for a in args if not a.startswith("--")), None)
        if not code:
            print("用法: python extract_review.py --find [代码] [--dir 目录] [--include-unmarked]",
                  file=sys.stderr)
            sys.exit(1)
        if not os.path.isdir(directory):
            print(f"错误：--dir 指向的目录不存在或不是目录: {directory}", file=sys.stderr)
            sys.exit(1)
        res = find_prev_report(code, directory, include_unmarked="--include-unmarked" in args)
        if res.path:
            print(f"发现同代码旧报告: {res.path} → 进入回测模式（先独立取数打分，再读本报告）",
                  file=sys.stderr)
            print(json.dumps(extract(res.path), ensure_ascii=False, indent=2))
            sys.exit(0)
        if res.status == ST_EXCLUDED:
            print(f"{directory} 内有 {norm_code(code)} 的同代码候选，但均无渲染器生成标记，"
                  f"已按严格档排除 → 确为 pre-v4.3 旧报告时加 --include-unmarked 放宽匹配；"
                  f"否则按正常首次分析处理", file=sys.stderr)
        elif res.status == ST_NO_CANDIDATES:
            print(f"{directory}（含子目录）内没有可解析的报告文件 → 正常首次分析，不进入回测模式"
                  f"（报告不在该目录时用 --dir <路径> 指定）", file=sys.stderr)
        else:
            print(f"{directory} 内未找到 {norm_code(code)} 的脚本生成旧报告 → 正常首次分析，不进入回测模式",
                  file=sys.stderr)
        sys.exit(0)
    if not os.path.exists(sys.argv[1]):
        print(f"错误：文件不存在: {sys.argv[1]}\n"
              f"提示：旧报告若是会话附件，先把它保存到工作目录再运行本脚本",
              file=sys.stderr)
        sys.exit(1)
    print(json.dumps(extract(sys.argv[1]), ensure_ascii=False, indent=2))
