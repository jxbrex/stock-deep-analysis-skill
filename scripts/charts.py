#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""charts.py — SVG 图表构建器兼容壳（v4.10 按图族拆分）

历史：v4.8.2 单文件 1347 行超审计线；v4.10 按图族拆为六个扁平兄弟模块（不建包目录）：
  - charts_base.py      色板常量 + 数值/格式/几何工具 + SVG 骨架 helper + _SCENARIO_*
  - charts_scenario.py  05 目标价走廊 / 三情景表+三指标卡 / 07 估值-质量散点图
  - charts_score.py     06 评分分布横条 / 02 敏感性龙卷风
  - charts_l1.py        3.1 业务构成 / 3.2 产业链 / 3.4 财务趋势图墙 + _inject_l1_charts
  - charts_cycle.py     10 章 PE 历史带 / 股价·PE 历史发丝图
  - charts_misc.py      4.1 利润增长图 + _inject_l3_charts / 11 户数趋势 / 12 回测哑铃
本文件是兼容壳：逐名 re-export 全部历史公开符号（含 _C_* 常量与 build_* 函数），
render_report/validate/测试的 `from charts import X` 与 `R.build_*` 访问一行不改。
依赖方向不变：scoring ← charts_base ← 各图族模块 ← 本壳。
"""
# 历史符号面兜底：原 charts.py 顶层 from scoring import 的同款再导出
from scoring import (DIMS, LAYER_NAMES, badge_class, _dim_verdict,  # noqa: F401
                     _num, _fmt, _esc)
from charts_base import (  # noqa: F401（再导出）
    _C_LABEL, _C_GRID, _C_AXIS, _C_BLUE, _C_PAPER, _C_INK, _C_BLACK, _C_STONE,
    _C_OLIVE, _C_SAND, _C_SAND_LT, _C_TRACK, _C_GOOD_LINE, _C_YEAR_GRID,
    _C_GREEN, _C_RED, _C_ORANGE,
    _fmt_price, _fmt_amt, _SCENARIO_COLORS, _SCENARIO_NAMES,
    _pad_domain, _lin_map, _text_w, _wrap_label, _ticks,
    _SVG_STYLE, _svg_open, _svg_close, _vgrid_ticks, _anchor_fit, _anchor_clamp,
)
from charts_scenario import (  # noqa: F401（再导出）
    build_scenario_spectrum, build_scenario_block, build_peers_plot,
)
from charts_score import (  # noqa: F401（再导出）
    build_score_bars, build_sensitivity_tornado,
)
from charts_l1 import (  # noqa: F401（再导出）
    build_segments_plot, build_chain_plot, build_fin_trend, _inject_l1_charts,
)
from charts_cycle import (  # noqa: F401（再导出）
    build_pe_band, build_price_history,
)
from charts_misc import (  # noqa: F401（再导出）
    build_growth_plot, build_holders_plot, build_review_dumbbell, _inject_l3_charts,
    build_triggers_strip,
)
