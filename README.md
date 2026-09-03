# stock-deep-analysis — 个股深度分析技能

基于「质量 × 估值 × 时机」三轨评分框架的个股深度分析技能（Kimi Code / ZCode 通用）。
一键取数、脚本拼装，产出单文件自包含 HTML 研究报告。

> ⚠️ 本技能产出的报告为 AI 生成的研究笔记，不构成投资建议。

## 整体逻辑

### 三轨评分：不是一个混合分，而是三个各司其职的分

| 轨 | 回答什么 | 决策作用 |
|----|---------|---------|
| **质量分** | 这家公司值不值得长期拥有 | 能不能买（资格） |
| **估值分** | 现在这个价格贵不贵 | 买多少 / 等不等 |
| **时机分** | 市场情绪与筹码状态 | ±1 档微调，不跨「买/不买」门槛 |

决策主轴 = 质量分 × 估值分。「好公司太贵」的正确结论是「等」，不是扣质量分——
估值分永远不进质量分。风险层（红/黄灯）不占权重：红灯直接熔断，黄灯从质量分往下扣。

### 分型定尺子

不用一套尺子量所有股票。六型分类（周期 / 稳定价值金融 / 稳健成长 / 快速成长 /
未盈利管线 / 困境反转）决定层权重与估值方法；金融、创新药、开发型地产、平台互联网
另有行业附录（红旗清单、体检表、估值主锚全套替换）。

### fill → render 工作流（核心设计）

模型只做两件事：分析、把分析写成一个 fill JSON。其余全部由脚本完成：
评分计算、徽章配色、SVG 图形（目标价走廊 / 估值-质量散点图）、内容地板校验
（不达标拒渲染）、文件自动命名。拼装环节模型 token 开销为零，且报告里的每个数字
都可复算、可校验——文件名里的分数就是脚本算出来的分数。

## 使用办法

### 安装

将 `stock-deep-analysis/` 目录放入技能目录：

- 用户级：`~/.agents/skills/` 或 `~/.zcode/skills/`
- 项目级：`<project>/.agents/skills/`

依赖：Python 3.8+、curl（Windows 10+ 自带）。tushare token 可选
（`TUSHARE_TOKEN` 环境变量自动发现；无 token 自动走东方财富公开接口）。

### 触发

对模型说「深度分析 600989」「给腾讯写一份研究报告」即可。首次分析走全流程；
同股再分析自动进入回测模式（见下）。

### 工作流四步

```bash
# 1. 一键取数（tushare 优先、东财兜底；A 股 6 位代码、港股 5 位代码自动识别）
python "<技能目录>/scripts/em_fetch.py" 600989 --peers=600309,002001

# 2-3. 模型分析打分（评分锚 references/scoring.md）→ 写 fill JSON（契约 references/fill-schema.md）

# 4. 渲染（评分/图形/校验/命名全由脚本完成；--check 为只预检不渲染）
python "<技能目录>/scripts/render_report.py" "_fill_600989.json"
```

### 回测模式（同股再分析）

```bash
python "<技能目录>/scripts/extract_review.py" --find 600989
```

脚本扫描工作目录：文件名匹配 + 渲染器生成标记验证 + 取日期最新——找到旧报告即进入
回测模式（先独立取数打分、再读旧报告、全量重写、最后新旧对比），并直接输出 prev
锚点与旧三情景假设。手写绕行的 HTML 无生成标记，不会误触发。

### 报告结构

固定 13 章：1 核心结论 ｜ 2 关键利润驱动 ｜ 3 公司本质 ｜ 4 未来预期 ｜ 5 风险评估（红/黄灯）｜
6 质量分汇总（脚本生成）｜ 7 估值与安全边际 ｜ 8 市场预期差 ｜ 9 同业横向对比 ｜
10 周期规律（条件） ｜ 11 仓位与时机决策 ｜ 12 回测复盘（条件） ｜ 13 跟踪仪表盘。

## 目录结构

```
stock-deep-analysis/
├── SKILL.md                    # 技能入口：工作流骨架 + 硬规则 + 分型表 + 参考文件索引
├── CHANGELOG.md                # 规则典故档案（每条规则的事故来历）+ 版本历史
├── references/
│   ├── data-collection.md      # 采集流程与纪律（Phase 1 唯一权威，采集前必读）
│   ├── data-sources.md         # 东财 API 端点手册 + 港股矩阵 + 429 规则
│   ├── scoring.md              # 评分与估值细则：三轨/红旗/治理/红黄灯/估值方法/基准率（评分+估值章必读）
│   ├── backtest.md             # 复盘校准与回测模式（回测必读）
│   ├── fill-schema.md          # fill→render JSON 契约 + HTML 骨架（报告结构唯一权威）
│   ├── forensic-accounting.md  # 财报质量核查（应计/M-Score/评级）
│   ├── industry-financials.md  # 银行/保险/券商口径（金融股必读）
│   ├── industry-pharma.md      # 创新药/管线股口径：rNPV 估值（医药管线股必读）
│   ├── industry-realestate.md  # 开发型地产口径：NAV 估值（地产股必读）
│   └── industry-internet.md    # 平台型互联网口径：SOTP 估值（平台互联网必读）
├── scripts/
│   ├── em_fetch.py             # 一键取数（A股/港股，tushare 优先 + 东财兜底，429 硬停）
│   ├── render_report.py        # fill JSON → 最终 HTML（评分计算+图形生成+校验+自动命名）
│   ├── extract_review.py       # 回测触发判定（--find）+ 旧报告复盘锚点提取
│   ├── test_render_core.py     # render_report 核心评分/落位回归测试
│   ├── test_em_fetch.py        # em_fetch 取数链路回归测试
│   ├── test_extract_review.py  # extract_review 回测触发/锚点提取回归测试
│   └── test_mcap_mode.py       # render_report 市值口径（mcap/metric_label）冒烟自检
└── assets/
    └── report-template.html    # 报告模板（唯一 CSS 权威版本）
```

## 测试与自检

`scripts/` 下四个测试文件全部离线可跑（无网络依赖）：

```bash
cd scripts
python test_render_core.py      # 决策矩阵落位 / 三情景取数 / 硬校验 / 币种
python test_em_fetch.py         # 市场映射 / 闰日 / 同比文字化 / 429 硬停
python test_extract_review.py   # 回测触发判定 / 锚点提取
python test_mcap_mode.py        # 市值口径渲染
```

## 版本历史

见 `CHANGELOG.md` 末尾「版本历史」节。

## 免责声明

本技能及产出的所有报告仅供个人研究学习使用，不构成任何投资建议。
数据来自公开接口，可能存在延迟、缺失或错误；投资决策请以官方披露为准。
