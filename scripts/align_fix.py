#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""align_fix.py — 表格对齐自动修正机（v4.10.2 自 render_report.py 独立成模块）

内容：fix_table_alignment（渲染末道工序：全表对齐类自动修正）与其全部 helper
（_classes_of/_align_class/_set_th_align/_strip_th_align/_is_plain_text/_is_prose_cell/
_content_vote），外加 _tag_timing_table（时机小表自动补类，自 validate.py 归位）。
纯 HTML transform，只依赖 scoring 的 _plain_text；不产出校验结论。
"""
import re

from scoring import _plain_text

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
    t = _plain_text(s)
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
    """num 列中应左对齐的文字格：剥括号注释后含句读的纯文字/长句，或剥括号后超 4 字的纯文字。
    括号内句读不参与判定（"±60-90 亿（手机毛利率仅 8.5%，缓冲更薄）"是数值+注释，随列右对齐）；
    短占位格（"未披露""未获取到""不适用""—（上年亏损）"）**不翻列**——v4.10.3 审计实证：
    原「超 2 字纯文字」阈值让这些占位格也翻转整列，存量 66 份报告 54 份因此被改动，远超申报口径；
    长数值串（"13,600-15,300亿"）因含数字天然右对齐。"""
    t = _plain_text(s)
    t2 = re.sub(r"[（(][^）)]*[）)]", "", t)  # 先剥括号注释：括号内句读不参与判定
    if re.search(r"[，。；、：]", t2) and (not re.search(r"\d", t2) or len(t2) > 20):
        return True   # 纯文字带句读→左对齐；带数字的长句（>20字）仍是说明文→左对齐
    return len(t2) > 4 and _is_plain_text(s)


def _content_vote(inner: str):
    """裸 td（无对齐类）按内容投票：数值/短数值串 → 'num'，文字/长句 → 'left'。
    解决两类不一致：th 有 num 而 td 全裸（表头右、数据左）；文字格被误标 num（核心业务行）。
    判定：剥括号注释后，去掉数字与数值符号所剩字符为空或仅为单位 → num，否则 left
    （"3.1 赛道与宏观"含数字但是文字标签；"12个月"/"+70.1%"是数值）。"""
    t = _plain_text(inner)
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
    （num/center 多数决，v4.10 起文字票平票即判左；v4.10.3 起列内出现说明文格 → 整列判左），
    给同列 th 配同类；第一列强制左对齐。matrix-table/scenario-table 跳过（后者类名由脚本写死、
    对齐属有意设计）。
    作用：模型手写 fragment 表头类不齐时（裸 th 配 td class=num/center），渲染层兜底对齐。
    限制：以非贪婪 `<table>…</table>` 正则切表，不支持表内嵌表（嵌套 <table> 会在内层
    起始处提前收表，行/列对齐只对外层可视段生效）——fragment 写作时禁止嵌套表。"""
    out = []
    pos = 0
    for tm in re.finditer(r'<table\b[^>]*>.*?</table>', html, flags=re.I | re.S):
        out.append(html[pos:tm.start()])
        tbl = tm.group(0)
        tbl_attrs_m = re.match(r'<table\b([^>]*)>', tbl, re.I)
        # matrix-table 既定跳过；scenario-table（v4.10 起）：类名全由 build_scenario_block
        # 写死、列对齐属有意设计（首列左、数据列右），多数决/长文剥类不再介入——
        # 否则触发条件行长文本会被 _is_prose_cell 剥回左对齐（工行报告对齐不一致实证）
        if tbl_attrs_m and {"matrix-table", "scenario-table"} & _classes_of(tbl_attrs_m.group(1)):
            out.append(tbl)
            pos = tm.end()
            continue
        # 收集每列的对齐类（td 数据格：有类按类投票，裸格按内容投票；rowspan 合并格需补偿列位，
        # colspan 格不计票）
        col_votes = {}
        col_prose = set()  # 列内含说明文格（_is_prose_cell）→ 整列判左，见下方列决策
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
                    if _is_prose_cell(inner):
                        col_prose.add(col)
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
            # v4.10.3：列内含说明文格（带句读的长文 / 剥括号后超 4 字纯文字；短占位格不翻列）→
            # 整列判左。原先只靠格级 _is_prose_cell 事后剥类，数字多数决仍判 num → 同列
            # 「数字右、长文左」锯齿；整列让位给左后，格级剥类路径不再可达（见下方 td 分支注释）。
            if i in col_prose:
                decided[i] = None
                continue
            num_n, cen_n, left_n = votes.count("num"), votes.count("center"), votes.count("left")
            # v4.10 平票判左：文本为主的表（8 章预期差对照表等）原规则在平票时判 num，
            # 同列出现「数字右、文字左」锯齿（工行 09-11 净息差判断行对齐混乱实证）——
            # 文字格右对齐比数字格左对齐更难看，平局一律让位给左
            if left_n and left_n >= num_n and left_n >= cen_n:
                decided[i] = None  # 文字列（内容投票多数或平票）→ 左对齐
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
                    # td 对齐统一（num 列）：v4.10.3 起「含 prose 格」的列已在决策层整列判左
                    # （col_prose），故到达本分支的 num 列必无 prose 格——原格级 _is_prose_cell
                    # 剥类分支成为不可达代码，已删；数字、含数字短值、≤4 字短标记（"基础""12个月"）
                    # 一律随列 num 右对齐
                    if colspan == 1 and decided.get(col) == "num":
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
