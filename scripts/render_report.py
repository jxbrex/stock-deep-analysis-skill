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

# ---------- 子模块导入与再导出（v4.8.3 重构：单文件 → scoring/charts_*/validate） ----------
# 本模块实际使用的符号直接从真身模块导入（删除 charts.py 兼容壳后不再经壳中转）。
# 依赖方向单向：scoring（共享基座）← charts_base / 各图族模块 / validate ← 本模块，无循环。
from scoring import (
    REQUIRED_SCALAR, valuation_badge_class,
    _esc, compute_scores,
    build_score_summary, build_valuation_process_card, build_position_card,
    _quality_verdict, _valuation_verdict,
    compute_valuation, compute_valuation_score,
)
from charts_base import _fmt_px, _prev_track_rows
from charts_scenario import (
    build_scenario_spectrum, build_scenario_block, build_peers_plot,
)
from charts_score import build_score_bars, build_sensitivity_tornado
from charts_l1 import _inject_l1_charts
from charts_cycle import build_pe_band, build_price_history
from charts_misc import (
    build_holders_plot, build_review_dumbbell, _inject_l3_charts, build_triggers_strip,
)
from align_fix import fix_table_alignment, _tag_timing_table
from validate import validate_content


# 渲染器版本：嵌入输出 HTML 尾部注释，事后可 grep 验证报告确由本脚本渲染
# （防"render 报错后手写全文 HTML 绕行"，巨石 2026-08-23 实证）
RENDERER_VERSION = "v4.10.2"

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


def build_prev_strip(prev: dict, quality: float, valuation: float, timing, target_range: str) -> str:
    """回测模式的 Hero 对比条：基于上版日期 + 质量分/估值分/时机分/目标价 旧→新。
    分数差值脚本计算，模型只在 prev 里给上版锚点数据。prev 为空 → 返回空串（非回测模式）。
    旧版 prev 键 research 自动映射到 quality（兼容旧回测数据）。
    v4.10.2 自 validate.py 归位（Hero 片段构建，与 build_toc 同区）。"""
    if not prev:
        return ""
    items = []
    for r in _prev_track_rows(prev, quality, valuation, timing):
        # v4.9：分数差是评价语义（升=好），用 good/bad 而非 up/down（后者 v4.9 起为股价方向色）
        cls = "good" if r["d"] >= 0 else "bad"
        items.append(f'{r["label"]} {r["old"]:.2f}→{r["new"]:.2f} <span class="{cls}">({r["d"]:+.2f})</span>')
    if prev.get("target_range"):
        items.append(f'目标价 {_esc(str(prev["target_range"]))} → {_esc(str(target_range))}')
    body = ' ｜ '.join(items)
    return (f'<div class="prev-strip"><span class="prev-tag">复盘更新</span>'
            f'基于 {_esc(str(prev.get("date", "?")))} 版' + (f' ｜ {body}' if body else '') + '</div>')


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


def _check_l4_order(l4_html: str) -> None:
    """黄灯四类须固定 a→b→c→d 顺序（SKILL.md L4 规范）；检出乱序则告警，由模型修正后重渲。
    不做自动重排——四类内容块结构多变（有/无命中、合并段落），程序重排太脆。
    v4.10：除 `<strong>(a` 行内形态外，同时识别扣分表形态 `<td>a 交易与股东行为</td>`
    （工行报告用表格绕过了原正则；v4.10 起表格为唯一正典，行内形态仅作单条引用）。
    v4.10.2 自 validate.py 归位（render 单点调用，非 validate_content 管线成员）。"""
    seq = [a or b for a, b in re.findall(
        r"<strong>\s*[（(]?\s*([abcd])\s*[)）]?|<td>\s*([abcd])[\s　]", l4_html or "")]
    if seq and seq != sorted(seq):
        print(f"⚠️ L4 黄灯扣分四类顺序应为 a→b→c→d，当前为 {'→'.join(seq)}；"
              f"请调整 l4_html 顺序后重新渲染", file=sys.stderr)


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
    # v4.9.1：旧触发条件核对表（backtest.md 老规则的手写四列表）废止，核对结果改由 triggers 状态条承载
    if prev and not fill.get("triggers"):
        print("⚠️ 回测模式（prev 已填）但 triggers 未填：旧触发条件核对结果应由 triggers 状态条承载"
              "（status=hit/miss/pending，metric 行写「阈值｜实际值」；v4.9.1 起 dash_html 不再手写旧核对表）",
              file=sys.stderr)
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
        # 目标价区间以脚本计算为准（消灭模型手写与 05 表不一致的可能）；
        # v4.10 起经 _fmt_px 展示（低价股两位小数，工行「8-8」假无区间实证）
        computed_tr = f"{_fmt_px(calc['base_lo'])}-{_fmt_px(calc['base_hi'])}"
        if target_range != "—":
            # 模型按精确值（如 25.2-27.5）填写时经同一 helper 格式化再比较，避免对正确填法误告警
            _tr_nums = re.findall(r"\d+\.?\d*", target_range)
            _tr_same = (len(_tr_nums) >= 2
                        and f"{_fmt_px(float(_tr_nums[0]))}-{_fmt_px(float(_tr_nums[1]))}" == computed_tr)
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
        # v4.9：触发条件状态条（triggers 可选字段，脚本生成，垫在手写仪表盘前）
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
        "QUALITY_WORD": _quality_verdict(quality),
        # 估值分（独立价格轨；徽章四档：≥8 绿 / 6-7.9 蓝 / 4-5.9 橙 / <4 红）
        "VALUATION_SCORE": f"{valuation:.1f}",
        "VALUATION_WORD": _valuation_verdict(valuation),
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


def _archive_artifacts(fill: dict, fill_path: str, out_path: str, date: str,
                       quality: float, valuation: float, timing, target_range: str,
                       red_flag: str, backtest: bool) -> None:
    """渲染成功后的归档（v4.10 B-min 归档库）：fill 与 E1 防伪落盘移入报告目录 `_archive/`，
    并往 `_archive/_index.jsonl` 追加一行索引（跨报告对比/评分校准的数据源）。
    只动 `_fill_`/`_em_` 前缀的会话临时文件（测试 fixture 与存量文件不误移）；
    防伪链在 validate 阶段已消费 quote 落盘，渲染成功后移动不断链；
    归档任何失败降级为告警，绝不让已成功的渲染报错。"""
    try:
        arch_dir = os.path.join(os.path.dirname(os.path.abspath(out_path)), "_archive")
        os.makedirs(arch_dir, exist_ok=True)
        company_s = _safe_filename(fill.get("company", "未命名"))
        code_s = _safe_filename(fill.get("code", "无代码"))
        date_s = _safe_filename(date)
        moved = []
        if os.path.basename(fill_path).startswith("_fill_") and os.path.exists(fill_path):
            dst = os.path.join(arch_dir, f"fill_{company_s}_{code_s}_{date_s}.json")
            os.replace(fill_path, dst)
            moved.append(os.path.basename(dst))
        qsf = (fill.get("quote") or {}).get("source_file") or ""
        if os.path.basename(qsf).startswith("_em_") and os.path.exists(qsf):
            dst = os.path.join(arch_dir, f"em_{code_s}_quote_{date_s}.json")
            os.replace(qsf, dst)
            moved.append(os.path.basename(dst))
        row = {
            "date": date, "company": fill.get("company"), "code": fill.get("code"),
            "html": os.path.basename(out_path), "quality": quality, "valuation": valuation,
            "timing": timing, "price": fill.get("price"), "currency": fill.get("currency") or "元",
            "target_range": target_range, "red_flag": red_flag or "", "backtest": backtest,
            "renderer": RENDERER_VERSION,
        }
        with open(os.path.join(arch_dir, "_index.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"归档 → {arch_dir}" + (f"（{'、'.join(moved)} + _index.jsonl）" if moved else "（_index.jsonl）"))
    except OSError as e:
        print(f"⚠️ 归档失败（报告本身已完成，不受影响）: {e}", file=sys.stderr)


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
        print(f"⚠️ 以下章节片段为空（如非故意请检查 fill JSON）: {empty}", file=sys.stderr)


def _preflight(fill_path: str):
    """--check 与 render 共用的预检单流水线（v4.10.2 合并双流水线，消除手工同步漂移：
    check 曾漏 company/code 必填校验、校验顺序与 render 不同、估值错误消息第三份拷贝）。
    解析 → 必填标量 → L4 顺序告警 → 估值计算 → 内容校验 → 评分计算 → 估值分可计算检查。
    通过返回 (fill, calc, sc, valuation, valuation_calc)；任何一步不过抛 ValueError。"""
    fill = _load_fill(fill_path)
    _check_required_scalars(fill)
    _check_l4_order(fill.get("l4_html", ""))
    # 估值计算（valuation 字段存在时，目标价/中枢/赔率/离散度全部脚本算）
    calc = compute_valuation(fill)
    validate_content(fill, calc)
    sc = compute_scores(fill)
    valuation, valuation_calc = _apply_valuation_score(fill, calc, sc["valuation"])
    return fill, calc, sc, valuation, valuation_calc


def render(fill_path: str, out_path: str = None) -> str:
    fill, calc, sc, valuation, valuation_calc = _preflight(fill_path)
    cur = str(fill.get("currency") or "元")  # 币种单位（默认「元」，港股 fill 填 currency="港元"）

    # 图形组件（脚本生成 SVG；数据缺省时为空串 → 模板条件块整块删除）
    spectrum_html = build_scenario_spectrum(fill, calc)
    scenario_block_html = build_scenario_block(calc, cur)
    peers_plot_html = build_peers_plot(fill)
    peers_html = _clean_peers_matrix(fill, peers_plot_html)

    layer_scores = sc["layer_scores"]
    pre_risk = sc["pre_risk_quality"]
    yellow_total = sc["yellow_total"]
    quality = sc["quality"]
    timing = sc["timing"]
    red_flag = sc["red_flag"]

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
    _archive_artifacts(fill, fill_path, out_path, date, quality, valuation, timing,
                       target_range, red_flag, backtest=bool(prev))
    return out_path


def check_fill(fill_path: str) -> None:
    """--check 模式：与 render 同一 _preflight 流水线（解析 + 评分/估值计算 + 内容校验），不渲染。
    替代手写 python -c json.load 自检（Windows 控制台引号/编码/路径反斜杠坑，
    中兴 2026-08-24 实证）。退出码：0=通过可渲染，2=存在拒渲染项。"""
    try:
        fill, _calc, _sc, _valuation, _vc = _preflight(fill_path)
    except ValueError as e:
        print(f"✗ 预检未通过（渲染将被拒绝）：\n  {e}", file=sys.stderr)
        sys.exit(2)
    print(f"OK JSON 可解析，共 {len(fill)} 个顶层键；内容预检通过，可执行渲染")


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
