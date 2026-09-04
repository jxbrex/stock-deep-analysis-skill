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
import os
import re
import sys

# Windows GBK 控制台打印 ⚠️/−/🔴 等字符会 UnicodeEncodeError，统一强制 UTF-8 + replace
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# ---------- 子模块导入与再导出（v4.8.3 重构：单文件 → scoring/charts/validate） ----------
# 测试与旧调用方以 `import render_report as R` 按名字访问内部函数（如 R.compute_scores、
# R._ticks、R.validate_content），拆分后子模块全部公开名字必须在此原样可访问。
# 依赖方向单向：scoring（共享基座）← charts / validate ← 本模块，无循环。
from scoring import (  # noqa: F401（再导出，供 R.xxx 按名访问）
    DIMS, DEFAULT_LAYER_SHARE, TIMING_DIMS, LAYER_NAMES, REQUIRED_SCALAR,
    _dim_verdict, badge_class, valuation_badge_class,
    _quality_verdict, _valuation_verdict, _timing_verdict,
    _num, _fmt, _esc, compute_scores,
    _scenario_numbers, _position_steps,
    _valuation_four_rows, build_score_summary, build_valuation_process_card,
    _POS_LADDER, _POS_LABEL, _matrix_slot, build_position_card,
)
from charts import (  # noqa: F401（再导出）
    _C_LABEL, _C_GRID, _C_AXIS, _C_BLUE, _C_PAPER, _C_INK, _C_BLACK, _C_STONE,
    _C_OLIVE, _C_SAND, _C_SAND_LT, _C_TRACK, _C_GOOD_LINE, _C_YEAR_GRID,
    _C_GREEN, _C_RED, _C_ORANGE,
    _fmt_price, _fmt_amt, _SCENARIO_COLORS, _SCENARIO_NAMES,
    _pad_domain, _lin_map, _text_w, _wrap_label, _ticks,
    _SVG_STYLE, _svg_open, _svg_close, _vgrid_ticks, _anchor_fit, _anchor_clamp,
    build_scenario_spectrum, build_scenario_block, build_peers_plot,
    build_score_bars, build_sensitivity_tornado, build_pe_band,
    build_segments_plot, build_chain_plot, build_fin_trend, build_growth_plot,
    _inject_l1_charts, _inject_l3_charts,
    build_price_history, build_holders_plot, build_review_dumbbell,
    build_triggers_strip,
)
from validate import (  # noqa: F401（再导出）
    _plain_text, _check_price_date, _check_quote_consistency,
    _check_score_ranges, _check_valuation_inputs, _check_valuation_scenarios,
    _check_red_flag_breaker, _check_thesis_consistency, _check_content_floor,
    _check_missing_required_warns, _check_stock_type_weights,
    _check_thesis_price_tags, _check_thesis_info_floor, _check_peers_plot_target,
    _check_timing_table_cells, _check_dim_blocks, _check_internal_codes,
    _check_writing_discipline, _check_prev_fields, _check_misc_required,
    _check_quote_present, _check_optional_charts,
    validate_content, _tag_timing_table, _check_l4_order, build_prev_strip,
)


# 渲染器版本：嵌入输出 HTML 尾部注释，事后可 grep 验证报告确由本脚本渲染
# （防"render 报错后手写全文 HTML 绕行"，巨石 2026-08-23 实证）
RENDERER_VERSION = "v4.9"

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
    作用：模型手写 fragment 表头类不齐时（裸 th 配 td class=num/center），渲染层兜底对齐。
    限制：以非贪婪 `<table>…</table>` 正则切表，不支持表内嵌表（嵌套 <table> 会在内层
    起始处提前收表，行/列对齐只对外层可视段生效）——fragment 写作时禁止嵌套表。"""
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
        profit, pe_lo, pe_hi, mc_lo, mc_hi = _scenario_numbers(s)
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
                     "color": _SCENARIO_COLORS.get(key, _C_LABEL),
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


# 侧栏目录条目：(锚点 id, 完整章节名[title 悬停提示], 侧栏简称)
_TOC_MAIN = [("s1", "1 核心结论", "结论"), ("s2", "2 关键利润驱动", "驱动"),
             ("s3", "3 公司本质", "本质"), ("s4", "4 未来预期", "预期"),
             ("s5", "5 风险评估", "风险"), ("s6", "6 质量分汇总", "评分"),
             ("s7", "7 估值与安全边际", "估值"), ("s8", "8 市场预期差", "分歧"),
             ("s9", "9 同业对比", "同业")]
_TOC_TAIL = [("s11", "11 仓位与时机决策", "仓位")]


def build_toc(has_cycle: bool, has_review: bool) -> str:
    """右缘固定侧栏目录（纯 CSS 零 JS；宽屏显示，窄屏与打印隐藏）：章节用两字简称，
    悬停可见全名（title）；条件章节（10 周期 / 12 回测）按存在性生成，
    编号与模板固定章节号一致（v4.8.1：12=回测复盘、13=跟踪仪表盘，先复盘后跟踪）。"""
    secs = list(_TOC_MAIN)
    if has_cycle:
        secs.append(("s10", "10 周期规律", "周期"))
    secs += _TOC_TAIL
    if has_review:
        secs.append(("s12", "12 回测复盘", "复盘"))
    secs.append(("s13", "13 跟踪仪表盘", "跟踪"))
    links = "".join(f'<a href="#{i}" title="{_esc(full)}">{_esc(short)}</a>' for i, full, short in secs)
    return f'<nav class="toc-side">{links}</nav>'


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
        # v4.8：3.1 业务构成图 / 3.2 产业链图由锚点 <!--SEGMENTS--> / <!--CHAIN--> 注入 l1_html
        # v4.9：3.4 财务趋势图墙 <!--FIN_TREND--> 同注入；4.1 利润增长图 <!--GROWTH--> 注入 l3_html
        "L1_HTML": _inject_l1_charts(fill.get("l1_html", ""), fill),
        "L3_HTML": _inject_l3_charts(fill.get("l3_html", ""), fill),
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
        # v4.10：触发条件状态条（triggers 可选字段，脚本生成，垫在手写仪表盘前）
        "TRIGGERS_HTML": build_triggers_strip(fill),
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
        # v4.8 新增：10 章股价/PE 发丝图（price_history，随第 10 章条件块同生共灭）、
        # 11 章股东户数趋势（holders，裸占位符空串替换）
        "PRICE_HIST_HTML": build_price_history(fill),
        "HOLDERS_PLOT_HTML": build_holders_plot(fill),
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

    # repl 值（fill 的 HTML fragment 文本）注入前把字面 {{ 实体化：fill 若自带「{{KEY}}」
    # 形态的示例/说明文本，会被下方占位符替换轮误吞（KEY 命中 repl 键 → 替换成别的值，
    # 静默错内容），或落入 _check_leftover 残留报错——实体化后按原样显示为 {{KEY}}
    repl = {k: (v.replace("{{", "&#123;&#123;") if isinstance(v, str) else v)
            for k, v in repl.items()}

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
