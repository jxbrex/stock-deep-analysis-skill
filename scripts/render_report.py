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

# Windows GBK 控制台打印 ⚠️/−/🔴 等字符会 UnicodeEncodeError，统一降级为 replace
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

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
_CLASS_ATTR = re.compile(r'class\s*=\s*["\']([^"\']*)["\']', re.I)


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
    """给 th 属性串设置对齐类（幂等：已有正确类则原样返回；已有另一类则替换而非叠加，
    避免 class="center num" 双类共存导致对齐结果取决于 CSS 声明顺序）。"""
    cls = _classes_of(attrs)
    if align in cls and not (cls & {"num", "center"} - {align}):
        return attrs
    m = _CLASS_ATTR.search(attrs or "")
    if m:
        kept = [c for c in m.group(1).split() if c not in ("num", "center")]
        new_cls = " ".join(kept + [align])
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


def _is_plain_text(s: str) -> bool:
    """判断单元格文本是否为纯文字（无数字、无★等特殊符号）——纯文字格应左对齐，
    剔除被误加的 num/center 类（如同业表"核心业务"行被复制成 class=num）。
    占比括号剥离："纯制冷剂(85%)"→"纯制冷剂" 判为文字；"1,350 亿（-1.5%）" 判为数值。"""
    t = re.sub(r"<[^>]+>", "", s or "").strip()
    if not t:
        return False
    if re.search(r"[★☆◆●■▲▶▼↑↓→≈∞×÷±]", t):  # 含星级/箭头/数学符号 → 保留原类
        # 注："+" 不在此列——"+30%" 类含数字会被下方数字检查拦截，
        # 而"动力+储能电池"这类纯文字描述里的 + 不应阻止纠偏
        return False
    t2 = re.sub(r"[（(][^）)]*[）)]", "", t)  # 剥离括号及其内容（占比/说明性数字）
    if re.search(r"\d", t2):
        return False
    return True


def _is_prose_cell(s: str) -> bool:
    """num 列中应左对齐的文字格：含句读符号，或超 4 字的纯文字。
    ≤4 字短标记（"基础""偏多"）随列右对齐，长数值串（"13,600-15,300亿"）因含数字天然右对齐。"""
    t = re.sub(r"<[^>]+>", "", s or "").strip()
    if re.search(r"[，。；、：]", t):
        return True
    return len(t) > 4 and _is_plain_text(s)


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
            # 逐单元格重建（所有行都走，td 纠偏对无 th 的数据行同样生效；
            # 无改动需求时重建结果=原文，无损）
            cells = list(_CELL.finditer(row))
            rebuilt = []
            last_in_row = 0
            col = 0
            for i, cm in enumerate(cells):
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
                    # td 对齐统一（num 列）：长文格（含句读 / 超 4 字纯文字）→ 去类左对齐；
                    # 数字、含数字短值、≤4 字短标记（"基础""12个月"）→ 统一 num 右对齐
                    if colspan == 1 and decided.get(col) == "num":
                        inner_end = cells[i + 1].start() if i + 1 < len(cells) else len(row)
                        inner = row[cm.end():inner_end]
                        if _is_prose_cell(inner):
                            attrs = _strip_th_align(attrs)  # 剔除 num/center → 左
                        else:
                            attrs = _set_th_align(attrs, "num")  # 随列右对齐
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


_SCENARIO_ROW_LABELS = ("悲观", "基础", "乐观")


def _transpose_scenario_table(html: str) -> str:
    """05 三情景表方向兜底：检测到旧模式（表体前 3+ 行首列恰为 悲观/基础/乐观，
    表头首格为"情景"或空、各行格数一致）→ 自动转置为纵向列排列
    （指标在行、情景在列，参照中国移动报告）并向 stderr 告警。
    已正确的表（首列为指标名）不命中，原样返回。"""
    for tm in re.finditer(r'<table\b[^>]*>.*?</table>', html, flags=re.I | re.S):
        tbl = tm.group(0)
        rows = list(_TR.finditer(tbl))
        if len(rows) < 4:
            continue
        parsed = []
        for rm in rows:
            matches = list(_CELL.finditer(rm.group(1)))
            segs = []
            for i, cm in enumerate(matches):
                end = matches[i + 1].start() if i + 1 < len(matches) else len(rm.group(1))
                inner = re.sub(r"</t[hd]>\s*$", "", rm.group(1)[cm.end():end], flags=re.I)
                segs.append({"tag": cm.group(1).lower(), "attrs": cm.group(2), "inner": inner})
            parsed.append(segs)
        header, body = parsed[0], parsed[1:]
        ncols = len(header)
        if ncols < 3 or any(len(r) != ncols for r in parsed):
            continue
        corner = re.sub(r"<[^>]+>", "", header[0]["inner"]).strip()
        if corner not in ("", "情景"):
            continue
        labels = []
        for r in body[:3]:
            t = re.sub(r"<[^>]+>", "", r[0]["inner"]).strip()
            t = t[:-2] if t.endswith("情景") else t
            if t not in _SCENARIO_ROW_LABELS:
                break
            labels.append(t)
        else:
            if len(body) >= 3 and len(labels) == 3:
                # 命中旧模式：转置（单元格 attrs/inner 原样搬运，对齐类交给 fix_table_alignment）
                new_head = "<tr><th>指标</th>" + "".join(
                    f'<th class="center">{lab}情景</th>' for lab in labels) + "</tr>"
                new_rows = []
                for j in range(1, ncols):
                    row_name = re.sub(r"<[^>]+>", "", header[j]["inner"]).strip()
                    cells = "".join(f'<td{r[j]["attrs"]}>{r[j]["inner"]}</td>' for r in body)
                    new_rows.append(f"<tr><td>{row_name}</td>{cells}</tr>")
                new_tbl = ('<table class="scenario-table"><thead>' + new_head + "</thead><tbody>"
                           + "".join(new_rows) + "</tbody></table>")
                print("⚠️ 05 三情景表为旧方向（情景在行），已自动转置为纵向列排列；"
                      "下次请按 fill-schema 骨架直接写对（指标在行、情景在列）", file=sys.stderr)
                return html[:tm.start()] + new_tbl + html[tm.end():]
    return html


def compute_scores(fill: dict):
    """v2.0 三层研究层 + 黄灯扣分 + 时机分。
    返回 dict：rows_html / layer_scores / pre_risk_research / yellow_total /
    research（最终研究分）/ timing（时机分）/ red_flag。
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

    # 时机分（2C 筹码 67% + 2B 技术 33%；只算分值，时机轨表在 11 由模型呈现，09 不再重复）
    t_scores = fill.get("timing_scores") or {}
    t_weights = {k: float((fill.get("timing_weights") or {}).get(k, dw)) for k, _n, dw in TIMING_DIMS}
    tw_sum = sum(t_weights.values())
    if abs(tw_sum - 100.0) > 0.01:
        raise ValueError(f"时机层权重总和 = {tw_sum}，必须为 100")
    timing = None
    if t_scores:
        timing = sum(float(t_scores.get(k, 0)) * t_weights[k] for k, _n, _w in TIMING_DIMS) / 100.0

    red_flag = (fill.get("red_flag") or "").strip()
    return {
        "rows_html": "\n".join(rows), "layer_scores": layer_scores,
        "layer_weights": layer_weights, "pre_risk_research": pre_risk,
        "yellow_total": yellow_total, "research": research,
        "timing": timing,
        "red_flag": red_flag,
    }


def _load_fill(fill_path: str) -> dict:
    r"""读取 fill JSON。模型手写 JSON 常带非法转义（如表头 "ROE \ PE" 的裸反斜杠），
    先标准解析；失败则把不属于合法转义（\\ \" \/ \b \f \n \r \t \uXXXX）的反斜杠
    自动转义后重试并告警；仍失败则抛出带行号/列号/片段上下文的错误。"""
    with open(fill_path, encoding="utf-8") as f:
        text = f.read()
    try:
        return json.loads(text)
    except json.JSONDecodeError as first_err:
        repaired = re.sub(r'\\(?![\\"/bfnrtu])', r"\\\\", text)
        try:
            fill = json.loads(repaired)
        except json.JSONDecodeError:
            line, col = first_err.lineno, first_err.colno
            lines = text.splitlines()
            excerpt = lines[line - 1] if 0 < line <= len(lines) else ""
            raise ValueError(
                f"fill JSON 解析失败: {first_err.msg}（第 {line} 行第 {col} 列）\n"
                f"  出错行: {excerpt.strip()[:200]}\n"
                f"  常见原因: 字符串内含裸反斜杠（须写 \\\\ 或改用全角＼）、"
                f"未转义的双引号、直接回车换行。"
            ) from None
        print(f"⚠️ fill JSON 含非法反斜杠转义（如 \\ 后接空格/字母），已自动修复并继续；"
              f"请检查 fragment 中的反斜杠写法（详见 fill-schema.md「JSON 书写硬规则」）",
              file=sys.stderr)
        return fill


# ---------- 图形组件（脚本生成 SVG：模型只填数据，坐标/百分比一律脚本计算） ----------

def _num(v):
    """"390.40" / "18,062.5" / 390.4 → float；取首个数字串，失败返回 None"""
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d[\d,]*\.?\d*", str(v))
    return float(m.group(0).replace(",", "")) if m else None


def _fmt(v):
    """390.4 → "390.4"；294.0 → "294" """
    return f"{v:g}"


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


_SCENARIO_COLORS = {"pess": "#c75b5b", "base": "#c08a2e", "opt": "#6ba86b"}
_SCENARIO_NAMES = {"pess": "悲观", "base": "基础", "opt": "乐观"}


def build_scenario_spectrum(fill: dict) -> str:
    """05 目标价走廊：竖向柱版——x 轴=悲观/基础/乐观（与三情景表列方向一致），y 轴=价格，
    区间竖条 + 中枢横刻 + 现价水平虚线 + 中枢较现价涨跌幅（全部脚本计算）。
    输入 fill["scenarios"] = [{"key":"pess|base|opt","label":"悲观","low":294,"high":331}, ...]，
    现价取 fill["price"]。缺数据 → 返回空串（模板条件块整块删除）。"""
    price = _num(fill.get("price"))
    cols = []
    for s in fill.get("scenarios") or []:
        lo, hi = _num(s.get("low")), _num(s.get("high"))
        if lo is None or hi is None or hi <= lo:
            continue
        key = str(s.get("key") or "").lower()
        cols.append({"key": key,
                     "label": s.get("label") or _SCENARIO_NAMES.get(key, "情景"),
                     "low": lo, "high": hi, "mid": (lo + hi) / 2,
                     "color": _SCENARIO_COLORS.get(key, "#8899a6")})
    if not cols or not price:
        return ""
    order = {"pess": 0, "base": 1, "opt": 2}
    cols.sort(key=lambda r: order.get(r["key"], 1))  # 悲观/基础/乐观 从左到右

    W, H, L, R, T, B = 1000, 400, 64, 24, 46, 64
    lo_d = min([c["low"] for c in cols] + [price])
    hi_d = max([c["high"] for c in cols] + [price])
    pad = (hi_d - lo_d) * 0.08 or 1
    lo_d -= pad
    hi_d += pad

    def Y(v):
        return T + (hi_d - v) / (hi_d - lo_d) * (H - T - B)

    n = len(cols)
    plot_w = W - L - R
    col_w = plot_w / n
    bar_w = min(80, col_w * 0.42)

    parts = [f'<div class="plot-wrap"><svg viewBox="0 0 {W} {H}" role="img" '
             f'aria-label="目标价走廊" style="width:100%;height:auto;display:block;font-family:inherit;">']
    # 价格轴（左侧刻度 + 横向浅网格线）
    for i in range(5):
        v = lo_d + (hi_d - lo_d) * i / 4
        gy = Y(v)
        parts.append(f'<line x1="{L}" y1="{gy:.1f}" x2="{W - R}" y2="{gy:.1f}" stroke="#eef1f5" stroke-width="1"/>')
        parts.append(f'<text x="{L - 8}" y="{gy + 4:.1f}" text-anchor="end" font-size="11" fill="#8899a6">{_fmt(round(v))}</text>')
    # 现价水平虚线 + 右端标签
    py = Y(price)
    parts.append(f'<line x1="{L}" y1="{py:.1f}" x2="{W - R}" y2="{py:.1f}" '
                 f'stroke="#4a6fa5" stroke-width="1.5" stroke-dasharray="5 4"/>')
    parts.append(f'<text x="{W - R}" y="{py - 8:.1f}" text-anchor="end" font-size="12" '
                 f'font-weight="700" fill="#4a6fa5">现价 {_fmt(price)}</text>')
    # 情景柱
    for i, c in enumerate(cols):
        cx = L + col_w * (i + 0.5)
        y_hi, y_lo, y_mid = Y(c["high"]), Y(c["low"]), Y(c["mid"])
        pct = c["mid"] / price - 1
        pct_color = "#6ba86b" if pct >= 0 else "#c75b5b"
        parts.append(f'<rect x="{cx - bar_w / 2:.1f}" y="{y_hi:.1f}" width="{bar_w:.1f}" height="{y_lo - y_hi:.1f}" rx="8" '
                     f'fill="{c["color"]}" fill-opacity="0.14" stroke="{c["color"]}" stroke-width="1.5"/>')
        parts.append(f'<line x1="{cx - bar_w / 2 - 5:.1f}" y1="{y_mid:.1f}" x2="{cx + bar_w / 2 + 5:.1f}" y2="{y_mid:.1f}" '
                     f'stroke="{c["color"]}" stroke-width="2.5"/>')
        parts.append(f'<text x="{cx:.1f}" y="{y_hi - 24:.1f}" text-anchor="middle" font-size="13" '
                     f'font-weight="700" fill="{c["color"]}">{_fmt(c["mid"])}</text>')
        parts.append(f'<text x="{cx:.1f}" y="{y_hi - 9:.1f}" text-anchor="middle" font-size="11.5" '
                     f'font-weight="700" fill="{pct_color}">{pct * 100:+.1f}%</text>')
        parts.append(f'<text x="{cx:.1f}" y="{H - B + 20}" text-anchor="middle" font-size="13" '
                     f'font-weight="600" fill="#2c3e50">{_esc(c["label"])}</text>')
        parts.append(f'<text x="{cx:.1f}" y="{H - B + 37}" text-anchor="middle" font-size="11" '
                     f'fill="#8899a6">{_fmt(c["low"])} - {_fmt(c["high"])}</text>')
    parts.append('</svg></div>')
    parts.append('<span class="source">目标价走廊（脚本按 scenarios 字段生成）：竖条=情景目标价区间，'
                 '横刻=区间中枢，虚线=现价；柱顶=中枢值与较现价涨跌幅</span>')
    return "".join(parts)


def build_peers_plot(fill: dict) -> str:
    """07 估值-质量散点图：直角坐标系精确点位（x=PE, y=ROE），3×3 分带背景，
    目标公司钢蓝大点 + 白色描边。输入 fill["peers_plot"]：
    {"points":[{"name":"宁德时代","roe":24.7,"pe":21.3,"target":true}, ...],
     "pe_bands":[15,25], "roe_bands":[8,15]}（bands 可省，数组形式亦可）。
    缺数据 → 返回空串（peers_html 里的 matrix-table 兜底）。"""
    pp = fill.get("peers_plot")
    if not pp:
        return ""
    if isinstance(pp, list):
        points, pe_bands, roe_bands = pp, [15.0, 25.0], [8.0, 15.0]
    else:
        points = pp.get("points") or []
        pe_bands = pp.get("pe_bands") or [15.0, 25.0]
        roe_bands = pp.get("roe_bands") or [8.0, 15.0]
    pts = []
    for p in points:
        roe, pe = _num(p.get("roe")), _num(p.get("pe"))
        if roe is None or pe is None:
            continue
        pts.append({"name": str(p.get("name") or "?"), "roe": roe, "pe": pe,
                    "target": bool(p.get("target"))})
    if len(pts) < 2:
        return ""

    W, H, L, R, T, B = 1000, 460, 64, 30, 34, 52
    pe_lo = min([p["pe"] for p in pts] + pe_bands)
    pe_hi = max([p["pe"] for p in pts] + pe_bands)
    roe_lo = min([p["roe"] for p in pts] + roe_bands)
    roe_hi = max([p["roe"] for p in pts] + roe_bands)
    pe_pad = (pe_hi - pe_lo) * 0.10 or 1
    roe_pad = (roe_hi - roe_lo) * 0.12 or 1
    pe_lo -= pe_pad
    pe_hi += pe_pad
    roe_lo = max(0.0, roe_lo - roe_pad)
    roe_hi += roe_pad

    def X(pe):
        return L + (pe - pe_lo) / (pe_hi - pe_lo) * (W - L - R)

    def Y(roe):
        return T + (roe_hi - roe) / (roe_hi - roe_lo) * (H - T - B)

    xb = [X(b) for b in pe_bands]
    yb = [Y(b) for b in roe_bands]  # roe_bands[0]=8 → 下方线 yb[0] 更大；[1]=15 → 上方线

    parts = [f'<div class="plot-wrap"><svg viewBox="0 0 {W} {H}" role="img" '
             f'aria-label="估值-质量散点图" style="width:100%;height:auto;display:block;font-family:inherit;">']
    # 最优/最差象限底色（高ROE·低PE = 左上绿；低ROE·高PE = 右下红）
    parts.append(f'<rect x="{L}" y="{T}" width="{xb[0] - L:.1f}" height="{yb[1] - T:.1f}" fill="#6ba86b" fill-opacity="0.06"/>')
    parts.append(f'<rect x="{xb[1]:.1f}" y="{yb[0]:.1f}" width="{W - R - xb[1]:.1f}" height="{H - B - yb[0]:.1f}" fill="#c75b5b" fill-opacity="0.06"/>')
    # 象限角标签
    parts.append(f'<text x="{L + 8}" y="{T + 16}" font-size="11" fill="#8899a6">高质量 · 低估值</text>')
    parts.append(f'<text x="{W - R - 8}" y="{T + 16}" text-anchor="end" font-size="11" fill="#8899a6">高质量 · 高估值</text>')
    parts.append(f'<text x="{L + 8}" y="{H - B - 8}" font-size="11" fill="#8899a6">低质量 · 低估值</text>')
    parts.append(f'<text x="{W - R - 8}" y="{H - B - 8}" text-anchor="end" font-size="11" fill="#8899a6">低质量 · 高估值</text>')
    # 分带虚线
    for bx in xb:
        parts.append(f'<line x1="{bx:.1f}" y1="{T}" x2="{bx:.1f}" y2="{H - B}" stroke="#d7dee6" stroke-width="1" stroke-dasharray="4 4"/>')
    for by in yb:
        parts.append(f'<line x1="{L}" y1="{by:.1f}" x2="{W - R}" y2="{by:.1f}" stroke="#d7dee6" stroke-width="1" stroke-dasharray="4 4"/>')
    # 坐标轴 + 刻度
    parts.append(f'<line x1="{L}" y1="{H - B}" x2="{W - R}" y2="{H - B}" stroke="#dde3ea" stroke-width="1.2"/>')
    parts.append(f'<line x1="{L}" y1="{T}" x2="{L}" y2="{H - B}" stroke="#dde3ea" stroke-width="1.2"/>')
    for i in range(5):
        v = pe_lo + (pe_hi - pe_lo) * i / 4
        parts.append(f'<text x="{X(v):.1f}" y="{H - B + 18}" text-anchor="middle" font-size="11" fill="#8899a6">{_fmt(round(v))}x</text>')
        v2 = roe_lo + (roe_hi - roe_lo) * i / 4
        parts.append(f'<text x="{L - 8}" y="{Y(v2) + 4:.1f}" text-anchor="end" font-size="11" fill="#8899a6">{_fmt(round(v2))}%</text>')
    parts.append(f'<text x="{W - R}" y="{H - 8}" text-anchor="end" font-size="11" fill="#8899a6">PE(TTM)</text>')
    parts.append(f'<text x="{L}" y="{T - 12}" font-size="11" fill="#8899a6">ROE</text>')
    # 数据点（直接标注，免图例；点位于右半区时文字放左侧防溢出）
    for p in pts:
        cx, cy = X(p["pe"]), Y(p["roe"])
        label = f'{p["name"]} {_fmt(p["roe"])}%/{_fmt(p["pe"])}x'
        if p["target"]:
            parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="8" fill="#4a6fa5" stroke="#fff" stroke-width="2">'
                         f'<title>{_esc(label)}</title></circle>')
            parts.append(f'<text x="{cx:.1f}" y="{cy - 14:.1f}" text-anchor="middle" font-size="12" '
                         f'font-weight="700" fill="#4a6fa5">{_esc(label)}</text>')
        else:
            anchor, lx = ("end", cx - 12) if cx > L + (W - L - R) * 0.68 else ("start", cx + 12)
            parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="#9aa7b4">'
                         f'<title>{_esc(label)}</title></circle>')
            parts.append(f'<text x="{lx:.1f}" y="{cy + 4:.1f}" text-anchor="{anchor}" font-size="11.5" '
                         f'fill="#5a6b7d">{_esc(label)}</text>')
    parts.append('</svg></div>')
    parts.append('<span class="source">估值-质量散点图（脚本按 peers_plot 字段生成）：横轴 PE(TTM)、纵轴 ROE，'
                 '虚线为低/中/高分带；左上绿底=优质低估区，右下红底=低质高估区</span>')
    return "".join(parts)


def _check_l4_order(l4_html: str) -> None:
    """黄灯四类须固定 a→b→c→d 顺序（SKILL.md L4 规范）；检出乱序则告警，由模型修正后重渲。
    不做自动重排——四类内容块结构多变（有/无命中、合并段落），程序重排太脆。"""
    seq = re.findall(r"<strong>\s*([abcd])\s*[)）]", l4_html or "")
    if seq and seq != sorted(seq):
        print(f"⚠️ L4 黄灯扣分四类顺序应为 a→b→c→d，当前为 {'→'.join(seq)}；"
              f"请调整 l4_html 顺序后重新渲染", file=sys.stderr)


def render(fill_path: str, out_path: str = None) -> str:
    fill = _load_fill(fill_path)
    for k in REQUIRED_SCALAR:
        if not fill.get(k):
            raise ValueError(f"缺必填字段: {k}")

    _check_l4_order(fill.get("l4_html", ""))

    # 图形组件（脚本生成 SVG；数据缺省时为空串 → 模板条件块整块删除）
    spectrum_html = build_scenario_spectrum(fill)
    peers_plot_html = build_peers_plot(fill)
    peers_html = fill.get("peers_html", "")
    if peers_plot_html and "matrix-table" in peers_html:
        # 散点图已生成 → 手写九宫格冗余，自动删除（含"估值-质量矩阵："引导句）
        cleaned = re.sub(r'<p[^>]*>\s*<strong>\s*估值[-—]质量矩阵[^<]*</strong>\s*</p>\s*', "", peers_html)
        cleaned = re.sub(r'<table\b[^>]*class="matrix-table"[^>]*>.*?</table>\s*', "", cleaned, flags=re.I | re.S)
        if cleaned != peers_html:
            print("⚠️ 已提供 peers_plot 散点图，peers_html 中手写的 matrix-table 九宫格冗余，已自动删除",
                  file=sys.stderr)
        peers_html = cleaned

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
        "VALUATION_HTML": _transpose_scenario_table(fill.get("valuation_html", "")),
        "GAP_TIER": fill.get("gap_tier", "—"),
        "GAP_HTML": fill.get("gap_html", ""),
        "PEERS_META": fill.get("peers_meta", ""),
        "PEERS_HTML": peers_html,
        "SCENARIO_SPECTRUM_HTML": spectrum_html,
        "PEERS_PLOT_HTML": peers_plot_html,
        "CYCLE_META": fill.get("cycle_meta", ""),
        "CYCLE_HTML": fill.get("cycle_html", ""),
        "NEXT_REVIEW": fill.get("next_review", "—"),
        "DASH_HTML": fill.get("dash_html", ""),
        "POSITION_HTML": fill.get("position_html", ""),
        "GEN_TIME": fill.get("gen_time", date),
        "CALIB_NOTE": fill.get("calib_note", ""),
        "SCORE_TABLE_ROWS": sc["rows_html"],
        # 研究分（不考虑风险 → 扣黄灯 → 最终研究分）
        "PRE_RISK_RESEARCH": f"{pre_risk:.2f}",
        "YELLOW_TOTAL": f"{yellow_total:.1f}",
        "RESEARCH_SCORE": f"{research:.2f}",
        "RESEARCH_BADGE_CLASS": badge_class(research),
        # 时机分
        "TIMING_SCORE": (f"{timing:.2f}" if timing is not None else "—"),
        "TIMING_BADGE_CLASS": (badge_class(timing) if timing is not None else "badge-blue"),
        "TIMING_VALUE_CLASS": ("score-good" if timing >= 6 else "score-mid" if timing >= 4
                               else "score-bad") if timing is not None else "score-mid",
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
    # 图形字段缺失要"响亮"：缺 scenarios/peers_plot 时条件块是静默删除的，必须显式提醒
    missing_plots = []
    if not repl["SCENARIO_SPECTRUM_HTML"]:
        missing_plots.append("scenarios（05 目标价走廊未生成）")
    if not repl["PEERS_PLOT_HTML"]:
        missing_plots.append("peers_plot（07 散点图未生成，仅 peers_html 手写 matrix-table 兜底）")
    if missing_plots:
        print(f"⚠️ fill JSON 缺图形字段: {'；'.join(missing_plots)}。"
              f"请补充字段后重新渲染（格式见 fill-schema.md 顶层字段表）", file=sys.stderr)
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
