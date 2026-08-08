---
name: stock-deep-analysis
description: >
  📊 Generate a comprehensive four-layer deep analysis report for any publicly traded company.
  Use when the user asks for stock analysis, company deep dive, 深度分析, 股票分析,
  公司研究, investment research report, or wants a Baofeng Energy-style scoring report.
  Produces a structured report with L1 Company Essence, L2 Market Timing, L3 Future
  Expectations, L4 Risk Assessment scoring framework, three-scenario valuation with
  historical-PE calibration, peer comparison with trend + quality-value matrix, and
  a post-analysis monitoring dashboard. Triggers on mentions of stock tickers, company
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
> 本地工具权限，本技能的全部指令就在你的上下文里，直接按 Phase 0 开始执行。
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

- **Default**: Write the report as a **single self-contained HTML file** in the current working
  directory. All CSS embedded in `<style>`, no external dependencies. Openable in any browser.
- **File naming convention**: `[公司名]_[股票代码]_[综合得分]_[YYYY-MM-DD].html`
  - 综合得分保留两位小数，如 `5.66`
  - Example: `宝丰能源_600989_5.66_2026-07-22.html`
  - English stocks: `Apple_AAPL_6.20_2026-07-22.html`
  - **港股**：代码用 5 位数字不带后缀，如 `壁仞科技_06082_5.95_2026-07-30.html`（不要写成
    `06082HK` 或 `06082.HK`——统一 5 位数字，与脚本 secid_of 识别规则一致）
- **Fallback**: If the user explicitly requests Markdown ("输出md" / "markdown格式"), write `.md` instead.
  Markdown 版按 Report Output Format 的同一章节顺序输出（H1=公司名、H2=各章节、
  表格用标准 md 表格、评分用 🟢🟡🔴 emoji 徽章、扣分项用红色文字标注"−X"），
  内容结构与 HTML 版完全一致，仅排版降级。
- **When to output inline**: If the user asks for a quick summary or "直接输出", output directly
  in the conversation. Otherwise always write the file.
- **After writing**: Inform the user of the file path and offer to adjust any section.

### HTML Styling — 浅色卡片建模风

**Design language**: 浅灰背景 + 白色卡片 + 钢蓝点缀的投资研究报告风格。顶部导航条、
指标卡条、编号分区卡片。Dense data, no decoration. 参考样式：LBO 模型分析报告（浅色版）。

#### Color Palette

| Role | Color | Usage |
|------|-------|-------|
| Page background | `#eef1f5` | 页面底色（浅灰） |
| Card background | `#ffffff` | 所有内容卡片 |
| Table header bg | `#f5f7fa` | `<th>` 背景 |
| Border | `#dde3ea` | 卡片边框、表格分隔线 |
| Inner divider | `#eef1f5` | 卡片内部细分隔、斑马纹 |
| Primary text | `#2c3e50` | 正文 |
| Heading text | `#1a2b4a` | H1、卡片标题 |
| Muted text | `#8899a6` | 标签、来源标注、辅助信息 |
| Steel blue accent | `#4a6fa5` | 唯一主强调色：编号标签、图标、目标公司列、矩阵高亮 |
| Steel blue tint bg | `#eef2f7` | 强调底色（编号标签底、矩阵 target 格） |
| Info card bg | `#f0f5fa` | 层小结、PE校准逻辑卡 |
| Positive green | `#6ba86b` | 评分≥7、上涨、利多 |
| Warning orange | `#d4a24c` | 评分4.0-6.9、中性警示 |
| Danger red | `#c75b5b` | 评分<4、风险扣分、利空 |

#### Typography

| Element | Font | Size | Weight |
|---------|------|------|--------|
| 汉字 | `"STKaiti", "KaiTi"`（华文楷体） | 14px body | 400 |
| 英文/数字 | `"Times New Roman"` | same | 400/700 |
| 统一 font stack | `"Times New Roman", "STKaiti", "KaiTi", serif` | — | Times 无中文字形，汉字自动落到楷体 |
| H1 | 同上 | 24px | 700 |
| Section title | 同上 | 15px | 600 |
| 指标卡大数字 | 同上 | 24px | 700 |
| Meta/Source | 同上 | 11-12px | 400, muted |

**Number convention**: 金额统一用 ¥/亿 或 ¥/万——同一张表内不混用单位。
Times New Roman 非等宽字体，数字列右对齐即可，不追求小数点严格对齐。

#### Layout Structure

报告由以下结构组成（自上至下）：

1. **Topbar** — logo色块（36×36, `#4a6fa5`, 内放公司名首字）+ 标题 + 右侧标签组（报告类型/框架/日期）
2. **Hero** — H1公司名 + 副标题 + 一句话结论（钢蓝左竖线引用块 `.thesis`）+ **5张指标卡**
   （股价/市值/PE/综合得分/目标价区间，`.metric-row` + `.metric-card`）
3. **Section cards** — 每个大章节一张白色卡片 `.section`：
   - 卡片头 `.section-header`：`.section-num` 编号标签（00/P0/L1-L4/05-10）+ 标题 + 右侧meta
   - 卡片体 `.section-body`：维度块 `.dim-block`（`.dim-header` 一行排开：维度名+权重+徽章，
     徽章用 `margin-left:auto` 推到右侧）、表格、`.deduction` 扣分项、`.layer-summary` 小结
4. **Disclaimer** — `.disclaimer` 底部细字

关键 CSS 类：
- `.metric-row` + `.metric-card` — 指标卡条（flex，label/value/sub 三层）
- `.section` / `.section-header` / `.section-body` — 章节卡片
- `.section-num` — 编号标签（`#eef2f7` 底 + `#4a6fa5` 字）
- `.dim-header` — 维度头（名称+权重+徽章横排）
- `.deduction` — 扣分行（红色 `#c75b5b`，左竖线 `#f0d0d0`，每条独立一行）
- `.layer-summary` — 层小结（`#f0f5fa` 底 + 钢蓝左竖线）
- `.info-card` / `.warning-card` / `.danger-card` — 蓝/橙/红三种提示卡（左竖线）
- `.conclusion-box` — 结论框（`#f8fafc` 底 + 边框）
- `.matrix-table` — 估值-质量矩阵（HTML表格实现，表头/表体一律居中，`.target` 格钢蓝高亮）
- `.flag-ok` / `.flag-bad` / `.flag-na` — 红旗三态色（✓绿 / ✗红 / △橙），1D 红旗清单行首用
- `.freeze-first` — 宽表首列冻结（≥5 列数据表如 07 同业指标表，横向滚动时首列常驻）
- `.source` — 数据来源标注（表格正下方，11px 斜体灰字）
- `.verdict` — 维度判词（斜体灰字）

#### CSS Skeleton

**不再内嵌在 SKILL.md**——完整 CSS 以 `assets/report-template.html` 内嵌样式为唯一权威版本
（fill→render 工作流下模型从不手写 CSS）。如需调整样式，直接改模板文件。
模板与本文档的配色/字体规则如有冲突，以模板为准。

#### Score Badge Convention

| Range | Class | Output |
|-------|-------|--------|
| ≥ 7.0 | `badge-green` | `<span class="badge badge-green">8.0</span>` |
| 4.0–6.9 | `badge-orange` | `<span class="badge badge-orange">5.5</span>` |
| < 4.0 | `badge-red` | `<span class="badge badge-red">3.2</span>` |
| Layer scores | `badge-blue` | `<span class="badge badge-blue">L1 7.2</span>` |

Badge 放在维度头 `.dim-header` 行内右侧（`margin-left:auto`），不单独占行：

```html
<div class="dim-header">
  <span class="dim-name">1A 赛道与宏观</span>
  <span class="dim-weight">7%</span>
  <span class="score-line" style="margin-left:auto;margin-bottom:0;"><span class="badge badge-green">8.0</span></span>
</div>
```

#### Data Source Attribution

Every table with financial data must include a source note directly below:

```html
<table>...</table>
<span class="source">数据来源：公司2025年年报（2026-03披露），Wind，2026-07-22查询</span>
```

If data is estimated or from secondary sources: `估算` or `来源：XX，未经审计`.

#### Anti-Patterns (DO NOT)

- No dark background — 本风格是浅色卡片风，页面底色固定 `#eef1f5`
- No gradients, no `box-shadow`（卡片用 1px border，不用投影）, no rounded corners >8px
- No emoji in headers — 用 `.section-num` 编号标签
- No multi-color accent schemes — steel blue (`#4a6fa5`) 是唯一主强调色（绿/橙/红仅用于评分与信号）
- No `text-shadow` or `transform` effects
- No external fonts, CDN links, or JavaScript — pure HTML+CSS
- 评分不允许裸数字，必须带 `.badge` 徽章
- 表格不允许缺表头、不允许同表混用金额单位；**表头必须与数据列同对齐**——数字列表头
  `<th class="num">`、居中列表头 `<th class="center">`（与对应 `<td>` 同规则，禁止裸 `<th>`
  配带类 `<td>`，否则表头左/数据右中对不齐）；矩阵表 `.matrix-table` 表头不加类
  （CSS 强制居中，见 fill-schema）
- 金额/户数类数值 ≥1000 必须带千位符（`2,949.2 亿`、`188,153 户`）；
  年份、PE/PB 倍数、百分比、股价、EPS、评分不加
- 禁止省略 `.section` 卡片包装——裸文本不配出现在 `.topbar` / `.hero` / `.disclaimer` 之外

---

## Workflow

### Phase 0: Identify Critical Profit Drivers (MANDATORY — before any scenario modeling)

Before building valuation scenarios, identify the **1-2 variables** that have the greatest leverage
on the company's profits. This step determines the entire analytical backbone of the report.

**How to identify:**
1. From the researched financials and business model, list all variables that affect revenue
   and costs (commodity prices, volume, utilization rates, FX, regulatory changes, etc.)
2. For each variable, estimate its impact magnitude: "a 10% change in X → approximately Y%
   change in operating profit"
3. Select the top 1-2 with the largest profit elasticity

**Sensitivity validation** (include in the report as a brief table):

| 关键变量 | 变动幅度 | 年利润影响 | 弹性等级 |
|----------|----------|------------|----------|
| [Variable 1, e.g. 布伦特油价] | ±$10/桶 | ±¥[X]亿 | ★★★★★ |
| [Variable 2, e.g. 煤价] | ±¥100/吨 | ±¥[Y]亿 | ★★★ |
| [Variable 3] | ... | ... | ★★ |

**Build scenarios around these drivers.** Each scenario (pessimistic/base/optimistic) is
defined by where these 1-2 key variables go, not by arbitrary profit ranges.

### Phase 0.5: Stock Classification (MANDATORY — 分型决定尺子)

**不要用一套尺子量所有股票。** 完成 Phase 0 后、Phase 1 深度调研前，必须给股票分型。
分型结果决定三件事：各层权重、估值方法、哪些维度是决定性维度。在报告 P0 卡片中
必须声明分型及理由。

| 类型 | 识别特征 | 权重调整 | 估值方法 | 决定性维度 |
|------|---------|---------|---------|-----------|
| **周期股** | 利润随商品价格/产能周期大幅波动（化工、航运、养殖、煤炭、有色、钢铁、半导体、面板） | 默认权重（L1 35/25/20/20），L2/L4 是胜负手 | PE 历史时段匹配法（本框架默认） | 2A 估值、4A 基本面风险、周期位置 |
| **稳定价值/金融** | 盈利稳定、高分红、杠杆经营（银行、保险、公用事业、高速公路） | L1→40%、L3→15%（增长不重要） | **PB-ROE 框架**（银行/保险）；DDM（高股息公用事业）。PE 仅作辅助 | 1D 资产质量、1E 治理、分红可持续性 |
| **稳健成长股** | 利润增速 10-25%、可预测性强（消费、医药白马、制造业龙头） | 默认权重 | PE 匹配 + DCF（通常满足 FCF 条件）+ PEG 辅助 | 1C 护城河、3A 增长持续性、2A 估值 |
| **快速成长股** | 利润增速 >25%，利润基数尚小 | L3→30%、L2→15%（买点容忍度高） | PEG、远期 PE 折现、终局市值反推 | 3A 增速、1A 赛道天花板、4C 增长风险 |
| **未盈利/管线股** | 当期亏损或利润无意义（创新药、早期科技） | L1→40%、L3→30%、L2→10% | **rNPV**（管线×成功概率×峰值销售）、P/S、EV/毛利。**禁用 PE 匹配** | 1A 赛道、1C 技术壁垒、现金消耗速率 |
| **困境反转** | 财务指标全面恶化但存在反转催化剂 | L1 评分仅作参考、L1<3.5 致命缺陷规则**豁免**（财务烂是前提不是缺陷），L3→30% | 正常化利润 PE、重置成本、清算价值对照 | 3B/3C 反转催化剂、4A 生存风险（现金流能否撑到反转） |

**分型规则：**
- 一只股票只归一个主类型；跨界时选"利润结构主导"的类型（如银行+成长 → 稳定价值）
- 分型必须在报告中写明理由（一句话，引用识别特征）
- 非周期股 → Phase 5 周期分析自动跳过（除非同时满足触发条件）
- 困境反转型豁免 L1<3.5 致命缺陷规则，但必须在核心结论中明示"本报告为困境反转框架，
  L1 低分是前提而非否决项"

### Phase 1: Research (MANDATORY — do NOT skip)

**数据获取优先级：取数脚本（首选）→ 环境自适应定性搜索 → 委派（极少用）。**
历史教训：紫光/阳光电源会话里子代理脱离技能上下文 + 环境无 WebSearch，退化为
74 次 WebFetch 抓搜索页、烧穿额度；"定性搜索只许用 WebSearch"这条规则本身
是错的——它假设了一个环境未必满足的前提。

#### Step 1.0: Structured API Fetch（首选，一条命令完成）

**优先使用捆绑脚本** `em_fetch.py`（取数+解析一步完成，只让 ~2KB 摘要进上下文）。
脚本位于**本 SKILL.md 同目录的 `scripts/` 子目录**——用技能目录的绝对路径执行，
禁止用相对路径（相对路径会因工作目录不同而找不到文件，历史实证：此错误导致整套
取数流程回退到 mcporter/agent-reach，浪费 25 分钟）：

```bash
python "<skill目录>\scripts\em_fetch.py" [代码] --peers=[peer1],[peer2],[peer3],[peer4]
# 例: python "<skill目录>\scripts\em_fetch.py" 600989 --peers=600309,002001
#      <skill目录> = 本 SKILL.md 所在目录（技能安装位置，因人而异）
```

**妙想 MCP 直调补充**（如 `mcp__mx-ds-mcp-stdio__mx_*` 在工具列表，脚本盲区/增强项）：
- **筹码分布（2C）**：tushare `cyq_*` 无权限 → `mx_ashare_finance_data(query="[公司] 最新获利比例、90%成本区间、平均成本、筹码集中度")`（实测返回平均成本/集中度）
- **行业估值水位（2A）**：`mx_index_block_finance_data(query="[申万煤炭/对应行业] 最新 PE PB 及历史分位")`——从"跟自己历史比"升级为"跟行业当前比"
- **大宗商品价格（P0 第一变量）**：`mx_macro_data(query="[动力煤/布伦特原油/对应品种] 最新价格及近30日走势")`
- **港股盈利预测（E5 港股补位）**：`mx_hk_finance_data(query="[公司] 券商盈利预测 目标价")`

**路径失败处理**：若提示找不到脚本，先在技能目录内定位（`find <技能目录> -name em_fetch.py`，
cmd 下用 `dir /s`），修正路径后重跑。**禁止因路径问题放弃脚本**——放弃脚本 = 触发
全套低效降级链。

脚本一次输出：E1 行情估值（A股附 PE/PB 5年带与当前分位、下次财报披露计划日）、
E3 五年财务年表+红旗五项判定（三态：✓真通过/✗真恶化/△数据不足，审计意见 tushare 自动填）、
E2 月线区间、E4 股东户数、业绩预告/快报、1E 治理包（质押/增减持/回购）、
E5 一致预期+目标价、E6 主营构成，含全部 peer。
**港股（5位数字代码，如 01880/06082）**：脚本自动识别 → secid 切 `116.` 前缀、
价格 ÷1000、K线按真实价；E1/E2 直接可用（tushare hk_daily 缓存复用绕限流）。
**E3 港股财务：优先妙想 MCP `mx_hk_finance_data` 直查**（自然语言查询，如
"壁仞科技(06082.HK) 2024年报和2025中报：营业总收入、归母净利、毛利率、ROE"，实测可用）；
妙想不可用再按 `data-sources.md` 港股手册手工 curl HKF10。
E4/E5/E6 输出"港股不支持"。**不要像壁仞项目那样手工探测 secid——脚本已内置。**

#### 环境工具探测（Phase 1 第一步，做一次记录一次）

正式取数前，先确认本会话有哪些可用工具。**不要假设——用以下顺序探一次**：

1. WebSearch 是否在工具列表里？（不是"试了失败"——是列表里有没有）
2. 妙想 MCP 工具（`mcp__mx-ds-mcp-stdio__mx_*`）是否在工具列表里？（定性检索与港股财务的关键通道）
3. curl 可用？（`curl --version` 0.3 秒即知）
4. python 可用？（脚本是否跑通即知）

把结果记在心里（如"有 curl + python，无 WebSearch"）。后续所有定性搜索路径都依据
这个探测结果选择，不要每条搜索都重探。

#### 定性搜索纪律（MANDATORY — 违反任何一条都是效率事故）

**核心原则：禁止用 WebFetch/curl 抓取 bing、baidu、google、duckduckgo、sogou、so.com
等搜索引擎结果页。** 历史实证：紫光子代理 74 次抓搜索页 → 429 限流 → 烧穿额度。
搜索引擎结果页是低质、反爬、且需要二次解析的最差数据源。

**按环境工具可用性分路径：**

| 环境 | 定性搜索主路径 | 顺序 |
|------|---------------|------|
| **有 WebSearch** | WebSearch 工具 | 定性搜索主入口，搜索页一律禁用 |
| **有妙想 MCP**（`mcp__mx-ds-mcp-stdio__mx_*` 在工具列表） | ① `mx_finance_search_news`（新闻/研报观点/评级/目标价，返回标题+摘要+来源+链接）<br>② `mx_finance_search_notice`（公告/年报原文，审计意见/重大事项） | 无 WebSearch 时的**定性首选**，检索质量高于 E7（实测） |
| **前两者都无** | ① `em_fetch.py --search` 调东财 E7 站内搜索（结构化 JSON）<br>② WebFetch 抓**已知 URL**的结构化页面：10jqka basic 四页（company/operate/holder/event）、巨潮公告、东财研报页 | E7 + 已知 URL；搜索页是最后手段 |

**通用硬规则（不分环境）：**
1. **禁止第三方搜索代理**（r.jina.ai/s.jina.ai、mcporter/exa 等）——慢且不可靠。
2. **禁止在 Bash 里内联 `python -c "..."` 传递含中文的代码**。Windows shell 对内联中文
   支持不可靠，中文会被静默吞掉（工业富联实证：连续 3 次内联中文调 E7 全部无输出）。
   需要跑含中文的 Python 代码时，一律先 Write 成临时 .py 文件再 `python file.py`。
3. **失效工具 30 秒内放弃，且当日不再回头**：失败一次→诊断换参重试一次→仍失败切降级链下一级，禁止同一份报告第三次触碰。
4. **同一调用禁止原样重试**：重试必须改参数（超时/端点/查询词），原样重试 = 浪费。
5. **已抓取的 URL 不重复抓**：同一页面只取一次，维护心中清单。
6. **429/限流是硬停止信号**：任一工具返回 429 或明确额度耗尽提示，立即停止当前路径整条降级链切下一级。紫光子代理在 12:12 第一次 429 后又跑 15 分钟到第二次 429 才停——这种"硬挺"是严格禁止的。
7. **搜索页抓取硬上限（仅当 WebSearch 和 E7 都不可用时的最后手段）**：单份报告搜索页 WebFetch ≤ 5 次，每次必须换查询词，抓完立即解析不再回抓。
8. **禁止静默降级**：任何降级必须同时满足 ① 已尝试 ≥2 种获取路径 ② 报告中明确标注降级原因。**禁止把"未检查"伪装成"通过"**——如"✓ API未触发"这类写法（芯原股份实证：应收/存货周转数据缺失被标成 ✓，读者误以为检查通过）。数据缺失时用三态标注：✓=真通过 / ✗=真恶化 / △=数据不足（写明缺了几期）。

#### Step 1.1: Qualitative Research（仅补 API 盲区，按环境路径执行）

API 给不了的是定性信息。**按"环境工具探测"结果选路径**，不要写死工具名：

有 WebSearch 时：
```
WebSearch(query="[Company Name] 主营业务 护城河 竞争优势 2025 2026")
WebSearch(query="[Company Name] 在建项目 产能 投产 审批 进展")
WebSearch(query="[Company Name] 控股股东 质押 减持 关联交易")
WebSearch(query="[Company Name] 重大事件 催化剂 [近6个月]")
WebSearch(query="[Industry] 市场规模 增速 2026")
```

无 WebSearch 但有妙想 MCP 时（定性首选，模型直调）：
```
mx_finance_search_news(query="[公司名] 主营业务 护城河 竞争优势 最新研报观点 评级 目标价")
mx_finance_search_news(query="[公司名] 在建项目 产能 投产 进展 重大事件 催化剂")
mx_finance_search_notice(query="[公司名] 控股股东 质押 减持 关联交易 公告")
mx_finance_search_notice(query="[公司名] 年度报告 审计意见")
```

前两者都无时（em_fetch.py --search 调 E7 + 已知 URL，避免手写接口）：
```
python "<skill目录>\scripts\em_fetch.py" [代码] --search="关键词1,关键词2"
WebFetch(http://basic.10jqka.com.cn/[代码]/company.html)   # 公司概况
WebFetch(http://basic.10jqka.com.cn/[代码]/event.html)     # 治理红旗数据（质押/减持/关联交易）
WebFetch(http://basic.10jqka.com.cn/[代码]/operate.html)   # 项目进展
```

**审计意见 = 必查项（MANDATORY）**：盈利质量红旗第 5 项不能停留在"需查年报"标注——
那只是待办描述，不是结果。必须实际查证后填写：

0. A股首选：**em_fetch.py 已用 tushare `fina_audit` 自动填**（脚本红旗输出第 5 行直接给结论），
   脚本显示 ✓/✗ 时直接采用；显示 △ 或港股时走下述手工路径
1. 妙想 MCP（如在工具列表）：`mx_finance_search_notice(query="[公司名] 年度报告 审计意见")`——
   实测可直接命中审计报告原文段落
2. 或：E7 搜 `[公司名] 年报 审计意见`（或 `[公司名] 标准无保留意见`），
   或 WebFetch 巨潮年报公告页 `http://www.cninfo.com.cn/new/disclosure/stock?stockCode={code}`
3. 年报 PDF 封面/审计报告首页即注明意见类型（标准无保留 / 保留 / 无法表示 / 否定）
4. 查到 → 红旗表填实际结论（"✓ 标准无保留意见" 或 "✗ 保留意见"）
5. 查不到（尝试 ≥2 种路径后）→ 填 `△ 审计意见 未查证（已尝试[X]路径）`，禁止直接沿用"需查年报"默认行

#### Step 1.2: Sell-Side Deep Dive（预期差档位A专用）

E5 已给出一致 EPS 和目标价（档位B）。若要升级档位A（具体假设对照）：

有 WebSearch 时 `WebSearch(query="[Company Name] 券商研报 关键假设 [年份]")`；
有妙想 MCP 时 `mx_finance_search_news(query="[公司名] 券商研报 关键假设 盈利预测 [年份]")`；
预期修订方向（"近30天上调X家/下调Y家"）：`mx_finance_search_news(query="[公司名] 近一个月 盈利预测 上调 下调 评级变动")`；
前两者都无时用 E7 搜"研报"或在
`data.eastmoney.com/report/zw_stock.jshtml?infocode=...` 研报页找假设。

找到具体假设必须记录来源（券商名+日期）；找不到就停在档位B，禁止编造。

#### Step 1.3: 委派子代理（极少用，定性调研禁止委派）

**定性调研一律在主会话内完成，禁止委派子代理。** 实证：紫光/阳光电源两次委派，
子代理脱离本技能上下文 + 环境无 WebSearch → 自动退化为 74 次 WebFetch 抓搜索页 +
烧穿额度。委派是最大效率陷阱。

委派仅在以下边界清晰的**机械子任务**才允许，且 prompt 必须逐字写入工具限制：
- 下载某指定公告 PDF 并提取某张表
- 抓取某指定 URL 列表的结构化字段

委派 prompt 必须包含（逐字）：
```
你只能使用：curl（东方财富 API）、WebFetch（仅已知 URL）、Read。
禁止：mcporter、r.jina.ai/s.jina.ai、抓取搜索引擎结果页、加载 agent-reach 技能、
      WebSearch（本环境不可用，不要尝试）。
遇到 429 或任何限流/额度提示：立即停止当前路径并返回已有结果，不要硬挺。
```

#### Research Checklist (verify each item before proceeding to scoring; 标注首选来源):

- [ ] Current price, market cap, PE(TTM), PB — **E1**
- [ ] Last 3-5 years: revenue, net profit, ROE, gross margin, net margin, debt ratio, FCF, capex, dividend — **E3**
- [ ] Core business breakdown (segment revenue %), industry chain position — **E6** + 定性搜索
- [ ] Competitive moat analysis (cost structure, scale, tech, policy, brand) — 定性搜索（E3 的研发占比/毛利率作辅证）
- [ ] Major projects in pipeline (approval status, timeline, capex, capacity contribution) — 定性搜索
- [ ] 3-5 key peers with comparable metrics — **E1+E3 对每个 peer 并行调用**（em_fetch.py --peers）
- [ ] Shareholder structure: top holders, shareholder count trend, institutional % — **E4** + 定性搜索
- [ ] Governance red flags: 控股股东质押率、关联交易占比、近12个月减持、实控人年龄/继任安排、近3年监管处罚 — 定性搜索（10jqka event.html 首选）
- [ ] 盈利质量红旗数据（现金含量/应收/存货周转） — **E3**（审计意见需定性搜索查年报）
- [ ] Recent major events (last 6 months) — 定性搜索（妙想 news/notice 首选，E7 备选）
- [ ] Historical PE range (3-5 years), current PE percentile — **E2**（月线）+ E3（净利）
- [ ] Key price levels: recent high/low, MA60, MA120 — **E2**（近6月日线）
- [ ] Analyst consensus (rating distribution, recent changes) — **E5**
- [ ] Sell-side estimates: 一致盈利预测（2026E/2027E净利）、一致目标价、关键假设（如有，必须带来源） — **E5**（档位B）+ 定性搜索（档位A）

> 注：清单中的"定性搜索"指 Step 1.1 的环境自适应路径——有 WebSearch 用 WebSearch，
> 有妙想 MCP 用 mx_finance_search_news/notice，都无则 E7 + 10jqka 已知 URL，不要写死工具名。

---

### Phase 2: Score Each Dimension

Score each dimension 1-10, then apply weights.

**Scoring principle**: Score based on evidence, not impression. For every score ≥7 or ≤3,
provide specific quantitative justification. Do NOT pre-calibrate to any range — let the
evidence determine the score.

#### L1: Company Essence (35% weight) — "What quality is this company?"

> **权重哲学**：本框架采用价值投资者视角——公司质量(L1 35%) > 价格(L2 25%) >
> 预期(L3 20%) = 风险(L4 20%)。深层逻辑：烂公司在任何价格都不值得买，好公司
> 买贵了还能靠时间消化。如需调整为趋势交易视角，L1/L2 权重可互换（即 L2 35%、
> L1 25%）。

| # | Dimension | Weight | Key Questions |
|---|-----------|--------|---------------|
| 1A | Sector & Macro | 7% | Market size (万亿级=9-10, 千亿级=7-8, 百亿级=5-6). Growth rate (>10%=8-10, 3-10%=6-7, <3%=4-5). Is the sector strategically favored by policy? Structural tailwinds? Capacity utilization vs industry average. |
| 1B | Industry Chain Position | 7% | Cost advantage vs competitors (quantify in ¥/ton or %). Upstream self-sufficiency. Downstream pricing power — price maker or price taker? Structural cost differential expected to persist? |
| 1C | Business Model & Moat | 7% | Enumerate moats explicitly: cost advantage, scale barrier, policy/regulatory barrier, technology/IP, brand, network effects, switching costs. For each: is it widening or narrowing? Does it protect against ALL key risks or only some? |
| 1D | Financial Health | 6% | ROE trend (3yr). Gross margin trend. Debt ratio and interest coverage. FCF strength (cumulative 5yr FCF). Dividend consistency. **必须先过盈利质量红旗清单（见下方 1D 细则）；重资产公司必须算增量 ROIC。** |

**1D 盈利质量红旗清单（MANDATORY — 先于评分执行）**：

利润是不是真钱，比利润多不多更重要。以下五项全部为公开数据，逐项检查：

| 红旗项 | 口径 | 判定 |
|--------|------|------|
| 利润现金含量 | 经营现金流净额 ÷ 净利润（F10 字段 NCO_NETPROFIT） | 连续2年 <0.7 → 红旗 |
| 应收账款周转 | F10 字段 YSZKZZTS（周转天数） | 最新年 > 最早年×1.3（连续恶化变长）→ 红旗 |
| 存货周转 | F10 字段 CHZZTS（周转天数） | 最新年 > 最早年×1.3（连续恶化变长）→ 红旗 |
| 毛利率异常 | 毛利率 vs 同业均值 | 高出同业均值 >50% 且无法给出业务解释 → 红旗 |
| 审计意见 | 最新年报审计意见类型（**必查项**，按 Step 1.1 查证后填写） | 非标（保留/无法表示/否定）→ 红旗 |

**三态标注（MANDATORY）**：每项判定结果只能是三种之一——
✓=真通过（有数据且未恶化，写明数值）；✗=真恶化/真命中（写明数据）；
**△=数据不足**（写明缺几期有效数据，如"△ 应收账款周转 数据不足（2期有效）"）。
禁止把"数据缺失"标成 ✓——那会让读者误以为检查通过（芯原股份实证）。
脚本 `em_fetch.py` 的 `red_flags()` 已按此三态输出，直接采用其结果，不要改写。

**命中处理**：每命中一项，1D 扣 1 分；命中 ≥2 项，除扣分外必须在**核心结论**中置顶提示
"⚠️ 盈利质量存在红旗（[具体项]），利润真实性存疑"。命中审计非标 → 直接触发 L1 致命缺陷
警告（视同 L1<3.5 处理）。

**1D 增量 ROIC（重资产公司 MANDATORY）**：对 capex 驱动的公司（近3年年均资本开支 >
折旧摊销×1.5），必须计算最新重大项目的增量资本回报：

```
增量 ROIC = 项目达产后年增净利润 ÷ 项目总投资
```

与 WACC（无数据时用 8% 作默认）对比：增量 ROIC > WACC×1.5 → 加分依据；
增量 ROIC < WACC → 1D 扣 1 分并在判词中说明"再投资在毁灭价值"。
（例：投137亿建四期，达产年增净利15-20亿 → 增量ROIC≈11-15% > 8% WACC → 回报可观。）
| 1E | Management Team | 8% | 采用**清单锚定 + 整体判断**混合制（见下方 1E 细则）。**This is the highest-weighted dimension in L1 — management quality determines whether financials and moats sustain or erode.** |

**1E 治理评分细则（混合制）**：先按清单计算锚定分（起始 10 分），再允许 ±1 分整体判断调整。

*量化扣分清单（口径必须严格遵守）：*

| 量化项 | 口径 | 扣分 |
|--------|------|------|
| 控股股东质押比例 | 质押股数 ÷ 其持股总数 | >50% → −0.5；>70% → −1.0 |
| 关联交易 | 年度关联交易金额 ÷ 营收 | >10% → −0.5；>20% → −1.0 |
| 近12个月减持 | 实控人+高管净减持股数 ÷ 总股本 | >0.5% → −0.5；>2% → −1.0 |
| 实控人年龄 | >68岁 且无公开继任安排 | −0.5 |
| 监管处罚/审计非标 | 近3年内 | −1.0 起，视严重性可加扣 |
| 正向锚 | 分红率连续3年>40%，或近12个月有回购 | +0.5（正向合计封顶 +0.5） |

*整体判断调整（±1 分以内）*：用于清单无法覆盖的治理风险或优势——治理文化、
一言堂倾向、历史污点、继任安排质量、战略定力。调整必须在报告中写明理由；
无调整需求时直接用锚定分。清单未扣分 ≠ 治理无问题，判词中不得这样暗示。

#### L2: Market Timing (25% weight) — "Is now a good price?"

| # | Dimension | Weight | Key Questions |
|---|-----------|--------|---------------|
| 2A | Valuation Attractiveness | 16% | Current PE vs 5yr historical range (percentile). Forward PE and what profit assumptions it embeds. PB vs peers. **Critical**: distinguish "PE looks low because profits are at cyclical peak" from "genuinely undervalued." Dividend yield normalized to mid-cycle earnings. **L2 的核心维度——价值框架里"价格 vs 价值"是买入决策的核心。** |
| 2B | Technical Analysis | 3% | Price vs MA60/MA120 (trend health). Recent drawdown magnitude. **仅占 3%：技术面与价值框架哲学上不兼容，仅作短期择时参考，不驱动结论。** |
| 2C | Capital & Sentiment | 6% | Shareholder count trend (rising = retail inflow = bearish signal; falling = accumulation = bullish). Institutional ownership % and trend. Analyst consensus (rating distribution, target price range). Insider trading if available. |

#### L3: Future Expectations (20% weight) — "Where is profit heading?"

| # | Dimension | Weight | Key Questions |
|---|-----------|--------|---------------|
| 3A | Profit Growth | 8% | Project 1-2 year earnings. Break down: volume growth, price/margin assumptions, new project ramp-up. Acknowledge uncertainty — flag which variables are external. Provide range, not point estimate. |
| 3B | Project Certainty | 7% | Pipeline: approval status, construction progress, funding secured. Distinguish "under construction" (high certainty) from "planning/awaiting approval" (low certainty). Timeline to profit contribution. |
| 3C | Catalysts | 5% | Upcoming re-rating events: earnings reports, project milestones, policy changes, index inclusion. Time horizon for each. |

#### L4: Risk Assessment (20% weight) — Deduction System

**L4 uses deduction scoring.** Each dimension starts at 10. Deductions are applied based on
identified risks. The final score = 10 − total deductions (floor at 1).

| # | Dimension | Weight | Deduction Rules |
|---|-----------|--------|-----------------|
| 4A | Fundamental Risk | 8% | **−3** if a single external variable (commodity price, FX, regulation) dominates >50% of profit variance. **−2** if supply-side overcapacity is building (industry capacity growth > demand growth). **−2** if cost structure has significant pass-through risk. **−1** for each additional material risk factor. **Must provide quantified sensitivity**: "every $X change in [variable] = ±¥Y impact on annual profit." |
| 4B | Sentiment & Capital Risk | 6% | **−2** if shareholder count increased >50% in past year (retail stampede). **−2** if institutional ownership <5%. **−1** if margin debt is elevated. **−1** if historical max drawdown in similar setups >30%. |
| 4C | Growth Risk | 6% | **−2** if growth beyond 3 years depends on unapproved projects. **−2** if core business faces structural decline (not just cyclical). **−1** if project execution history is mixed. **−1** if growth ceiling visible within 5 years with no diversification path. |

**L4 Pre-mortem（MANDATORY — 扣分之后执行）**：

扣分清单防的是已知风险，pre-mortem 防的是"我没看见的风险"。完成 4A-4C 评分后，
必须写一段 3-5 句的叙事性压力测试：

> **假设两年后这笔投资亏损 30%，最可能的故事是什么？**

从第一个字开始强迫自己站在空头立场叙事（"2026年10月，XX事件发生，市场发现……"），
写完回答一个问题：**这个故事和 4A-4C 清单里的风险是同一件事的概率有多大？**
如果是清单里已有风险的复述 → 说明风险识别充分；如果是清单外的新风险 → 回到 4A-4C
补扣分。L4 答"有哪些风险"，pre-mortem 答"哪个风险最可能真的杀死我"。

---

### Phase 3: Build Valuation Model

Construct three scenarios defined by the Phase 0 profit drivers:

1. **Pessimistic Scenario**: The key negative driver materializes. Define the trigger (e.g.,
   "oil drops to $60 on peace deal"), trace through to profits.

2. **Base Scenario**: Most likely path given current information. Use current forward curve
   or consensus for key drivers.

3. **Optimistic Scenario**: The key positive driver materializes. Define the trigger.

For each scenario:
- **Time horizon（MANDATORY）**：每个情景必须标注时间维度（默认 12 个月，即"下一个年报节点"）。
  不同情景可以有不同时间维度（如悲观 12 个月、乐观 24 个月），但必须写明——
  +40%/1年 和 +40%/3年 是完全不同的机会。
- **Net profit range** (annual, with derivation shown)
- **EPS**
- **PE multiple** — calibrate using **historical period matching**:
  - Find 2-3 historical periods with similar growth rate, profit scale, and macro backdrop
  - Use PE range from those periods
  - Apply "scale discount": if current profits >> historical, PE should be systematically lower
    (larger base → slower future growth → lower multiple)
  - Document the logic: "Historical period X had Y% growth and PE A-Bx. Current profit is Z×
    larger, applying ~N% discount → calibrated PE C-Dx."
- **Target market cap** = Net profit × PE
- **Target price** = Target market cap ÷ shares outstanding
- **Upside/downside** vs current price

#### 三指标提取（MANDATORY — 跨股可比性的基础）

三情景确定后，必须提取以下三个指标。**不做概率赋值**——概率不可预测，
这三个指标全部从三情景的价格结构中直接导出，不引入额外主观判断。

**1. 中枢期望收益率**（替代"概率加权期望"）：

```
中枢期望收益 = 基础情景目标价中值 ÷ 现价 − 1
年化中枢收益 = (1 + 中枢期望收益) ^ (1 ÷ 时间年数) − 1
```

基础情景的定义本身就是"最可能路径"，直接用其中值作为中枢估计。
判断没有消失，只是脱掉了 20/60/20 的假精确外衣；三情景表永远并排展示，不对称性不被隐藏。
**跨股对比统一使用年化中枢收益**——不年化，+40%/1年和+40%/3年会被错误拉平。

**2. 赔率**（上行/下行不对称性，只需价格、不需概率）：

```
赔率 = (基础目标价中值 − 现价) ÷ (现价 − 悲观目标价下限)
```

边界情况必须处理：
- **悲观下限 > 现价** → 赔率记为 `∞`（悲观情景仍是正收益），这是最强信号，仓位映射可上浮一档
- **基础中值 < 现价** → 中枢期望收益为负，直接触发"回避"判定，无论综合得分多少——
  这是"好公司但太贵"的拦截器

**3. 情景离散度**（不确定性的客观度量，概率的真正替代品）：

```
离散度 = (乐观目标价中值 − 悲观目标价中值) ÷ 现价
```

- <30%：结果收敛 → 这只股票**可预测**，命运掌握在公司自己手里
- 30-60%：中等不确定
- >60%：结果高度发散 → 本质在赌外部变量

离散度不回答"好事发生的概率"（没人能回答），它回答"这只股票的结果有多可预测"。

**定性概率提示（可选，仅在有强外部证据时）**：当存在权威调查、事件日历、隐含波动率等
可观测证据时（如"路透调查58%预期停火"），在估值模块下方加一段文字提示，**只定性、不定量**。
无证据时不写，禁止凭空给出概率数字。

#### DCF Anchor (Conditional)

**Check**: Calculate the company's past 5-year FCF/Net Profit ratio and its standard deviation.

```
If (avg(FCF/NetProfit over 5yr) > 70%) AND (stdev(FCF/NetProfit over 5yr) < 30%):
    → Company has stable, high-quality cash conversion
    → Add a DCF valuation as an independent anchor
    → Compare DCF-implied value with scenario-based targets
    → If DCF aligns with a scenario, that scenario gets extra credibility
    → If DCF is far from all scenarios, flag the discrepancy and potential reasons
Else:
    → Skip DCF — earnings are too volatile or cash conversion too weak for meaningful DCF
```

If DCF is run, present it as a supplementary table:

| DCF参数 | 假设值 | 说明 |
|---------|--------|------|
| 预测期 | 5年 | |
| 永续增长率 | X% | |
| WACC | X% | |
| DCF得出每股价值 | ¥X | |
| 对应情景 | 悲观/基础/乐观 | |

#### 市场预期差拆解（MANDATORY — 说明超额收益的来源）

估值完成后，必须回答一个问题：**你的模型和卖方一致预期的分歧在哪里？**
如果你的假设和卖方一致，就没有预期差，没有预期差就没有超额收益。
"卖方偏乐观，本文不采纳"只是一句断言，必须把分歧拆到具体假设层面。

按数据可得性分三档输出（严禁编造卖方假设——找不到就写"未披露"）：

**档位A：找到具体卖方假设（有出处）→ 完整对照表**

| 关键假设 | 卖方假设 | 本文假设 | 分歧对利润的影响 | 来源 |
|----------|----------|----------|------------------|------|
| [如：硅料价格] | ¥X/kg | ¥Y/kg | ±¥Z亿 | [券商名]研报，[日期] |
| [如：出货量] | X万台 | Y万台 | ±¥Z亿 | [券商名]研报，[日期] |

**档位B：只有一致目标价和评级 → 反推隐含假设**

用 `一致目标价 ÷ 一致PE 反推卖方隐含利润`，与本文利润假设对比：
"卖方隐含2026年净利 X亿 vs 本文 Y亿，分歧±Z%，主要集中在[变量1]和[变量2]。"

**档位C：什么都找不到 → 只列分歧维度**

"本文与市场的分歧大概率在[变量1]和[变量2]两个变量上。卖方假设未披露，无法精确对照。"
明确标注"卖方假设未披露"，禁止填任何数字。

拆解完成后，用一句话总结预期差方向：本文比卖方**更乐观/更悲观/基本一致**，
以及这个预期差如果被证伪（卖方对、本文错），利润和目标的修正方向。

---

### Phase 4: Build Peer Comparison

#### 4.1 Current Metrics Table

| 指标 | [Target] | [Peer 1] | [Peer 2] | [Peer 3] | [Peer 4] |
|------|----------|----------|----------|----------|----------|
| 核心业务 | | | | | |
| 营收(最新财年,亿) | | | | | |
| 归母净利(亿) | | | | | |
| ROE(TTM) | | | | | |
| 毛利率(TTM) | | | | | |
| 净利率(TTM) | | | | | |
| 资产负债率 | | | | | |
| PE(TTM) | | | | | |
| PB | | | | | |
| Forward PE | | | | | |

#### 4.2 Trend Comparison (3-Year)

| 指标 | [Target] | [Peer 1] | [Peer 2] | [Peer 3] | [Peer 4] |
|------|----------|----------|----------|----------|----------|
| ROE变化 (3年前→现在) | X%→Y% | ... | | | |
| 毛利率变化 (3年前→现在) | X%→Y% | ... | | | |
| 净利率变化 (3年前→现在) | X%→Y% | ... | | | |
| 负债率变化 (3年前→现在) | X%→Y% | ... | | | |

**Trend conclusions**: Who is improving? Who is deteriorating? Is the target company gaining
or losing competitive position relative to peers?

#### 4.3 Valuation-Quality Matrix

Plot peers on a conceptual ROE (quality) vs PE (valuation) matrix:

```
高 ROE ↑
      │  ★ [Peer A]          ★ [Target Company]
      │  高ROE·低PE           高ROE·高PE
      │  ← 潜在低估            ← 合理/偏贵
      │
      │  ★ [Peer B]          ★ [Peer C]
      │  低ROE·低PE           低ROE·高PE
      │  ← 价值陷阱?           ← 最差组合
      │
      └──────────────────────────────────→ 高 PE
```

Describe the matrix in text form (no need to generate an actual image — use ASCII art or
descriptive text). Identify: who sits in the "high quality + low valuation" sweet spot?
Where does the target company sit relative to the fair-value line?

---

### Phase 5: Historical Cycle Analysis

**启动条件（满足任一即执行 Phase 5，否则跳过）：**

- 过去 5 年 PE(TTM) 波动幅度 > 50%（即 (maxPE − minPE) / minPE > 0.5）
- 归母净利润出现过 ≥2 次连续 2 个季度以上下滑、之后又恢复增长
- 公司所属行业为：大宗商品、化工、航运、养殖、半导体、面板、钢铁、煤炭、有色

不满足以上任一条件 → 公司利润和估值波动不足以形成可辨识的周期 → 跳过此章。
（与 Phase 0.5 分型联动：非周期股默认跳过，仅当仍满足上述触发条件时才执行。）

**执行时：**

```
阶段1：[名称]（[日期区间]，股价[范围]，PE[范围]）— [驱动因素和特征]
阶段2：[名称]（[日期区间]，股价[范围]，PE[范围]）— [驱动因素和特征]
...
阶段N：当前位置 — [判断当前处于周期何处]
```

Extract **3-5 reusable patterns** from the cycle (see Tips section below for examples).

---

### Phase 6: Monitoring Dashboard (MANDATORY)

After completing the analysis, define what the user should track going forward. This is
critical for practical value — a static report is a snapshot; the dashboard makes it a
living tool.

#### 6.1 Key Tracking Indicators

| # | 指标 | 当前值 | 关注原因 | 数据来源 | 更新频率 |
|---|------|--------|----------|----------|----------|
| 1 | [Primary profit driver, e.g. 布伦特原油] | [$X] | [弹性说明] | [来源] | 日/周 |
| 2 | [Secondary driver, e.g. 动力煤价格] | [¥X] | [弹性说明] | [来源] | 周 |
| 3 | [Operational metric, e.g. 产能利用率] | [X%] | [说明] | [来源] | 月/季 |
| 4 | [Sentiment metric, e.g. 股东户数] | [X万] | [说明] | [来源] | 季 |
| 5 | [Valuation metric, e.g. PE(TTM)] | [Xx] | [说明] | [来源] | 日 |

#### 6.2 Re-Evaluation Triggers

Define specific thresholds that should trigger a full re-analysis:

| 触发条件 | 阈值 | 触发后操作 |
|----------|------|------------|
| [Primary driver] 突破 | [价格/水平] | 重新计算三情景利润 |
| [Key event] 发生 | [具体事件] | 调整PE校准参照时段 |
| [Sentiment indicator] 变化 | [阈值] | 重评L2市场时机得分 |
| 财报发布 | 季报/年报 | 更新L1财务数据+重算L3利润预测 |
| [Catalyst] 兑现/失效 | — | 更新L3催化剂得分 |

#### 6.3 Next Review Date

Schedule the next full review: `[Date]` (after [next key event, e.g., Q3 earnings]).

#### 6.4 Position Sizing Map

Map the combined score and risk level to a suggested position cap. This is a guideline,
not advice — the user adjusts based on their own risk tolerance and portfolio context.

| 综合得分 | L4 风险等级 | 仓位建议 | 逻辑 |
|----------|------------|----------|------|
| ≥7.0 | 低 (L4≥7) | 可重仓，单一股票上限 20% | 公司质量好 + 风险可控，高置信度 |
| 5.5–7.0 | 中 (L4 4–7) | 标准仓，单一股票上限 10% | 有吸引力但存在不可忽视的风险 |
| 4.0–5.5 | 高 (L4<4) | 轻仓试探，单一股票上限 5% | 赔率可能吸引但风险显著 |
| <4.0 或 L1<3.5 | 任意 | **不建议参与** | 基本面致命缺陷或综合质量过低 |

**仓位逻辑说明**：得分越高、风险越低，可配置比例越高。L1<3.5 的公司（基本面致命缺陷）
无论其他层得分如何，一律不建议参与——烂公司在任何价格都不值得买。

**离散度调节（MANDATORY）**：上表给出基准仓位，再用 Phase 3 的情景离散度修正——
- 离散度 >60%：仓位上限**降一档**（重仓→标准仓、标准仓→轻仓、轻仓→回避或保持轻仓观望）
- 离散度 <30%：仓位上限可**上浮一档**（轻仓→标准仓、标准仓→重仓，20% 仍为硬顶）
- 30-60%：不调整

原理：仓位 ∝ 1/不确定性。离散度高的股票即使期望收益诱人，结果也高度发散，
重仓的代价是赌外部变量。这是波动率配仓的标准做法，比拍概率可靠。

**赔率调节**：赔率 = ∞（悲观情景仍正收益）时，仓位上限可上浮一档（20% 硬顶不变）。
中枢期望收益为负（基础中值 < 现价）时，无论得分如何，仓位建议直接改为"回避"。

#### 6.5 复盘校准模板（MANDATORY — 校准分析师自己，而不只是跟踪股票）

6.1-6.4 回答"这只股票接下来看什么"，本节回答"**我过去的判断哪里错了**"。
没有复盘，框架用一百次也不会变好；有了复盘，用户会攒出"个人偏差档案"——
信息劣势只能靠更快的自我修正弥补。

**触发时机**：到达 6.3 的审查日期、或 6.2 任一触发条件兑现时执行。

**复盘四格表**（写入报告附录或独立复盘文件 `[公司名]_[代码]_复盘_[YYYY-MM-DD].md`）：

| 复盘项 | 当时预测 | 实际结果 | 偏差 | 归因 |
|--------|---------|---------|------|------|
| 利润 | [三情景净利预测] | [实际财报] | 落在哪个情景？ | 哪个变量看错了？ |
| 股价 | [三情景目标价] | [实际股价路径] | 中枢收益兑现了多少？ | 利润偏差 or PE偏差？ |
| 评分 | [14维度得分] | — | 哪些维度看对/看错？ | 逐维度简评 |
| 离散度 | [当时估计的离散度] | [实际波动幅度] | 估计过宽还是过窄？ | 校准下次离散度 |

**归因纪律**：每个偏差必须归因到具体原因，禁止写"市场不可预测"。
利润偏差和 PE 偏差必须分开归因——利润对、PE 错 = 估值方法问题；
利润错、PE 对 = 预测能力问题；两者解决方式完全不同。

**偏差档案**：连续多份复盘后，总结反复出现的偏差模式（如"系统性高估项目确定性"
"系统性低估散户踩踏深度"），并在下一次分析对应维度时主动修正。

---

### Phase 7: Assemble the Final Report

**⚠️ L1 致命缺陷检查（在输出报告前执行）：**

```
if L1_综合得分 < 3.5:
    → 核心结论段开头必须加此警告：
    "⚠️ 公司基本面存在致命缺陷（L1得分 [X]/10），不建议以投资为目的持有。
       以下报告仍完整呈现分析过程，供研究和学习参考。"
    → 仓位映射自动归入"不建议参与"
    → 报告其余部分正常输出，不隐藏分析内容

例外：Phase 0.5 分型为「困境反转」的股票豁免此检查
（财务恶化是其前提而非缺陷），改为在核心结论中明示
"本报告为困境反转框架，L1 低分是前提而非否决项"。
```

## Report Output Format

**报告生成采用 fill→render 工作流（MANDATORY）**：

1. **写 fill-data JSON**：把全部分析内容写成一个 JSON 文件（字段契约见
   `references/fill-schema.md`）。分析和文字照常由你生成——脚本只做拼装。
   保存为 `_fill_[代码].json`（下划线前缀=临时文件）。
2. **渲染**：
   ```bash
   python "<skill目录>/scripts/render_report.py" "_fill_[代码].json"
   ```
   脚本完成：14维评分×权重计算（层分/总分/徽章色全自动）、占位符替换、
   残留校验（发现 `{{}}` 或 `【】` 残留即报错）、按规范自动命名输出
   `{公司名}_{代码}_{总分}_{日期}.html`。
3. **完成后**：删除 `_fill_[代码].json` 临时文件，告知用户报告路径和综合得分。

**为什么不用 Edit 写 HTML**：每次 Edit 都要重发整个会话上下文（实证：国电南瑞 18 次
Edit 消耗 2.2M input token，占全程 73%）。fill→render 把拼装环节的模型开销降为**零**——
你只需输出一次 ~10-15k token 的 JSON，脚本零 token 完成拼装。

**禁止事项**：
- 禁止用 Edit 逐段改 HTML（上面的 token 实证）
- 禁止单次 Write 全文 HTML（阳光电源实证：654 秒/23k tokens）
- 禁止 Read 模板来"学习结构"（结构骨架在 fill-schema.md 里，读它不要读模板）
- 禁止手算综合得分/层分（脚本算，手算易错；文件名里的总分也来自脚本计算）

**评分数据流**：你在 JSON 里只填 14 维原始得分（`scores`）+ 可选权重覆盖（`weights`，
分型调整时用）。层分、总分、徽章色、加权列、评分汇总表全部由脚本生成——
报告里的数字与文件名里的总分必然一致。

报告结构按以下顺序（每个大章节是一张 `.section` 卡片，Topbar/Hero/Disclaimer 除外；
各片段应包含的要素按此清单写入对应 `_html` 字段）：

### 1. Topbar（`.topbar`）

- 左侧：`.topbar-icon`（36×36 钢蓝色块，内放一个单字如"股"）+ `.topbar-title`（如"个股深度分析引擎"）+ `.topbar-sub`（英文副标题）
- 右侧：`.topbar-tag` 标签组（报告类型、分析框架、日期；日期用 `.active` 高亮）

### 2. Hero（`.hero`）

- `<h1>` 公司名 + 股票代码
- `.subtitle`：行业标签 + 报告日期
- `.thesis`：**一句话结论**——三情景目标价 + 核心逻辑，钢蓝左竖线引用块，涨幅用绿色标注
- **5 张指标卡**（`.metric-row` + `.metric-card`）：
  1. 当前股价（sub 行放今日涨跌幅，涨 `.up` 绿 / 跌 `.down` 红）
  2. 总市值（sub 行放总股本）
  3. PE(TTM)（sub 行放历史分位）
  4. 综合得分（badge-lg 徽章）+ sub 行放 L1-L4 各层分数
  5. 目标价区间（sub 行放涨跌幅范围）

### 3. 00 核心结论（`.section`）

- 3-5 句总结：公司关键优势、关键弱点、当前市场认知、核心投资逻辑
- 若 L1 < 3.5：开头插入 `.danger-card`，写明"⚠️ 公司基本面存在致命缺陷（L1得分 X/10），不建议以投资为目的持有"
  （困境反转型豁免此规则，改为明示"本报告为困境反转框架，L1 低分是前提而非否决项"）
- 若盈利质量红旗命中 ≥2 项：插入 `.danger-card`，写明"⚠️ 盈利质量存在红旗（[具体项]），利润真实性存疑"
- 若有显著情绪/筹码风险：用 `.warning-card` 单独提示

### 4. P0 关键利润驱动识别（`.section`）

- **开头声明股票分型**（`.section-tag` + 一句话理由，引用 Phase 0.5 识别特征）：
  如 `周期股` — "利润随油价大幅波动，2022-2025归母净利在56-113亿间震荡"
- 敏感性表格（变量/变动幅度/年利润影响/弹性等级★）+ `.source` 标注估算依据

### 5-8. L1-L4 四层评分（各一张 `.section`）

卡片头 `.section-header`：
- `.section-num`：L1 / L2 / L3 / L4
- `.section-title`：层名 + 权重 + 一句设问（如"公司本质（35%）— 什么成色"）
  （分型调整权重时，标题中写调整后的权重，如"公司本质（40%）"）
- `.section-meta`：`<span class="badge badge-blue">L1 X.XX</span>`（L4 用 badge-red）

卡片体 `.section-body`：
- 每个维度一个 `.dim-block`：`.dim-header`（维度名 + 权重 + 徽章右置）+ 分析正文 + `.verdict` 斜体判词
- **1D 财务健康**：① 盈利质量红旗清单五项检查表（每项标注"通过 ✓ / 红旗 ✗"）② 3-5 年财务
  数据表 + `.source` ③ 重资产公司附增量 ROIC 计算（投资额/年增净利/增量ROIC vs WACC）
- **2A/2C**：估值表、筹码情绪表 + `.source`
- **L3 开头**：预测前提用 `<ul>` 列 2-3 条已确认事实
- **L4 扣分制**：每个维度用 `.deduction` 逐条列出扣分项（−X + 原因），`.verdict` 写明"总计扣减X分，得Y分"；
  **L4 末尾加 Pre-mortem 卡片**（`.danger-card`）："假设两年后亏损30%，最可能的故事是……" 3-5 句空头叙事
- 每层末尾 `.layer-summary`：1-2 句层小结

### 9. 05 估值三情景（`.section`）

- 开头标注分型对应的估值方法（如"本报告按周期股框架，采用 PE 历史时段匹配法"）
- 三情景对比表：悲观（`.scenario-pess`）/ 基础（`.scenario-base`）/ 乐观（`.scenario-opt`），
  行含：**时间维度**、触发条件、关键变量、净利、EPS、PE、目标市值、目标价、较现价
- `.info-card`：**PE校准逻辑**——历史时段匹配法推导过程（参照时段、当时PE、增速、体量折扣）；
  非周期股替换为对应方法说明（PB-ROE / rNPV / PEG / 正常化利润PE）
- **三指标卡条**（`.metric-row`，3 张 `.metric-card`）：
  1. **年化中枢期望收益**（sub 行同时显示未年化总值 + 时间维度；负值红色并标注"回避"）
  2. **赔率**（公式见 Phase 3；悲观下限>现价时显示 ∞，绿色）
  3. **情景离散度**（<30% 绿色"可预测"/30-60% 橙色"中不确定"/>60% 红色"高发散"）
- 条件性定性概率提示（仅当有强外部证据时，`.warning-card`，只定性不定量）
- 条件性 DCF 表（仅当过去5年 FCF/净利润>70% 且波动率<30% 时输出）

### 10. 06 市场预期差拆解（`.section`）

- 按 Phase 3 的三档降级输出（档位A完整对照表 / 档位B反推隐含假设 / 档位C只列分歧维度）
- 卖方假设必须带来源；档位C明确标注"卖方假设未披露"
- 末尾一句话总结：本文比卖方更乐观/更悲观/基本一致 + 预期差被证伪时的修正方向

### 11. 07 同业横向对比（`.section`）

- **当前指标表**：目标公司列加粗 + 钢蓝色（`style="color:#4a6fa5;font-weight:700;"`），4-5 家可比公司 + `.source`
- **3年趋势表**：ROE/毛利率/负债率变化方向（↑绿 ↓红）+ `.source`
- **估值-质量矩阵**：`.matrix-table`，3×3 网格（ROE 高中低 × PE 低中高），目标公司格用 `.target` 高亮
- `.conclusion-box`：3-5 条同业对比结论（① ② ③ 编号列表）

### 12. 08 周期规律（`.section`，条件触发）

按 Phase 5 启动条件判断，不满足则整张卡片跳过。
- 阶段拆解表：阶段/时间/股价/PE/驱动因素
- `.conclusion-box`：3-5 条可复用规律

### 13. 09 评分汇总（`.section`）

- 14 维度加权表：层级列用 `rowspan` 合并（L1 rowspan=5，L2/L3/L4 rowspan=3），
  得分列一律用 badge 徽章，综合得分行 `style="border-top:2px solid #dde3ea;"` + badge-lg

### 14. 10 跟踪仪表盘（`.section`）

- `.section-meta` 放下次审查日期
- 关键跟踪指标表（#/指标/当前值/关注原因/更新频率）+ `.source`
- 重新评估触发条件表（触发条件/阈值/操作）
- **复盘占位提示**：写明"到达审查日或触发条件兑现时，按 Phase 6.5 复盘四格表执行复盘，
  生成 `[公司名]_[代码]_复盘_[日期].md`"

### 15. 11 仓位映射（`.section`）

- 映射表（综合得分徽章 / L4风险等级 / 基准仓位）
- **调整行**：离散度调节（>60% 降档 /<30% 升档）+ 赔率调节（∞ 升档 / 中枢收益为负→回避），
  列出最终仓位建议
- `.info-card`：一句话仓位逻辑（含离散度和赔率的理由）

### 16. 跨股对比（`.section`，条件触发）

仅当用户请求对比多只股票、或工作目录中已有多份本框架报告时输出（可独立生成）。
表格列：股票 / 分型 / 综合得分 / L1质量 / **年化中枢期望收益** / 赔率 / 离散度 / 悲观回撤 / 仓位建议。
注意：跨股对比只在同一年化口径下有意义；分型不同的股票，评分本身不完全可比，
表中必须保留分型列提醒读者。
不给出唯一"标准答案"——用 `.conclusion-box` 分列两种偏好的选择：
求稳（高L1+低离散+高赔率）vs 求弹性（高年化中枢收益+可承受离散）。

### 17. Disclaimer（`.disclaimer`）

```
本报告为AI生成的研究笔记，不构成投资建议。所有数据和结论基于公开信息，
可能存在偏差和错误。生成时间：[Timestamp]。
```

---

## Analytical Tips from Historical Reports

These insights, distilled from the Baofeng Energy analysis and applicable across companies,
should inform scoring and reasoning throughout the report:

1. **PE波动幅度远超利润波动。** 周期股最大的风险和机会都不在利润，在估值倍数。PE
   振幅往往是利润振幅的2-3倍。分析时必须同时考虑"利润可能怎么变"和"PE可能怎么变"。

2. **"事件驱动→PE先杀→利润后跌"是周期见顶的标准顺序。** PE变动领先产品价格约1-2个月。
   当重大利空事件发生时，市场先杀估值，利润下滑随后才在财报中体现。同理，反转时
   PE先涨、利润后涨。这意味着仅看当期利润判断估值会滞后。

3. **产能扩张是穿越周期的唯一硬逻辑。** 即使吨利润腰斩，产能翻倍后的总利润可能
   仍然高于以前。评估周期股时，产能轨迹比当期利润率更重要。

4. **"业绩确认"是扭转悲观定价的关键节点。** 财报不是用来验证利润是否惊艳，而是
   确认"结构性变化"（如产能扩张贡献）是否已经发生。一旦确认永久性因子，PE会向
   正常化中枢回归。

5. **PE历史波动范围是估值时必须尊重的"锚"。** 每只股票都有自己的PE波动区间——
   找出过去3-5年的PE最低值和最高值，这是市场在不同环境下给予该股票的估值边界。
   突破历史区间的PE需要"这次不一样"级别的理由。

6. **PE分位在历史最低≠便宜。** 这是周期股最常见的估值陷阱——当前PE在历史最低
   分位，仅仅是因为当前利润在历史最高。应计算"正常化利润PE"而非"峰值利润PE"。

7. **周期股铁律：利润增速越高PE越低。** 暴利被市场视为"不可持续"——市场不给溢价
   反而给折价。增速+50%时PE可能只有12-15x，而增速0%稳定利润反而能享受18-20x。
   PE和增速呈反向关系，这是周期股区别于成长股的核心特征。

8. **股东户数暴增+机构退出=典型周期股顶部信号。** 筹码结构比股价更能揭示风险。
   散户涌入、机构退出的阶段，即使基本面良好，股价也可能因筹码松动而大幅回调。

9. **筹码结构差但PE已有折价时，最惨烈的阶段可能已经过去。** 散户踩踏的杀伤力
   在于"估值从合理杀到低估"这一段。如果PE已经跌至历史底部区域，即使筹码未改善，
   下行空间也有限——市场已经定价了部分悲观预期。

10. **任何单一外部变量主导利润的公司，本质是一个"变量看涨期权"。** 如果油价/煤价/
    汇率/政策决定了>50%的利润方向，那么分析的核心不是公司本身，而是那个外部变量。
    诚实面对这一点，不要把变量预判伪装成公司分析。

---

## Error Handling & Data Degradation

When data is incomplete, use the following degradation ladder. **Never fabricate data.**
Flag all uncertain numbers with explicit markers.

**取数降级链（任一数据项通用）**：

```
em_fetch.py（data-sources.md，首选：tushare 优先、东财自动兜底）
  → 超时/失败，重试一次
    → 仍失败 → 妙想 MCP 直查（mx_ashare/hk_finance_data 等，如在工具列表；港股财务首选）
      → 仍失败 → 东财手工 curl 补特定字段（港股财务 HKF10 等，见 data-sources.md）
        → 仍失败 → 定性查询（有WebSearch用WebSearch；有妙想用 mx_finance_search_news/notice；都无则E7+10jqka已知URL）
          → 仍无 → 委派仅限边界清晰机械任务（见Step 1.3，定性调研禁委派）
            → 仍无 → 按下表降级规则处理，禁止编造
遇 429：立即停止当前路径整条链，切下一级，禁止硬挺。
```

### Degradation Ladder

| Situation | Response |
|-----------|----------|
| **Current price unavailable** | Use the most recent available close price. Mark as "约¥X (最近可获取)" with date. |
| **PE/PB data missing** | Try PB or PS as fallback valuation metric. Note: "PE数据不可得，以PB [X]x 替代评估。" |
| **Financial history < 3 years** | Work with available years. Note: "仅有[N]年财务数据，趋势判断受限。" |
| **Peer data limited** | Reduce to 2-3 best-known peers. Note: "可比公司数据有限，对比仅供参考。" |
| **Shareholder count unavailable** | Skip 2C shareholder count analysis. Use institutional ownership as partial signal. Note the gap. |
| **Historical PE range unclear** | Use sector average PE as anchor. Flag: "历史PE数据不足，以行业均值[X]x为参照。" |
| **Key profit driver sensitivity unknown** | Estimate from business logic (cost structure, revenue mix). Mark: "敏感性为基于业务结构估算，非精确值。" |
| **Critical data missing (>40% of checklist)** | Narrow the scope: produce a "快速评估" instead of full report. State what's missing and why the analysis is limited. Offer to redo when data becomes available. |

### Anti-Hallucination Rules

- **Every number must have a source** — either web search result, or marked as "基于[X]估算"
- **NEVER invent PE ranges, profit numbers, or peer metrics**
- **If a search returns no result**, state "未在公开信息中找到[X]数据" rather than guessing
- **Price targets must trace back to Phase 0 drivers and Phase 3 PE calibration** — never
  pull targets from "market convention" or generic rules of thumb
- **When multiple conflicting data points exist**, present the range and note the conflict
