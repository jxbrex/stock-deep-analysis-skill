---
name: stock-deep-analysis
description: >
  📊 Generate a comprehensive four-layer deep analysis report for any publicly traded company.
  Use when the user asks for stock analysis, company deep dive, 深度分析, 股票分析,
  公司研究, investment research report, or wants a Baofeng Energy-style scoring report.
  Produces a structured report with L1 Company Essence, L2 Valuation, L3 Future
  Expectations, L4 Risk（红/黄灯双层）scoring framework + 独立时机轨（技术面/筹码面）,
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

- **Default**: 单文件自包含 HTML，写在当前工作目录（fill→render 工作流，见 Report Output Format）。
- **文件命名由脚本完成**：`{公司名}-{代码}-{研究分}-{时机分}-{日期}.html`
  （回测模式 `…-{时机分}-复盘-{日期}.html`；港股代码 5 位数字不带后缀，如 `06082`）。
  模型不要自己命名文件。
- **Fallback**: 用户明确要求 Markdown 时输出 `.md`，章节顺序与 HTML 版一致（评分用 🟢🟡🔴 徽章 emoji）。
- 用户要求"直接输出/快速总结"时才在对话内联输出，否则一律写文件。
- **完成后**：告知用户报告路径和研究分+时机分。

### HTML Styling — 浅色卡片建模风

**Design language**: 浅灰底 + 白色卡片 + 钢蓝（`#4a6fa5`）点缀的投资研究报告风。
Dense data, no decoration。**色值/字体/布局的全部权威定义在 `assets/report-template.html`，
模型从不手写 CSS，也不许 Read 模板"学习结构"**——写 fragment 需要的全部类名与骨架
（dim-block/badge/table/metric-card/提示卡/高亮等）见 `references/fill-schema.md`，以其为唯一契约。

**写作期只需记住的硬规则**：
- 评分数字一律用 `.badge` 徽章（色阶脚本自动，手写 fragment 时：≥7 绿 / 4.0-6.9 橙 / <4 红）
- 每张数据表正下方必须有 `<span class="source">数据来源：…</span>`；估算值标 `估算`
- 金额/户数 ≥1000 带千位符；年份、PE/PB 倍数、百分比、股价、EPS、评分不加
- 数据表格尽量不加对齐类，交给渲染器统一（数字右/长文左/短标记随列）
- 禁止暗色背景、渐变、投影、外部字体/CDN/JS

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

| 类型 | 识别特征 | 研究层权重调整（L1/L2/L3） | 估值方法 | 决定性维度 |
|------|---------|---------|---------|-----------|
| **周期股** | 利润随商品价格/产能周期大幅波动（化工、航运、养殖、煤炭、有色、钢铁、半导体、面板） | 默认权重（50/30/20），L2 估值与黄灯 b/c 是胜负手 | PE 历史时段匹配法（本框架默认） | 2A 估值、黄灯 b/c、周期位置 |
| **稳定价值/金融** | 盈利稳定、高分红、杠杆经营（银行、保险、公用事业、高速公路） | L1→55%、L3→15%（增长不重要） | **PB-ROE 框架**（银行/保险）；DDM（高股息公用事业）。PE 仅作辅助 | 1D 资产质量、1E 治理、分红可持续性 |
| **稳健成长股** | 利润增速 10-25%、可预测性强（消费、医药白马、制造业龙头） | 默认权重 | PE 匹配 + DCF（通常满足 FCF 条件）+ PEG 辅助 | 1C 护城河、3A 增长持续性、2A 估值 |
| **快速成长股** | 利润增速 >25%，利润基数尚小 | L3→30%、L2→20%、L1→50%（买点容忍度高） | PEG、远期 PE 折现、终局市值反推 | 3A 增速、1A 赛道天花板、黄灯 c 增长持续性 |
| **未盈利/管线股** | 当期亏损或利润无意义（创新药、早期科技） | L1→55%、L3→30%、L2→15% | **rNPV**（管线×成功概率×峰值销售）、P/S、EV/毛利。**禁用 PE 匹配** | 1A 赛道、1C 技术壁垒、现金消耗速率 |
| **困境反转** | 财务指标全面恶化但存在反转催化剂 | L1 评分仅作参考、红灯财务类**部分豁免**（财务烂是前提不是缺陷，但造假/立案/退市风险不豁免），L3→30% | 正常化利润 PE、重置成本、清算价值对照 | 3B/3C 反转催化剂、红灯 a 生存风险（现金流能否撑到反转） |

**分型规则：**
- 一只股票只归一个主类型；跨界时选"利润结构主导"的类型（如银行+成长 → 稳定价值）
- 分型必须在报告中写明理由（一句话，引用识别特征）
- 非周期股 → Phase 5 周期分析自动跳过（除非同时满足触发条件）
- 困境反转型豁免红灯财务类（连续亏损/ST 属前提），但造假/立案/退市风险不豁免；
  必须在核心结论中明示"本报告为困境反转框架，财务恶化是前提而非否决项"

### Phase 1: Research (MANDATORY — do NOT skip)

**数据获取优先级：取数脚本（首选）→ 环境自适应定性搜索 → 委派（仅限机械子任务，见 Step 1.3）。**

#### Step 1.0: Structured API Fetch（首选，一条命令完成）

**优先使用捆绑脚本** `em_fetch.py`（取数+解析一步完成，只让 ~2KB 摘要进上下文）。
脚本位于**本 SKILL.md 同目录的 `scripts/` 子目录**——用技能目录的绝对路径执行，
禁止用相对路径（相对路径会因工作目录不同而找不到文件，历史实证：此错误导致整套
取数流程回退到 mcporter/agent-reach，浪费 25 分钟）：

```bash
python "<skill目录>\scripts\em_fetch.py" [代码] --peers=[peer1],[peer2],[peer3],[peer4]
# 例: python "C:\Users\rexji\.agents\skills\stock-deep-analysis\scripts\em_fetch.py" 600989 --peers=600309,002001
```

**妙想 MCP 直调补充**（如 `mcp__mx-ds-mcp-stdio__mx_*` 在工具列表，脚本盲区/增强项）：
- **筹码分布（筹码面）**：tushare `cyq_*` 无权限 → `mx_ashare_finance_data(query="[公司] 最新获利比例、90%成本区间、平均成本、筹码集中度")`（实测返回平均成本/集中度）
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
**禁止给 em_fetch 加 `| tail` / `| head` 等截断管道**（新华保险实证：`| tail -120` 砍掉头部，
而输出头部正是目标公司本体数据，尾部只剩同业——截断=丢本体留同业，还得重跑一遍）。
输出本就是紧凑摘要（约 3.5KB/股），直接进上下文是安全的。
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

**定性调研一律在主会话内完成**（子代理脱离技能上下文会退化为抓搜索页，见上方纪律）。
委派仅允许边界清晰的**机械子任务**（下载指定公告 PDF 并提取某张表、抓取指定 URL 列表的结构化字段），
且 prompt 必须逐字写入工具限制：

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

#### L1: Company Essence (50% weight) — "What quality is this company?"

> **权重哲学（v2.0）**：本框架采用价值投资视角——企业质地（L1 50%）是研究的核心，
> 估值（L2 30%）与预期（L3 20%）次之。风险不再占权重，改为红/黄灯双层（见 L4）。
> 深层逻辑：宁可错过便宜的平庸公司，不妥协质地。研究分（L1+L2+L3，10分制）回答
> "这公司值不值得拥有"；时机分（技术+筹码，见 11）单独回答"现在该不该伸手"。

| # | Dimension | Weight | Key Questions |
|---|-----------|--------|---------------|
| 1A | Sector & Macro | 10% | Market size (万亿级=9-10, 千亿级=7-8, 百亿级=5-6). Growth rate (>10%=8-10, 3-10%=6-7, <3%=4-5). Is the sector strategically favored by policy? Structural tailwinds? Capacity utilization vs industry average. |
| 1B | Industry Chain Position | 10% | Cost advantage vs competitors (quantify in ¥/ton or %). Upstream self-sufficiency. Downstream pricing power — price maker or price taker? Structural cost differential expected to persist? |
| 1C | Business Model & Moat | 10% | Enumerate moats explicitly: cost advantage, scale barrier, policy/regulatory barrier, technology/IP, brand, network effects, switching costs. For each: is it widening or narrowing? Does it protect against ALL key risks or only some? |
| 1D | Financial Health | 10% | ROE trend (3yr). Gross margin trend. Debt ratio and interest coverage. FCF strength (cumulative 5yr FCF). Dividend consistency. **评"财务现状健康度"（静态体检）；边际恶化信号归黄灯 c 类。** 必须先过盈利质量红旗清单（见下方 1D 细则）；重资产公司必须算增量 ROIC。 |

**1D 盈利质量红旗清单（MANDATORY — 先于评分执行）**：

利润是不是真钱，比利润多不多更重要。以下五项全部为公开数据，逐项检查：

| 红旗项 | 口径 | 判定 |
|--------|------|------|
| 利润现金含量 | 经营现金流净额 ÷ 净利润（F10 字段 NCO_NETPROFIT） | 连续2年 <0.7 → 红旗 |
| 应收账款周转 | F10 字段 YSZKZZTS（周转天数） | 最新年 > 最早年×1.3（连续恶化变长）→ 红旗 |
| 存货周转 | F10 字段 CHZZTS（周转天数） | 最新年 > 最早年×1.3（连续恶化变长）→ 红旗 |
| 毛利率异常 | 毛利率 vs 同业均值 | 高出同业均值 >50% 且无法给出业务解释 → 红旗 |
| 审计意见 | 最新年报审计意见类型（**必查项**，按 Step 1.1 查证后填写） | 非标（保留/无法表示/否定）→ **红灯**（见 L4 红灯 a） |

**三态标注（MANDATORY）**：每项判定结果只能是三种之一——
✓=真通过（有数据且未恶化，写明数值）；✗=真恶化/真命中（写明数据）；
**△=数据不足**（写明缺几期有效数据，如"△ 应收账款周转 数据不足（2期有效）"）。
禁止把"数据缺失"标成 ✓——那会让读者误以为检查通过（芯原股份实证）。
脚本 `em_fetch.py` 的 `red_flags()` 已按此三态输出，直接采用其结果，不要改写。

**命中处理**：审计意见非标（否定/无法表示意见）→ **红灯，直接回避**（见 L4）；
其余四项每命中一项，1D 扣 1 分；命中 ≥2 项，除扣分外必须在**核心结论**中置顶提示
"⚠️ 盈利质量存在红旗（[具体项]），利润真实性存疑"。

**1D 增量 ROIC（重资产公司 MANDATORY）**：对 capex 驱动的公司（近3年年均资本开支 >
折旧摊销×1.5），必须计算最新重大项目的增量资本回报：

```
增量 ROIC = 项目达产后年增净利润 ÷ 项目总投资
```

与 WACC（无数据时用 8% 作默认）对比：增量 ROIC > WACC×1.5 → 加分依据；
增量 ROIC < WACC → 1D 扣 1 分并在判词中说明"再投资在毁灭价值"。
（例：投137亿建四期，达产年增净利15-20亿 → 增量ROIC≈11-15% > 8% WACC → 回报可观。）
| 1E | Management Team | 10% | 采用**清单锚定 + 整体判断**混合制（见下方 1E 细则）。**This is the highest-weighted dimension in L1 — management quality determines whether financials and moats sustain or erode.** |

**1E 治理评分细则（混合制）**：先按清单计算锚定分（起始 10 分），再允许 ±1 分整体判断调整。

*量化扣分清单（口径必须严格遵守）：*

| 量化项 | 口径 | 扣分 |
|--------|------|------|
| 控股股东质押比例 | 质押股数 ÷ 其持股总数 | >50% → −0.5；>70% → −1.0 |
| 近12个月减持 | 实控人+高管净减持股数 ÷ 总股本 | >0.5% → −0.5；>2% → −1.0 |
| 实控人年龄 | >68岁 且无公开继任安排 | −0.5 |
| 监管处罚 | 近3年内重大监管处罚 | −1.0 起，视严重性可加扣 |
| 正向锚 | 分红率连续3年>40%，或近12个月有回购 | +0.5（正向合计封顶 +0.5） |

（v2.0 变更：关联交易从 1E 移出，统一归黄灯 d 类评估；减持区分——经营者减持留 1E，
财务投资人减持归筹码面/时机层，大股东/实控人减持归黄灯 a 类。）

*整体判断调整（±1 分以内）*：用于清单无法覆盖的治理风险或优势——治理文化、
一言堂倾向、历史污点、继任安排质量、战略定力。调整必须在报告中写明理由；
无调整需求时直接用锚定分。清单未扣分 ≠ 治理无问题，判词中不得这样暗示。

#### L2: Valuation (30% weight) — "Is this price cheap relative to value?"

**v2.0：L2 整层只含估值，技术面/筹码面已剥离至 11 仓位与时机决策。**

| # | Dimension | Weight | Key Questions |
|---|-----------|--------|---------------|
| 2A | Valuation | 30% | Current PE vs 5yr historical range (percentile, em_fetch 已自动算). Forward PE and what profit assumptions it embeds. PB vs peers. **Critical**: distinguish "PE looks low because profits are at cyclical peak" from "genuinely undervalued." Dividend yield normalized to mid-cycle earnings. **得分应由 05 三情景的中枢期望收益与估值分位推导**——中枢为正且分位低 → 高分，而非孤立看 PE 绝对值。 |

#### L3: Future Expectations (20% weight) — "Where is profit heading?"

| # | Dimension | Weight | Key Questions |
|---|-----------|--------|---------------|
| 3A | Profit Growth | 8% | Project 1-2 year earnings. Break down: volume growth, price/margin assumptions, new project ramp-up. Acknowledge uncertainty — flag which variables are external. Provide range, not point estimate. **并入增长风险评估（原 4C）：3 年后增长是否依赖未批项目、核心业务是否结构性衰退。** |
| 3B | Project Certainty | 7% | Pipeline: approval status, construction progress, funding secured. Distinguish "under construction" (high certainty) from "planning/awaiting approval" (low certainty). Timeline to profit contribution. |
| 3C | Catalysts | 5% | Upcoming re-rating events: earnings reports, project milestones, policy changes, index inclusion. Time horizon for each. |

#### L4: Risk Assessment (不占权重 — 红/黄灯双层评估)

**v2.0：L4 不再产出分数、不再占权重，改为"风险双层评估"——红灯熔断 + 黄灯扣分。**
先查红灯（Phase 0 前置，命中即直接回避，不再深算研究分）；红灯未过再评黄灯，
黄灯从"不考虑风险研究分"（L1+L2+L3 加权）往下扣，得出最终**研究分**。

**红灯（致命风险 → 直接回避，不看分数）**，命中任一即触发：

| 红灯项 | 判定口径 |
|--------|---------|
| a) 财务造假/极高杠杆 | 财务造假实锤；商誉/净资产 >50%且标的严重不达标；控股股东质押>80%；连续亏损 ST 带帽/*ST；**审计意见否定或无法表示意见** |
| b) 立案调查/重大违规 | 实控人或公司被立案调查、重大非法违规，可能导致经营问题甚至退市 |
| c) 主营不可逆衰退 | 核心产品被禁/被主要市场抛弃（药明康德式）、行业政策毁灭性打击（新东方式）、主营业务不可逆衰退（诺基亚式） |

**黄灯（可控风险 → 扣分制，从研究分往下扣）**：不改变长期内在价值、不造成永久损害，
但提升波动/不确定性、拉长持股周期、降低胜率。**单项上限 1 分，黄灯累计扣分上限 2 分；
累计 >2 分或命中 ≥4 项 → 升红灯（直接回避）。** 四大类：

- **a) 交易与股东行为风险**（限售解禁为主；减持区分：经营者减持留 1E、财务投资人减持归筹码面、大股东/实控人减持归此类）：
  解禁占总股本 <1%（0.1）/ 1-5% 普通机构（0.4）/ >5% 首发原始股东或定增深度获利盘（0.8）
- **b) 行业与政策环境风险**：政策边际收紧（传闻 0.2 / 落地影响盈利 5-10% 0.5 / 超预期收紧影响 >10% 0.9）；
  竞争格局恶化（0.2/0.5/0.8）；上游成本大幅波动（0.2/0.4/0.7）
- **c) 盈利与财务质量风险**（**评"边际恶化信号"，与 1D 的"现状体检"区分**）：
  业绩不及一致预期（0.3/0.6/1.0）；盈利能力持续下滑（0.2/0.5/0.8）；
  经营现金流恶化（0.2/0.4/0.7）；商誉减值潜在风险（0.2/0.4/0.7）
- **d) 经营与公司治理风险**：重大诉讼仲裁（0.2/0.5/0.8）；**关联交易占比过高（0.2/0.4/0.6，从 1E 移入）**；
  公司治理瑕疵（0.2/0.4/0.7）；客户/产品集中度风险（0.2/0.4/0.7）

**L4 Pre-mortem（MANDATORY — 红/黄灯评估之后执行）**：

红/黄灯清单防的是已知风险，pre-mortem 防的是"我没看见的风险"。完成评估后，
必须写一段 3-5 句的叙事性压力测试：

> **假设两年后这笔投资亏损 30%，最可能的故事是什么？**

从第一个字开始强迫自己站在空头立场叙事（"2026年10月，XX事件发生，市场发现……"），
写完回答一个问题：**这个故事和红/黄灯清单里的风险是同一件事的概率有多大？**
如果是清单里已有风险的复述 → 说明风险识别充分；如果是清单外的新风险 → 回到红/黄灯
补评。红/黄灯答"有哪些风险"，pre-mortem 答"哪个风险最可能真的杀死我"。

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

每家同业的 ROE 与 PE 都是精确值（em_fetch 已输出），不要只归入九宫格——
在 fill JSON 顶层填 `peers_plot` 字段，由渲染脚本生成**直角坐标系散点图**
（横轴 PE、纵轴 ROE，3×3 分带背景 + 每家公司精确点位 + 目标公司高亮）：

```json
"peers_plot": {"points": [
  {"name": "目标公司", "roe": 24.7, "pe": 21.3, "target": true},
  {"name": "同业A", "roe": 15.1, "pe": 29.8}
], "pe_bands": [15, 25], "roe_bands": [8, 15]}
```

分带阈值可按行业调整（`pe_bands` / `roe_bands` 可省，默认 PE 15/25、ROE 8/15）。
仅当同业数据不足以给出精确 ROE/PE 时，才退化为在 `peers_html` 里手写 `.matrix-table` 九宫格。

分析要点不变：谁落在"高质量 + 低估值"甜区？目标公司相对公允价值线偏左还是偏右？
散点图能看出象限内的细分位置（如同样"高ROE·中PE"，贴左缘与贴右缘的性价比完全不同），
结论里要点名这种位置差异。

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
| [Sentiment indicator] 变化 | [阈值] | 重评筹码面得分（时机分） |
| 财报发布 | 季报/年报 | 更新L1财务数据+重算L3利润预测 |
| [Catalyst] 兑现/失效 | — | 更新L3催化剂得分 |

#### 6.3 Next Review Date

Schedule the next full review: `[Date]` (after [next key event, e.g., Q3 earnings]).

#### 6.4 Position Sizing Map（仓位与时机决策）

**v2.0：仓位由"研究分 + 时机分"双输入决定，不再用单一综合得分。**
研究分（L1 50+L2 30+L3 20−黄灯扣分）回答"值不值得拥有"；时机分（筹码 67% + 技术 33%）
回答"现在该不该伸手"。This is a guideline, not advice — the user adjusts based on their own
risk tolerance and portfolio context.

**先过红灯**：命中红灯（财务造假/立案/主营衰退/审计非标）→ **不建议参与**，无论研究分多高。

**双输入仓位矩阵（红灯未命中时）**：

| 研究分 | 时机分 | 判定 | 仓位建议 |
|--------|--------|------|----------|
| ≥7.0 | ≥6 | 好公司·好时机 | 可重仓，单一股票上限 20% |
| ≥7.0 | 4–6 | 好公司·中性时机 | 标准仓，上限 10% |
| ≥7.0 | <4 | 好公司·差时机 | **观察池**：轻仓 ≤5% 试探或空仓等价格/筹码修复 |
| 5.5–7.0 | ≥6 | 质地中上·好时机 | 标准仓，上限 10% |
| 5.5–7.0 | <6 | 质地中上·时机欠佳 | 轻仓试探，上限 5% |
| 4.0–5.5 | 任意 | 质地一般 | 轻仓试探，上限 5% |
| <4.0 或 红灯 | 任意 | **不建议参与** | 研究价值不足或致命风险 |

**仓位逻辑说明**：研究分定"入池资格"（质地不够格则任何时机都不碰），时机分定"建仓节奏"
（质地够格但时机差则等）。黄灯扣分已在研究分里体现（扣完 <5.5 → 自动落入轻仓/回避档）。

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

**触发时机**：到达 6.3 的审查日期、或 6.2 任一触发条件兑现时执行（回测模式下执行，见 6.6）。

**复盘四格表**（写入报告 **R 回测复盘章节**；**禁止生成独立 `_复盘.md` 文件**——md 已废止，
复盘内容只进 R 章节，两处维护必然不一致；目录里遗留的旧 `_复盘.md` 不作为模仿对象）：

| 复盘项 | 当时预测 | 实际结果 | 偏差 | 归因 |
|--------|---------|---------|------|------|
| 利润 | [三情景净利预测] | [实际财报] | 落在哪个情景？ | 哪个变量看错了？ |
| 股价 | [三情景目标价] | [实际股价路径] | 中枢收益兑现了多少？ | 利润偏差 or PE偏差？ |
| 评分 | [各维度得分] | — | 哪些维度看对/看错？ | 逐维度简评 |
| 离散度 | [当时估计的离散度] | [实际波动幅度] | 估计过宽还是过窄？ | 校准下次离散度 |

**归因纪律**：每个偏差必须归因到具体原因，禁止写"市场不可预测"。
利润偏差和 PE 偏差必须分开归因——利润对、PE 错 = 估值方法问题；
利润错、PE 对 = 预测能力问题；两者解决方式完全不同。

**偏差档案**：连续多份复盘后，总结反复出现的偏差模式（如"系统性高估项目确定性"
"系统性低估散户踩踏深度"），并在下一次分析对应维度时主动修正。

#### 6.6 回测模式（MANDATORY — 同股再分析时自动启用）

**触发**：用户要求深度分析的公司，工作目录已存在**同代码**的旧报告
（文件名 `公司名-代码-研究分-时机分-日期.html` 可解析，取日期最新者）→ 进入回测模式；
仅当用户明确要求"重新做一份全新报告"时豁免。

**执行顺序（防锚定纪律，写死）**：
1. **先独立取数、独立打分**——按正常流程跑完数据管线，不许先读旧报告的结论；
2. 再读旧报告（及同股历史复盘章节），提取：关键假设清单、偏差模式、触发条件清单；
3. **全量重写报告**（不是局部改写旧文），最后才做新旧对比标注。

**输出差异（相对正常模式）**：
- fill JSON 加 `prev`（上版 date/research/timing/target_range）+ `review_html`，两者必须成对；
- 文件名自动变为 `公司名-代码-研究分-时机分-复盘-日期.html`（脚本处理）；
- Hero 数据条下自动生成「复盘更新」对比条：研究分/时机分（含差值，脚本算）+ 目标价区间 旧→新；
- **变更高亮纪律**：用 `<span class="rev">` / `<td class="rev">`，只标三类——
  评分变化（旧→新+一句原因）、被验证/被证伪的关键假设、新增重大变量；宁缺毋滥；
- **R 回测复盘章节**（09 评分汇总后、10 跟踪仪表盘前）：复盘四格表（6.5）+
  新财报关键数据 vs 原假设对比表（项目/实际值/原假设/判定）；
- **10 跟踪仪表盘**：第一段固定为「旧触发条件核对表」（条件/阈值/实际/结论），其后才是新仪表盘；
- 旧报告文件保留不覆盖（版本链是偏差档案的原始素材）；
- **禁止生成独立 `_复盘.md` 文件**（已废止；复盘内容只进 R 章节）

---

### Phase 7: Assemble the Final Report

**⚠️ 红灯熔断检查（在输出报告前执行，对应 L4 红灯层）：**

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

## Report Output Format

**报告生成采用 fill→render 工作流（MANDATORY）**：

1. **写 fill-data JSON**：把全部分析内容写成一个 JSON 文件（字段契约见
   `references/fill-schema.md`）。分析和文字照常由你生成——脚本只做拼装。
   保存为 `_fill_[代码].json`（下划线前缀=临时文件）。
2. **渲染**：
   ```bash
   python "<skill目录>/scripts/render_report.py" "_fill_[代码].json"
   ```
   脚本完成：三层评分×权重计算（不考虑风险研究分=L1 50+L2 30+L3 20）、扣黄灯得研究分、
   时机分（筹码67+技术33）、徽章色全自动、占位符替换、
   残留校验（发现 `{{}}` 或 `【】` 残留即报错）、按规范自动命名输出
   `{公司名}-{代码}-{研究分}-{时机分}-{日期}.html`
   （回测模式自动变为 `…-{时机分}-复盘-{日期}.html`，见 6.6）。
   **渲染后检查警告**：若输出含 `⚠️ fill JSON 缺图形字段`（scenarios / peers_plot），
   必须补上字段重新渲染后再交付——缺失时 05 目标价走廊 / 07 散点图会被静默跳过。
3. **完成后**：删除 `_fill_[代码].json` 临时文件，告知用户报告路径和研究分+时机分。

**为什么不用 Edit 写 HTML**：每次 Edit 都要重发整个会话上下文（实证：国电南瑞 18 次
Edit 消耗 2.2M input token，占全程 73%）。fill→render 把拼装环节的模型开销降为**零**——
你只需输出一次 ~10-15k token 的 JSON，脚本零 token 完成拼装。

**禁止事项**：
- 禁止用 Edit 逐段改 HTML（上面的 token 实证）
- 禁止单次 Write 全文 HTML（阳光电源实证：654 秒/23k tokens）
- 禁止 Read 模板来"学习结构"（结构骨架在 fill-schema.md 里，读它不要读模板）
- 禁止手算研究分/时机分/层分（脚本算，手算易错；文件名里的研究分也来自脚本计算）

**评分数据流**：你在 JSON 里填研究层各维原始得分（`scores`：1A-1E/2A/3A-3C）+
时机层得分（`timing_scores`：技术面/筹码面）+ 黄灯扣分明细（`yellow_deductions`）+
红灯标记（`red_flag`）+ 可选权重覆盖（`weights`，分型调整时用）。
层分、不考虑风险研究分、研究分、时机分、徽章色、加权列、评分汇总表全部由脚本生成——
报告里的数字与文件名里的研究分必然一致。

报告章节顺序与**内容要点**（结构骨架/类名/字段契约一律以 `references/fill-schema.md` 为唯一权威——
写 fragment 前读它，禁止读模板"学习结构"）：

Topbar / Hero / 09 评分汇总 / Disclaimer 由脚本+模板自动完成（Hero 含研究分/时机分双卡，
回测模式自动加「复盘更新」对比条），模型只需提供对应标量字段。

- **00 核心结论**：开头双轨判词卡（研究分×时机分一句话判定）；命中红灯 → 首部 `.danger-card`
  （困境反转型改为明示框架）；盈利质量红旗命中 ≥2 项 → `.danger-card` 置顶"利润真实性存疑"；
  显著情绪/筹码风险 → `.warning-card`
- **P0**：开头声明分型（一句话理由）+ 敏感性表（★弹性等级）+ `.source`
- **L1-L4**：每维度一个 dim-block（名称+权重+徽章+正文+`.verdict` 判词），层末 `.layer-summary`。
  1D 含红旗五项三态表+3-5 年财务表（重资产附增量 ROIC）；L2 得分注明"由 05 中枢与分位推导"；
  L3 开头 `<ul>` 列 2-3 条已确认事实；L4 红灯 checklist → 黄灯四类（**固定 a→b→c→d**，
  deduction 间不加 `<br>`）→ verdict → 末尾 Pre-mortem `.danger-card`
- **05 估值三情景**：填 `scenarios`（走廊图脚本生成）+ 三情景表（scenario-table 骨架）+
  PE 校准逻辑 info-card + 三指标卡条（年化中枢/赔率/离散度）+ 条件性概率提示/DCF 表（条件见 Phase 3）
- **06 预期差**：按 Phase 3 三档输出（卖方假设必须带来源）；末尾一句话总结（更乐观/悲观/一致
  + 证伪时修正方向）
- **07 同业**：当前指标表（目标公司列加粗钢蓝）+ 3年趋势表（文字方向标注，不用箭头）+
  `peers_plot` 散点（勿再手写九宫格）+ `.conclusion-box` 3-5 条结论
- **08 周期**：满足 Phase 5 条件才输出；阶段拆解表 + `.conclusion-box` 可复用规律
- **R 回测复盘**（回测模式专属）：复盘四格表 + 新财报数据 vs 原假设对比表（见 6.5/6.6）
- **10 跟踪仪表盘**：跟踪指标表 + 触发条件表；回测模式第一段固定为「旧触发条件核对表」；
  末尾复盘占位提示（按 6.5/6.6 进入回测模式，不再生成独立 md）
- **11 仓位与时机**：时机判定小表（技术面/筹码面/时机分，渲染器自动补 timing-table 类）→
  双输入仓位映射表 → 离散度/赔率调整行 → `.info-card` 一句话决策逻辑
- **跨股对比**（条件触发）：仅用户要求多股对比、或目录已有多份本框架报告时输出；
  模板无独立章节，附加在 `position_html` 末尾。列：股票/分型/研究分/时机分/L1/年化中枢收益/
  赔率/离散度/悲观回撤/仓位建议；只在同一年化口径下可比，分型列必须保留；
  `.conclusion-box` 分列"求稳 vs 求弹性"两种选择，不给唯一答案

---

## Analytical Tips

宝丰能源报告提炼的 10 条分析经验（PE 波动领先利润、周期股增速与 PE 反相关、
筹码顶部信号等），在 Phase 2 评分与 Phase 3 估值时参考——
见 `references/analytical-tips.md`（评分前读一次即可，不必每次重读）。

---

## Error Handling & Data Degradation

When data is incomplete, use the following degradation ladder. **Never fabricate data.**
Flag all uncertain numbers with explicit markers.
取数路径与降级顺序见 Phase 1（Step 1.0 → 妙想 MCP → 手工 curl → 定性查询 → 委派），
遇 429 立即切下一级；本节只规定"实在拿不到"时的处理方式：

### Degradation Ladder

| Situation | Response |
|-----------|----------|
| **Current price unavailable** | Use the most recent available close price. Mark as "约¥X (最近可获取)" with date. |
| **PE/PB data missing** | Try PB or PS as fallback valuation metric. Note: "PE数据不可得，以PB [X]x 替代评估。" |
| **Financial history < 3 years** | Work with available years. Note: "仅有[N]年财务数据，趋势判断受限。" |
| **Peer data limited** | Reduce to 2-3 best-known peers. Note: "可比公司数据有限，对比仅供参考。" |
| **Shareholder count unavailable** | Skip 筹码面 shareholder count analysis. Use institutional ownership as partial signal. Note the gap. |
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
