#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_report.py — 用 fill-data JSON 渲染个股深度分析 HTML 报告（零模型拼装）

用法:
    python render_report.py fill_600989.json                 # 渲染并自动命名输出
    python render_report.py fill_600989.json --out=out.html  # 指定输出路径

fill JSON 契约见 references/fill-schema.md。
核心特性：
- 评分汇总表由脚本计算（9 质量维度 + 2 时机维度×权重→加权→质量分/估值分/时机分→自动徽章色），消除模型算术错误
- 文件名自动生成：{公司名}-{代码}-{质量分}-{估值分}-{日期}.html（分数是算出来的，不是模型填的）
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

# 维度元数据：key -> (层, 显示名, 层内默认权重)
# v4.0 质量层：L1 本质六维（1A-1F 层内权重和=100）+ L3 预期三维（3A-3C 层内权重和=100）。
# 估值（原 2A）独立成估值分（valuation_score），不进质量分。
DIMS = [
    ("1A", "L1", "3.1 赛道与宏观", 12),
    ("1B", "L1", "3.2 产业链位置", 12),
    ("1C", "L1", "3.3 商业模式与护城河", 20),
    ("1D", "L1", "3.4 财务健康", 16),
    ("1E", "L1", "3.5 治理与资本配置", 20),
    ("1F", "L1", "3.6 资本回报质量", 20),
    ("3A", "L3", "4.1 利润增长", 40),
    ("3B", "L3", "4.2 项目确定性", 35),
    ("3C", "L3", "4.3 催化剂", 25),
]
# 层占比（质量分内 L1:L3，分型可通过 layer_share 覆盖）
DEFAULT_LAYER_SHARE = {"L1": 70, "L3": 30}
# 时机层（不入质量分）：筹码面 67% / 技术面 33%
TIMING_DIMS = [
    ("筹码面", "筹码面", 67),
    ("技术面", "技术面", 33),
]
# 旧版键名兼容（v2.1 前：2C=筹码面、2B=技术面）
_TIMING_LEGACY = {"2C": "筹码面", "2B": "技术面"}


def _timing_field(fill: dict, name: str) -> dict:
    """读取时机层字段（timing_scores / timing_weights），旧键名 2B/2C 自动映射并告警。"""
    src = fill.get(name) or {}
    out, legacy = {}, []
    for k, v in src.items():
        nk = _TIMING_LEGACY.get(k, k)
        if nk != k:
            legacy.append(k)
        out[nk] = v
    if legacy:
        print(f"⚠️ {name} 使用了旧版键名 {sorted(legacy)}，已按 2C→筹码面 / 2B→技术面 映射；"
              f"请改用新键名（fill-schema 已更新）", file=sys.stderr)
    return out
LAYER_NAMES = {"L1": "公司本质", "L3": "未来预期"}
REQUIRED_SCALAR = ["company", "code", "date"]

# Windows 文件名非法字符：\ / : * ? " < > | 及 ASCII 控制字符（\x00-\x1f）
_WIN_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _safe_filename(part: str) -> str:
    """清洗文件名片段中的 Windows 非法字符，替换为「·」。

    公司名可能带 *（如「南京工艺*ST」）、/、: 等字符，直接拼进文件名会导致
    Windows 报非法文件名。除非法字符外，还会去首尾空格与点（Windows 不允许结尾点）。
    """
    part = str(part).strip()
    part = _WIN_ILLEGAL.sub("·", part)
    part = part.rstrip(" .")
    return part or "未命名"


def badge_class(score: float) -> str:
    if score >= 7.0:
        return "badge-green"
    if score >= 4.0:
        return "badge-orange"
    return "badge-red"


def valuation_badge_class(score: float) -> str:
    """估值分徽章四档配色：≥8 绿 / 6-7.9 蓝 / 4-5.9 橙 / <4 红。"""
    if score >= 8.0:
        return "badge-green"
    if score >= 6.0:
        return "badge-blue"
    if score >= 4.0:
        return "badge-orange"
    return "badge-red"


def _quality_verdict(q: float) -> str:
    """质量分判词：≥7 好公司 / 5.5-6.9 中上 / 4-5.4 一般 / <4 回避。"""
    if q >= 7.0:
        return "好公司"
    if q >= 5.5:
        return "中上"
    if q >= 4.0:
        return "一般"
    return "回避"


def _valuation_verdict(v: float) -> str:
    """估值分判词（唯一口径）：≥8 深度安全边际 / 6-7.9 合理偏便宜 / 4-5.9 合理无安全边际 / <4 贵。"""
    if v >= 8.0:
        return "深度安全边际"
    if v >= 6.0:
        return "合理偏便宜"
    if v >= 4.0:
        return "合理无安全边际"
    return "贵"


def _timing_verdict(t: float) -> str:
    """时机分判词：≥6 好时机 / 4-5.9 中性 / <4 差时机。"""
    if t >= 6.0:
        return "好时机"
    if t >= 4.0:
        return "中性"
    return "差时机"


_CLASS_ALIASES = {"metric-label": "label", "metric-value": "value", "metric-sub": "sub"}


def _normalize_class_aliases(html: str) -> str:
    """模型偶发的幻觉类名归一：metric-label/metric-value/metric-sub → label/value/sub
    （模板只定义后者；前者无样式，三指标卡条会塌成无样式文本）。仅限 class 属性值内替换。"""
    def fix(m):
        quote, val = m.group(1), m.group(2)
        tokens = [_CLASS_ALIASES.get(t, t) for t in val.split()]
        return f"class={quote}{' '.join(tokens)}{quote}"
    return re.sub(r"class\s*=\s*([\"'])([^\"']*)\1", fix, html)


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
    """num 列中应左对齐的文字格：剥括号注释后含句读的纯文字/长句，或超 4 字的纯文字。
    括号内句读不参与判定（"±60-90 亿（手机毛利率仅 8.5%，缓冲更薄）"是数值+注释，随列右对齐）；
    ≤4 字短标记（"基础""偏多"）随列右对齐，长数值串（"13,600-15,300亿"）因含数字天然右对齐。"""
    t = re.sub(r"<[^>]+>", "", s or "").strip()
    t2 = re.sub(r"[（(][^）)]*[）)]", "", t)  # 先剥括号注释：括号内句读不参与判定
    if re.search(r"[，。；、：]", t2) and (not re.search(r"\d", t2) or len(t2) > 20):
        return True   # 纯文字带句读→左对齐；带数字的长句（>20字）仍是说明文→左对齐
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
    """v4.0 三轨：质量分（L1 六维 + L3 三维，不含估值）+ 估值分（独立）+ 时机分（微调）。
    返回 dict：rows_html（质量层明细）/ layer_scores / layer_share / pre_risk_quality /
    yellow_total / quality（质量分）/ valuation（估值分）/ timing（时机分）/ red_flag。
    校验：L1 六维层内权重和=100；L3 三维层内权重和=100；layer_share 两值和=100；
    时机层权重和=100。"""
    scores = fill.get("scores") or {}
    w_override = fill.get("weights") or {}
    missing = [d[0] for d in DIMS if d[0] not in scores]
    if missing:
        raise ValueError(f"scores 缺维度: {missing}")

    # 1D 红旗扣分（结构化字段 red_deductions：[{item, points}]，单项上限 1 分）
    red_deductions = fill.get("red_deductions") or []
    for r in red_deductions:
        rp = float(r.get("points", 0))
        if rp > 1:
            raise ValueError(f"red_deductions 单项扣分 {rp} > 1（{r.get('item', '?')}）："
                             f"1D 红旗每项扣分上限 1 分")
    red_total = round(sum(float(r.get("points", 0)) for r in red_deductions), 2)
    if red_total:
        scores = dict(scores)
        scores["1D"] = max(0.0, float(scores["1D"]) - red_total)  # 下限 0

    # 层内权重（分型可通过 weights 覆盖；默认值即各分型的基础权重，见 scoring.md）
    weights = {}
    for key, _layer, _name, default_w in DIMS:
        weights[key] = float(w_override.get(key, default_w))
    for layer in ("L1", "L3"):
        layer_w = sum(weights[d[0]] for d in DIMS if d[1] == layer)
        if abs(layer_w - 100.0) > 0.01:
            raise ValueError(f"{layer} 层内权重总和 = {layer_w}，必须为 100（分型调整时各层内权重之和仍须等于100）")

    # 层占比（质量分内 L1:L3，分型可通过 layer_share 覆盖）
    ls_raw = fill.get("layer_share") or {}
    ls = {k: float(ls_raw.get(k, DEFAULT_LAYER_SHARE[k])) for k in ("L1", "L3")}
    if abs(sum(ls.values()) - 100.0) > 0.01:
        raise ValueError(f"layer_share 之和 = {sum(ls.values())}，必须为 100")

    layer_scores = {}
    rows = []
    for layer in ("L1", "L3"):
        dims = [d for d in DIMS if d[1] == layer]
        layer_s = sum(float(scores[d[0]]) * weights[d[0]] for d in dims) / 100.0
        layer_scores[layer] = layer_s
        for j, (key, _l, name, _dw) in enumerate(dims):
            s = float(scores[key])
            w = weights[key]
            wtd = s * w / 100.0
            badge = badge_class(s)
            first = (f'<td rowspan="{len(dims)}"><strong>{layer}</strong> '
                     f'{LAYER_NAMES[layer]}（占质量分 {ls[layer]:.0f}%）</td>') if j == 0 else ""
            rows.append(
                f'<tr>{first}<td>{name}</td>'
                f'<td class="center score-cell"><span class="badge {badge}">{s:.1f}</span></td>'
                f'<td class="num">{w:g}%</td><td class="num">{wtd:.2f}</td></tr>'
            )

    # 不考虑风险质量分 = L1 层分×L1占比 + L3 层分×L3占比
    pre_risk = sum(layer_scores[l] * ls[l] for l in ("L1", "L3")) / 100.0

    # 黄灯扣分（模型填 yellow_deductions 明细：[{label, points}]）
    # 硬校验：单项 >1 或累计 >2 → 拒渲染（按规则应升红灯）
    yellow = fill.get("yellow_deductions") or []
    for y in yellow:
        yp = float(y.get("points", 0))
        if yp > 1:
            raise ValueError(f"黄灯单项扣分 {yp} > 1（{y.get('label', '?')}）："
                             f"累计扣分>2 或单项>1，应按规则升红灯")
    yellow_total = round(sum(float(y.get("points", 0)) for y in yellow), 2)
    if yellow_total > 2:
        raise ValueError(f"黄灯累计扣分 {yellow_total} > 2：累计扣分>2 或单项>1，应按规则升红灯")
    quality = max(0.0, round(pre_risk - yellow_total, 2))  # 最终质量分（下限 0）

    # 估值分（独立价格轨；fill 里的 valuation_score 只做范围校验，
    # 最终值由 render 用四件套计算结果覆盖，见 compute_valuation_score）
    valuation = None
    v_raw = fill.get("valuation_score")
    if v_raw is not None:
        try:
            valuation = float(v_raw)
        except (TypeError, ValueError):
            raise ValueError("valuation_score 必须是 0-10 数字")
        if not (0 <= valuation <= 10):
            raise ValueError(f"valuation_score = {valuation} 超出 0-10 范围")

    # 时机分（筹码面 67% + 技术面 33%；只算分值，时机轨表在 11 由模型呈现，09 只给小结）
    t_scores = _timing_field(fill, "timing_scores")
    t_weights = {k: float(_timing_field(fill, "timing_weights").get(k, dw)) for k, _n, dw in TIMING_DIMS}
    tw_sum = sum(t_weights.values())
    if abs(tw_sum - 100.0) > 0.01:
        raise ValueError(f"时机层权重总和 = {tw_sum}，必须为 100")
    timing = None
    if t_scores:
        timing = sum(float(t_scores.get(k, 0)) * t_weights[k] for k, _n, _w in TIMING_DIMS) / 100.0

    red_flag = (fill.get("red_flag") or "").strip()
    return {
        "rows_html": "\n".join(rows), "layer_scores": layer_scores,
        "layer_share": ls, "pre_risk_quality": pre_risk,
        "yellow_total": yellow_total, "quality": quality,
        "red_total": red_total, "red_deductions": red_deductions,
        "valuation": valuation, "timing": timing,
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


def _fmt_price(v):
    """走廊图价格标签：最多 4 位有效数字（472.3 / 46.15），精度匹配不确定性。"""
    return f"{v:.4g}"


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


_SCENARIO_COLORS = {"pess": "#c75b5b", "base": "#c08a2e", "opt": "#6ba86b"}
_SCENARIO_NAMES = {"pess": "悲观", "base": "基础", "opt": "乐观"}


def build_scenario_spectrum(fill: dict, calc: dict = None) -> str:
    """05 目标价走廊：竖向柱版——x 轴=悲观/基础/乐观（与三情景表列方向一致），y 轴=价格，
    区间竖条 + 中枢横刻 + 现价水平虚线 + 中枢较现价涨跌幅（全部脚本计算）。
    calc（compute_valuation 结果）存在时用其算出的目标价区间（与三情景表严格一致）；
    否则回退到 fill["scenarios"] 手写区间。缺数据 → 返回空串（模板条件块整块删除）。"""
    price = _num(fill.get("price"))
    if calc:
        cols = [{"label": r["label"], "low": r["low"], "high": r["high"], "mid": r["mid"],
                 "color": r["color"]} for r in calc["rows"]]
    else:
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
    if not calc:
        order = {"pess": 0, "base": 1, "opt": 2}
        cols.sort(key=lambda r: order.get(r.get("key", ""), 1))  # 悲观/基础/乐观 从左到右

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
                     f'font-weight="700" fill="{c["color"]}">{_fmt_price(c["mid"])}</text>')
        parts.append(f'<text x="{cx:.1f}" y="{y_hi - 9:.1f}" text-anchor="middle" font-size="11.5" '
                     f'font-weight="700" fill="{pct_color}">{pct * 100:+.1f}%</text>')
        parts.append(f'<text x="{cx:.1f}" y="{H - B + 20}" text-anchor="middle" font-size="13" '
                     f'font-weight="600" fill="#2c3e50">{_esc(c["label"])}</text>')
        parts.append(f'<text x="{cx:.1f}" y="{H - B + 37}" text-anchor="middle" font-size="11" '
                     f'fill="#8899a6">{_fmt_price(c["low"])} - {_fmt_price(c["high"])}</text>')
    parts.append('</svg></div>')
    parts.append('<span class="source">目标价走廊（脚本按 scenarios 字段生成）：竖条=情景目标价区间，'
                 '横刻=区间中枢，虚线=现价；柱顶=中枢值与较现价涨跌幅</span>')
    return "".join(parts)


def compute_valuation(fill: dict):
    """valuation 字段（结构化三情景假设）→ 全部估值数字由脚本计算。
    输入：{"shares": 46.27（亿股）, "horizon": "12个月",
           "scenarios": [{"key":"pess","label":"悲观","trigger":"…","profit":850（归母净利,亿）,"pe":[16,18]}, …]}
    返回 None（字段缺失/数据不足）或 dict：
    rows（含每情景 eps/price_lo/price_hi/mid/upside）、central（年化中枢）、
    odds（赔率）、dispersion（离散度）、base_lo/base_hi、horizon。"""
    v = fill.get("valuation")
    if not v:
        return None
    price = _num(fill.get("price"))
    shares = _num(v.get("shares"))
    if not price or not shares:
        print("⚠️ valuation 已填但缺 price/shares，情景表与三指标卡未生成", file=sys.stderr)
        return None
    order = {"pess": 0, "base": 1, "opt": 2}
    rows = []
    for s in v.get("scenarios") or []:
        profit, pe = _num(s.get("profit")), s.get("pe") or []
        pe_lo, pe_hi = (_num(pe[0]), _num(pe[1])) if len(pe) >= 2 else (None, None)
        if profit is None or pe_lo is None or pe_hi is None:
            continue
        key = str(s.get("key") or "").lower()
        lo, hi = profit * pe_lo / shares, profit * pe_hi / shares
        mid = (lo + hi) / 2
        rows.append({"key": key, "label": s.get("label") or _SCENARIO_NAMES.get(key, "情景"),
                     "color": _SCENARIO_COLORS.get(key, "#8899a6"),
                     "trigger": str(s.get("trigger") or ""), "horizon": str(s.get("horizon") or v.get("horizon") or "12个月"),
                     "profit": profit, "pe_lo": pe_lo, "pe_hi": pe_hi,
                     "eps": profit / shares, "low": lo, "high": hi, "mid": mid,
                     "upside": mid / price - 1})
    if not rows:
        return None
    rows.sort(key=lambda r: order.get(r["key"], 1))
    pess, base, opt = rows[0], rows[1] if len(rows) > 1 else rows[0], rows[-1]
    horizon = str(v.get("horizon") or "12个月")
    m = re.search(r"(\d+\.?\d*)", horizon)
    if m:
        hv = float(m.group(1))
        months = hv * 12 if "年" in horizon else hv  # 含"年"→×12；含"月"或纯数字 → 按月
    else:
        print(f"⚠️ horizon「{horizon}」无法解析出时长，按 12 个月处理", file=sys.stderr)
        months = 12.0
    central_raw = base["mid"] / price - 1
    central = (1 + central_raw) ** (12 / months) - 1 if months > 0 else central_raw
    down = price - pess["low"]
    odds = None if down <= 0 else (base["mid"] - price) / down  # down<=0 → 悲观仍正收益 → ∞
    dispersion = (opt["mid"] - pess["mid"]) / price
    if rows[0]["mid"] > rows[-1]["mid"]:
        print("⚠️ valuation 三情景目标价顺序异常（悲观中枢 > 乐观中枢），请检查 profit/pe 假设", file=sys.stderr)
    return {"rows": rows, "central": central, "central_raw": central_raw, "months": months,
            "odds": odds, "dispersion": dispersion, "base_lo": base["low"], "base_hi": base["high"],
            "horizon": horizon, "price": price}


def _map_central(central: float) -> float:
    pct = central * 100
    if pct >= 20:
        return 9.0
    if pct >= 15:
        return 8.0
    if pct >= 10:
        return 7.0
    if pct >= 5:
        return 6.0
    if pct >= 0:
        return 5.0
    if pct >= -5:
        return 4.0
    if pct >= -10:
        return 3.0
    return 2.0


def _map_odds(odds) -> float:
    if odds is None:
        return 10.0  # ∞（悲观仍正收益）
    if odds >= 2:
        return 8.5
    if odds >= 1.5:
        return 7.5
    if odds >= 1.0:
        return 6.0
    if odds >= 0.5:
        return 5.0
    if odds >= 0:
        return 3.5
    return 2.0


def _map_warranted(pe_ttm: float, band: list) -> float:
    mid = (band[0] + band[1]) / 2
    ratio = pe_ttm / mid
    if ratio < 0.8:
        return 9.0
    if ratio < 0.9:
        return 8.0
    if ratio < 1.0:
        return 7.0
    if ratio <= 1.1:
        return 5.0
    if ratio <= 1.2:
        return 3.5
    return 2.0


def _map_div(div_yield: float, risk_free: float) -> float:
    spread = div_yield - risk_free
    if spread >= 3:
        return 9.0
    if spread >= 2:
        return 8.0
    if spread >= 1:
        return 7.0
    if spread >= 0:
        return 6.0
    if spread >= -1:
        return 5.0
    return 4.0


def compute_valuation_score(calc: dict, inputs: dict):
    """估值分四件套量化 = 中枢×0.4 + 赔率×0.25 + 合理倍数×0.25 + 股息×0.1。
    inputs: {"pe_ttm": 13.5, "pe_band": [14.5, 15.5], "div_yield": 1.6, "risk_free": 1.7}
    返回 dict（score + 四件套各分 + formula 文字）或 None（缺 calc/inputs/字段）。"""
    if not calc or not inputs:
        return None
    pe_ttm = _num(inputs.get("pe_ttm"))
    band = inputs.get("pe_band") or []
    if pe_ttm is None or len(band) < 2:
        return None
    band = [_num(band[0]), _num(band[1])]
    if band[0] is None or band[1] is None or band[1] <= band[0]:
        return None
    central_s = _map_central(calc["central"])
    odds_s = _map_odds(calc["odds"])
    warranted_s = _map_warranted(pe_ttm, band)
    div_yield = _num(inputs.get("div_yield"))
    risk_free = _num(inputs.get("risk_free"))
    div_s = _map_div(div_yield, risk_free) if (div_yield is not None and risk_free is not None) else 5.0
    total = round(central_s * 0.4 + odds_s * 0.25 + warranted_s * 0.25 + div_s * 0.1, 1)
    return {
        "score": total,
        "central_s": central_s, "odds_s": odds_s,
        "warranted_s": warranted_s, "div_s": div_s,
        "formula": (f"中枢 {central_s:g}×0.4 + 赔率 {odds_s:g}×0.25 + "
                    f"合理倍数 {warranted_s:g}×0.25 + 股息 {div_s:g}×0.1"),
    }


def build_scenario_block(calc: dict) -> str:
    """由 compute_valuation 结果生成三情景对比表 + 三指标卡条（scenario-table/metric-card 骨架，
    类名全部脚本写死，杜绝幻觉类名与手算错误）。"""
    if not calc:
        return ""
    rows = calc["rows"]
    head = ('<tr><th>指标</th>' + "".join(
        f'<th class="center">{_esc(r["label"])}情景</th>' for r in rows) + "</tr>")

    def row(name, fmt, cls="num"):
        cells = "".join(f'<td class="{cls}">{fmt(r)}</td>' if cls else f"<td>{fmt(r)}</td>" for r in rows)
        return f"<tr><td>{name}</td>{cells}</tr>"

    body = "".join([
        row("时间维度", lambda r: _esc(r["horizon"]), "center"),
        row("触发条件", lambda r: _esc(r["trigger"]), ""),
        row("归母净利", lambda r: f"{r['profit']:,.0f} 亿"),
        row("EPS", lambda r: f"{r['eps']:.2f}"),
        row("PE", lambda r: f"{r['pe_lo']:g}-{r['pe_hi']:g}x"),
        row("目标价", lambda r: f"{r['low']:.0f}-{r['high']:.0f} 元"),
        row("较现价", lambda r: f'<span class="{"up" if r["upside"] >= 0 else "down"}">{r["upside"] * 100:+.1f}%</span>（中值{r["mid"]:.0f}）'),
    ])
    table = ('<div class="table-scroll"><table class="scenario-table"><thead>'
             + head + "</thead><tbody>" + body + "</tbody></table></div>")

    c, odds, disp = calc["central"], calc["odds"], calc["dispersion"]
    c_cls = "up" if c >= 0 else "down"
    c_sub = f'基础中值 {calc["rows"][1]["mid"] if len(calc["rows"])>1 else calc["rows"][0]["mid"]:.0f} ÷ 现价 {calc["price"]:g} − 1（{calc["horizon"]}）'
    if c < 0:
        c_sub += "；中枢为负 → 回避"
    if odds is None:
        o_val, o_cls, o_sub = "∞", "up", "悲观下限高于现价——最强不对称信号，仓位可上浮一档"
    else:
        o_val, o_cls = f"{odds:.2f}", "up" if odds >= 1.5 else "down"
        o_sub = "(基础中值−现价)÷(现价−悲观下限)；>1.5 为良好不对称"
    if disp < 0.30:
        d_cls, d_note = "up", "可预测"
    elif disp <= 0.60:
        d_cls, d_note = "mid", "中不确定"
    else:
        d_cls, d_note = "down", "高发散，仓位降一档"
    cards = (
        '<div class="metric-row">'
        f'<div class="metric-card"><div class="label">年化中枢期望收益</div>'
        f'<div class="value {c_cls}">{c * 100:+.1f}%</div><div class="sub">{c_sub}</div></div>'
        f'<div class="metric-card"><div class="label">赔率（上行/下行）</div>'
        f'<div class="value {o_cls}">{o_val}</div><div class="sub">{o_sub}</div></div>'
        f'<div class="metric-card"><div class="label">情景离散度</div>'
        f'<div class="value {d_cls}">{disp * 100:.1f}%</div>'
        f'<div class="sub">（乐观中值−悲观中值）÷ 现价；{d_note}</div></div>'
        '</div>')
    return table + cards


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
            # 靠近顶部/右侧时标签改放下方/左侧，避免与象限角标、图边重叠
            if cy < T + 50:
                lx, ly, anchor = cx, cy + 24, "middle"
            elif cx > L + (W - L - R) * 0.75:
                lx, ly, anchor = cx - 14, cy + 4, "end"
            else:
                lx, ly, anchor = cx, cy - 14, "middle"
            parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" font-size="12" '
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


def _plain_text(frag: str) -> str:
    """剥掉 HTML 标签后的纯文本（用于内容地板字数校验）。"""
    return re.sub(r"<[^>]+>", "", frag or "").strip()


def validate_content(fill: dict, calc: dict = None) -> None:
    """内容级校验（成稿前自动复核，借鉴 equity-research 检查器思路）。
    硬错误（拒渲染）：分数越界、valuation_inputs 缺失、valuation 三情景字段不全、
    红灯熔断缺"不建议参与"、thesis 手写价与脚本计算值不一致、内容地板（空心章节）、
    表格缺来源标注；其余 → stderr 告警（P1），模型看到即修正。
    calc 为 compute_valuation 结果（thesis 一致性校验用）。"""
    # 分数范围（0-10）越界是硬错误
    for field in ("scores", "timing_scores"):
        for k, v in (_timing_field(fill, field) if field == "timing_scores" else (fill.get(field) or {})).items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{field}.{k} 不是数字: {v!r}")
            if not (0 <= fv <= 10):
                raise ValueError(f"{field}.{k} = {fv} 超出 0-10 范围")

    # valuation_inputs 必填（估值分强制脚本化，四键缺一不可）
    vi = fill.get("valuation_inputs")
    if not isinstance(vi, dict):
        raise ValueError('valuation_inputs 为必填字段：{"pe_ttm":…, "pe_band":[低,高], '
                         '"div_yield":…, "risk_free":…}（估值分由脚本四件套计算，不再接受手填）')
    miss_vi = [k for k in ("pe_ttm", "pe_band", "div_yield", "risk_free") if k not in vi]
    if miss_vi:
        raise ValueError(f"valuation_inputs 缺键: {miss_vi}（四键必填：pe_ttm / pe_band / div_yield / risk_free）")

    # valuation 结构化三情景必填且完整（每情景：净利 + PE 区间 + horizon）
    v = fill.get("valuation")
    if not isinstance(v, dict) or not v.get("scenarios"):
        raise ValueError("valuation 为必填字段：结构化三情景假设（shares / horizon / scenarios），"
                         "目标价与估值分全部由脚本计算")
    if _num(v.get("shares")) is None:
        raise ValueError("valuation.shares 缺失或非法（总股本，亿股）")
    skeys = set()
    for s in v.get("scenarios") or []:
        skeys.add(str(s.get("key") or "").lower())
        slab = s.get("label") or s.get("key") or "?"
        if _num(s.get("profit")) is None:
            raise ValueError(f"valuation.scenarios[{slab}] 缺净利假设（profit，归母净利亿元）")
        pe = s.get("pe") or []
        if len(pe) < 2 or _num(pe[0]) is None or _num(pe[1]) is None:
            raise ValueError(f"valuation.scenarios[{slab}] 缺 PE 区间（pe: [低, 高]）")
        if not str(s.get("horizon") or v.get("horizon") or "").strip():
            raise ValueError(f"valuation.scenarios[{slab}] 缺时间维度（horizon，可放情景级或 valuation 级）")
    if not {"pess", "base", "opt"} <= skeys:
        raise ValueError(f"valuation.scenarios 必须含 pess/base/opt 三情景，当前只有: {sorted(skeys)}")

    # 红灯熔断：red_flag 非空 → position_html 必须包含"不建议参与"
    red_flag = (fill.get("red_flag") or "").strip()
    pos_html = fill.get("position_html") or ""
    if red_flag and "不建议参与" not in _plain_text(pos_html):
        raise ValueError(f"红灯熔断：red_flag「{red_flag}」非空，position_html 必须包含「不建议参与」结论")

    # thesis 三情景价一致性：手写 span 价 vs 脚本按 valuation 算出的中枢价
    th = fill.get("thesis_html", "")
    span_prices = {}
    for cls, key in (("scenario-pess", "pess"), ("scenario-base", "base"), ("scenario-opt", "opt")):
        m = re.search(r'<span\b[^>]*class="[^"]*\b' + cls + r'\b[^"]*"[^>]*>(.*?)</span>', th, re.I | re.S)
        if m:
            span_prices[key] = _num(re.sub(r"<[^>]+>", "", m.group(1)))
    if len(span_prices) == 3 and calc:
        cmap = {r["key"]: r["mid"] for r in calc["rows"]}
        bad = []
        for k in ("pess", "base", "opt"):
            c, f = cmap.get(k), span_prices[k]
            if c and f is not None and abs(f - c) > 0.1 and abs(f - c) / c > 0.02:
                bad.append(f"{_SCENARIO_NAMES[k]} 手写 {f:g} vs 脚本 {c:.2f}")
        if bad:
            raise ValueError("thesis_html 三情景手写价与 valuation 计算值不一致（相对偏差>2% 且绝对差>0.1）："
                             + "；".join(bad)
                             + f"。手写={ {k: span_prices[k] for k in ('pess','base','opt')} }，"
                             + f"脚本={ {k: round(cmap.get(k, 0), 2) for k in ('pess','base','opt')} }")

    # 内容地板（空心章节一律拒渲染）
    concl_len = len(_plain_text(fill.get("conclusion_html")))
    if concl_len < 200:
        raise ValueError(f"conclusion_html 纯文本仅 {concl_len} 字 < 200：核心结论四段不能为空洞")
    for name, need in (("l1_html", 6), ("l3_html", 3)):
        n = len(re.findall(r"dim-block", fill.get(name) or ""))
        if n < need:
            raise ValueError(f"{name} 仅 {n} 个 dim-block < {need}：每个评分维度必须各有一个维度块")
    if "<table" not in (fill.get("peers_html") or ""):
        raise ValueError("peers_html 不含 <table>：同业对比必须有数据表")
    pos_len = len(_plain_text(pos_html))
    if pos_len < 100:
        raise ValueError(f"position_html 纯文本仅 {pos_len} 字 < 100：仓位决策四步不能为空洞")
    # 含表格的章节字段：source 来源标注数必须 ≥ 表格数
    for name in ("conclusion_html", "p0_html", "l1_html", "l3_html", "l4_html", "valuation_html",
                 "gap_html", "peers_html", "dash_html", "position_html", "review_html"):
        frag = fill.get(name) or ""
        n_tbl, n_src = frag.count("<table"), frag.count('class="source"')
        if n_tbl and n_src < n_tbl:
            raise ValueError(f"{name} 含 {n_tbl} 张数据表但只有 {n_src} 个 `.source` 来源标注："
                             f"每张表下方必须有来源标注")

    warns = []
    # 必填字段缺失告警（fill-schema 标 ✓ 但渲染器原零校验，静默缺失会让分数算错或结构残缺）
    if not fill.get("timing_scores"):
        warns.append("timing_scores 缺失或为空：时机分将显示 —，请补筹码面/技术面得分")
    if "yellow_deductions" not in fill:
        warns.append("yellow_deductions 键缺失：黄灯扣分按 0 处理，质量分可能虚高；无扣分请显式填 []")
    if not th.strip():
        warns.append("thesis_html 缺失：Hero 一句话结论为空")
    # 分型权重交叉校验：非默认分型必须显式填 weights/layer_share，否则静默用默认值算错分
    st = str(fill.get("stock_type") or "")
    if any(t in st for t in ("稳定价值", "金融", "银行", "保险", "券商", "快速成长", "未盈利", "困境反转")):
        if not fill.get("layer_share"):
            warns.append(f"stock_type={st} 层占比非默认，但未填 layer_share——脚本将用默认 70:30 计算，分数可能错误")
        if not fill.get("weights"):
            warns.append(f"stock_type={st} L1 权重非默认，但未填 weights——脚本将用基础权重计算，分数可能错误")
    # thesis 三情景价格标注完整性
    if th and not all(c in th for c in ("scenario-pess", "scenario-base", "scenario-opt")):
        warns.append("thesis_html 缺三情景价格标注（scenario-pess/base/opt span 未齐）")
    # peers_plot 目标公司标记
    pp = fill.get("peers_plot")
    pts = (pp.get("points") if isinstance(pp, dict) else pp) or []
    if pts:
        tg = [p for p in pts if p.get("target")]
        if not tg:
            warns.append("peers_plot 没有 target=true 的目标公司点")
        elif fill.get("company") and str(fill["company"]) not in str(tg[0].get("name", "")):
            warns.append(f"peers_plot 目标点名称「{tg[0].get('name')}」与公司名「{fill['company']}」不一致")
    # prev 内部字段校验（回测模式锚点缺项会静默显示 "?"/"—"）
    if fill.get("prev"):
        pv = fill["prev"]
        for k in ("date", "quality", "valuation", "timing", "target_range"):
            if not pv.get(k):
                warns.append(f"prev.{k} 缺失：回测对比条该行将显示缺省值，请补全上版锚点")
        # 复盘高亮校验：评分变化/被证伪假设/新增变量应挂 .rev（全文 <3 处说明漏标）
        rev_n = sum((fill.get(name) or "").count('class="rev"')
                    for name in ("thesis_html", "conclusion_html", "p0_html", "l1_html", "l3_html",
                                 "l4_html", "valuation_html", "gap_html", "peers_html",
                                 "dash_html", "position_html", "review_html"))
        if rev_n < 3:
            warns.append(f"回测模式下 .rev 高亮过少（全文仅 {rev_n} 处 < 3）："
                         f"评分变化/被证伪假设/新增变量应标注（fill-schema 的 .rev 规则）")
    # 其余 fill-schema 标 ✓ 但渲染器零校验的必填字段
    for name in ("valuation_method", "stock_type", "gap_tier", "peers_meta", "next_review"):
        if not str(fill.get(name) or "").strip() or fill.get(name) == "—":
            warns.append(f"{name} 缺失或为占位符：对应章节标题/meta 将为空白")
    if not (fill.get("subtitle") or "").strip():
        warns.append("subtitle 缺失：Hero 副标题为空")
    elif "报告日期" in fill["subtitle"]:
        warns.append("subtitle 含「报告日期」：模板 Hero 会自动追加报告日期，subtitle 请勿再写日期")
    for w in warns:
        print(f"⚠️ 内容校验: {w}", file=sys.stderr)


def _tag_timing_table(html: str) -> str:
    """11 时机判定小表（表体含 技术面/筹码面 行的表）自动补 class="timing-table"——
    模板 CSS 对该表除末列（依据长文）外强制不换行，防止"技术面/筹码面/时机分"折行。"""
    def repl_table(m):
        tbl = m.group(0)
        if "技术面" not in tbl or "筹码面" not in tbl or "timing-table" in tbl:
            return tbl
        open_m = re.match(r"<table\b([^>]*)>", tbl, re.I)
        attrs = open_m.group(1)
        cm = re.search(r'class\s*=\s*(["\'])([^"\']*)\1', attrs, re.I)
        if cm:
            new_attrs = (attrs[:cm.start()] + f'class={cm.group(1)}{cm.group(2)} timing-table{cm.group(1)}'
                         + attrs[cm.end():])
        else:
            new_attrs = attrs.rstrip() + ' class="timing-table"'
        return f"<table{new_attrs}>" + tbl[open_m.end():]
    return re.sub(r"<table\b[^>]*>.*?</table>", repl_table, html, flags=re.I | re.S)


def _check_l4_order(l4_html: str) -> None:
    """黄灯四类须固定 a→b→c→d 顺序（SKILL.md L4 规范）；检出乱序则告警，由模型修正后重渲。
    不做自动重排——四类内容块结构多变（有/无命中、合并段落），程序重排太脆。"""
    seq = re.findall(r"<strong>\s*[（(]?\s*([abcd])\s*[)）]?", l4_html or "")
    if seq and seq != sorted(seq):
        print(f"⚠️ L4 黄灯扣分四类顺序应为 a→b→c→d，当前为 {'→'.join(seq)}；"
              f"请调整 l4_html 顺序后重新渲染", file=sys.stderr)


def build_prev_strip(prev: dict, quality: float, valuation: float, timing, target_range: str) -> str:
    """回测模式的 Hero 对比条：基于上版日期 + 质量分/估值分/时机分/目标价 旧→新。
    分数差值脚本计算，模型只在 prev 里给上版锚点数据。prev 为空 → 返回空串（非回测模式）。
    旧版 prev 键 research 自动映射到 quality（兼容旧回测数据）。"""
    if not prev:
        return ""
    items = []
    for label, old, new in (("质量分", _num(prev.get("quality", prev.get("research"))), quality),
                            ("估值分", _num(prev.get("valuation")), valuation),
                            ("时机分", _num(prev.get("timing")), timing)):
        if old is not None and new is not None:
            d = new - old
            cls = "up" if d >= 0 else "down"
            items.append(f'{label} {old:.2f}→{new:.2f} <span class="{cls}">({d:+.2f})</span>')
    if prev.get("target_range"):
        items.append(f'目标价 {_esc(str(prev["target_range"]))} → {_esc(str(target_range))}')
    body = ' ｜ '.join(items)
    return (f'<div class="prev-strip"><span class="prev-tag">复盘更新</span>'
            f'基于 {_esc(str(prev.get("date", "?")))} 版' + (f' ｜ {body}' if body else '') + '</div>')


# ---------- 脚本生成区块（6 质量分汇总 / 7 估值过程卡 / 11 三轨判定与仓位结论卡） ----------

def _valuation_four_rows(calc: dict, vc: dict, inputs: dict):
    """估值四件套明细行（项目/输入值/映射得分/权重），7 估值过程卡用。"""
    pe_ttm = _num(inputs.get("pe_ttm"))
    band = inputs.get("pe_band") or [None, None]
    band_lo, band_hi = _num(band[0]), _num(band[1])
    div_yield = _num(inputs.get("div_yield"))
    risk_free = _num(inputs.get("risk_free"))
    odds_txt = "∞（悲观下限高于现价）" if calc["odds"] is None else f"{calc['odds']:.2f}"
    div_txt = (f"股息率 {div_yield:g}% − 无风险 {risk_free:g}% = {div_yield - risk_free:+.1f}pct"
               if div_yield is not None and risk_free is not None else "缺股息输入（按中性 5 分）")
    return [
        ("中枢分", f"年化中枢 {calc['central'] * 100:+.1f}%（{calc['horizon']}）", vc["central_s"], 40),
        ("赔率分", f"赔率 {odds_txt}", vc["odds_s"], 25),
        ("合理倍数分", f"PE(TTM) {pe_ttm:g}x vs 合理带 {band_lo:g}-{band_hi:g}x", vc["warranted_s"], 25),
        ("股息分", div_txt, vc["div_s"], 10),
    ]


def build_score_summary(sc: dict) -> str:
    """6 质量分汇总章节（全部脚本生成）：只保留质量分明细表
    （1A-1F + 3A-3C 每维一行 → 层分×层占比 → 1D 红旗扣分 → 黄灯扣分 → 最终质量分）。
    估值分/时机分明细不在此汇总——估值分过程卡在 7 章顶部，时机判定表在 11 章由模型呈现。"""
    layer_scores, ls = sc["layer_scores"], sc["layer_share"]
    quality, yellow_total = sc["quality"], sc["yellow_total"]
    red_total = sc["red_total"]

    q_rows = [sc["rows_html"]]
    for layer in ("L1", "L3"):
        q_rows.append(
            f'<tr><td colspan="2"><strong>{layer} 层分 × 层占比</strong>'
            f'（{layer_scores[layer]:.2f} × {ls[layer]:.0f}%）</td>'
            f'<td></td><td class="num">{ls[layer]:.0f}%</td>'
            f'<td class="num">{layer_scores[layer] * ls[layer] / 100:.2f}</td></tr>')
    q_rows.append(
        f'<tr><td colspan="2"><span class="down">1D 红旗扣分</span>'
        + (f'（{_esc("；".join(str(r.get("item", "")) for r in sc["red_deductions"]))}）' if sc["red_deductions"] else "")
        + f'</td><td></td><td></td><td class="num"><span class="down">−{red_total:.1f}</span></td></tr>')
    q_rows.append(
        f'<tr><td colspan="2"><span class="down">黄灯扣分合计</span></td><td></td><td></td>'
        f'<td class="num"><span class="down">−{yellow_total:.1f}</span></td></tr>')
    q_rows.append(
        f'<tr><td colspan="2"><strong>最终质量分</strong></td>'
        f'<td class="center score-cell"><span class="badge {badge_class(quality)} badge-lg">{quality:.2f}</span></td>'
        f'<td></td><td></td></tr>')
    return ('<span class="section-tag">质量分明细</span>'
            '<div class="table-scroll"><table><thead><tr><th>层</th><th>维度</th>'
            '<th class="center">得分</th><th class="num">权重</th><th class="num">加权</th></tr></thead>'
            '<tbody>' + "".join(q_rows) + '</tbody></table></div>')


def build_valuation_process_card(calc: dict, vc: dict, inputs: dict) -> str:
    """7 估值与安全边际章顶部过程卡（脚本生成）：四件套 输入值→映射得分→权重→加权，
    总分行并入表格末行（加权和明细 + 最终估值分徽章 + 判词），档位图例留在表下小字。"""
    four = _valuation_four_rows(calc, vc, inputs)
    rows = []
    for name, inp, s, w in four:
        rows.append(
            f'<tr><td>{name}</td><td>{_esc(inp)}</td>'
            f'<td class="center score-cell"><span class="badge {badge_class(s)}">{s:.1f}</span></td>'
            f'<td class="num">×{w}%</td><td class="num">{s * w / 100:.2f}</td></tr>')
    score = vc["score"]
    # 总分行：加权和明细 + 最终分徽章 + 判词（不再单列 decision-bar）
    wsum = " + ".join(f"{s * w / 100:.2f}" for _n, _i, s, w in four)
    rows.append(
        f'<tr><td colspan="2"><strong>估值分 = {wsum} = {score:.1f}</strong></td>'
        f'<td class="center score-cell"><span class="badge {valuation_badge_class(score)} badge-lg">'
        f'{score:.1f}</span></td>'
        f'<td colspan="2"><strong>{_valuation_verdict(score)}</strong></td></tr>')
    table = ('<div class="table-scroll"><table><thead><tr><th>套件</th><th>输入值</th>'
             '<th class="center">映射得分</th><th class="num">权重</th><th class="num">加权</th></tr></thead>'
             '<tbody>' + "".join(rows) + '</tbody></table></div>')
    legend = ('<span class="source">估值分档位：≥8 深度安全边际 / 6-7.9 合理偏便宜 / '
              '4-5.9 合理无安全边际 / &lt;4 贵</span>')
    return ('<span class="section-tag">估值分计算</span>' + table + legend)


# 仓位档位序列（上浮 20% 硬顶、下调 0 兜底）
_POS_LADDER = [0, 5, 10, 20]
_POS_LABEL = {0: "不建议参与", 5: "轻仓 ≤5%", 10: "标准仓 ≤10%", 20: "重仓 ≤20%"}


def _matrix_slot(q: float, v: float):
    """决策矩阵落位（唯一口径）：返回 (档位描述, 档位值或'观察池', 命中行号)。"""
    if q >= 7.0:
        if v >= 8.0:
            return ("好公司·好价格", 20, 0)
        if v >= 6.0:
            return ("好公司·合理偏便宜", 10, 1)
        if v >= 4.0:
            return ("好公司·合理无安全边际", 5, 2)
        return ("好公司·差价格", "观察池", 3)
    if q >= 5.5:
        if v >= 8.0:
            return ("中上·好价格", 10, 4)
        if v >= 6.0:
            return ("中上·合理偏便宜", 5, 5)
        return ("中上·差价格", "观察池", 6)
    if q >= 4.0:
        return ("质地一般", 5, 7)
    return ("质量<4", "不建议参与", 8)


def build_position_card(fill: dict, quality: float, valuation: float, timing,
                        calc: dict, red_flag: str) -> str:
    """11 仓位与时机决策章末尾三轨判定卡（脚本生成，置于 position_html 之后）：
    ① 三轨判定行（质量/估值/时机各带落档判词）→ ② 调节轨迹（只列实际触发条目）
    → ③ 最终仓位结论徽章行。完整决策矩阵规则见 references/scoring.md，报告不展开。"""
    parts = ['<span class="section-tag">三轨判定与仓位结论</span>']

    # ① 三轨判定行
    t_txt = f"{timing:.2f}" if timing is not None else "—"
    t_verdict = _timing_verdict(timing) if timing is not None else "—"
    parts.append(
        '<div class="metric-row">'
        f'<div class="metric-card"><div class="label">质量分</div>'
        f'<div class="value">{quality:.2f}</div><div class="sub">{_quality_verdict(quality)}'
        f'（≥7 好公司 / 5.5-6.9 中上 / 4-5.4 一般 / &lt;4 回避）</div></div>'
        f'<div class="metric-card"><div class="label">估值分</div>'
        f'<div class="value">{valuation:.1f}</div><div class="sub">{_valuation_verdict(valuation)}'
        f'（≥8 深度安全边际 / 6-7.9 合理偏便宜 / 4-5.9 合理 / &lt;4 贵）</div></div>'
        f'<div class="metric-card"><div class="label">时机分</div>'
        f'<div class="value">{t_txt}</div><div class="sub">{t_verdict}'
        f'（≥6 好时机 / 4-5.9 中性 / &lt;4 差时机）</div></div>'
        '</div>')

    # ② 调节轨迹（固定优先级：红灯熔断 > 中枢为负拦截器 > 矩阵落位
    #    > 时机分调节 > 离散度调节 > 赔率 ∞ 上浮；只列实际触发条目，未触发不列）
    steps = []
    slot_txt = None
    if red_flag:
        final_label = "不建议参与"
        steps.append(f"红灯熔断：命中「{_esc(red_flag)}」→ 不建议参与（后续调节不再适用）")
    elif calc and calc["central_raw"] < 0:
        final_label = "回避（中枢为负，等价格）"
        steps.append(f"中枢为负拦截器：年化中枢 {calc['central'] * 100:+.1f}% < 0 → 直接回避"
                     f"（后续调节不再适用）")
    else:
        slot_desc, pos, _hit = _matrix_slot(quality, valuation)
        pos_txt = _POS_LABEL.get(pos, pos) if isinstance(pos, int) else pos
        slot_txt = f"矩阵落位：质量 {quality:.2f} × 估值 {valuation:.1f} → {slot_desc} → {pos_txt}"
        if isinstance(pos, int) and pos > 0:
            idx = _POS_LADDER.index(pos)
            # 时机分调节（≥6 上浮一档 / <4 下调一档）
            if timing is not None and timing >= 6 and idx < len(_POS_LADDER) - 1:
                steps.append(f"时机分调节：时机分 {timing:.2f} ≥ 6 → 上浮一档"
                             f"（{_POS_LABEL[_POS_LADDER[idx]]}→{_POS_LABEL[_POS_LADDER[idx + 1]]}）")
                idx += 1
            elif timing is not None and timing < 4:
                steps.append(f"时机分调节：时机分 {timing:.2f} < 4 → 下调一档"
                             f"（{_POS_LABEL[_POS_LADDER[idx]]}→{_POS_LABEL[_POS_LADDER[idx - 1]]}）")
                idx -= 1
            # 离散度调节（>60% 下调一档 / <30% 上浮一档）
            if calc and calc["dispersion"] > 0.60:
                steps.append(f"离散度调节：离散度 {calc['dispersion'] * 100:.1f}% > 60% → 下调一档"
                             f"（{_POS_LABEL[_POS_LADDER[idx]]}→{_POS_LABEL[_POS_LADDER[idx - 1]]}）")
                idx -= 1
            elif calc and calc["dispersion"] < 0.30 and idx < len(_POS_LADDER) - 1:
                steps.append(f"离散度调节：离散度 {calc['dispersion'] * 100:.1f}% < 30% → 上浮一档"
                             f"（{_POS_LABEL[_POS_LADDER[idx]]}→{_POS_LABEL[_POS_LADDER[idx + 1]]}）")
                idx += 1
            # 赔率 ∞ 上浮一档（20% 硬顶）
            if calc and calc["odds"] is None and idx < len(_POS_LADDER) - 1:
                steps.append(f"赔率调节：赔率 ∞（悲观仍正收益）→ 上浮一档"
                             f"（{_POS_LABEL[_POS_LADDER[idx]]}→{_POS_LABEL[_POS_LADDER[idx + 1]]}）")
                idx += 1
            final_label = _POS_LABEL[_POS_LADDER[idx]]
        elif pos == 0:
            final_label = "不建议参与"
        else:
            # 观察池：不因时机/赔率上浮；时机 <4 或离散度 >60% 下调为不建议参与
            down = []
            if timing is not None and timing < 4:
                down.append(f"时机分 {timing:.2f} < 4")
            if calc and calc["dispersion"] > 0.60:
                down.append(f"离散度 {calc['dispersion'] * 100:.1f}% > 60%")
            if down:
                steps.append(f"{'；'.join(down)} → 观察池下调为不建议参与")
                final_label = "不建议参与"
            else:
                final_label = "观察池"
        if not steps:
            steps.append("矩阵落位直接生效，无调节项触发")

    parts.append('<div class="track-summary">' + "".join(
        f'<div class="ts-row"><span class="ts-formula">{s}</span></div>' for s in steps) + '</div>')

    # ③ 最终仓位结论徽章行（落位信息并入，报告只显示落位与结论）
    final_badge = ("badge-red" if final_label in ("不建议参与",) or final_label.startswith("回避")
                   else "badge-orange" if final_label in ("观察池", "轻仓 ≤5%")
                   else "badge-blue" if final_label.startswith("标准仓") else "badge-green")
    slot_html = f'<span class="muted">{slot_txt} ｜ </span>' if slot_txt else ""
    parts.append(f'<div class="decision-bar"><strong>最终仓位结论：</strong>{slot_html}'
                 f'<span class="badge {final_badge} badge-lg">{final_label}</span></div>')
    return "".join(parts)


def render(fill_path: str, out_path: str = None) -> str:
    fill = _load_fill(fill_path)
    for k in REQUIRED_SCALAR:
        if not fill.get(k):
            raise ValueError(f"缺必填字段: {k}")

    _check_l4_order(fill.get("l4_html", ""))

    # 估值计算（valuation 字段存在时，目标价/中枢/赔率/离散度全部脚本算）
    calc = compute_valuation(fill)
    validate_content(fill, calc)

    # 图形组件（脚本生成 SVG；数据缺省时为空串 → 模板条件块整块删除）
    spectrum_html = build_scenario_spectrum(fill, calc)
    scenario_block_html = build_scenario_block(calc)
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
    layer_share = sc["layer_share"]
    pre_risk = sc["pre_risk_quality"]
    yellow_total = sc["yellow_total"]
    quality = sc["quality"]
    valuation = sc["valuation"]
    timing = sc["timing"]
    red_flag = sc["red_flag"]

    # 估值分强制脚本化：四件套计算结果直接覆盖 fill 里的 valuation_score（填了也只作提示）
    valuation_calc = compute_valuation_score(calc, fill.get("valuation_inputs"))
    if valuation_calc is None:
        raise ValueError("估值分无法计算：valuation_inputs 四键或 valuation 三情景字段不完整"
                         "（pe_ttm/pe_band/div_yield/risk_free + 每情景 profit/pe/horizon）")
    if valuation is not None and abs(valuation_calc["score"] - valuation) > 0.11:
        print(f"⚠️ fill 手填估值分 {valuation:.1f} 与脚本四件套计算 {valuation_calc['score']:.1f} 不一致，"
              f"已按脚本计算值覆盖（valuation_score 字段已废弃，可删除）", file=sys.stderr)
    valuation = valuation_calc["score"]

    # 回测模式：fill 带 prev 字段（上版锚点）→ Hero 对比条 + R 复盘章节 + 文件名加"复盘"
    prev = fill.get("prev") or None
    review_html = fill.get("review_html", "")
    if prev and not review_html:
        print("⚠️ 回测模式（prev 已填）但 review_html 为空：R 回测复盘章节将缺失", file=sys.stderr)
    if review_html and not prev:
        print("⚠️ 有 review_html 但未填 prev：文件名与 Hero 不会标记「复盘」，请补 prev 字段", file=sys.stderr)

    date = fill["date"]
    # 防御性剥离：模型在 subtitle 误写的"报告日期：YYYY-MM-DD"片段（模板 Hero 自动追加日期，
    # 不剥会渲染出两次"报告日期"），连同悬空分隔符 ｜/| 一起去掉
    subtitle = re.sub(r"[｜|]?\s*报告日期[：:]\s*\d{4}[-/]\d{1,2}[-/]\d{1,2}", "",
                      fill.get("subtitle", "")).strip().strip("｜|").strip()
    target_range = fill.get("target_range", "—")
    if calc:
        # 目标价区间以脚本计算为准（消灭模型手写与 05 表不一致的可能）
        computed_tr = f"{calc['base_lo']:.0f}-{calc['base_hi']:.0f}"
        if target_range != "—":
            # 模型按精确值（如 25.2-27.5）填写时先取整再比较，避免对正确填法误告警
            _tr_nums = re.findall(r"\d+\.?\d*", target_range)
            _tr_same = (len(_tr_nums) >= 2
                        and f"{float(_tr_nums[0]):.0f}-{float(_tr_nums[1]):.0f}" == computed_tr)
            if not _tr_same and target_range != computed_tr:
                print(f"⚠️ target_range「{target_range}」与 valuation 计算区间「{computed_tr}」不一致，"
                      f"已按计算结果覆盖", file=sys.stderr)
        target_range = computed_tr
    repl = {
        "TOP_ICON": fill.get("top_icon") or fill["company"][0],
        "DATE": date,
        "COMPANY": fill["company"],
        "CODE": fill["code"],
        "SUBTITLE": subtitle,
        "THESIS_HTML": fill.get("thesis_html", ""),
        "PRICE": str(fill.get("price", "—")),
        "PRICE_SUB_HTML": fill.get("price_sub_html", ""),
        "MCAP": str(fill.get("mcap", "—")),
        "MCAP_SUB": fill.get("mcap_sub", ""),
        "PE_TTM": str(fill.get("pe_ttm", "—")),
        "PE_SUB": fill.get("pe_sub", ""),
        "HORIZON": fill.get("horizon", "12个月"),
        "TARGET_RANGE": str(target_range),
        "TARGET_SUB_HTML": fill.get("target_sub_html", ""),
        "CONCLUSION_HTML": fill.get("conclusion_html", ""),
        "P0_HTML": fill.get("p0_html", ""),
        "L1_HTML": fill.get("l1_html", ""),
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
        "SCENARIO_BLOCK_HTML": scenario_block_html,
        "PEERS_PLOT_HTML": peers_plot_html,
        "CYCLE_META": fill.get("cycle_meta", ""),
        "CYCLE_HTML": fill.get("cycle_html", ""),
        "NEXT_REVIEW": fill.get("next_review", "—"),
        "DASH_HTML": fill.get("dash_html", ""),
        "POSITION_HTML": _tag_timing_table(fill.get("position_html", "")),
        # 脚本生成区块：6 质量分汇总 / 7 估值过程卡 / 11 三轨判定与仓位结论卡
        "SCORE_SUMMARY_HTML": build_score_summary(sc),
        "VALUATION_PROCESS_HTML": build_valuation_process_card(calc, valuation_calc,
                                                               fill.get("valuation_inputs") or {}),
        "POSITION_CARD_HTML": build_position_card(fill, quality, valuation, timing, calc, red_flag),

        # 回测模式（prev 存在时生效，否则条件块自动删除）
        "PREV_HTML": build_prev_strip(prev, quality, valuation, timing, target_range),
        "PREV_DATE": str((prev or {}).get("date", "—")),
        "REVIEW_HTML": review_html,
        "GEN_TIME": fill.get("gen_time", date),
        "CALIB_NOTE": fill.get("calib_note", ""),
        # 质量分（扣黄灯 → 最终质量分）
        "YELLOW_TOTAL": f"{yellow_total:.1f}",
        "QUALITY_SCORE": f"{quality:.2f}",
        # 估值分（独立价格轨；徽章四档：≥8 绿 / 6-7.9 蓝 / 4-5.9 橙 / <4 红）
        "VALUATION_SCORE": f"{valuation:.1f}",
        "VALUATION_BADGE_CLASS": valuation_badge_class(valuation),
        "VALUATION_VALUE_CLASS": ("score-good" if valuation >= 7 else "score-mid" if valuation >= 4 else "score-bad"),

        # 时机分（微调）
        "TIMING_SCORE": (f"{timing:.2f}" if timing is not None else "—"),
        "RED_FLAG_HTML": (f'<div class="danger-card">🔴 <strong>红灯回避</strong>：{red_flag}</div>' if red_flag else ""),
        "L1_SCORE": f"{layer_scores['L1']:.2f}", "L1_W": f"{layer_share['L1']:.0f}",
        "L3_SCORE": f"{layer_scores['L3']:.2f}", "L3_W": f"{layer_share['L3']:.0f}",
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

    # 幻觉类名归一（metric-label/value/sub → label/value/sub），在表格对齐修正前执行
    html = _normalize_class_aliases(html)

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
        review_tag = "-复盘" if prev else ""
        company_s = _safe_filename(fill["company"])
        code_s = _safe_filename(fill["code"])
        date_s = _safe_filename(date)
        out_path = os.path.join(os.path.dirname(os.path.abspath(fill_path)),
                                f"{company_s}-{code_s}-{quality:.2f}-{valuation:.1f}{review_tag}-{date_s}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    empty = [k for k in ("CONCLUSION_HTML", "P0_HTML", "L1_HTML", "L3_HTML",
                         "L4_HTML", "VALUATION_HTML", "GAP_HTML", "PEERS_HTML",
                         "DASH_HTML", "POSITION_HTML") if not repl.get(k)]
    # 图形字段缺失要"响亮"：缺 valuation/scenarios/peers_plot 时条件块是静默删除的，必须显式提醒
    missing_plots = []
    if not repl["SCENARIO_SPECTRUM_HTML"]:
        if fill.get("valuation"):
            missing_plots.append("valuation 已填但情景数据不足（profit/pe/shares 缺失或非法），"
                                 "05 图未生成——请检查 valuation.scenarios 完整性")
        else:
            missing_plots.append("valuation（或手写 scenarios）（05 目标价走廊+情景表+三指标卡未生成）")
    if not repl["PEERS_PLOT_HTML"]:
        # 合规省略：peers_html 已手写 matrix-table 九宫格时不误报
        if "matrix-table" not in (fill.get("peers_html") or ""):
            missing_plots.append("peers_plot（07 散点图未生成，仅 peers_html 手写 matrix-table 兜底）")
    if missing_plots:
        print(f"⚠️ fill JSON 缺图形字段: {'；'.join(missing_plots)}。"
              f"请补充字段后重新渲染（格式见 fill-schema.md 顶层字段表）", file=sys.stderr)
    print(f"OK → {out_path}")
    timing_s = f"{timing:.2f}" if timing is not None else "—"
    print(f"质量分 {quality:.2f}（不考虑风险 {pre_risk:.2f} − 黄灯 {yellow_total:.1f}）| "
          f"估值分 {valuation:.1f} | 时机分 {timing_s} | " +
          " ".join(f"{l} {layer_scores[l]:.2f}" for l in ["L1", "L3"]) +
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
