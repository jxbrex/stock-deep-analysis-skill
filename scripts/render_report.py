#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_report.py — 用 fill-data JSON 渲染个股深度分析 HTML 报告（零模型拼装）

用法:
    python render_report.py fill_600989.json                 # 渲染并自动命名输出
    python render_report.py fill_600989.json --out=out.html  # 指定输出路径

fill JSON 契约见 references/fill-schema.md。
核心特性：
- 评分汇总表由脚本计算（14维度得分×权重→加权→层分→总分→自动徽章色），消除模型算术错误
- 文件名自动生成：{公司名}_{代码}_{综合得分}_{日期}.html（总分是算出来的，不是模型填的）
- 条件章节：模板中 <!--IF:CYCLE_HTML--> 包裹的块在该键为空时整块删除
- 渲染后校验：残留 {{...}} 或 【...】 占位符即报错退出
"""
import json
import os
import re
import sys

# 维度元数据：key -> (层, 显示名, 默认权重)
# v2.0 研究层：L1 本质 50（1A-1E 各10）+ L2 估值 30（2A 独占）+ L3 预期 20（3A8/3B7/3C5）
DIMS = [
    ("1A", "L1", "1A 赛道与宏观", 10),
    ("1B", "L1", "1B 产业链位置", 10),
    ("1C", "L1", "1C 商业模式与护城河", 10),
    ("1D", "L1", "1D 财务健康", 10),
    ("1E", "L1", "1E 管理团队", 10),
    ("2A", "L2", "2A 估值水平", 30),
    ("3A", "L3", "3A 利润增长", 8),
    ("3B", "L3", "3B 项目确定性", 7),
    ("3C", "L3", "3C 催化剂", 5),
]
# 时机层（不入研究分）：筹码 67% / 技术 33%
TIMING_DIMS = [
    ("2C", "筹码与情绪", 67),
    ("2B", "技术面", 33),
]
LAYER_NAMES = {"L1": "公司本质", "L2": "估值水平", "L3": "未来预期"}
REQUIRED_SCALAR = ["company", "code", "date"]


def badge_class(score: float) -> str:
    if score >= 7.0:
        return "badge-green"
    if score >= 4.0:
        return "badge-orange"
    return "badge-red"


_TD_CELL = re.compile(r'<td\b([^>]*)>', re.I)
_TH_CELL = re.compile(r'<th\b([^>]*)>', re.I)
_CELL = re.compile(r'<(t[hd])\b([^>]*)>', re.I)
_TR = re.compile(r'<tr\b[^>]*>(.*?)</tr>', re.I | re.S)
_CLASS_ATTR = re.compile(r'class\s*=\s*"([^"]*)"', re.I)


def _classes_of(attrs: str) -> set:
    m = _CLASS_ATTR.search(attrs or "")
    return set(m.group(1).split()) if m else set()


def _align_class(attrs: str):
    """返回单元格的对齐类：num / center / None"""
    cls = _classes_of(attrs)
    if "num" in cls:
        return "num"
    if "center" in cls:
        return "center"
    return None


def _set_th_align(attrs: str, align: str) -> str:
    """给 th 属性串设置对齐类（幂等：已有正确类则原样返回）。"""
    cls = _classes_of(attrs)
    if align in cls:
        return attrs
    m = _CLASS_ATTR.search(attrs or "")
    if m:
        new_cls = (m.group(1).strip() + " " + align).strip()
        return (attrs[:m.start()] + f'class="{new_cls}"' + attrs[m.end():])
    return (attrs.rstrip() + f' class="{align}"')


def _strip_th_align(attrs: str) -> str:
    """剔除 th 属性串里的 num/center（用于第一列或文字列）。"""
    cls = _classes_of(attrs)
    bad = cls & {"num", "center"}
    if not bad:
        return attrs
    cm = _CLASS_ATTR.search(attrs)
    new_cls = " ".join(c for c in cm.group(1).split() if c not in bad)
    if new_cls:
        return attrs[:cm.start()] + f'class="{new_cls}"' + attrs[cm.end():]
    return _CLASS_ATTR.sub("", attrs).rstrip()


def fix_table_alignment(html: str) -> str:
    """表格对齐自动修正：逐单元格解析（th/td 都按列计数，处理行头 th），按列统计 td 对齐类
    （num/center 多数决），给同列 th 配同类；第一列强制左对齐。matrix-table 跳过。
    作用：模型手写 fragment 表头类不齐时（裸 th 配 td class=num/center），渲染层兜底对齐。"""
    out = []
    pos = 0
    for tm in re.finditer(r'<table\b[^>]*>.*?</table>', html, flags=re.I | re.S):
        out.append(html[pos:tm.start()])
        tbl = tm.group(0)
        tbl_attrs_m = re.match(r'<table\b([^>]*)>', tbl, re.I)
        if tbl_attrs_m and "matrix-table" in _classes_of(tbl_attrs_m.group(1)):
            out.append(tbl)
            pos = tm.end()
            continue
        # 收集每列的对齐类（仅统计 td 数据格；rowspan 合并格需补偿列位，colspan 格不计票）
        col_votes = {}
        rowspans = []  # [(col, remaining_rows)]，行首 rem 即上方剩余占用
        for trm in _TR.finditer(tbl):
            col = 0
            for cm in _CELL.finditer(trm.group(1)):
                # 跳过被上方 rowspan 占用的列
                while any(c == col and rem > 0 for c, rem in rowspans):
                    col += 1
                tag, attrs = cm.group(1).lower(), cm.group(2)
                cs = re.search(r'colspan\s*=\s*"?(\d+)', attrs)
                colspan = int(cs.group(1)) if cs else 1
                if tag == "td" and colspan == 1:
                    a = _align_class(attrs)
                    if a:
                        col_votes.setdefault(col, []).append(a)
                # 登记本格 rowspan（跨 N 行 → 下方 N-1 行该列被占用）
                rs = re.search(r'rowspan\s*=\s*"?(\d+)', attrs)
                if rs and int(rs.group(1)) > 1:
                    rowspans.append((col, int(rs.group(1))))  # 行首即消耗，故存 N
                col += colspan
            # 行尾衰减：本行已消耗的占用减 1（行首 rem=N 表示上方还有 N 行占用）
            rowspans = [(c, rem - 1) for c, rem in rowspans if rem - 1 > 0]
        if not col_votes:
            out.append(tbl)
            pos = tm.end()
            continue
        decided = {}
        for i, votes in col_votes.items():
            if i == 0:
                decided[i] = None  # 第一列强制左
            else:
                num_n = votes.count("num")
                cen_n = votes.count("center")
                decided[i] = "num" if num_n >= cen_n and num_n > 0 else ("center" if cen_n > 0 else None)

        # 显式行循环重建（rowspan 是表级状态，逐行追踪列位）
        tr_parts = []
        last = 0
        rowspans2 = []
        for trm in _TR.finditer(tbl):
            tr_parts.append(tbl[last:trm.start()])
            row = trm.group(0)
            if not _TH_CELL.search(row):
                tr_parts.append(row)
                # 仍要推进 rowspan（该行无 th 但可能有 td 的 rowspan，且上方 rowspan 继续消耗）
                col = 0
                for cm in _CELL.finditer(trm.group(1)):
                    while any(c == col and rem > 0 for c, rem in rowspans2):
                        col += 1
                    rs = re.search(r'rowspan\s*=\s*"?(\d+)', cm.group(2))
                    if rs and int(rs.group(1)) > 1:
                        rowspans2.append((col, int(rs.group(1))))  # 行首即消耗，故存 N
                    col += 1
                rowspans2 = [(c, rem - 1) for c, rem in rowspans2 if rem - 1 > 0]
                last = trm.end()
                continue
            # 该行有 th：逐单元格重建（保持列对齐，含 rowspan/colspan 补偿）
            rebuilt = []
            last_in_row = 0
            col = 0
            for cm in _CELL.finditer(row):
                while any(c == col and rem > 0 for c, rem in rowspans2):
                    col += 1
                rebuilt.append(row[last_in_row:cm.start()])
                tag, attrs = cm.group(1), cm.group(2)
                cs = re.search(r'colspan\s*=\s*"?(\d+)', attrs)
                colspan = int(cs.group(1)) if cs else 1
                if tag.lower() == "th":
                    want = decided.get(col)
                    attrs = _strip_th_align(attrs) if want is None else _set_th_align(attrs, want)
                else:
                    rs = re.search(r'rowspan\s*=\s*"?(\d+)', attrs)
                    if rs and int(rs.group(1)) > 1:
                        rowspans2.append((col, int(rs.group(1))))  # 行首即消耗，故存 N
                rebuilt.append(f"<{tag}{attrs}>")
                last_in_row = cm.end()
                col += colspan
            rebuilt.append(row[last_in_row:])
            tr_parts.append("".join(rebuilt))
            rowspans2 = [(c, rem - 1) for c, rem in rowspans2 if rem - 1 > 0]
            last = trm.end()
        tr_parts.append(tbl[last:])
        out.append("".join(tr_parts))
        pos = tm.end()
    out.append(html[pos:])
    return "".join(out)


def compute_scores(fill: dict):
    """v2.0 三层研究层 + 黄灯扣分 + 时机分。
    返回 dict：rows_html / layer_scores / pre_risk_research / yellow_total /
    research（最终研究分）/ timing_rows_html / timing（时机分）/ red_flag。
    校验：研究层权重和=100；时机层权重和=100。"""
    scores = fill.get("scores") or {}
    w_override = fill.get("weights") or {}
    missing = [d[0] for d in DIMS if d[0] not in scores]
    if missing:
        raise ValueError(f"scores 缺维度: {missing}")
    weights = {}
    for key, _layer, _name, default_w in DIMS:
        weights[key] = float(w_override.get(key, default_w))
    total_w = sum(weights.values())
    if abs(total_w - 100.0) > 0.01:
        raise ValueError(f"研究层权重总和 = {total_w}，必须为 100（分型调整时各维度权重之和仍须等于100）")

    layer_scores, layer_weights = {}, {}
    rows = []
    for layer in ["L1", "L2", "L3"]:
        dims = [d for d in DIMS if d[1] == layer]
        layer_w = sum(weights[d[0]] for d in dims)
        layer_s = sum(float(scores[d[0]]) * weights[d[0]] for d in dims) / layer_w
        layer_scores[layer] = layer_s
        layer_weights[layer] = layer_w
        for j, (key, _l, name, _dw) in enumerate(dims):
            s = float(scores[key])
            w = weights[key]
            wtd = s * w / 100.0
            badge = badge_class(s)
            first = (f'<td rowspan="{len(dims)}"><strong>{layer}</strong> '
                     f'{LAYER_NAMES[layer]} ({layer_w:.0f}%)</td>') if j == 0 else ""
            rows.append(
                f'<tr>{first}<td>{name}</td>'
                f'<td class="center score-cell"><span class="badge {badge}">{s:.1f}</span></td>'
                f'<td class="num">{w:.0f}%</td><td class="num">{wtd:.2f}</td></tr>'
            )
    # 不考虑风险研究分（L1+L2+L3 加权）
    pre_risk = sum(float(scores[d[0]]) * weights[d[0]] for d in DIMS) / 100.0

    # 黄灯扣分（模型填 yellow_deductions 明细：[{label, points}]）
    yellow = fill.get("yellow_deductions") or []
    yellow_total = round(sum(float(y.get("points", 0)) for y in yellow), 2)
    research = round(pre_risk - yellow_total, 2)  # 最终研究分

    # 时机分（2C 筹码 67% + 2B 技术 33%）
    t_scores = fill.get("timing_scores") or {}
    t_weights = {k: float((fill.get("timing_weights") or {}).get(k, dw)) for k, _n, dw in TIMING_DIMS}
    tw_sum = sum(t_weights.values())
    if abs(tw_sum - 100.0) > 0.01:
        raise ValueError(f"时机层权重总和 = {tw_sum}，必须为 100")
    timing = None
    timing_rows = []
    if t_scores:
        timing = sum(float(t_scores.get(k, 0)) * t_weights[k] for k, _n, _w in TIMING_DIMS) / 100.0
        for k, name, _dw in TIMING_DIMS:
            s = float(t_scores.get(k, 0))
            w = t_weights[k]
            timing_rows.append(
                f'<tr><td>{name}</td>'
                f'<td class="center score-cell"><span class="badge {badge_class(s)}">{s:.1f}</span></td>'
                f'<td class="num">{w:.0f}%</td></tr>'
            )

    red_flag = (fill.get("red_flag") or "").strip()
    return {
        "rows_html": "\n".join(rows), "layer_scores": layer_scores,
        "layer_weights": layer_weights, "pre_risk_research": pre_risk,
        "yellow_total": yellow_total, "research": research,
        "timing_rows_html": "\n".join(timing_rows), "timing": timing,
        "red_flag": red_flag,
    }


def render(fill_path: str, out_path: str = None) -> str:
    fill = json.load(open(fill_path, encoding="utf-8"))
    for k in REQUIRED_SCALAR:
        if not fill.get(k):
            raise ValueError(f"缺必填字段: {k}")

    sc = compute_scores(fill)
    layer_scores = sc["layer_scores"]
    layer_weights = sc["layer_weights"]
    pre_risk = sc["pre_risk_research"]
    yellow_total = sc["yellow_total"]
    research = sc["research"]
    timing = sc["timing"]
    red_flag = sc["red_flag"]

    # 双轨判定词（研究分定资格、时机分定节奏；红灯优先）
    if red_flag:
        verdict = f"🔴 红灯回避（{red_flag}）"
    elif research >= 7 and (timing is not None and timing >= 6):
        verdict = "好公司·好时机 → 可进攻"
    elif research >= 7 and (timing is not None and timing < 5):
        verdict = "好公司·差时机 → 观察池等价格"
    elif research >= 7:
        verdict = "好公司·时机中性 → 标准仓"
    elif research >= 5.5:
        verdict = "质地中上 → 轻仓/标准仓"
    else:
        verdict = "研究价值不足 → 回避"

    date = fill["date"]
    repl = {
        "TOP_ICON": fill.get("top_icon") or fill["company"][0],
        "DATE": date,
        "COMPANY": fill["company"],
        "CODE": fill["code"],
        "SUBTITLE": fill.get("subtitle", ""),
        "THESIS_HTML": fill.get("thesis_html", ""),
        "PRICE": str(fill.get("price", "—")),
        "PRICE_SUB_HTML": fill.get("price_sub_html", ""),
        "MCAP": str(fill.get("mcap", "—")),
        "MCAP_SUB": fill.get("mcap_sub", ""),
        "PE_TTM": str(fill.get("pe_ttm", "—")),
        "PE_SUB": fill.get("pe_sub", ""),
        "HORIZON": fill.get("horizon", "12个月"),
        "TARGET_RANGE": fill.get("target_range", "—"),
        "TARGET_SUB_HTML": fill.get("target_sub_html", ""),
        "CONCLUSION_HTML": fill.get("conclusion_html", ""),
        "P0_HTML": fill.get("p0_html", ""),
        "L1_HTML": fill.get("l1_html", ""),
        "L2_HTML": fill.get("l2_html", ""),
        "L3_HTML": fill.get("l3_html", ""),
        "L4_HTML": fill.get("l4_html", ""),
        "VALUATION_METHOD": fill.get("valuation_method", ""),
        "STOCK_TYPE": fill.get("stock_type", ""),
        "VALUATION_HTML": fill.get("valuation_html", ""),
        "GAP_TIER": fill.get("gap_tier", "—"),
        "GAP_HTML": fill.get("gap_html", ""),
        "PEERS_META": fill.get("peers_meta", ""),
        "PEERS_HTML": fill.get("peers_html", ""),
        "CYCLE_META": fill.get("cycle_meta", ""),
        "CYCLE_HTML": fill.get("cycle_html", ""),
        "NEXT_REVIEW": fill.get("next_review", "—"),
        "DASH_HTML": fill.get("dash_html", ""),
        "POSITION_HTML": fill.get("position_html", ""),
        "GEN_TIME": fill.get("gen_time", date),
        "CALIB_NOTE": fill.get("calib_note", ""),
        "SCORE_TABLE_ROWS": sc["rows_html"],
        "TIMING_TABLE_ROWS": sc["timing_rows_html"],
        # 研究分（不考虑风险 → 扣黄灯 → 最终研究分）
        "PRE_RISK_RESEARCH": f"{pre_risk:.2f}",
        "YELLOW_TOTAL": f"{yellow_total:.1f}",
        "RESEARCH_SCORE": f"{research:.2f}",
        "RESEARCH_BADGE_CLASS": badge_class(research),
        # 时机分
        "TIMING_SCORE": (f"{timing:.2f}" if timing is not None else "—"),
        "TIMING_BADGE_CLASS": (badge_class(timing) if timing is not None else "badge-blue"),
        "VERDICT_DUAL": verdict,
        "RED_FLAG_HTML": (f'<div class="danger-card">🔴 <strong>红灯回避</strong>：{red_flag}</div>' if red_flag else ""),
        "SCORE_SUB": "｜".join(f"{l} {layer_scores[l]:.2f}" for l in ["L1", "L2", "L3"]),
        "L1_SCORE": f"{layer_scores['L1']:.2f}", "L1_W": f"{layer_weights['L1']:.0f}",
        "L2_SCORE": f"{layer_scores['L2']:.2f}", "L2_W": f"{layer_weights['L2']:.0f}",
        "L3_SCORE": f"{layer_scores['L3']:.2f}", "L3_W": f"{layer_weights['L3']:.0f}",
    }

    tmpl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "report-template.html")
    html = open(tmpl_path, encoding="utf-8").read()

    # 条件章节：<!--IF:KEY--> ... <!--ENDIF-->
    def handle_conditional(m):
        key = m.group(1)
        block = m.group(2)
        return block if repl.get(key) else ""
    html = re.sub(r"<!--IF:([A-Z_]+)-->(.*?)<!--ENDIF-->", handle_conditional, html, flags=re.S)

    for k, v in repl.items():
        html = html.replace("{{" + k + "}}", v)

    # 表格对齐自动修正（fragment 手写表头类不齐的兜底，matrix-table 跳过）
    html = fix_table_alignment(html)

    # 校验残留
    leftover_double = re.findall(r"\{\{[A-Z_0-9]+\}\}", html)
    if leftover_double:
        raise ValueError(f"残留未替换占位符: {sorted(set(leftover_double))}")
    leftover_cn = re.findall(r"【[^】]{0,40}】", html)
    if leftover_cn:
        raise ValueError(f"残留中文占位符: {sorted(set(leftover_cn))}")

    if not out_path:
        out_path = os.path.join(os.path.dirname(os.path.abspath(fill_path)),
                                f"{fill['company']}_{fill['code']}_{research:.2f}_{date}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    empty = [k for k in ("CONCLUSION_HTML", "P0_HTML", "L1_HTML", "L2_HTML", "L3_HTML",
                         "L4_HTML", "VALUATION_HTML", "GAP_HTML", "PEERS_HTML",
                         "DASH_HTML", "POSITION_HTML") if not repl.get(k)]
    print(f"OK → {out_path}")
    timing_s = f"{timing:.2f}" if timing is not None else "—"
    print(f"研究分 {research:.2f}（不考虑风险 {pre_risk:.2f} − 黄灯 {yellow_total:.1f}）| "
          f"时机分 {timing_s} | " +
          " ".join(f"{l} {layer_scores[l]:.2f}" for l in ["L1", "L2", "L3"]) +
          (f" | 🔴红灯: {red_flag}" if red_flag else ""))
    if empty:
        print(f"⚠️ 以下章节片段为空（如非故意请检查 fill JSON）: {empty}")
    return out_path


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = {a[2:].split("=")[0]: a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--") and "=" in a}
    if not args:
        print(__doc__)
        sys.exit(1)
    render(args[0], opts.get("out"))
