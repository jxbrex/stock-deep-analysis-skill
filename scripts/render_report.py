#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_report.py — 用 fill-data JSON 渲染个股深度分析 HTML 报告（零模型拼装）

用法:
    python render_report.py fill_600989.json                 # 渲染并自动命名输出
    python render_report.py fill_600989.json --check         # 只预检不渲染（fill 落盘后自检的唯一合法方式）
    python render_report.py fill_600989.json --out=out.html  # 指定输出路径

fill JSON 契约见 references/fill-schema.md。
核心特性：
- 评分汇总表由脚本计算（9 质量维度 + 2 时机维度×权重→加权→质量分/估值分/时机分→自动徽章色），消除模型算术错误
- 文件名自动生成：{公司名}-{代码}-{质量分}-{估值分}-{日期}.html（分数是算出来的，不是模型填的）
- 条件章节：模板中 <!--IF:CYCLE_HTML--> 包裹的块在该键为空时整块删除
- 渲染后校验：残留 {{...}} 或 【...】 占位符即报错退出
"""
import json
import math
import os
import re
import sys

# Windows GBK 控制台打印 ⚠️/−/🔴 等字符会 UnicodeEncodeError，统一强制 UTF-8 + replace
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
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


def _dim_verdict(s: float) -> str:
    """单维得分判词（第 6 章汇总表用）：≥8 优秀 / ≥7 良好 / ≥6 中上 / ≥5 中等 / ≥4 偏弱 / <4 警示。"""
    if s >= 8.0:
        return "优秀"
    if s >= 7.0:
        return "良好"
    if s >= 6.0:
        return "中上"
    if s >= 5.0:
        return "中等"
    if s >= 4.0:
        return "偏弱"
    return "警示"


LAYER_NAMES = {"L1": "公司本质", "L3": "未来预期"}
REQUIRED_SCALAR = ["company", "code", "date"]
# 渲染器版本：嵌入输出 HTML 尾部注释，事后可 grep 验证报告确由本脚本渲染
# （防"render 报错后手写全文 HTML 绕行"，巨石 2026-08-23 实证）
RENDERER_VERSION = "v4.7"

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
    """num 列中应左对齐的文字格：剥括号注释后含句读的纯文字/长句，或超 2 字的纯文字。
    括号内句读不参与判定（"±60-90 亿（手机毛利率仅 8.5%，缓冲更薄）"是数值+注释，随列右对齐）；
    ≤2 字短标记（"基础""亏损""偏多"）随列右对齐，长数值串（"13,600-15,300亿"）因含数字天然右对齐。"""
    t = re.sub(r"<[^>]+>", "", s or "").strip()
    t2 = re.sub(r"[（(][^）)]*[）)]", "", t)  # 先剥括号注释：括号内句读不参与判定
    if re.search(r"[，。；、：]", t2) and (not re.search(r"\d", t2) or len(t2) > 20):
        return True   # 纯文字带句读→左对齐；带数字的长句（>20字）仍是说明文→左对齐
    return len(t) > 2 and _is_plain_text(s)


def _content_vote(inner: str):
    """裸 td（无对齐类）按内容投票：数值/短数值串 → 'num'，文字/长句 → 'left'。
    解决两类不一致：th 有 num 而 td 全裸（表头右、数据左）；文字格被误标 num（核心业务行）。
    判定：剥括号注释后，去掉数字与数值符号所剩字符为空或仅为单位 → num，否则 left
    （"3.1 赛道与宏观"含数字但是文字标签；"12个月"/"+70.1%"是数值）。"""
    t = re.sub(r"<[^>]+>", "", inner or "").strip()
    if not t:
        return None
    if re.search(r"[，。；、：]", t):
        return "left"
    t2 = re.sub(r"[（(][^）)]*[）)]", "", t)  # 剥括号注释后判断
    rest = re.sub(r"[\d.,%x×+\-~～/ ±≈]", "", t2)
    if not rest:
        return "num"
    if rest in {"亿", "万", "元", "倍", "个月", "月", "天", "年", "户", "手", "港元", "美元"}:
        return "num" if re.search(r"\d", t2) else "left"
    return "left"


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
        # 收集每列的对齐类（td 数据格：有类按类投票，裸格按内容投票；rowspan 合并格需补偿列位，
        # colspan 格不计票）
        col_votes = {}
        rowspans = []  # [(col, remaining_rows)]，行首 rem 即上方剩余占用
        for trm in _TR.finditer(tbl):
            col = 0
            row_cells = list(_CELL.finditer(trm.group(1)))
            for ci, cm in enumerate(row_cells):
                # 跳过被上方 rowspan 占用的列
                while any(c == col and rem > 0 for c, rem in rowspans):
                    col += 1
                tag, attrs = cm.group(1).lower(), cm.group(2)
                cs = re.search(r'colspan\s*=\s*"?(\d+)', attrs)
                colspan = int(cs.group(1)) if cs else 1
                if tag == "td" and colspan == 1:
                    a = _align_class(attrs)
                    inner_end = (row_cells[ci + 1].start() if ci + 1 < len(row_cells)
                                 else len(trm.group(1)))
                    inner = trm.group(1)[cm.end():inner_end]
                    if a == "num" and _is_plain_text(inner):
                        a = "left"  # 纯文字格误标 num（如"综合医药"）→ 按文字列投票
                    elif a is None:
                        a = _content_vote(inner)
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
                continue
            num_n, cen_n, left_n = votes.count("num"), votes.count("center"), votes.count("left")
            if left_n and left_n > num_n and left_n > cen_n:
                decided[i] = None  # 文字列（内容投票占多数）→ 左对齐
            else:
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
                    # td 对齐统一（num 列）：长文格（含句读 / 超 2 字纯文字）→ 去类左对齐；
                    # 数字、含数字短值、≤4 字短标记（"基础""12个月"）→ 统一 num 右对齐
                    if colspan == 1 and decided.get(col) == "num":
                        inner_end = cells[i + 1].start() if i + 1 < len(cells) else len(row)
                        inner = row[cm.end():inner_end]
                        if _is_prose_cell(inner):
                            attrs = _strip_th_align(attrs)  # 剔除 num/center → 左
                        else:
                            attrs = _set_th_align(attrs, "num")  # 随列右对齐
                    elif colspan == 1 and decided.get(col) is None:
                        attrs = _strip_th_align(attrs)  # 文字列/无投票列：剔除误标的 num/center → 左
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
        if rp < 0:
            raise ValueError(f"red_deductions 单项扣分 {rp} < 0（{r.get('item', '?')}）："
                             f"负扣分等于变相加分、绕过扣分上限，拒渲染")
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
            # 1D 红旗注解：红旗已先行扣入 1D 得分，单元格显示「原始分 − 红旗扣分 = 扣后分」
            # （footer 算式不再列红旗项，避免与已扣分的 layer_scores 重复计算）
            score_txt = (f"{s + red_total:.1f} − {red_total:.1f} 红旗 = {s:.1f}"
                         if key == "1D" and red_total else f"{s:.1f}")
            first = (f'<td rowspan="{len(dims)}"><strong>{LAYER_NAMES[layer]}</strong>'
                     f'（占质量分 {ls[layer]:.0f}%）</td>') if j == 0 else ""
            rows.append(
                f'<tr>{first}<td>{name}</td>'
                f'<td class="center score-cell"><span class="badge {badge}">{score_txt}</span></td>'
                f'<td class="center">{_dim_verdict(s)}</td>'
                f'<td class="num">{w:g}%</td><td class="num">{wtd:.2f}</td></tr>'
            )

    # 不考虑风险质量分 = L1 层分×L1占比 + L3 层分×L3占比
    pre_risk = sum(layer_scores[l] * ls[l] for l in ("L1", "L3")) / 100.0

    # 黄灯扣分（模型填 yellow_deductions 明细：[{label, points}]）
    # 硬校验：单项 >1 或累计 >2 → 拒渲染（按规则应升红灯）
    # 黄灯扣分明细为必填键（fill-schema 标 ✓）：缺失即拒渲染，无扣分必须显式填 []
    if "yellow_deductions" not in fill:
        raise ValueError("yellow_deductions 键缺失：黄灯扣分明细必须显式给出，无扣分请填 []")
    yellow = fill.get("yellow_deductions") or []
    for y in yellow:
        yp = float(y.get("points", 0))
        if yp < 0:
            raise ValueError(f"黄灯单项扣分 {yp} < 0（{y.get('label', '?')}）："
                             f"负扣分等于变相加分、绕过扣分上限，拒渲染")
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
    # timing_scores 为必填键：缺失或缺维度即拒渲染（不允许静默按 0 计入，消除 get(k,0) 兜底）
    t_scores = fill.get("timing_scores")
    if not isinstance(t_scores, dict) or not t_scores:
        raise ValueError("timing_scores 为必填字段：时机层得分对象（筹码面/技术面），缺失即拒渲染")
    miss_t = [k for k, _n, _w in TIMING_DIMS if k not in t_scores]
    if miss_t:
        raise ValueError(f"timing_scores 缺维度: {miss_t}（筹码面/技术面缺一不可，不接受缺维按 0 计）")
    bad_t = [k for k in t_scores if k not in {d[0] for d in TIMING_DIMS}]
    if bad_t:
        raise ValueError(f"timing_scores 含非法键名 {bad_t}：只接受 筹码面/技术面（2B/2C 旧键名兼容已移除）")
    t_weights = {k: float((fill.get("timing_weights") or {}).get(k, dw)) for k, _n, dw in TIMING_DIMS}
    tw_sum = sum(t_weights.values())
    if abs(tw_sum - 100.0) > 0.01:
        raise ValueError(f"时机层权重总和 = {tw_sum}，必须为 100")
    timing = sum(float(t_scores[k]) * t_weights[k] for k, _n, _w in TIMING_DIMS) / 100.0

    red_flag = (fill.get("red_flag") or "").strip()
    return {
        "rows_html": "\n".join(rows), "layer_scores": layer_scores,
        "layer_share": ls, "pre_risk_quality": pre_risk,
        "yellow_total": yellow_total, "quality": quality,
        "red_total": red_total, "red_deductions": red_deductions,
        "valuation": valuation, "timing": timing,
        "red_flag": red_flag,
        # 供评分横条图使用（与汇总表同一份口径：1D 已含红旗扣减，权重为实际生效值）
        "weights": weights,
        "adj_scores": {k: float(scores[k]) for k, _l, _n, _w in DIMS},
    }


def _norm_class_quote(v):
    """递归把 fill 里 HTML 片段的 class='x' 归一为 class="x"。模型在 JSON 内嵌 HTML 时
    常用单引号避转义（万华 2026-08-26 实证 258 处），而校验计数与模板只认双引号。"""
    if isinstance(v, str):
        return re.sub(r"class='([^'\"]*)'", r'class="\1"', v)
    if isinstance(v, dict):
        return {k: _norm_class_quote(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_norm_class_quote(x) for x in v]
    return v


def _load_fill(fill_path: str) -> dict:
    r"""读取 fill JSON。模型手写 JSON 常带非法转义（如表头 "ROE \ PE" 的裸反斜杠），
    先标准解析；失败则把不属于合法转义（\\ \" \/ \b \f \n \r \t \uXXXX）的反斜杠
    自动转义后重试并告警；仍失败则抛出带行号/列号/片段上下文的错误。
    解析成功后对 class 属性做引号归一（见 _norm_class_quote）。"""
    # utf-8-sig 兼容带 BOM 的文件；非 UTF-8 编码单独给出友好报错
    try:
        with open(fill_path, encoding="utf-8-sig") as f:
            text = f.read()
    except UnicodeDecodeError as e:
        raise ValueError(f"fill JSON 文件不是 UTF-8 编码（{e}）：请用 UTF-8（可含 BOM）重新保存后重试") from None
    try:
        return _norm_class_quote(json.loads(text))
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
        return _norm_class_quote(fill)


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


def _pad_domain(lo: float, hi: float, ratio: float, floor=None):
    """值域向两端各扩 ratio 比例（防贴边）；floor 给下限（如 ROE 不为负）。"""
    pad = (hi - lo) * ratio or 1
    lo -= pad
    hi += pad
    if floor is not None:
        lo = max(floor, lo)
    return lo, hi


def _lin_map(a: float, b: float, A: float, B: float):
    """线性映射：数值域 [a,b] → 像素域 [A,B]（a→A，b→B）。"""
    return lambda v: A + (v - a) / (b - a) * (B - A)


def _text_w(s: str, font_size: float) -> float:
    """粗估 SVG 文本像素宽（中文/全角≈1em、ASCII≈0.56em），用于标签避让与碰撞检测。"""
    return sum(1.0 if ord(ch) > 0x2E7F else 0.56 for ch in str(s)) * font_size


def _ticks(lo: float, hi: float, n: int = 5) -> list:
    """nice-number 刻度：步长取 1/2/2.5/5×10^k，返回落在 [lo,hi] 内的步长整数倍刻度。
    取代旧版「等距后取整」（会产出 19/32/44/57/69 这类间隔观感不齐的读数）。"""
    span = hi - lo
    if not span > 0:
        return [lo]
    raw = span / (n - 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = mag
    for m in (1, 2, 2.5, 5, 10):
        if m * mag >= raw:
            step = m * mag
            break
    t = math.ceil(lo / step - 1e-9) * step
    out = []
    while t <= hi + 1e-9:
        out.append(round(t, 9))
        t += step
    return out


def build_scenario_spectrum(fill: dict, calc: dict = None) -> str:
    """05 目标价走廊（横版区间条）：x 轴=价格（nice 刻度+单位），每情景一条横向实心区间条
    （悲观→乐观 从上到下，与三情景表列序一致），白条刻=区间中枢，条上方=中枢值与较现价
    涨跌幅，竖虚线=现价（全部脚本计算）。横版取代旧竖版：窄区间不再退化成幽灵胶囊。
    calc（compute_valuation 结果）存在时用其算出的目标价区间；
    否则回退到 fill["scenarios"] 手写区间。缺数据 → 返回空串（模板条件块整块删除）。"""
    price = _num(fill.get("price"))
    cur = str(fill.get("currency") or "元")
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
                         "color": _SCENARIO_COLORS.get(key, "#8a8375")})
    if not cols or not price:
        return ""
    if not calc:
        order = {"pess": 0, "base": 1, "opt": 2}
        cols.sort(key=lambda r: order.get(r.get("key", ""), 1))  # 悲观/基础/乐观 从上到下

    W = 1000
    L, R, T = 128, 24, 34           # 左列=情景名+区间；上=现价标签
    ROW_H, BAR_H = 52, 28
    AXIS_PAD = 46                   # 末行条到刻度标签的纵向空间
    H = T + len(cols) * ROW_H + AXIS_PAD
    lo_d, hi_d = _pad_domain(min([c["low"] for c in cols] + [price]),
                             max([c["high"] for c in cols] + [price]), 0.06)
    X = _lin_map(lo_d, hi_d, L, W - R)

    parts = [f'<div class="plot-wrap"><svg viewBox="0 0 {W} {H}" role="img" '
             f'aria-label="目标价走廊" style="width:100%;min-width:760px;height:auto;display:block;font-family:inherit;">']
    axis_y = T + len(cols) * ROW_H + 6
    # 价格轴：竖向浅网格线 + nice 刻度 + 单位注
    for v in _ticks(lo_d, hi_d):
        gx = X(v)
        parts.append(f'<line x1="{gx:.1f}" y1="{T - 10}" x2="{gx:.1f}" y2="{axis_y}" stroke="#ece7db" stroke-width="1"/>')
        parts.append(f'<text x="{gx:.1f}" y="{axis_y + 17}" text-anchor="middle" font-size="11" fill="#8a8375">{_fmt(v)}</text>')
    parts.append(f'<line x1="{L}" y1="{axis_y}" x2="{W - R}" y2="{axis_y}" stroke="#e0d7c3" stroke-width="1.2"/>')
    parts.append(f'<text x="4" y="{axis_y + 17}" font-size="11" fill="#8a8375">单位：{_esc(cur)}</text>')
    # 现价竖虚线 + 顶部标签（近边缘时改对齐防溢出）
    px = X(price)
    parts.append(f'<line x1="{px:.1f}" y1="{T - 12}" x2="{px:.1f}" y2="{axis_y}" '
                 f'stroke="#4a6fa5" stroke-width="1.5" stroke-dasharray="5 4"/>')
    price_label = f"现价 {_fmt(price)}"
    anchor, tx = "middle", px
    if px - _text_w(price_label, 12) / 2 < L:
        anchor, tx = "start", max(px - 2, L)
    elif px + _text_w(price_label, 12) / 2 > W - R:
        anchor, tx = "end", min(px + 2, W - R)
    parts.append(f'<text x="{tx:.1f}" y="{T - 18}" text-anchor="{anchor}" font-size="12" '
                 f'font-weight="700" fill="#4a6fa5">{price_label}</text>')
    # 情景区间条
    for i, c in enumerate(cols):
        cy = T + i * ROW_H + (ROW_H - BAR_H) / 2
        x_lo, x_hi, x_mid = X(c["low"]), X(c["high"]), X(c["mid"])
        parts.append(f'<text x="{L - 12}" y="{cy + 11}" text-anchor="end" font-size="13" '
                     f'font-weight="600" fill="#3a362e">{_esc(c["label"])}</text>')
        parts.append(f'<text x="{L - 12}" y="{cy + 25}" text-anchor="end" font-size="10.5" '
                     f'fill="#8a8375">{_fmt_price(c["low"])}–{_fmt_price(c["high"])}</text>')
        parts.append(f'<rect x="{x_lo:.1f}" y="{cy:.1f}" width="{max(x_hi - x_lo, 3):.1f}" '
                     f'height="{BAR_H}" rx="8" fill="{c["color"]}"/>')
        parts.append(f'<line x1="{x_mid:.1f}" y1="{cy + 5:.1f}" x2="{x_mid:.1f}" y2="{cy + BAR_H - 5:.1f}" '
                     f'stroke="#fffdf9" stroke-width="3"/>')
        pct = c["mid"] / price - 1
        vlabel = f'{_fmt_price(c["mid"])}（{pct * 100:+.1f}%）'
        # 中枢标签统一放条上方（v4.7.1：原"条外右侧放不下塞条内白字"与白刻交叠且手机上更挤）
        vw = _text_w(vlabel, 12.5)
        cx_mid = (x_lo + x_hi) / 2
        anchor, tx = "middle", cx_mid
        if cx_mid + vw / 2 > W - 4:
            anchor, tx = "end", W - 4
        elif cx_mid - vw / 2 < L:
            anchor, tx = "start", L
        parts.append(f'<text x="{tx:.1f}" y="{cy - 6:.1f}" text-anchor="{anchor}" font-size="12.5" '
                     f'font-weight="700" fill="{c["color"]}">{vlabel}</text>')
    parts.append('</svg></div>')
    parts.append('<span class="source">目标价走廊（脚本按 valuation/scenarios 字段生成）：横条=情景目标价区间，'
                 '白条刻=区间中枢，竖虚线=现价；条上方=中枢值与较现价涨跌幅</span>')
    return "".join(parts)


def compute_valuation(fill: dict):
    """valuation 字段（结构化三情景假设）→ 全部估值数字由脚本计算。
    输入：{"shares": 46.27（亿股）, "horizon": "12个月",
           "scenarios": [{"key":"pess","label":"悲观","trigger":"…","profit":850（归母净利,亿）,"pe":[16,18]}, …]}
    情景口径二选一：profit+pe（利润口径）或 "mcap":[低,高]（目标总市值亿元，
    NAV/rNPV/SOTP 行业附录用；目标价 = mcap ÷ shares，无利润/EPS/PE 口径）。
    返回 None（字段缺失/数据不足）或 dict：
    rows（含每情景 eps/price_lo/price_hi/mid/upside）、central（年化中枢）、
    odds（赔率）、dispersion（离散度）、base_lo/base_hi、horizon、mode（pe/mcap）。"""
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
        mc = s.get("mcap") or []
        mc_lo, mc_hi = (_num(mc[0]), _num(mc[1])) if len(mc) >= 2 else (None, None)
        key = str(s.get("key") or "").lower()
        if mc_lo is not None and mc_hi is not None:
            lo, hi = mc_lo / shares, mc_hi / shares
            profit = pe_lo = pe_hi = eps = None
        elif profit is not None and pe_lo is not None and pe_hi is not None:
            lo, hi = profit * pe_lo / shares, profit * pe_hi / shares
            eps = profit / shares
            mc_lo = mc_hi = None
        else:
            continue
        mid = (lo + hi) / 2
        rows.append({"key": key, "label": s.get("label") or _SCENARIO_NAMES.get(key, "情景"),
                     "color": _SCENARIO_COLORS.get(key, "#8a8375"),
                     "trigger": str(s.get("trigger") or ""), "horizon": str(s.get("horizon") or v.get("horizon") or "12个月"),
                     "profit": profit, "pe_lo": pe_lo, "pe_hi": pe_hi,
                     "mcap_lo": mc_lo, "mcap_hi": mc_hi,
                     "eps": eps, "low": lo, "high": hi, "mid": mid,
                     "upside": mid / price - 1})
    if not rows:
        return None
    rows.sort(key=lambda r: order.get(r["key"], 1))
    # 按 key 建字典取三情景：scenarios 含多余 key 或顺序混乱时，按排序位置取行会取错
    by_key = {r["key"]: r for r in rows}
    pess = by_key.get("pess", rows[0])
    base = by_key.get("base", rows[1] if len(rows) > 1 else rows[0])
    opt = by_key.get("opt", rows[-1])
    # 年化中枢的时间维度用 base 情景的 horizon（rows 里已按情景级优先、valuation 级兜底解析）
    horizon = base["horizon"]
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
            "horizon": horizon, "price": price,
            "mode": "mcap" if rows[0]["mcap_lo"] is not None else "pe"}


def _lookup(val, pairs, default):
    """阈值表查找：pairs 为 [(阈值, 分值)] 降序，返回首个 val >= 阈值 的分值。"""
    for t, s in pairs:
        if val >= t:
            return s
    return default


def _lookup_lt(val, pairs, default):
    """严格小于阈值表查找（合理倍数等「越低越好」口径用；pairs 升序）。"""
    for t, s in pairs:
        if val < t:
            return s
    return default


# 估值分四件套阈值表（规则正文唯一权威在 scoring.md，改动须同步）
_CENTRAL_TABLE = [(20, 9.0), (15, 8.0), (10, 7.0), (5, 6.0), (0, 5.0), (-5, 4.0), (-10, 3.0)]
_ODDS_TABLE = [(2, 8.5), (1.5, 7.5), (1.0, 6.0), (0.5, 5.0), (0, 3.5)]
_DIV_TABLE = [(3, 9.0), (2, 8.0), (1, 7.0), (0, 6.0), (-1, 5.0)]
# 合理倍数：ratio = 现价 PE ÷ 带中枢，越低越便宜；1e-9 偏移保留原 ≤ 边界语义（≤1.1→5.0 / ≤1.2→3.5）
_WARRANTED_TABLE = [(0.8, 9.0), (0.9, 8.0), (1.0, 7.0), (1.1 + 1e-9, 5.0), (1.2 + 1e-9, 3.5)]


def _map_central(central: float) -> float:
    return _lookup(central * 100, _CENTRAL_TABLE, 2.0)


def _map_odds(odds) -> float:
    if odds is None:
        return 10.0  # ∞（悲观仍正收益）
    return _lookup(odds, _ODDS_TABLE, 2.0)


def _map_warranted(pe_ttm: float, band: list) -> float:
    ratio = pe_ttm / ((band[0] + band[1]) / 2)
    return _lookup_lt(ratio, _WARRANTED_TABLE, 2.0)


def _map_div(div_yield: float, risk_free: float) -> float:
    return _lookup(div_yield - risk_free, _DIV_TABLE, 4.0)


def compute_valuation_score(calc: dict, inputs: dict):
    """估值分四件套量化 = 中枢×0.4 + 赔率×0.25 + 合理倍数×0.25 + 股息×0.1。
    inputs: {"pe_ttm": 13.5, "pe_band": [14.5, 15.5], "div_yield": 1.6, "risk_free": 1.7}
    可选 metric_label：行业口径（P/NAV、P/rNPV、P/EV、经调整PE 等）替换过程卡默认 PE(TTM) 标签。
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


def build_scenario_block(calc: dict, cur: str = "元") -> str:
    """由 compute_valuation 结果生成三情景对比表 + 三指标卡条（scenario-table/metric-card 骨架，
    类名全部脚本写死，杜绝幻觉类名与手算错误）。cur 为目标价币种单位（默认「元」，港股传「港元」）。"""
    if not calc:
        return ""
    rows = calc["rows"]
    head = ('<tr><th>指标</th>' + "".join(
        f'<th class="center">{_esc(r["label"])}情景</th>' for r in rows) + "</tr>")

    def row(name, fmt, cls="num"):
        cells = "".join(f'<td class="{cls}">{fmt(r)}</td>' if cls else f"<td>{fmt(r)}</td>" for r in rows)
        return f"<tr><td>{name}</td>{cells}</tr>"

    if calc.get("mode") == "mcap":
        # 市值口径（NAV/rNPV/SOTP 行业附录）：无净利/EPS/PE 行，改显示目标市值区间
        driver_rows = [row("目标市值", lambda r: f"{r['mcap_lo']:,.0f}-{r['mcap_hi']:,.0f} 亿")]
    else:
        driver_rows = [
            row("归母净利", lambda r: f"{r['profit']:,.0f} 亿"),
            row("EPS", lambda r: f"{r['eps']:.2f}"),
            row("PE", lambda r: f"{r['pe_lo']:g}-{r['pe_hi']:g}x"),
        ]
    body = "".join([
        row("时间维度", lambda r: _esc(r["horizon"]), "center"),
        row("触发条件", lambda r: _esc(r["trigger"]), ""),
        *driver_rows,
        row("目标价", lambda r: f"{r['low']:.0f}-{r['high']:.0f} {_esc(cur)}"),
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
    if disp < 0.40:
        d_cls, d_note = "up", "可预测"
    elif disp <= 0.90:
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
    pe_lo, pe_hi = _pad_domain(min([p["pe"] for p in pts] + pe_bands),
                               max([p["pe"] for p in pts] + pe_bands), 0.10)
    roe_lo, roe_hi = _pad_domain(min([p["roe"] for p in pts] + roe_bands),
                                 max([p["roe"] for p in pts] + roe_bands), 0.12, floor=0.0)
    X = _lin_map(pe_lo, pe_hi, L, W - R)
    Y = _lin_map(roe_lo, roe_hi, H - B, T)

    xb = [X(b) for b in pe_bands]
    yb = [Y(b) for b in roe_bands]  # roe_bands[0]=8 → 下方线 yb[0] 更大；[1]=15 → 上方线

    parts = [f'<div class="plot-wrap"><svg viewBox="0 0 {W} {H}" role="img" '
             f'aria-label="估值-质量散点图" style="width:100%;min-width:760px;height:auto;display:block;font-family:inherit;">']
    # 最优/最差象限底色（高ROE·低PE = 左上绿；低ROE·高PE = 右下红）
    parts.append(f'<rect x="{L}" y="{T}" width="{xb[0] - L:.1f}" height="{yb[1] - T:.1f}" fill="#6ba86b" fill-opacity="0.12"/>')
    parts.append(f'<rect x="{xb[1]:.1f}" y="{yb[0]:.1f}" width="{W - R - xb[1]:.1f}" height="{H - B - yb[0]:.1f}" fill="#c75b5b" fill-opacity="0.12"/>')
    # 象限角标签
    parts.append(f'<text x="{L + 8}" y="{T + 16}" font-size="11" fill="#8a8375">高质量 · 低估值</text>')
    parts.append(f'<text x="{W - R - 8}" y="{T + 16}" text-anchor="end" font-size="11" fill="#8a8375">高质量 · 高估值</text>')
    parts.append(f'<text x="{L + 8}" y="{H - B - 8}" font-size="11" fill="#8a8375">低质量 · 低估值</text>')
    parts.append(f'<text x="{W - R - 8}" y="{H - B - 8}" text-anchor="end" font-size="11" fill="#8a8375">低质量 · 高估值</text>')
    # 分带虚线
    for bx in xb:
        parts.append(f'<line x1="{bx:.1f}" y1="{T}" x2="{bx:.1f}" y2="{H - B}" stroke="#ddd3bd" stroke-width="1" stroke-dasharray="4 4"/>')
    for by in yb:
        parts.append(f'<line x1="{L}" y1="{by:.1f}" x2="{W - R}" y2="{by:.1f}" stroke="#ddd3bd" stroke-width="1" stroke-dasharray="4 4"/>')
    # 坐标轴 + 刻度
    parts.append(f'<line x1="{L}" y1="{H - B}" x2="{W - R}" y2="{H - B}" stroke="#e0d7c3" stroke-width="1.2"/>')
    parts.append(f'<line x1="{L}" y1="{T}" x2="{L}" y2="{H - B}" stroke="#e0d7c3" stroke-width="1.2"/>')
    for v in _ticks(pe_lo, pe_hi):
        parts.append(f'<text x="{X(v):.1f}" y="{H - B + 18}" text-anchor="middle" font-size="11" fill="#8a8375">{_fmt(v)}x</text>')
    for v2 in _ticks(roe_lo, roe_hi):
        parts.append(f'<text x="{L - 8}" y="{Y(v2) + 4:.1f}" text-anchor="end" font-size="11" fill="#8a8375">{_fmt(v2)}%</text>')
    parts.append(f'<text x="{W - R}" y="{H - 8}" text-anchor="end" font-size="11" fill="#8a8375">PE(TTM)</text>')
    parts.append(f'<text x="{L}" y="{T - 12}" font-size="11" fill="#8a8375">ROE</text>')
    # 数据点（直接标注，免图例；可选 size 字段编码市值——面积 ∝ 市值，sqrt 换算半径；
    # 标签按候选位做简单碰撞避让，目标公司 上/右/下/左，同业 右/左/上/下）
    def _box(lx, ly, anchor, w, fs):
        x0 = lx - w / 2 if anchor == "middle" else (lx - w if anchor == "end" else lx)
        return (x0, ly - fs, x0 + w, ly + 4)

    def _overlap(b, boxes):
        return any(not (b[2] < p[0] or b[0] > p[2] or b[3] < p[1] or b[1] > p[3]) for p in boxes)

    def _pick_label(cands, fw, fs, boxes):
        """按偏好顺序取第一个「不越出 SVG 边界且不压已有标签」的位置；
        全都压标签时退回首个不越界位（v4.8 修复：右缘公司标签曾越界被裁）。"""
        in_bounds = [c for c in cands
                     if 8 <= _box(c[0], c[1], c[2], fw, fs)[0]
                     and _box(c[0], c[1], c[2], fw, fs)[2] <= W - 8]
        pool = in_bounds or cands
        for c in pool:
            if not _overlap(_box(c[0], c[1], c[2], fw, fs), boxes):
                return c
        return pool[0]

    placed = [  # 四个象限角标的近似盒，数据标签先让它们
        (L + 6, T + 4, L + 150, T + 20), (W - R - 156, T + 4, W - R - 6, T + 20),
        (L + 6, H - B - 20, L + 150, H - B - 4), (W - R - 156, H - B - 20, W - R - 6, H - B - 4),
    ]
    sizes = [sv for sv in (_num(p.get("size")) for p in pts) if sv]
    max_size = max(sizes) if sizes else None
    for p in pts:
        cx, cy = X(p["pe"]), Y(p["roe"])
        r = 6.0
        if max_size:
            sv = _num(p.get("size")) or 0.0
            r = max(5.0, min(12.0, 4 + 8 * math.sqrt(max(sv, 0.0) / max_size)))
        label = f'{p["name"]} {_fmt(p["roe"])}%/{_fmt(p["pe"])}x'
        if p["target"]:
            rr = r + 2
            parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{rr:.1f}" fill="#4a6fa5" stroke="#fffdf9" stroke-width="2">'
                         f'<title>{_esc(label)}</title></circle>')
            # 近顶优先放下方，近右优先放左侧；其余放上方；再与已放置标签做碰撞避让
            cands = []
            if cy < T + 50:
                cands.append((cx, cy + rr + 16, "middle"))
            if cx > L + (W - L - R) * 0.75:
                cands.append((cx - rr - 10, cy + 4, "end"))
            cands += [(cx, cy - rr - 8, "middle"), (cx + rr + 10, cy + 4, "start"),
                      (cx - rr - 10, cy + 4, "end"), (cx, cy + rr + 16, "middle")]
            fs, fw = 12, _text_w(label, 12)
            lx, ly, anchor = _pick_label(cands, fw, fs, placed)
            placed.append(_box(lx, ly, anchor, fw, fs))
            parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" font-size="12" '
                         f'font-weight="700" fill="#4a6fa5">{_esc(label)}</text>')
        else:
            parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="#66604f">'
                         f'<title>{_esc(label)}</title></circle>')
            cands = [(cx + r + 10, cy + 4, "start"), (cx - r - 10, cy + 4, "end"),
                     (cx, cy - r - 8, "middle"), (cx, cy + r + 16, "middle")]
            fs, fw = 12, _text_w(label, 12)
            lx, ly, anchor = _pick_label(cands, fw, fs, placed)
            placed.append(_box(lx, ly, anchor, fw, fs))
            parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" font-size="12" '
                         f'fill="#57524a">{_esc(label)}</text>')
    parts.append('</svg></div>')
    size_note = '；点大小 ∝ 总市值（sqrt 缩放）' if max_size else ''
    parts.append('<span class="source">估值-质量散点图（脚本按 peers_plot 字段生成）：横轴 PE(TTM)、纵轴 ROE，'
                 '虚线为低/中/高分带；左上绿底=优质低估区，右下红底=低质高估区' + size_note + '；'
                 '目标公司与同业须同口径（A/H 股、IFRS/经调整），混排须在 peers_meta 注明</span>')
    return "".join(parts)


def build_score_bars(sc: dict) -> str:
    """06 质量分汇总·九维评分横条图：条长=维度得分（0-10 定域，跨报告可比），条色=徽章档，
    条端=得分，最右列=层内权重；按层分组（公司本质/未来预期），虚线=7.0 良好线。
    数据全部来自 compute_scores（adj_scores/weights，与汇总表同一份口径）。"""
    adj, weights, ls = sc.get("adj_scores") or {}, sc.get("weights") or {}, sc["layer_share"]
    if not adj:
        return ""
    W = 1000
    NL, BAR_A, BAR_B = 200, 210, 820  # 名称列右缘 / 条形起点（0 分） / 条形终点（10 分）
    WT_X = 965                        # 权重·加权列右缘
    T, ROW_H, BAR_H, GROUP_GAP = 34, 32, 18, 26
    H = T + 9 * ROW_H + GROUP_GAP + 36
    X = _lin_map(0, 10, BAR_A, BAR_B)
    badge_color = {"badge-green": "#6ba86b", "badge-orange": "#c08a2e", "badge-red": "#c75b5b"}

    parts = ['<span class="section-tag">评分分布</span>',
             f'<div class="plot-wrap"><svg viewBox="0 0 {W} {H}" role="img" '
             f'aria-label="九维评分分布" style="width:100%;min-width:760px;height:auto;display:block;font-family:inherit;">']
    for v in _ticks(0, 10, 6):
        gx = X(v)
        parts.append(f'<line x1="{gx:.1f}" y1="{T - 8}" x2="{gx:.1f}" y2="{H - 30}" stroke="#ece7db" stroke-width="1"/>')
        parts.append(f'<text x="{gx:.1f}" y="{H - 14}" text-anchor="middle" font-size="11" fill="#8a8375">{_fmt(v)}</text>')
    gx7 = X(7.0)
    parts.append(f'<line x1="{gx7:.1f}" y1="{T - 8}" x2="{gx7:.1f}" y2="{H - 30}" stroke="#c9bfa8" stroke-width="1.2" stroke-dasharray="5 4"/>')
    parts.append(f'<text x="{gx7:.1f}" y="{T - 14}" text-anchor="middle" font-size="10.5" fill="#8a8375">良好线 7.0</text>')
    y = T
    for layer in ("L1", "L3"):
        dims = [d for d in DIMS if d[1] == layer]
        parts.append(f'<text x="0" y="{y - 8}" font-size="11" font-weight="600" fill="#8a8375">'
                     f'{LAYER_NAMES[layer]} · 占质量分 {ls[layer]:.0f}%</text>')
        for key, _l, name, _dw in dims:
            s = float(adj.get(key, 0))
            w = float(weights.get(key, 0))
            cy = y + 2
            color = badge_color[badge_class(s)]
            parts.append(f'<rect x="{BAR_A}" y="{cy}" width="{BAR_B - BAR_A}" height="{BAR_H}" rx="5" fill="#efe9db"/>')
            parts.append(f'<rect x="{BAR_A}" y="{cy}" width="{max((BAR_B - BAR_A) * s / 10.0, 3):.1f}" '
                         f'height="{BAR_H}" rx="5" fill="{color}"/>')
            parts.append(f'<text x="{NL - 10}" y="{cy + BAR_H / 2 + 4.5:.1f}" text-anchor="end" font-size="12" '
                         f'fill="#3a362e">{_esc(name)}</text>')
            parts.append(f'<text x="{BAR_A + max((BAR_B - BAR_A) * s / 10.0, 3) + 8:.1f}" y="{cy + BAR_H / 2 + 4.5:.1f}" '
                         f'font-size="12" font-weight="700" fill="{color}">{s:.1f} {_dim_verdict(s)}</text>')
            parts.append(f'<text x="{WT_X}" y="{cy + BAR_H / 2 + 4.5:.1f}" text-anchor="end" font-size="11" '
                         f'fill="#8a8375">{w:g}% · {s * w / 100:.2f}</text>')
            y += ROW_H
        y += GROUP_GAP
    parts.append('</svg></div>')
    parts.append('<span class="source">评分分布（脚本按 scores/weights 生成）：条长=维度得分（0-10 定域），'
                 '条色=徽章档（≥7 绿 / 4-6.9 橙 / &lt;4 红），条端=得分与判词，右列=层内权重 · 加权得分，'
                 '虚线=7.0 良好线</span>')
    return "".join(parts)


def build_sensitivity_tornado(fill: dict) -> str:
    """02 关键利润驱动·敏感性龙卷风（fill["sensitivity"] 可选字段）：变量 ±10% 变动对归母净利
    影响幅度（%）的双向条，红=不利方向、绿=有利方向，排序=弹性大小（首行=第一变量）。
    sensitivity: [{"name":"矿产金售价（金价）","impact":20,"delta":"±10%","amount":"约±9-10亿元"}, ...]
    （impact 取绝对值；delta/amount 可选——填了即在变量名下展示「变动幅度 → 金额影响」，
    信息覆盖旧敏感性表，填了本字段 P0 就不必再手写敏感性表）。字段缺失 → 返回空串。"""
    items = []
    for s in fill.get("sensitivity") or []:
        imp = _num(s.get("impact"))
        name = str(s.get("name") or "").strip()
        if imp is None or not name:
            continue
        items.append({"name": name, "impact": abs(imp),
                      "delta": str(s.get("delta") or "").strip(),
                      "amount": str(s.get("amount") or "").strip()})
    if not items:
        return ""
    items.sort(key=lambda r: -r["impact"])
    has_detail = any(it["delta"] or it["amount"] for it in items)
    W = 860
    NL, X0, HALF = 200, 520, 260    # 变量名列右缘 / 中轴 / 中轴到满幅端（v4.7.1 收窄：手机缩放比例提高）
    T, ROW_H, BAR_H = 30, 56 if has_detail else 46, 22
    H = T + len(items) * ROW_H + 44
    imax = items[0]["impact"]
    k = HALF / imax if imax else 1.0
    parts = ['<span class="section-tag">敏感性排序</span>',
             f'<div class="plot-wrap"><svg viewBox="0 0 {W} {H}" role="img" '
             f'aria-label="敏感性龙卷风" style="width:100%;min-width:760px;height:auto;display:block;font-family:inherit;">']
    axis_y = T + len(items) * ROW_H + 4
    for v in _ticks(0, imax, 4):
        for sign in (-1, 1):
            gx = X0 + sign * v * k
            parts.append(f'<line x1="{gx:.1f}" y1="{T - 6}" x2="{gx:.1f}" y2="{axis_y}" stroke="#ece7db" stroke-width="1"/>')
            lbl = f'{"+" if sign > 0 else "−"}{_fmt(v)}%' if v > 0 else "0"
            if v > 0 or sign > 0:
                parts.append(f'<text x="{gx:.1f}" y="{axis_y + 16}" text-anchor="middle" font-size="11" fill="#8a8375">{lbl}</text>')
    parts.append(f'<line x1="{X0}" y1="{T - 6}" x2="{X0}" y2="{axis_y}" stroke="#b3ab93" stroke-width="1.2"/>')
    for i, it in enumerate(items):
        cy = T + i * ROW_H + (ROW_H - BAR_H) / 2
        w = it["impact"] * k
        first = (i == 0)
        if has_detail:
            # 双行：变量名 + 「变动幅度 → 金额影响」（替代旧敏感性表的信息）
            detail = " → ".join(x for x in (it["delta"], it["amount"]) if x)
            parts.append(f'<text x="{NL}" y="{cy + 3:.1f}" text-anchor="end" font-size="13" '
                         f'font-weight="{700 if first else 400}" fill="{"#2b2620" if first else "#3a362e"}">'
                         f'{_esc(it["name"])}{"（第一变量）" if first else ""}</text>')
            if detail:
                parts.append(f'<text x="{NL}" y="{cy + 19:.1f}" text-anchor="end" font-size="11" '
                             f'fill="#8a8375">{_esc(detail)}</text>')
        else:
            parts.append(f'<text x="{NL}" y="{cy + BAR_H / 2 + 4.5:.1f}" text-anchor="end" font-size="13" '
                         f'font-weight="{700 if first else 400}" fill="{"#2b2620" if first else "#3a362e"}">'
                         f'{_esc(it["name"])}{"（第一变量）" if first else ""}</text>')
        parts.append(f'<rect x="{X0 - w:.1f}" y="{cy:.1f}" width="{w:.1f}" height="{BAR_H}" fill="#c75b5b"/>')
        parts.append(f'<rect x="{X0:.1f}" y="{cy:.1f}" width="{w:.1f}" height="{BAR_H}" fill="#6ba86b"/>')
        parts.append(f'<text x="{X0 - w - 8:.1f}" y="{cy + BAR_H / 2 + 4.5:.1f}" text-anchor="end" font-size="12" '
                     f'font-weight="700" fill="#c75b5b">−{_fmt(it["impact"])}%</text>')
        parts.append(f'<text x="{X0 + w + 8:.1f}" y="{cy + BAR_H / 2 + 4.5:.1f}" font-size="12" '
                     f'font-weight="700" fill="#6ba86b">+{_fmt(it["impact"])}%</text>')
    parts.append('</svg></div>')
    parts.append('<span class="source">敏感性龙卷风（脚本按 sensitivity 字段生成）：条长=变量变动对归母净利的'
                 '影响幅度（估算绝对值），红=不利方向、绿=有利方向，左列=变动幅度与金额影响，'
                 '排序=弹性大小（首行=第一变量）；填了本字段，P0 不必再写敏感性表</span>')
    return "".join(parts)


def build_pe_band(fill: dict) -> str:
    """07→10 估值·PE 历史带（fill["pe_history"] 可选字段 + valuation_inputs 的 pe_band/pe_ttm）：
    横向子弹图——浅带=历史 PE 区间，钢蓝段=合理带，黑刻=当前值，灰虚刻=关键时点。
    v4.7.1 起图挪至 10 周期规律章（手写时段拆解前，概览→明细）。
    pe_history: {"hist_lo":13.7, "hist_hi":83.2, "label":"近5年",
                 "milestones":[{"label":"2021H1","pe":46.9}, …]}（label 可选；milestones 可选，
                 建议 3-6 个关键时点：峰值/谷值/典型时段，与时段拆解表同源取数）；
    字段缺失或与 valuation_inputs 不齐 → 返回空串（可选增强，静默跳过）。"""
    ph = fill.get("pe_history") or {}
    vi = fill.get("valuation_inputs") or {}
    hist_lo, hist_hi = _num(ph.get("hist_lo")), _num(ph.get("hist_hi"))
    cur = _num(vi.get("pe_ttm"))
    band = vi.get("pe_band") or []
    band_lo = _num(band[0]) if len(band) >= 1 else None
    band_hi = _num(band[1]) if len(band) >= 2 else None
    if None in (hist_lo, hist_hi, cur, band_lo, band_hi) or hist_hi <= hist_lo or band_hi < band_lo:
        return ""
    lo_d, hi_d = _pad_domain(min(hist_lo, band_lo, cur), max(hist_hi, band_hi, cur), 0.04, floor=0.0)
    W, H, L, R = 1000, 196, 64, 64
    X = _lin_map(lo_d, hi_d, L, W - R)
    cy, BH = 100, 30
    mlabel = str(vi.get("metric_label") or "PE(TTM)")
    plabel = str(ph.get("label") or "历史")
    parts = [f'<span class="section-tag">{_esc(mlabel)} 历史带</span>',
             f'<div class="plot-wrap"><svg viewBox="0 0 {W} {H}" role="img" '
             f'aria-label="{_esc(mlabel)}历史带" style="width:100%;min-width:760px;height:auto;display:block;font-family:inherit;">']
    for v in _ticks(lo_d, hi_d, 6):
        gx = X(v)
        parts.append(f'<line x1="{gx:.1f}" y1="38" x2="{gx:.1f}" y2="{cy + BH + 10}" stroke="#ece7db" stroke-width="1"/>')
        parts.append(f'<text x="{gx:.1f}" y="{cy + BH + 26}" text-anchor="middle" font-size="11" fill="#8a8375">{_fmt(v)}x</text>')
    parts.append(f'<line x1="{L}" y1="{cy + BH + 10}" x2="{W - R}" y2="{cy + BH + 10}" stroke="#e0d7c3" stroke-width="1.2"/>')
    # 历史区间浅带 + 带标签
    xh_lo, xh_hi = X(hist_lo), X(hist_hi)
    parts.append(f'<rect x="{xh_lo:.1f}" y="{cy}" width="{xh_hi - xh_lo:.1f}" height="{BH}" rx="8" '
                 f'fill="#efe9db" stroke="#e0d7c3"/>')
    parts.append(f'<text x="{xh_lo:.1f}" y="{cy - 40}" font-size="11" fill="#8a8375">'
                 f'{_esc(plabel)} {_esc(mlabel)} 区间 {_fmt(hist_lo)}–{_fmt(hist_hi)}x</text>')
    # 合理带（钢蓝实心段；标签放得下就带内白字，否则带下灰字）
    xb_lo, xb_hi = X(band_lo), X(band_hi)
    band_label = f'合理带 {_fmt(band_lo)}–{_fmt(band_hi)}x'
    parts.append(f'<rect x="{xb_lo:.1f}" y="{cy}" width="{max(xb_hi - xb_lo, 2):.1f}" height="{BH}" rx="8" fill="#4a6fa5"/>')
    if _text_w(band_label, 11) + 14 <= xb_hi - xb_lo:
        parts.append(f'<text x="{(xb_lo + xb_hi) / 2:.1f}" y="{cy + BH / 2 + 4:.1f}" text-anchor="middle" '
                     f'font-size="11" font-weight="700" fill="#fffdf9">{band_label}</text>')
    else:
        parts.append(f'<text x="{(xb_lo + xb_hi) / 2:.1f}" y="{cy + BH + 40}" text-anchor="middle" '
                     f'font-size="11" fill="#4a6fa5">{band_label}</text>')
    # 当前值黑刻 + 标签（近边缘改对齐）
    cxp = X(cur)
    parts.append(f'<line x1="{cxp:.1f}" y1="{cy - 12}" x2="{cxp:.1f}" y2="{cy + BH + 12}" stroke="#2b2620" stroke-width="3"/>')
    parts.append(f'<circle cx="{cxp:.1f}" cy="{cy + BH / 2}" r="5" fill="#2b2620"/>')
    cur_label = f'当前 {_fmt(cur)}x'
    anchor, tx = "middle", cxp
    if cxp - _text_w(cur_label, 12) / 2 < L:
        anchor, tx = "start", max(cxp - 4, L)
    elif cxp + _text_w(cur_label, 12) / 2 > W - R:
        anchor, tx = "end", min(cxp + 4, W - R)
    parts.append(f'<text x="{tx:.1f}" y="{cy - 20}" text-anchor="{anchor}" font-size="12" '
                 f'font-weight="700" fill="#2b2620">{cur_label}</text>')
    # 关键时点标注（v4.7.1 milestones 可选）：灰虚刻 + 带上方单层标签
    # debt: 标签单层排布，pe 过近会叠——现网 3-6 个时点足够分散，真叠时升级为上下双层交错
    ms_items = []
    for ms in ph.get("milestones") or []:
        mv = _num(ms.get("pe"))
        mlbl = str(ms.get("label") or "").strip()
        if mv is None or not mlbl or not (lo_d <= mv <= hi_d):
            continue
        ms_items.append((mv, mlbl))
    for mv, mlbl in sorted(ms_items):  # 按 pe 升序 = 画布从左到右
        mx = X(mv)
        parts.append(f'<line x1="{mx:.1f}" y1="{cy - 6:.1f}" x2="{mx:.1f}" y2="{cy + BH + 6:.1f}" '
                     f'stroke="#8a8375" stroke-width="1.2" stroke-dasharray="3 3"/>')
        mtext = f'{mlbl} {_fmt(mv)}x'
        mw = _text_w(mtext, 10.5)
        ma, mtx = "middle", mx
        if mx + mw / 2 > W - 4:
            ma, mtx = "end", W - 4
        elif mx - mw / 2 < 4:
            ma, mtx = "start", 4
        parts.append(f'<text x="{mtx:.1f}" y="{cy - 58}" text-anchor="{ma}" font-size="10.5" '
                     f'fill="#57524a">{_esc(mtext)}</text>')
    parts.append('</svg></div>')
    parts.append(f'<span class="source">{_esc(mlabel)} 历史带（脚本按 pe_history + valuation_inputs 生成）：'
                 f'浅带={_esc(plabel)}区间，钢蓝段=合理带，黑刻=当前值，灰虚刻=关键时点 PE；三者同一口径</span>')
    return "".join(parts)


def build_review_dumbbell(prev: dict, quality: float, valuation: float, timing) -> str:
    """13 回测复盘·三轨分新旧对比哑铃图（0-10 定域）：灰点=上版、蓝点=本版，
    连线绿=上调、红=下调，右列=分差。prev 为空 → 返回空串。"""
    if not prev:
        return ""
    rows = []
    for label, old, new in (("质量分", _num(prev.get("quality", prev.get("research"))), quality),
                            ("估值分", _num(prev.get("valuation")), valuation),
                            ("时机分", _num(prev.get("timing")), timing)):
        if old is None or new is None:
            continue
        rows.append({"label": label, "old": old, "new": float(new)})
    if not rows:
        return ""
    W, NL, BAR_A, BAR_B = 1000, 110, 140, 890
    T, ROW_H = 30, 50
    H = T + len(rows) * ROW_H + 36
    X = _lin_map(0, 10, BAR_A, BAR_B)
    parts = ['<span class="section-tag">三轨分新旧对比</span>',
             f'<div class="plot-wrap"><svg viewBox="0 0 {W} {H}" role="img" '
             f'aria-label="三轨分新旧对比" style="width:100%;min-width:760px;height:auto;display:block;font-family:inherit;">']
    for v in _ticks(0, 10, 6):
        gx = X(v)
        parts.append(f'<line x1="{gx:.1f}" y1="{T - 6}" x2="{gx:.1f}" y2="{H - 30}" stroke="#ece7db" stroke-width="1"/>')
        parts.append(f'<text x="{gx:.1f}" y="{H - 14}" text-anchor="middle" font-size="11" fill="#8a8375">{_fmt(v)}</text>')
    for i, r in enumerate(rows):
        cy = T + i * ROW_H + ROW_H / 2 - 6
        xo, xn = X(r["old"]), X(r["new"])
        d = r["new"] - r["old"]
        dcolor = "#6ba86b" if d >= 0 else "#c75b5b"
        parts.append(f'<line x1="{xo:.1f}" y1="{cy:.1f}" x2="{xn:.1f}" y2="{cy:.1f}" stroke="{dcolor}" stroke-width="3"/>')
        parts.append(f'<circle cx="{xo:.1f}" cy="{cy:.1f}" r="6" fill="#b3ab93"/>')
        parts.append(f'<circle cx="{xn:.1f}" cy="{cy:.1f}" r="7.5" fill="#4a6fa5" stroke="#fffdf9" stroke-width="2"/>')
        parts.append(f'<text x="{NL}" y="{cy + 4.5:.1f}" text-anchor="end" font-size="12.5" fill="#3a362e">{r["label"]}</text>')
        # 新旧点过近时旧值改放下方，避免两个数值标签重叠
        old_y = cy + 24 if abs(xn - xo) < 70 else cy - 14
        parts.append(f'<text x="{xo:.1f}" y="{old_y:.1f}" text-anchor="middle" font-size="11" fill="#8a8375">{_fmt(r["old"])}</text>')
        parts.append(f'<text x="{xn:.1f}" y="{cy - 14:.1f}" text-anchor="middle" font-size="12" '
                     f'font-weight="700" fill="#4a6fa5">{_fmt(r["new"])}</text>')
        parts.append(f'<text x="{BAR_B + 10}" y="{cy + 4.5:.1f}" font-size="12" font-weight="700" '
                     f'fill="{dcolor}">{d:+.2f}</text>')
    parts.append('</svg></div>')
    parts.append(f'<span class="source">三轨分新旧对比（脚本按 prev 字段生成）：灰点={_esc(str(prev.get("date", "上版")))} 上版，'
                 f'蓝点=本版；连线绿=上调、红=下调；右列=分差；0-10 定域</span>')
    return "".join(parts)


# 侧栏目录条目：(锚点 id, 完整章节名[title 悬停提示], 侧栏简称)
_TOC_MAIN = [("s1", "1 核心结论", "结论"), ("s2", "2 关键利润驱动", "驱动"),
             ("s3", "3 公司本质", "本质"), ("s4", "4 未来预期", "预期"),
             ("s5", "5 风险评估", "风险"), ("s6", "6 质量分汇总", "评分"),
             ("s7", "7 估值与安全边际", "估值"), ("s8", "8 市场预期差", "分歧"),
             ("s9", "9 同业对比", "同业")]
_TOC_TAIL = [("s11", "11 仓位与时机决策", "仓位"), ("s12", "12 跟踪仪表盘", "跟踪")]


def build_toc(has_cycle: bool, has_review: bool) -> str:
    """右缘固定侧栏目录（纯 CSS 零 JS；宽屏显示，窄屏与打印隐藏）：章节用两字简称，
    悬停可见全名（title）；条件章节（10 周期 / 13 回测）按存在性生成，
    编号与模板固定章节号一致。"""
    secs = list(_TOC_MAIN)
    if has_cycle:
        secs.append(("s10", "10 周期规律", "周期"))
    secs += _TOC_TAIL
    if has_review:
        secs.append(("s13", "13 回测复盘", "复盘"))
    links = "".join(f'<a href="#{i}" title="{_esc(full)}">{_esc(short)}</a>' for i, full, short in secs)
    return f'<nav class="toc-side">{links}</nav>'


def _plain_text(frag: str) -> str:
    """剥掉 HTML 标签后的纯文本（用于内容地板字数校验）。"""
    return re.sub(r"<[^>]+>", "", frag or "").strip()


def _check_price_date(fill: dict) -> None:
    """price/date 校验：缺失/非法即拒渲染。"""
    # price 缺失/非数字、date 格式非法在此拦截（友好报错先于估值计算结果的所有使用方）
    if _num(fill.get("price")) is None:
        raise ValueError(f"price 缺失或无法解析为数字: {fill.get('price')!r}"
                         f"（Hero 指标卡与估值三情景计算都依赖现价）")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(fill.get("date") or "")):
        raise ValueError(f"date 格式非法: {fill.get('date')!r}（必须严格 YYYY-MM-DD）")


def _check_quote_consistency(fill: dict) -> None:
    """quote 防伪（神华 601088 现价造假事故修复）：fill 声明 quote.source_file 时，
    读 em_fetch --out 落盘 JSON，比对 price/pe_ttm，偏差 >1% 拒渲染（与估值分四件套同级）。
    quote 字段缺失不拒（存量 fill 兼容），由 _check_quote_present 走告警。"""
    q = fill.get("quote")
    if q is None:
        return
    if not isinstance(q, dict) or not q.get("source_file"):
        raise ValueError('quote 字段需为 {"source_file": "em_fetch --out 落盘路径", "date": "YYYY-MM-DD"}')
    src = q["source_file"]
    try:
        with open(src, encoding="utf-8") as f:
            ref = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"quote.source_file 读取失败: {src}（{e}）——防伪链断裂不能静默放行，"
                         f"请重跑 em_fetch --out 落盘后再渲染")
    for fill_key, ref_key in (("price", "price"), ("pe_ttm", "pe_ttm")):
        fv, rv = _num(fill.get(fill_key)), _num(ref.get(ref_key))
        if fv is None or rv is None or rv == 0:
            continue
        if abs(fv - rv) / abs(rv) > 0.01:
            raise ValueError(f"{fill_key} 与 E1 落盘值不一致: fill={fv:g} vs {src}={rv:g}"
                             f"（偏差 {abs(fv - rv) / abs(rv) * 100:.1f}% > 1%）——现价类数字禁止手填，"
                             f"以 em_fetch --out 落盘值为准修正后重渲")


def _check_score_ranges(fill: dict) -> None:
    """分数范围（0-10）越界是硬错误。"""
    # 分数范围（0-10）越界是硬错误
    for field in ("scores", "timing_scores"):
        for k, v in (fill.get(field) or {}).items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{field}.{k} 不是数字: {v!r}")
            if not (0 <= fv <= 10):
                raise ValueError(f"{field}.{k} = {fv} 超出 0-10 范围")


def _check_valuation_inputs(fill: dict) -> None:
    """valuation_inputs 必填（估值分强制脚本化，四键缺一不可）。"""
    # valuation_inputs 必填（估值分强制脚本化，四键缺一不可）
    vi = fill.get("valuation_inputs")
    if not isinstance(vi, dict):
        raise ValueError('valuation_inputs 为必填字段：{"pe_ttm":…, "pe_band":[低,高], '
                         '"div_yield":…, "risk_free":…}（估值分由脚本四件套计算，不再接受手填）')
    miss_vi = [k for k in ("pe_ttm", "pe_band", "div_yield", "risk_free") if k not in vi]
    if miss_vi:
        raise ValueError(f"valuation_inputs 缺键: {miss_vi}（四键必填：pe_ttm / pe_band / div_yield / risk_free）")


def _check_valuation_scenarios(fill: dict) -> None:
    """valuation 结构化三情景必填且完整（每情景：profit+PE 区间 或 mcap 市值区间 + horizon）。"""
    # valuation 结构化三情景必填且完整（每情景：profit+PE 区间 或 mcap 市值区间 + horizon）
    v = fill.get("valuation")
    if not isinstance(v, dict) or not v.get("scenarios"):
        raise ValueError("valuation 为必填字段：结构化三情景假设（shares / horizon / scenarios），"
                         "目标价与估值分全部由脚本计算")
    shares_n = _num(v.get("shares"))
    if shares_n is None or shares_n <= 0:
        raise ValueError("valuation.shares 缺失、非法或 ≤0（总股本，亿股，必须为正数）")
    skeys = set()
    modes = set()
    for s in v.get("scenarios") or []:
        skeys.add(str(s.get("key") or "").lower())
        slab = s.get("label") or s.get("key") or "?"
        mc = s.get("mcap") or []
        has_mc = len(mc) >= 2 and _num(mc[0]) is not None and _num(mc[1]) is not None
        has_profit = _num(s.get("profit")) is not None
        if has_mc and has_profit:
            raise ValueError(f"valuation.scenarios[{slab}] 口径冲突：profit+pe 与 mcap 同情景只能二选一")
        if has_mc:
            # 市值口径（NAV/rNPV/SOTP 行业附录）：mcap = [低, 高] 目标总市值（亿元）
            if _num(mc[0]) <= 0 or _num(mc[1]) < _num(mc[0]):
                raise ValueError(f"valuation.scenarios[{slab}] mcap 区间非法（mcap: [低, 高]，亿元，需 0<低≤高）")
            modes.add("mcap")
        else:
            if not has_profit:
                raise ValueError(f"valuation.scenarios[{slab}] 缺净利假设（profit，归母净利亿元）"
                                 f"或目标市值区间（mcap: [低, 高]，亿元）")
            pe = s.get("pe") or []
            if len(pe) < 2 or _num(pe[0]) is None or _num(pe[1]) is None:
                raise ValueError(f"valuation.scenarios[{slab}] 缺 PE 区间（pe: [低, 高]）")
            # 与 mcap 侧对称的区间校验：倒挂（高<低）或非正值一律拒渲染
            if _num(pe[0]) <= 0 or _num(pe[1]) < _num(pe[0]):
                raise ValueError(f"valuation.scenarios[{slab}] PE 区间非法（pe: [低, 高]，需 0<低≤高）")
            modes.add("pe")
        if not str(s.get("horizon") or v.get("horizon") or "").strip():
            raise ValueError(f"valuation.scenarios[{slab}] 缺时间维度（horizon，可放情景级或 valuation 级）")
    if len(modes) > 1:
        raise ValueError("valuation.scenarios 口径混用：profit+pe 与 mcap 三情景必须统一口径")
    if not {"pess", "base", "opt"} <= skeys:
        raise ValueError(f"valuation.scenarios 必须含 pess/base/opt 三情景，当前只有: {sorted(skeys)}")


def _check_red_flag_breaker(fill: dict) -> None:
    """红灯熔断：red_flag 非空 → position_html 必须包含「不建议参与」。"""
    # 红灯熔断：red_flag 非空 → position_html 必须包含"不建议参与"
    red_flag = (fill.get("red_flag") or "").strip()
    pos_html = fill.get("position_html") or ""
    if red_flag and "不建议参与" not in _plain_text(pos_html):
        raise ValueError(f"红灯熔断：red_flag「{red_flag}」非空，position_html 必须包含「不建议参与」结论")


def _check_thesis_consistency(fill: dict, calc: dict) -> None:
    """thesis 三情景价一致性：手写 span 价 vs 脚本按 valuation 算出的中枢价。"""
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
            if c is None or f is None:
                continue
            if c > 0:
                mismatch = abs(f - c) > 0.1 and abs(f - c) / c > 0.02
            else:
                # c≤0（极端负中枢）时相对偏差无意义，只按绝对差 >0.1 判定
                mismatch = abs(f - c) > 0.1
            if mismatch:
                bad.append(f"{_SCENARIO_NAMES[k]} 手写 {f:g} vs 脚本 {c:.2f}")
        if bad:
            raise ValueError("thesis_html 三情景手写价与 valuation 计算值不一致（相对偏差>2% 且绝对差>0.1）："
                             + "；".join(bad)
                             + f"。手写={ {k: span_prices[k] for k in ('pess','base','opt')} }，"
                             + f"脚本={ {k: round(cmap.get(k, 0), 2) for k in ('pess','base','opt')} }")


def _check_content_floor(fill: dict) -> None:
    """内容地板（空心章节一律拒渲染）+ 表格来源标注数必须 ≥ 表格数。"""
    # 内容地板（空心章节一律拒渲染）
    concl_len = len(_plain_text(fill.get("conclusion_html")))
    if concl_len < 200:
        raise ValueError(f"conclusion_html 纯文本仅 {concl_len} 字 < 200：核心结论四段不能为空洞")
    for name, need in (("l1_html", 6), ("l3_html", 3)):
        # 与下方字数地板同口径（re.split），避免 class="dim-block x" 之类写法两口径打架
        n = len(re.split(r'<div class="dim-block">', fill.get(name) or "")) - 1
        if n < need:
            raise ValueError(f"{name} 仅 {n} 个 dim-block < {need}：每个评分维度必须各有一个维度块")
    if "<table" not in (fill.get("peers_html") or ""):
        raise ValueError("peers_html 不含 <table>：同业对比必须有数据表")
    pos_html = fill.get("position_html") or ""
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
                             f"每张表下方必须有来源标注——在缺口表格下方补 "
                             f'<span class="source">数据来源：…</span> 后重新渲染'
                             f"（报错后禁止绕过脚本手写全文 HTML，只能修 fill 重渲）")


def _check_missing_required_warns(fill: dict, warns: list) -> None:
    """必填字段缺失告警（fill-schema 标 ✓ 但渲染器原零校验，静默缺失会让分数算错或结构残缺）。"""
    # 必填字段缺失告警（fill-schema 标 ✓ 但渲染器原零校验，静默缺失会让分数算错或结构残缺）
    if not fill.get("timing_scores"):
        warns.append("timing_scores 缺失或为空：时机分将显示 —，请补筹码面/技术面得分")
    if "yellow_deductions" not in fill:
        warns.append("yellow_deductions 键缺失：黄灯扣分按 0 处理，质量分可能虚高；无扣分请显式填 []")
    th = fill.get("thesis_html", "")
    if not th.strip():
        warns.append("thesis_html 缺失：Hero 一句话结论为空")


def _check_stock_type_weights(fill: dict, warns: list) -> None:
    """分型权重交叉校验：非默认分型必须显式填 weights/layer_share，否则静默用默认值算错分。"""
    # 分型权重交叉校验：非默认分型必须显式填 weights/layer_share，否则静默用默认值算错分
    st = str(fill.get("stock_type") or "")
    if any(t in st for t in ("稳定价值", "金融", "银行", "保险", "券商", "快速成长", "未盈利", "困境反转")):
        if not fill.get("layer_share"):
            warns.append(f"stock_type={st} 层占比非默认，但未填 layer_share——脚本将用默认 70:30 计算，分数可能错误")
        if not fill.get("weights"):
            warns.append(f"stock_type={st} L1 权重非默认，但未填 weights——脚本将用基础权重计算，分数可能错误")


def _check_thesis_price_tags(fill: dict, warns: list) -> None:
    """thesis 三情景价格标注完整性。"""
    # thesis 三情景价格标注完整性
    th = fill.get("thesis_html", "")
    if th and not all(c in th for c in ("scenario-pess", "scenario-base", "scenario-opt")):
        warns.append("thesis_html 缺三情景价格标注（scenario-pess/base/opt span 未齐）")


def _check_thesis_info_floor(fill: dict, warns: list) -> None:
    """thesis 信息量地板：Hero 一句话是全文提纲挈领，不能只塞三个价格。"""
    # thesis 信息量地板：Hero 一句话是全文提纲挈领，不能只塞三个价格
    # （中兴 2026-08-24 实证：thesis 只有"12个月目标价：悲观/基础/乐观"）
    th = fill.get("thesis_html", "")
    th_txt_len = len(_plain_text(th))
    if th_txt_len:
        th_no_price = re.sub(r'<span\b[^>]*class="[^"]*\bscenario-(?:pess|base|opt)\b[^"]*"[^>]*>.*?</span>',
                             "", th, flags=re.I | re.S)
        th_rest = len(_plain_text(th_no_price))
        if th_txt_len < 60 or th_rest < 20:
            warns.append(f"thesis_html 信息量不足（纯文本 {th_txt_len} 字，剥掉三情景价后仅 {th_rest} 字）："
                         f"一句话结论 = 论点 + 关键证据 + 三情景价 + 操作结论，不能只塞目标价")


def _check_peers_plot_target(fill: dict, warns: list) -> None:
    """peers_plot 目标公司标记 + 目标点 PE 与估值四件套口径一致性。"""
    # peers_plot 目标公司标记
    pp = fill.get("peers_plot")
    pts = (pp.get("points") if isinstance(pp, dict) else pp) or []
    if pts:
        tg = [p for p in pts if p.get("target")]
        if not tg:
            warns.append("peers_plot 没有 target=true 的目标公司点")
        elif fill.get("company") and str(fill["company"]) not in str(tg[0].get("name", "")):
            warns.append(f"peers_plot 目标点名称「{tg[0].get('name')}」与公司名「{fill['company']}」不一致")
        # 口径一致性（赤峰 2026-09-02 实证：图中目标点用 A 股 PE 23.58x，正文用 H 股 18.6x）
        if tg:
            tpe = _num(tg[0].get("pe"))
            vpe = _num((fill.get("valuation_inputs") or {}).get("pe_ttm"))
            if tpe and vpe and abs(tpe - vpe) / abs(vpe) > 0.3:
                warns.append(f"peers_plot 目标公司 PE（{tpe:g}）与 valuation_inputs.pe_ttm（{vpe:g}）偏差 >30%："
                             f"请确认口径一致（A/H 股、IFRS/经调整、TTM/预测），确需混排在 peers_meta 注明")


def _check_timing_table_cells(fill: dict, warns: list) -> None:
    """时机判定小表单元格超长告警（长句塞格会溢出横向滚动；长解释应挪到表下 .source 行）。"""
    # 时机判定小表单元格超长告警（长句塞格会溢出横向滚动；长解释应挪到表下 .source 行）
    pos_html = fill.get("position_html") or ""
    for tm in re.finditer(r"<table\b[^>]*>.*?</table>", pos_html, re.I | re.S):
        tbl = tm.group(0)
        if "技术面" not in tbl or "筹码面" not in tbl:
            continue
        for cell in re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", tbl, re.I | re.S):
            if len(_plain_text(cell)) > 40:
                warns.append("时机判定小表存在 >40 字单元格：只写短语（≤15 字/条），"
                             "长解释与降级说明挪到表下 .source 行（fill-schema 固定 4 行 3 列格式）")
                break


def _check_dim_blocks(fill: dict, warns: list) -> None:
    """dim-block 内容地板（纯文本 <40 字拒渲染 / <80 字告警）与极端分证据校验。"""
    # dim-block 内容地板（deepseek 中兴/豪威"每块一句话凑数"缩水实证）：
    # 纯文本 <40 字 → 拒渲染（连一条论据都写不出）；<80 字 → 告警。
    # 同循环保留极端分证据校验：≥8 或 ≤3 的维度，dim-block 纯文本 <50 字 → 告警（极端分须配量化依据）
    thin_reject, thin_warn = [], []
    for field, layer in (("l1_html", "L1"), ("l3_html", "L3")):
        blocks = re.split(r'<div class="dim-block">', fill.get(field) or "")[1:]
        for (key, _l, name, _dw), blk in zip([d for d in DIMS if d[1] == layer], blocks):
            blen = len(_plain_text(blk))
            if blen < 40:
                thin_reject.append(f"{name} 仅 {blen} 字")
            elif blen < 80:
                thin_warn.append(f"{name} 仅 {blen} 字")
            sv = (fill.get("scores") or {}).get(key)
            if sv is None:
                continue
            sv = float(sv)
            if (sv >= 8 or sv <= 3) and blen < 50:
                warns.append(f"{name} 得分 {sv:g}（极端分）但 dim-block 纯文本仅 {blen} 字 < 50："
                             f"≥8 或 ≤3 必须配具体量化依据")
    if thin_reject:
        raise ValueError("dim-block 内容地板：" + "；".join(thin_reject)
                         + "（纯文本 <40 字）：每个维度块至少写出论据+数据，不能只写一句判语")
    if thin_warn:
        warns.append("dim-block 内容偏薄（纯文本 <80 字）：" + "；".join(thin_warn)
                     + "——每个维度块应有论据、数据与判词，薄块请补写后重渲")


def _check_internal_codes(fill: dict, warns: list) -> None:
    """框架内部代号泄漏检查：正文引用只准用章节编号/名称（L1/L3/L4/1D 代号禁入正文）。"""
    # 框架内部代号泄漏检查：正文引用只准用章节编号/名称（L1/L3/L4/1D 代号禁入正文；
    # "L1:L3" 占比记法是分型声明的合法写法，先剥离再检查）
    for name in ("thesis_html", "conclusion_html", "p0_html", "l1_html", "l3_html", "l4_html",
                 "valuation_html", "gap_html", "peers_html", "dash_html", "position_html", "review_html"):
        txt = _plain_text(fill.get(name) or "").replace("L1:L3", "")
        hits = sorted(set(re.findall(r"(?<![A-Za-z0-9])(?:L[134]|1D)(?![A-Za-z0-9])", txt)))
        if hits:
            warns.append(f"{name} 正文出现框架内部代号 {'/'.join(hits)}："
                         f"请改用章节编号/名称（第 3 章 / 3.4 / 第 5 章风险评估）")


def _check_writing_discipline(fill: dict, warns: list) -> None:
    """v4.7.1 写作纪律告警（东方电气反馈）：四拍挤段 / 3 年趋势三年并排 / pe_history 无第 10 章承载。"""
    # 四拍各自成段（fill-schema dim-block 四拍结构）：判词/论据/对比/收口挤进同一个 <p> → 提示拆段
    beats = ("判词：", "论据：", "对比：", "收口：")
    for name in ("l1_html", "l3_html"):
        for pm in re.finditer(r"<p[^>]*>(.*?)</p>", fill.get(name) or "", flags=re.S):
            hits = sum(1 for b in beats if b in pm.group(1))
            if hits >= 2:
                warns.append(f"{name} 存在四拍挤段（单段含 {hits} 个拍名）："
                             f"判词/论据/对比/收口应各自成段（fill-schema dim-block 四拍结构）")
                break  # 每字段报一次即可
    # 3 年趋势表只写 起→终（方向词）：三年数字并排反而看不出趋势
    peers = fill.get("peers_html") or ""
    if "<table" in peers:
        yseq = []
        for tm in re.finditer(r"<th[^>]*>(.*?)</th>", peers, flags=re.S):
            t = re.sub(r"<[^>]+>", "", tm.group(1)).strip()
            yseq.append(bool(re.fullmatch(r"20\d{2}年?", t)))
        stacked = any(len(re.findall(r"20\d{2}\s*[：:]", cdm.group(1))) >= 2
                      for cdm in re.finditer(r"<td[^>]*>(.*?)</td>", peers, flags=re.S))
        if any(yseq[i] and yseq[i + 1] and yseq[i + 2] for i in range(len(yseq) - 2)) or stacked:
            warns.append("3 年趋势表疑似三年数字并排：应写「起→终（方向词）」"
                         "（如 8.0→30.8（大升），方向词按指标语义着色），见 fill-schema 趋势表规则")
    # pe_history 图已挂第 10 章（v4.7.1）：cycle_html 缺失 → 整章删除，图无处显示
    if (fill.get("pe_history") or {}).get("hist_lo") is not None and not (fill.get("cycle_html") or "").strip():
        warns.append("pe_history 已填但 cycle_html 缺失：PE 历史带图挂第 10 章，整章被删后图不显示"
                     "——v4.7.1 起四类分型（周期/稳健成长/稳定价值/困境反转）应写第 10 章，或删除 pe_history")


def _check_prev_fields(fill: dict, warns: list) -> None:
    """prev 内部字段校验（回测模式锚点缺项会静默显示 "?"/"—"）。"""
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
        # 关键假设变更表（防评分漂移，backtest.md 6.6 硬性要求）
        rv = fill.get("review_html") or ""
        if rv and ("<table" not in rv or "假设" not in rv):
            warns.append("review_html 缺关键假设变更表：R 章节必须含相邻两版三情景假设对比表"
                         "（假设未变也要显式写明），见 backtest.md 6.6")


def _check_misc_required(fill: dict, warns: list) -> None:
    """其余 fill-schema 标 ✓ 但渲染器零校验的必填字段。"""
    # 其余 fill-schema 标 ✓ 但渲染器零校验的必填字段
    for name in ("valuation_method", "stock_type", "gap_tier", "peers_meta", "next_review"):
        if not str(fill.get(name) or "").strip() or fill.get(name) == "—":
            warns.append(f"{name} 缺失或为占位符：对应章节标题/meta 将为空白")
    if not (fill.get("subtitle") or "").strip():
        warns.append("subtitle 缺失：Hero 副标题为空")
    elif "报告日期" in fill["subtitle"]:
        warns.append("subtitle 含「报告日期」：模板 Hero 会自动追加报告日期，subtitle 请勿再写日期")


def _check_quote_present(fill: dict, warns: list) -> None:
    """quote 缺失 → 告警不拒（存量 fill 兼容）；quote 存在但不一致已在 _check_quote_consistency 拒渲染。"""
    if not fill.get("quote"):
        warns.append("quote 字段缺失：现价/PE(TTM) 无 em_fetch --out 落盘防伪（神华 601088 事故修复项）"
                     "——新报告应在 em_fetch 时加 --out 落盘，并在 fill 回填 quote.source_file")


def validate_content(fill: dict, calc: dict = None) -> None:
    """内容级校验（成稿前自动复核，借鉴 equity-research 检查器思路）。
    硬错误（拒渲染）：分数越界、valuation_inputs 缺失、valuation 三情景字段不全、
    红灯熔断缺"不建议参与"、thesis 手写价与脚本计算值不一致、内容地板（空心章节）、
    表格缺来源标注；其余 → stderr 告警（P1），模型看到即修正。
    calc 为 compute_valuation 结果（thesis 一致性校验用）。"""
    _check_price_date(fill)
    _check_quote_consistency(fill)
    _check_score_ranges(fill)

    _check_valuation_inputs(fill)
    _check_valuation_scenarios(fill)

    _check_red_flag_breaker(fill)
    _check_thesis_consistency(fill, calc)
    _check_content_floor(fill)

    warns = []
    _check_missing_required_warns(fill, warns)
    _check_stock_type_weights(fill, warns)
    _check_thesis_price_tags(fill, warns)
    _check_thesis_info_floor(fill, warns)
    _check_peers_plot_target(fill, warns)
    _check_timing_table_cells(fill, warns)
    _check_dim_blocks(fill, warns)
    _check_internal_codes(fill, warns)
    _check_writing_discipline(fill, warns)
    _check_prev_fields(fill, warns)
    _check_misc_required(fill, warns)
    _check_quote_present(fill, warns)
    for w in warns:
        print(f"⚠️ 内容校验: {w}", file=sys.stderr)


def _tag_timing_table(html: str) -> str:
    """11 时机判定小表（表体含 技术面/筹码面 行的表）自动补 class="timing-table"——
    模板 CSS 对该表除末列（依据长文）外强制不换行，防止"技术面/筹码面/时机分"折行。
    末行文本含「合计/时机分」时给该 <tr> 补 class="total"（合计行加粗+浅底，与明细行区分）。"""
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
        tagged = f"<table{new_attrs}>" + tbl[open_m.end():]
        # 合计行标记：只看末个 <tr>，文本含「合计」或「时机分」才补 total 类（无明文合计行不误标）
        trs = list(re.finditer(r"<tr\b[^>]*>", tagged, re.I))
        if trs:
            last = trs[-1]
            row_txt = re.sub(r"<[^>]+>", "", tagged[last.end():])
            if ("合计" in row_txt or "时机分" in row_txt) and "class" not in last.group(0):
                tagged = (tagged[:last.start()] + last.group(0)[:-1].rstrip()
                          + ' class="total">' + tagged[last.end():])
        return tagged
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
    # 行业口径标签（P/NAV、P/rNPV、P/EV、经调整PE 等），缺省 PE(TTM)
    mlabel = str(inputs.get("metric_label") or "PE(TTM)")
    return [
        ("中枢分", f"年化中枢 {calc['central'] * 100:+.1f}%（{calc['horizon']}）", vc["central_s"], 40),
        ("赔率分", f"赔率 {odds_txt}", vc["odds_s"], 25),
        ("合理倍数分", f"{mlabel} {pe_ttm:g}x vs 合理带 {band_lo:g}-{band_hi:g}x", vc["warranted_s"], 25),
        ("股息分", div_txt, vc["div_s"], 10),
    ]


def build_score_summary(sc: dict) -> str:
    """6 质量分汇总章尾公式条（脚本生成）：层分×占比 ± 黄灯 → 最终质量分。
    9 行维度明细表已并入上方的评分分布横条图（得分/判词/权重/加权全部由图承载，见
    build_score_bars），本章不再重复表格——footer 只保留算式与最终分。"""
    layer_scores, ls = sc["layer_scores"], sc["layer_share"]
    quality, yellow_total = sc["quality"], sc["yellow_total"]
    red_total = sc["red_total"]

    terms = " + ".join(
        f"{LAYER_NAMES[layer]} {layer_scores[layer]:.2f} × {ls[layer]:.0f}%"
        for layer in ("L1", "L3"))
    parts = [terms]
    if yellow_total:
        parts.append(f"− 黄灯 {yellow_total:.1f}")
    formula = " ".join(parts)
    # 红旗扣分已在 1D 维度分内先行扣减（图上 3.4 条为扣后分），算式不重复列入
    red_note = ""
    if red_total:
        red_items = "；".join(str(r.get("item", "")) for r in sc["red_deductions"])
        red_note = (f' <span class="muted">（3.4 财务健康得分已含红旗扣分 {red_total:.1f}'
                    + (f'：{_esc(red_items)}' if red_items else "") + '）</span>')
    return (f'<div class="layer-summary">质量分 = {formula} = '
            f'<span class="badge {badge_class(quality)} badge-lg">{quality:.2f}</span>'
            f' <strong>{_quality_verdict(quality)}</strong>{red_note}</div>')


def build_valuation_process_card(calc: dict, vc: dict, inputs: dict) -> str:
    """7 估值与安全边际章末尾汇总卡（脚本生成，作为本节结论列在最后）：四件套 输入值→映射得分→权重→加权，
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


# 仓位档位序列（上浮 20% 硬顶、下调 0 兜底；规则正文唯一权威在 references/scoring.md 决策主轴节，改动须同步）
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
    # 注意：必须返回整数 0（_POS_LADDER 档位），返回字符串会被 build_position_card
    # 落入「观察池」分支——质量 <4 的正确结论是「不建议参与」
    return ("质量<4", 0, 8)


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
    #    > 时机分调节 > 离散度调节 > 赔率 ∞ 上浮；只列实际触发条目，未触发不列。
    #    上浮类合计净效应 ≤ +1 档且不进 20 档，被拦项以「上浮封顶」条目说明）
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
            # 上浮封顶（规则见 references/scoring.md 决策主轴节）：上浮类调节合计净效应
            # ≤ +1 档，且任何调节不得进入 20 档——重仓唯一入口是矩阵直接落位（≥7×≥8）。
            # 防两类历史缺陷：①轻仓被时机+离散+赔率三连浮推成重仓；②下调缺 0 兜底时
            # 负索引回卷到重仓。被拦项统一记入 blocked_by_cap，在轨迹中说明未生效原因。
            up_used = 0
            blocked_by_cap = []
            # 时机分调节（≥6 上浮一档 / <4 下调一档；0 兜底）
            if timing is not None and timing >= 6:
                if (up_used == 0 and idx + 1 < len(_POS_LADDER)
                        and _POS_LADDER[idx + 1] < 20):
                    steps.append(f"时机分调节：时机分 {timing:.2f} ≥ 6 → 上浮一档"
                                 f"（{_POS_LABEL[_POS_LADDER[idx]]}→{_POS_LABEL[_POS_LADDER[idx + 1]]}）")
                    idx += 1
                    up_used = 1
                elif idx + 1 < len(_POS_LADDER):  # 落位已在顶格时不重复解释
                    blocked_by_cap.append(f"时机分 {timing:.2f} ≥ 6")
            elif timing is not None and timing < 4:
                new_idx = max(idx - 1, 0)
                steps.append(f"时机分调节：时机分 {timing:.2f} < 4 → 下调一档"
                             f"（{_POS_LABEL[_POS_LADDER[idx]]}→{_POS_LABEL[_POS_LADDER[new_idx]]}）")
                idx = new_idx
            # 离散度调节（>90% 下调一档 / <40% 上浮一档；60% 旧阈值在 20 份报告中触发率 70%，
            # 形同普遍降档，已按经验分布收紧到极端档）
            if calc and calc["dispersion"] > 0.90:
                new_idx = max(idx - 1, 0)
                steps.append(f"离散度调节：离散度 {calc['dispersion'] * 100:.1f}% > 90% → 下调一档"
                             f"（{_POS_LABEL[_POS_LADDER[idx]]}→{_POS_LABEL[_POS_LADDER[new_idx]]}）")
                idx = new_idx
            elif calc and calc["dispersion"] < 0.40:
                if (up_used == 0 and idx + 1 < len(_POS_LADDER)
                        and _POS_LADDER[idx + 1] < 20):
                    steps.append(f"离散度调节：离散度 {calc['dispersion'] * 100:.1f}% < 40% → 上浮一档"
                                 f"（{_POS_LABEL[_POS_LADDER[idx]]}→{_POS_LABEL[_POS_LADDER[idx + 1]]}）")
                    idx += 1
                    up_used = 1
                elif idx + 1 < len(_POS_LADDER):
                    blocked_by_cap.append(f"离散度 {calc['dispersion'] * 100:.1f}% < 40%")
            # 赔率 ∞ 上浮一档（受封顶约束）
            if calc and calc["odds"] is None:
                if (up_used == 0 and idx + 1 < len(_POS_LADDER)
                        and _POS_LADDER[idx + 1] < 20):
                    steps.append(f"赔率调节：赔率 ∞（悲观仍正收益）→ 上浮一档"
                                 f"（{_POS_LABEL[_POS_LADDER[idx]]}→{_POS_LABEL[_POS_LADDER[idx + 1]]}）")
                    idx += 1
                    up_used = 1
                elif idx + 1 < len(_POS_LADDER):
                    blocked_by_cap.append("赔率 ∞")
            if blocked_by_cap:
                steps.append("上浮封顶：" + "、".join(blocked_by_cap)
                             + " 同样满足上浮条件，受「上浮合计 ≤1 档且不进 20 档」限制未生效")
            final_label = _POS_LABEL[_POS_LADDER[idx]]
        elif pos == 0:
            final_label = "不建议参与"
        else:
            # 观察池：不因时机/赔率上浮；时机 <4 或离散度 >90% 下调为不建议参与
            down = []
            if timing is not None and timing < 4:
                down.append(f"时机分 {timing:.2f} < 4")
            if calc and calc["dispersion"] > 0.90:
                down.append(f"离散度 {calc['dispersion'] * 100:.1f}% > 90%")
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


def _strip_unit(v, units: str) -> str:
    """剥掉 fill 值尾部的单位字符（模板已带单位 span，防"9,237.6亿 亿"/"14.97x 倍"叠床架屋）。"""
    return re.sub(rf"\s*[{units}]+$", "", str(v or "—").strip())


def _fmt_thousands(v: str) -> str:
    """Hero 金额类数值卡显示层千位符归一（神华修复版 Hero 总市值 10330.7 裸数字事故修复）：
    "10330.7" / "10,330.7" → "10,330.7"；整数部分 <1000、非纯数字（"—"、已带单位）原样返回。
    只用于纯展示字段（mcap）；price 走 _num 解析，禁止带逗号，不经此函数。"""
    s = str(v or "").strip()
    if not re.fullmatch(r"\d[\d,]*\.?\d*", s):
        return s
    int_part, dot, frac = s.replace(",", "").partition(".")
    if len(int_part) < 4:
        return int_part + (dot + frac if dot else "")
    return f"{int(int_part):,}" + (dot + frac if dot else "")


def _check_required_scalars(fill: dict) -> None:
    """必填标量字段（company/code/date）缺失即拒渲染。"""
    for k in REQUIRED_SCALAR:
        if not fill.get(k):
            raise ValueError(f"缺必填字段: {k}")


def _clean_peers_matrix(fill: dict, peers_plot_html: str) -> str:
    """散点图已生成 → 手写九宫格冗余，自动删除（含"估值-质量矩阵："引导句）。"""
    peers_html = fill.get("peers_html", "")
    if peers_plot_html and "matrix-table" in peers_html:
        # 散点图已生成 → 手写九宫格冗余，自动删除（含"估值-质量矩阵："引导句）
        cleaned = re.sub(r'<p[^>]*>\s*<strong>\s*估值[-—]质量矩阵[^<]*</strong>\s*</p>\s*', "", peers_html)
        cleaned = re.sub(r'<table\b[^>]*class="matrix-table"[^>]*>.*?</table>\s*', "", cleaned, flags=re.I | re.S)
        if cleaned != peers_html:
            print("⚠️ 已提供 peers_plot 散点图，peers_html 中手写的 matrix-table 九宫格冗余，已自动删除",
                  file=sys.stderr)
        peers_html = cleaned
    return peers_html


def _apply_valuation_score(fill: dict, calc: dict, fill_valuation):
    """估值分强制脚本化：四件套计算结果直接覆盖 fill 里的 valuation_score（填了也只作提示）。
    返回 (覆盖后估值分, valuation_calc)。"""
    # 估值分强制脚本化：四件套计算结果直接覆盖 fill 里的 valuation_score（填了也只作提示）
    valuation_calc = compute_valuation_score(calc, fill.get("valuation_inputs"))
    if valuation_calc is None:
        raise ValueError("估值分无法计算：valuation_inputs 四键或 valuation 三情景字段不完整"
                         "（pe_ttm/pe_band/div_yield/risk_free + 每情景 profit/pe 或 mcap + horizon）")
    if fill_valuation is not None and abs(valuation_calc["score"] - fill_valuation) > 0.11:
        print(f"⚠️ fill 手填估值分 {fill_valuation:.1f} 与脚本四件套计算 {valuation_calc['score']:.1f} 不一致，"
              f"已按脚本计算值覆盖（valuation_score 字段已废弃，可删除）", file=sys.stderr)
    return valuation_calc["score"], valuation_calc


def _check_backtest_flags(fill: dict):
    """回测模式一致性告警：prev（上版锚点）与 review_html 应成对出现。
    返回 (prev, review_html) 供 repl/文件名使用。"""
    # 回测模式：fill 带 prev 字段（上版锚点）→ Hero 对比条 + R 复盘章节 + 文件名加"复盘"
    prev = fill.get("prev") or None
    review_html = fill.get("review_html", "")
    if prev and not review_html:
        print("⚠️ 回测模式（prev 已填）但 review_html 为空：R 回测复盘章节将缺失", file=sys.stderr)
    if review_html and not prev:
        print("⚠️ 有 review_html 但未填 prev：文件名与 Hero 不会标记「复盘」，请补 prev 字段", file=sys.stderr)
    return prev, review_html


def _build_context(fill: dict, calc: dict):
    """日期/副标题/目标价区间解析（目标价区间以脚本计算为准）。
    返回 (date, subtitle, target_range)。"""
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
    return date, subtitle, target_range


def _build_repl_map(fill: dict, cur: str, calc: dict, sc: dict, valuation: float,
                    valuation_calc: dict, prev: dict, review_html: str, date: str,
                    subtitle: str, target_range: str, peers_html: str, spectrum_html: str,
                    scenario_block_html: str, peers_plot_html: str) -> dict:
    """组装模板占位符映射（repl）：全部字段值在此定稿，条件块/替换/渲染后校验都消费它。"""
    layer_scores = sc["layer_scores"]
    layer_share = sc["layer_share"]
    quality = sc["quality"]
    timing = sc["timing"]
    red_flag = sc["red_flag"]
    yellow_total = sc["yellow_total"]
    repl = {
        "DATE": _esc(date),
        "COMPANY": _esc(fill["company"]),
        "CODE": _esc(fill["code"]),
        "SUBTITLE": _esc(subtitle),
        "CUR": _esc(cur),
        "THESIS_HTML": fill.get("thesis_html", ""),
        "PRICE": str(fill.get("price", "—")),
        "PRICE_SUB_HTML": fill.get("price_sub_html", ""),
        "MCAP": _fmt_thousands(_strip_unit(fill.get("mcap"), "亿万")),
        "MCAP_SUB": fill.get("mcap_sub", ""),
        "PE_TTM": _strip_unit(fill.get("pe_ttm"), "xX倍"),
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
        "VALUATION_HTML": fill.get("valuation_html", ""),
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
        # v4.8 图表与导航增强（评分分布横条 / 敏感性龙卷风 / PE 历史带 / 回测哑铃 / 侧栏目录；
        # 龙卷风与 PE 带依赖可选字段，缺失返回空串 → 模板条件块整块删除）
        "TOC_HTML": build_toc(bool(fill.get("cycle_html")), bool(review_html)),
        "SCORE_BARS_HTML": build_score_bars(sc),
        "SENSITIVITY_PLOT_HTML": build_sensitivity_tornado(fill),
        "PE_BAND_HTML": build_pe_band(fill),
        "REVIEW_PLOT_HTML": build_review_dumbbell(prev, quality, valuation, timing),
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
        "VALUATION_VALUE_CLASS": ("score-good" if valuation >= 8 else "score-mid" if valuation >= 4 else "score-bad"),

        # 时机分（微调）
        "TIMING_SCORE": (f"{timing:.2f}" if timing is not None else "—"),
        "RED_FLAG_HTML": (f'<div class="danger-card">🔴 <strong>红灯回避</strong>：{_esc(red_flag)}</div>' if red_flag else ""),
        "L1_SCORE": f"{layer_scores['L1']:.2f}", "L1_W": f"{layer_share['L1']:.0f}",
        "L3_SCORE": f"{layer_scores['L3']:.2f}", "L3_W": f"{layer_share['L3']:.0f}",
    }
    return repl


def _fill_template(repl: dict) -> str:
    """读模板 → 条件块（<!--IF:-->）/占位符（{{...}}）替换 → 表格对齐自动修正。"""
    tmpl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "report-template.html")
    html = open(tmpl_path, encoding="utf-8").read()

    # 条件章节：<!--IF:KEY--> ... <!--ENDIF-->
    def handle_conditional(m):
        key = m.group(1)
        block = m.group(2)
        return block if repl.get(key) else ""
    html = re.sub(r"<!--IF:([A-Z_]+)-->(.*?)<!--ENDIF-->", handle_conditional, html, flags=re.S)

    html = re.sub(r"\{\{([A-Z_0-9]+)\}\}", lambda m: repl.get(m.group(1), m.group(0)), html)

    # 表格对齐自动修正（fragment 手写表头类不齐的兜底，matrix-table 跳过）
    html = fix_table_alignment(html)
    return html


def _check_leftover(html: str) -> None:
    """渲染后残留占位符校验：任何 {{...}} / 【...】 残留即报错退出。"""
    # 校验残留
    leftover_double = re.findall(r"\{\{[A-Za-z_0-9]+\}\}", html)
    if leftover_double:
        raise ValueError(f"残留未替换占位符: {sorted(set(leftover_double))}")
    leftover_cn = re.findall(r"【[^】]{0,40}】", html)
    # 黄灯类别标注（【b 行业与政策环境】这类以单个 a-d 字母开头的）是合法引用，不算占位符
    leftover_cn = [x for x in leftover_cn if not re.match(r"【[a-dA-D][ 、\s]", x)]
    if leftover_cn:
        raise ValueError(f"残留中文占位符: {sorted(set(leftover_cn))}")


def _make_output_path(fill_path: str, fill: dict, date: str, quality: float,
                      valuation: float, prev: dict) -> str:
    """自动命名输出：{公司名}-{代码}-{质量分}-{估值分}{-复盘}-{日期}.html"""
    review_tag = "-复盘" if prev else ""
    company_s = _safe_filename(fill["company"])
    code_s = _safe_filename(fill["code"])
    date_s = _safe_filename(date)
    return os.path.join(os.path.dirname(os.path.abspath(fill_path)),
                        f"{company_s}-{code_s}-{quality:.2f}-{valuation:.1f}{review_tag}-{date_s}.html")


def _write_html(html: str, out_path: str) -> None:
    """写输出文件：覆盖告警 + 注入 RENDERER_VERSION 尾部注释。"""
    if os.path.exists(out_path):
        print(f"⚠️ 输出文件已存在，将被覆盖: {out_path}", file=sys.stderr)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html.replace("</body>",
                             f"<!-- generated by render_report.py {RENDERER_VERSION} -->\n</body>"))


def _post_render_checks(repl: dict, fill: dict, out_path: str, quality: float, pre_risk: float,
                        yellow_total: float, valuation: float, timing, red_flag: str,
                        layer_scores: dict) -> None:
    """渲染后校验：空章节片段告警 + 图形字段缺失"响亮"提醒 + 结果一行打印。"""
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


def render(fill_path: str, out_path: str = None) -> str:
    fill = _load_fill(fill_path)
    _check_required_scalars(fill)

    _check_l4_order(fill.get("l4_html", ""))
    cur = str(fill.get("currency") or "元")  # 币种单位（默认「元」，港股 fill 填 currency="港元"）

    # 估值计算（valuation 字段存在时，目标价/中枢/赔率/离散度全部脚本算）
    calc = compute_valuation(fill)
    validate_content(fill, calc)

    # 图形组件（脚本生成 SVG；数据缺省时为空串 → 模板条件块整块删除）
    spectrum_html = build_scenario_spectrum(fill, calc)
    scenario_block_html = build_scenario_block(calc, cur)
    peers_plot_html = build_peers_plot(fill)
    peers_html = _clean_peers_matrix(fill, peers_plot_html)

    sc = compute_scores(fill)
    layer_scores = sc["layer_scores"]
    pre_risk = sc["pre_risk_quality"]
    yellow_total = sc["yellow_total"]
    quality = sc["quality"]
    timing = sc["timing"]
    red_flag = sc["red_flag"]

    valuation, valuation_calc = _apply_valuation_score(fill, calc, sc["valuation"])

    prev, review_html = _check_backtest_flags(fill)

    date, subtitle, target_range = _build_context(fill, calc)
    repl = _build_repl_map(fill, cur, calc, sc, valuation, valuation_calc, prev, review_html,
                           date, subtitle, target_range, peers_html, spectrum_html,
                           scenario_block_html, peers_plot_html)

    html = _fill_template(repl)
    _check_leftover(html)

    if not out_path:
        out_path = _make_output_path(fill_path, fill, date, quality, valuation, prev)
    _write_html(html, out_path)

    _post_render_checks(repl, fill, out_path, quality, pre_risk, yellow_total,
                        valuation, timing, red_flag, layer_scores)
    return out_path


def check_fill(fill_path: str) -> None:
    """--check 模式：fill JSON 落盘后预检（解析 + 评分/估值计算 + 内容校验），不渲染。
    替代手写 python -c json.load 自检（Windows 控制台引号/编码/路径反斜杠坑，
    中兴 2026-08-24 实证）。退出码：0=通过可渲染，2=存在拒渲染项。"""
    try:
        fill = _load_fill(fill_path)
        print(f"OK JSON 可解析，共 {len(fill)} 个顶层键")
        calc = None
        if fill.get("valuation"):
            calc = compute_valuation(fill)
        compute_scores(fill)
        validate_content(fill, calc)
        # 与 render 同路径：估值分必须可计算——否则 check 退出码 0 但 render 在估值分处才失败
        if compute_valuation_score(calc, fill.get("valuation_inputs")) is None:
            raise ValueError("估值分无法计算：valuation_inputs 四键或 valuation 三情景字段不完整"
                             "（pe_ttm/pe_band/div_yield/risk_free + 每情景 profit/pe 或 mcap + horizon）")
    except ValueError as e:
        print(f"✗ 预检未通过（渲染将被拒绝）：\n  {e}", file=sys.stderr)
        sys.exit(2)
    print("OK 内容预检通过，可执行渲染")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a[2:] for a in sys.argv[1:] if a.startswith("--") and "=" not in a}
    opts = {a[2:].split("=")[0]: a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--") and "=" in a}
    if not args:
        print(__doc__)
        sys.exit(1)
    if "check" in flags:
        check_fill(args[0])
    else:
        try:
            render(args[0], opts.get("out"))
        except ValueError as e:
            # 与 --check 同款友好捕获：校验失败不把完整 traceback 吐进 agent 上下文
            print(f"✗ 渲染被拒绝：\n  {e}", file=sys.stderr)
            sys.exit(2)
