---
name: stock-deep-analysis
description: >
  📊 Generate a comprehensive four-layer deep analysis report for any publicly traded company.
  Use when the user asks for stock analysis, company deep dive, 深度分析, 股票分析,
  公司研究, investment research report, or wants a Baofeng Energy-style scoring report.
  Produces a structured report with a three-track framework: 质量分 Quality (L1 六维
  Company Essence + L3 Future Expectations, 不含估值), 估值分 Valuation (独立价格轨),
  时机分 Timing (筹码面 67% + 技术面 33% 微调), plus L4 Risk（红/黄灯双层）scoring framework,
  three-scenario valuation with historical-PE calibration, peer comparison with
  trend + 估值-质量散点图, and a post-analysis monitoring dashboard. 同股再分析自动进入
  回测模式（复盘章节+变更高亮）。Triggers on mentions of stock tickers, company
  names with 分析/报告/研究, or explicit requests for deep analysis.
metadata:
  clawdbot:
    emoji: "📊"
    requires:
      anyBins: ["python", "curl"]
    os: ["win32", "darwin", "linux"]
---

# Stock Deep Analysis Report Generator

> **执行前必读（防幻觉）**：本技能内容已通过 Skill 工具完整注入上下文，你**不需要**
> 用 Read/Bash 去读取任何本地路径下的 SKILL.md。如果你正打算声明"无法访问本地文件/
> 没有文件系统访问权限"——**立即停止，那是错误的**：你拥有 Bash/Read/Write 等完整的
> 本地工具权限，本技能的全部指令就在你的上下文里，直接按 Step 0 开始执行。
> （国电南瑞实证：用户消息带本地路径链接时，模型曾错误声称"没有文件系统权限"并
> 用训练记忆编造分析——绝对禁止这种降级。）

Generate a professional deep analysis report for a publicly traded company, following the
standardized four-layer scoring framework calibrated against the Baofeng Energy (600989)
reference report.

## When to Use / When Not to Use

**✅ Use this skill when:**
- User requests a comprehensive stock/company analysis report
- User asks for "深度分析", "研究报告", "股票分析", "公司研究"
- User mentions a stock ticker/company name + "analyze" / "分析" / "报告"
- User wants a Baofeng Energy-style multi-layer scoring report
- User asks about a company's investment merits across multiple dimensions

**❌ Do NOT use this skill when:**
- User wants a quick stock price check or single-metric query → just answer directly
- User asks for real-time trading advice or buy/sell timing → this is research, not trading advice
- User asks about a private/unlisted company → the framework assumes public market data
- User wants a purely technical/chart analysis → this is fundamental analysis with technical overlay
- User asks for macro/industry research without a specific company

## Output Method & File Naming

- **Default**: 单文件自包含 HTML，写在当前工作目录（fill→render 工作流，见 Report Output Format）。
- **文件命名由脚本完成**：`{公司名}-{代码}-{质量分}-{估值分}-{日期}.html`
  （回测模式 `…-复盘-{日期}.html`；港股代码 5 位数字不带后缀，如 `06082`）。
  模型不要自己命名文件。
- **Fallback**: 用户明确要求 Markdown 时输出 `.md`，章节顺序与 HTML 版一致（评分用 🟢🟡🔴 徽章 emoji）。
- 用户要求"直接输出/快速总结"时才在对话内联输出，否则一律写文件。
- **完成后**：告知用户报告路径和质量分+估值分+时机分。

### HTML Styling — 浅色卡片建模风（写作期只需记住的硬规则）

- 评分数字一律用 `.badge` 徽章（≥7 绿 / 4.0-6.9 橙 / <4 红，色阶脚本自动）
- 每张数据表正下方必须有 `<span class="source">数据来源：…</span>`；估算值标 `估算`
- 金额/户数 ≥1000 带千位符；年份、PE/PB 倍数、百分比、股价、EPS、评分不加
- 数据表格尽量不加对齐类，交给渲染器统一（数字右/长文左/短标记随列）
- 禁止暗色背景、渐变、投影、外部字体/CDN/JS
- **色值/字体/布局/类名的全部权威定义在 `assets/report-template.html` + `references/fill-schema.md`，
  模型从不手写 CSS，也不许 Read 模板"学习结构"——写 fragment 需要的类名与骨架见 fill-schema.md**

---

## Workflow

### Step 0: 确认标的与口径

- 确认**公司名 + 代码 + 上市地**（A股 6 位 / 港股 5 位数字）；模糊或多地上市先一句话确认。
- 确认输出格式：默认单文件 HTML；用户明确要 Markdown 才输出 `.md`。
- 同股再分析自动进回测模式（见 Phase 6.5/6.6，读 `references/backtest.md`）。

### Phase 0: Identify Critical Profit Drivers (MANDATORY — before any scenario modeling)

先识别对利润弹性最大的 **1-2 个变量**（商品价/量/产能利用率/汇率/政策……），估
"X 变 10% → 利润约变 Y%"，选弹性最大的 1-2 个。敏感性表（含 ★弹性等级）写进报告 P0 卡。
**三情景必须围绕这 1-2 个驱动定义，而不是拍利润区间。**

### Phase 0.5: Stock Classification (MANDATORY — 分型决定尺子)

**不要用一套尺子量所有股票。** 完成 Phase 0 后、Phase 1 深度调研前，必须给股票分型。
分型结果决定：各层权重、估值方法、决定性维度。报告 P0 卡片必须声明分型及理由。

| 类型 | 识别特征 | 质量分内 L1:L3 占比 | 估值方法（估值轨） | 决定性维度 |
|------|---------|---------|---------|-----------|
| **周期股** | 利润随商品价格/产能周期大幅波动（化工、航运、养殖、煤炭、有色、钢铁、半导体、面板） | 70:30（默认） | PE 历史时段匹配法；估值轨与黄灯 b/c 是胜负手 | 估值分、黄灯 b/c、周期位置 |
| **稳定价值/金融** | 盈利稳定、高分红、杠杆经营（银行、保险、公用事业、高速公路） | **85:15**（增长不重要） | **PB-ROE 框架**（银行/保险）；DDM（高股息公用事业，税后股息）。PE 仅作辅助 | 1D 资产质量、1E 治理、1F 分红可持续性 |
| **稳健成长股** | 利润增速 10-25%、可预测性强（消费、医药白马、制造业龙头） | 70:30（默认） | PE 匹配 + DCF（满足 FCF 条件）+ PEG 辅助 | 1C 护城河、3A 增长持续性、1F 资本回报 |
| **快速成长股** | 利润增速 >25%，利润基数尚小 | 60:40（增长进质量分，买点容忍度高） | PEG、远期 PE 折现、终局市值反推 | 3A 增速、1A 赛道天花板、黄灯 c 增长持续性 |
| **未盈利/管线股** | 当期亏损或利润无意义（创新药、早期科技） | 75:25 | **rNPV**（管线×成功概率×峰值销售）、P/S、EV/毛利。**禁用 PE 匹配**（创新药管线五件套见 `industry-pharma.md`） | 1A 赛道、1C 技术壁垒、现金消耗速率 |
| **困境反转** | 财务指标全面恶化但存在反转催化剂 | 70:30 | 正常化利润 PE、重置成本、清算价值对照 | 3B/3C 反转催化剂、红灯 a 生存风险（现金流能否撑到反转） |

**L1 六维权重（层内）按分型浮动，详见 `references/scoring.md`**——决定性维度上浮、噪音维度下沉，
不再等权。金融子类（银行/保险/券商）另见 `references/industry-financials.md`；创新药管线、
开发型地产、多元平台互联网分别另见 `references/industry-pharma.md`、`references/industry-realestate.md`、
`references/industry-internet.md`（触发条件以各附录开头声明为准）。

**分型规则：**
- 一只股票只归一个主类型；跨界时选"利润结构主导"的类型（如银行+成长 → 稳定价值）
- 分型必须在报告中写明理由（一句话，引用识别特征）
- 非周期股 → Phase 5 周期分析自动跳过（除非同时满足触发条件）
- 困境反转型豁免红灯财务类（连续亏损/ST 属前提），但造假/立案/退市风险不豁免；
  必须在核心结论中明示"本报告为困境反转框架，财务恶化是前提而非否决项"

### Phase 1: Research (MANDATORY — do NOT skip)

**采集前必读 `references/data-collection.md`（硬门禁——未完成读取并应用，不得进入下一 Phase）**——脚本命令（em_fetch.py 用技能目录绝对路径执行）、
环境工具探测、定性搜索纪律、审计意见必查、卖方深挖、委派模板、Research Checklist 全部在那里。
端点/字段/港股矩阵/429 规则在 `references/data-sources.md`（需要手工 curl 时再读）。

取数优先级：**em_fetch.py（首选，一条命令）→ 妙想 MCP 直调 → 手工 curl → 定性搜索**。
**条件强制委派（MANDATORY）**：同业 peer **≥3 只**的 `--peers` 批量取数、公告 PDF 下载提表
**必须委派子智能体**（回传结构化原文数据，主会话只核对来源；委派模板与工具限制逐字见
data-collection.md Step 1.3）；peer <3 只时主会话直接跑，不必委派。
目标公司本体取数与定性调研一律主会话完成，禁止委派子代理做定性。

**工具检查硬门禁（开始取数前执行）**：检查工具列表是否含 `mcp__mx-ds-mcp-stdio__mx_*`（妙想 MCP）。
缺席 → 定性检索/筹码分布/行业估值水位走降级链（见 data-collection.md），且**必须在报告显式标注
「妙想 MCP 缺席，已走降级路径」**——禁止静默跳过（缺席未标注 = 违反降级纪律，见文末「数据降级与反幻觉」）。

### Phase 2: Score Each Dimension

**评分章必读 `references/scoring.md`（硬门禁——未完成读取并应用，不得进入下一 Phase）**——三轨定义、L1 六维权重矩阵（分型浮动）、1D 盈利质量
红旗清单、1F 资本回报质量、估值分推导、时机分微调、红/黄灯扣分细则、损失预演全部在那里。这里只留骨架：

- **三轨**：质量分（L1 六维 + L3，不含估值）/ 估值分（独立，脚本按 `valuation_inputs` 四件套强制计算，无手填路径）/ 时机分（筹码 67% + 技术 33%，微调）
- **决策主轴 = 质量分 × 估值分**；时机分 ±1 档微调，不跨「买/不买」门槛；估值分不进质量分
- **评分原则**：基于证据不基于印象；每个 ≥7 或 ≤3 的分数给具体量化依据；不预校准区间
- **1D 先过红旗清单再评分**（利润是不是真钱，比利润多不多更重要）；财报可信度评级引用
  `references/forensic-accounting.md` 口径；金融股红旗清单替换见 `industry-financials.md`
- **分型决定权重与估值方法**（见 Phase 0.5），报告里必须声明分型与层占比

### Phase 3: Build Valuation Model

**估值章必读 `references/valuation.md`（硬门禁——未完成读取并应用，不得进入下一 Phase）**——三情景构建、PE 历史时段匹配校准、三指标提取
（中枢期望收益/赔率/离散度）、DCF 条件触发、市场预期差三档拆解全部在那里。
关键假设标 base rate 分位（先读 `references/base-rates.md`，同为硬门禁）。

一句话骨架：三情景由 Phase 0 的 1-2 个关键驱动定义；估值分由脚本按 `valuation_inputs` 四件套
（中枢×40% + 赔率×25% + 合理倍数×25% + 股息×10%）强制计算，模型只填输入不手算；
预期差必须拆到具体假设层面（无预期差 = 无超额收益）。

### Phase 4: Build Peer Comparison

- 当前指标表 + 3 年趋势表（方向用文字升/降/缓升/缓降，**不用箭头**）
- **估值-质量散点图**：填顶层 `peers_plot` 字段（脚本生成 SVG 直角坐标系，目标公司高亮）；
  同业数据不全才在 `peers_html` 手写 `.matrix-table` 九宫格兜底，两者二选一
- `.conclusion-box` 3-5 条结论；点名象限内位置差异（同为"高ROE·中PE"，贴左缘与贴右缘性价比完全不同）

### Phase 5: Historical Cycle Analysis（条件触发）

满足任一才执行，否则跳过：① 过去5年 PE(TTM) 波动幅度 >50%；② 归母净利出现过 ≥2 次
连续2个季度以上下滑、之后又恢复；③ 行业为大宗商品/化工/航运/养殖/半导体/面板/钢铁/煤炭/有色。
非周期股（Phase 0.5）默认跳过。
执行：阶段拆解（日期区间/股价范围/PE范围/驱动因素）+ 当前位置判断 + 提取 3-5 条可复用规律。

### Phase 6: Monitoring Dashboard（MANDATORY）

#### 6.1-6.3 跟踪仪表盘

- 关键跟踪指标表（指标/当前值/关注原因/数据来源/更新频率）+ 触发条件表（条件/阈值/触发后操作）+ 下次审查日期
- **预测登记纪律**：每条核心预测必须带基准值、区间/方向、验证日期、先行指标、失效条件；
  禁止"长期向好"类无法判定的句子。命中状态只用 命中/部分命中/未命中/无法验证（无法验证必须解释）

#### 6.4 仓位与时机决策（质量分 × 估值分为主轴，时机分微调）

质量分（L1+L3−黄灯扣分）定"入池资格"；估值分（脚本按四件套强制计算）定"买多少/等不等"；时机分
（筹码 67% + 技术 33%）只做 ±1 档微调。**先过红灯**：命中红灯 → 不建议参与，无论质量分多高。

**决策矩阵全表（9 行）只在 `references/scoring.md`，报告中不再出现**——报告第 11 章只显示落位与结论，
顺序固定为：① 模型先写时机判定小表（给时机分）→ ② 脚本生成「三轨判定与仓位结论」卡
（三轨判词小卡 + 只列触发项的调节轨迹 + 最终仓位徽章）。

**调节规则（MANDATORY，固定优先级）**：红灯熔断 > 中枢为负拦截器 > 矩阵落位 > 时机分调节
（≥6 上浮一档 / <4 下调一档）> 离散度（>90% 下调一档 / <40% 上浮一档）> 赔率 ∞ 上浮一档。
**档位序列：0（不建议参与）/ 5（轻仓）/ 10（标准仓）/ 20（重仓）**——上浮一档（20% 硬顶）、
下调一档（0 兜底）；观察池不因时机/赔率上浮升为买入。**估值轨拦截器**：中枢期望收益为负
（基础中值<现价）→ 无论质量分，仓位直接"回避当前价格/等"。
**矩阵落位、调节轨迹、最终仓位结论全部由脚本生成**，模型不手写判词。

#### 6.5-6.6 复盘校准与回测模式

**回测模式必读 `references/backtest.md`（硬门禁——未完成读取并应用，不得开始写回测 fill）**——复盘四格表、分开复盘纪律、归因纪律、偏差档案、
回测触发与输出差异全部在那里。触发：工作目录已存在同代码旧报告 → 自动进入回测模式
（先独立取数打分 → 再读旧报告 → 全量重写 → 最后新旧对比）。复盘内容只进 R 章节，
**禁止生成独立 `_复盘.md` 文件**。

### Phase 7: Assemble the Final Report

**⚠️ 红灯熔断检查（输出报告前执行，对应第 5 章红灯层）：**

```
if 命中红灯项（财务造假/ST/立案调查/主营不可逆衰退/审计非标）:
    → 核心结论段开头必须加此警告：
    "🔴 命中红灯风险（[具体项]），触发直接回避，不建议以投资为目的持有。
       以下报告仍完整呈现分析过程，供研究和学习参考。"
    → 仓位与时机决策自动归入"不建议参与"
    → 报告其余部分正常输出，不隐藏分析内容

例外：Phase 0.5 分型为「困境反转」的股票豁免红灯 a 类中的"连续亏损/ST"项
（财务恶化是其前提而非缺陷），但造假/立案/退市风险不豁免；
改为在核心结论中明示"本报告为困境反转框架，财务恶化是前提而非否决项"。
```

---

## Report Output Format（fill→render 工作流）

**结构骨架/字段契约/HTML 类名/评分计算规则的唯一权威：`references/fill-schema.md`——
写 fragment 前必读（硬门禁——未完成读取并应用，不得开始写 fill JSON），禁止 Read 模板"学习结构"。**

1. **写 fill-data JSON**：把全部分析内容写成一个 `_fill_[代码].json`（下划线前缀=临时文件）。
   字段契约见 fill-schema.md。分析和文字照常由你生成——脚本只做拼装。
   **写盘方式硬规则**：fill JSON 一律用 **Write 工具直接写盘**——禁止用 python/bash/heredoc
   拼接生成 JSON（Windows 下必踩 GBK 编码/引号转义/大文本截断坑，恒瑞/中免/阿里"卡住"与
   赢合/东方财富 Python 报错均源于此）。唯一的 Python 调用是渲染命令本身。
   **分段写盘（防网关超时）**：fill JSON 预计超 ~8k token 时必须分 2-3 段写——
   Write 写首段，后续用 append 追加，单次响应 ≤8k token。单次超长响应流式输出数分钟，
   极易撞网关 504/连接中断且重试无断点（紫金实证：16.5k token 单次必挂，6.6k 分段一次过）。
2. **渲染**：
   ```bash
   python "<技能目录>/scripts/render_report.py" "_fill_[代码].json"
   ```
   脚本完成：三轨评分×权重计算（质量分 = L1 层分×L1占比 + L3 层分×L3占比 − 黄灯扣分；
   **估值分按 `valuation_inputs` 四件套脚本强制计算，fill 手填值一律被覆盖**；时机分筹码67+技术33）、
   徽章色、三轨判词、决策矩阵落位与「三轨判定与仓位结论」卡、质量分汇总章（第 6 章，只含质量轨明细）、占位符替换、
   内容地板硬校验（不达标拒渲染）、自动命名输出。
   **渲染后检查警告**：若输出含 `⚠️ fill JSON 缺图形字段`（scenarios / peers_plot），
   必须补上字段重新渲染后再交付——缺失时 7 估值章目标价走廊 / 9 同业章散点图会被静默跳过。
3. **完成后**：删除 `_fill_[代码].json` 临时文件，告知用户报告路径和质量分+估值分+时机分。

**为什么不用 Edit 写 HTML**：每次 Edit 都要重发整个会话上下文（国电南瑞 18 次 Edit 消耗
2.2M input token，占全程 73%）。fill→render 把拼装环节的模型开销降为**零**——你只需输出
一次 ~10-15k token 的 JSON，脚本零 token 完成拼装。

**禁止事项**：Edit 逐段改 HTML；单次 Write 全文 HTML；**渲染报错后手写全文 HTML 绕行**（报错信息已指明
缺什么——修 fill 重渲是唯一合法路径，巨石 2026-08-23 绕行实证）；Read 模板学结构；
手算质量分/估值分/时机分/层分（脚本算，手算易错；文件名里的分数也来自脚本）。

**评分数据流**：你在 JSON 里填质量层各维原始得分（`scores`：1A-1F/3A-3C）+
估值分输入（`valuation_inputs` 四件套 + `valuation` 结构化三情景，**估值分永远脚本计算，无手填路径**）+
时机层得分（`timing_scores`：筹码面/技术面）+
黄灯扣分明细（`yellow_deductions`）+ 1D 红旗扣分明细（`red_deductions`）+ 红灯标记（`red_flag`）+ 可选权重覆盖
（`weights` 层内权重、`layer_share` 层占比，分型调整时用）。
质量分、估值分、时机分、徽章色、加权列、质量分汇总（第 6 章）、三轨判词与「三轨判定与仓位结论」卡（第 11 章，时机判定小表由模型先写）全部由脚本生成——报告里的数字与文件名一致。

**fill 产出前自检清单（内容地板硬门禁，不达标渲染器直接拒绝、不生成报告）：**

- [ ] `conclusion_html` 四段齐全（关键优势/关键弱点/当前市场认知/核心投资逻辑）且纯文本 ≥200 字
- [ ] `l1_html` 六维 dim-block ≥6 个；`l3_html` 三维 dim-block ≥3 个
- [ ] `peers_html` 含 `<table>`；**每张数据表下方都有 `.source` 标注**（表格数 ≤ source 数）
- [ ] `valuation_inputs` 四键齐全（pe_ttm / pe_band / div_yield / risk_free），均有取数来源或标估算
- [ ] `valuation` 三情景完整（pess/base/opt，每情景 profit + pe 区间 + horizon，horizon 含"年/月"单位；行业附录市值口径用 mcap 区间替代 profit+pe，三情景须同口径）
- [ ] `thesis_html` 三情景价与 `valuation` 一致（与脚本计算中枢价偏差 >2% 且 >0.1 即拒渲染）
- [ ] 黄灯扣分单项 ≤1、累计 ≤2（超出须升红灯）；`red_deductions` 单项 ≤1
- [ ] `position_html` 纯文本 ≥100 字，且只含时机判定小表 + 决策逻辑 info-card + 触发条件（三轨判词/调节轨迹/仓位徽章由脚本生成）；`red_flag` 非空时必须含「不建议参与」
- [ ] 正文引用章节一律用编号/名称（第 3 章 / 3.4 / 第 5 章风险评估）；**禁止 L1/L3/L4/1D 等框架内部代号出现在正文**（只允许在评分表、P0 卡与 fill JSON 字段名里；渲染器检出会告警）

---

## 参考文件（按需加载，主文件只留骨架）

| 文件 | 何时必读 | 章节 |
|------|---------|------|
| `references/data-collection.md` | **采集前必读** | Phase 1 |
| `references/data-sources.md` | 端点字段/港股矩阵/429 细查时 | Phase 1 |
| `references/scoring.md` | **评分章必读** ||
| `references/valuation.md` | **估值章必读** | Phase 3 / 估值分 |
| `references/base-rates.md` | **估值章必读**（外部视角分位） | Phase 3 |
| `references/forensic-accounting.md` | 1D 财报可信度评级时必读 | Phase 2 1D |
| `references/industry-financials.md` | **银行/保险/券商评分与估值时必读** | Phase 0.5 / 2 / 3 |
| `references/industry-pharma.md` | **创新药/管线型医药评分与估值（rNPV）时必读** | Phase 0.5 / 2 / 3 |
| `references/industry-realestate.md` | **开发型地产评分与估值（NAV）时必读** | Phase 0.5 / 2 / 3 |
| `references/industry-internet.md` | **多元平台互联网评分与估值（SOTP）时必读** | Phase 0.5 / 2 / 3 |
| `references/analytical-tips.md` | 评分/估值时按需 | Phase 2/3 |
| `references/backtest.md` | **回测模式必读** | Phase 6.5/6.6 |
| `references/fill-schema.md` | **写 fragment 前必读** | Report Output |
| `scripts/em_fetch.py` | 执行取数（`python` 运行，**不 Read**） | Phase 1 |
| `scripts/render_report.py` | 执行渲染（`python` 运行，**不 Read**） | Report Output |

---

## 成稿前质量自检

- [ ] 红灯是否已查（财务造假/立案/主营衰退/审计非标）？命中是否已熔断并加 `.danger-card`？
- [ ] 核心结论是否四段齐全：①关键优势 ≥2 条带数据 ②关键弱点 ≥2 条不回避 ③当前市场认知引用卖方 ④核心投资逻辑 + 可观测证伪条件 + 路径判断？是否**无评分表/无判词卡/无三块评分卡**（评分数字已在 Hero 与 section-meta）？
- [ ] 盈利质量红旗四项是否三态标注（✓/✗/△），无"数据缺失标 ✓"？△ 是否附"已尝试 N 种路径"降级说明？应收/存货是否已由脚本用东财 F10 补齐（正常不应再 △）？金融股是否已按 `industry-financials.md` 换行业口径？医药管线/地产/平台互联网是否已按对应行业附录换行业口径？
- [ ] 1F 资本回报质量是否已评（ROIC vs WACC、再投资、分红可持续）？稳定价值/金融分型下 1F 权重是否上浮？
- [ ] 估值分是否独立（不进质量分）且由脚本按四件套（中枢+赔率+合理倍数+税后股息）计算？`valuation_inputs` 四键是否已填、各有来源或标估算？
- [ ] 港股/AH 比价是否用了税后股息？税率是否标"以最新法规为准"？
- [ ] 每个关键数字是否有来源或标"估算"？缺失是否写"未获取到"？
- [ ] 三情景是否围绕 Phase 0 驱动？三指标（中枢/赔率/离散度）是否脚本算？
- [ ] 预期差是否到档位（A/B/C），卖方假设是否带来源？
- [ ] `peers_plot` 是否已填（缺失则图静默跳过）？
- [ ] 回测模式：`prev` 与 `review_html` 是否成对？复盘是否只进 R 章节？
- [ ] 渲染后是否无 `{{}}`/`【】` 残留、无缺字段警告？
- [ ] 报告源码尾部是否有 `generated by render_report.py` 标记？（无标记 = 手写绕行产物，作废重渲）
- [ ] 文件命名是否由脚本生成（自己没手写名字）？

---

## 数据降级与反幻觉

数据缺失按降级阶梯处理（详细阶梯见 `data-collection.md` / `data-sources.md` 降级链），
核心是**永不编造**：

- 每个数字必须有来源，或标"基于[X]估算"；找不到就写"未在公开信息中找到[X]数据"
- **估值分已无手填路径（v4.1 起）**：`valuation_inputs` 四件套（pe_ttm/pe_band/div_yield/risk_free）
  每一项都必须有取数来源或标注估算——pe_ttm/pe_band 来自取数与历史时段匹配校准，div_yield 按
  近 12 个月分红折算税后，risk_free 用中国 10 年期国债收益率（查不到时手工填最近公开值并注明
  来源与日期、标"估算"）；缺键渲染器直接拒绝
- **NEVER invent PE ranges, profit numbers, or peer metrics**
- 目标价必须可追溯到 Phase 0 驱动 + Phase 3 PE 校准，不套"市场惯例"或经验法则
- 数据冲突时并列呈现区间并注明冲突
- 降级必须同时满足：① 已尝试 ≥2 种路径 ② 报告中明确标注降级原因
- **妙想 MCP 缺席未在报告标注「已走降级路径」= 违反降级纪律**（Phase 1 工具检查硬门禁，禁止静默跳过）
