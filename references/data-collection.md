# 数据采集流程与纪律（Phase 1 唯一权威）

> 本文件承接 SKILL.md 的 Phase 1。**采集前必读**：脚本命令、环境工具探测、
> 定性搜索纪律、审计意见必查、卖方深挖、委派模板、Research Checklist 全部在这里。
> 端点/字段细节、港股矩阵、429 规则、定性数据源 URL 在 `data-sources.md`——
> 需要具体字段名或手工 curl 时再读它，不要混为一谈。

## Step 1.0：结构化 API 取数（首选，一条命令完成）

**优先使用捆绑脚本** `em_fetch.py`（取数+解析一步完成，只让 ~2KB 摘要进上下文）。
脚本位于**技能目录的 `scripts/` 子目录**（本文件在 `references/` 下，脚本在上一级）。
**用技能目录的绝对路径执行，禁止相对路径**（相对路径会因工作目录不同而找不到文件，
历史实证：此错误导致整套取数流程回退到 mcporter/agent-reach，浪费 25 分钟）：

```bash
python "<技能目录>\scripts\em_fetch.py" [代码] --peers=[peer1],[peer2],[peer3],[peer4]
# 例: python "C:\Users\rexji\.agents\skills\stock-deep-analysis\scripts\em_fetch.py" 600989 --peers=600309,002001
```

**妙想 MCP 直调补充**（如 `mcp__mx-ds-mcp-stdio__mx_*` 在工具列表，脚本盲区/增强项）：
- **筹码分布（筹码面）**：tushare `cyq_*` 无权限 → `mx_ashare_finance_data(query="[公司] 最新获利比例、90%成本区间、平均成本、筹码集中度")`（实测返回平均成本/集中度）
- **行业估值水位（2A）**：`mx_index_block_finance_data(query="[申万煤炭/对应行业] 最新 PE PB 及历史分位")`——从"跟自己历史比"升级为"跟行业当前比"
- **大宗商品价格（P0 第一变量）**：`mx_macro_data(query="[动力煤/布伦特原油/对应品种] 最新价格及近30日走势")`
- **港股盈利预测（E5 港股补位）**：`mx_hk_finance_data(query="[公司] 券商盈利预测 目标价")`

**无风险利率（risk_free，估值分四件套输入）**：tushare `yc_cb` 多数账号无权限（40203）→ 降级 WebSearch
"中国 10 年期国债到期收益率 最新"（中债登/中国货币网口径），取最近公开值并注明来源、日期、标"估算"；
详细规则见 `data-sources.md`「估值分四件套取数」。

**路径失败处理**：若提示找不到脚本，先在技能目录内定位（`find <技能目录> -name em_fetch.py`，
cmd 下用 `dir /s`），修正路径后重跑。**禁止因路径问题放弃脚本**——放弃脚本 = 触发
全套低效降级链。

脚本一次输出：E1 行情估值（A股附 PE/PB 5年带与当前分位、下次财报披露计划日）、
E3 五年财务年表+红旗四项判定（三态：✓真通过/✗真恶化/△数据不足）+ 有息负债与短债覆盖行、
审计意见 tushare 自动填（供 L4 红灯 a 判定）、
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

## 环境工具探测（Phase 1 第一步，做一次记录一次）

正式取数前，先确认本会话有哪些可用工具。**不要假设——用以下顺序探一次**：

1. WebSearch 是否在工具列表里？（不是"试了失败"——是列表里有没有）
2. 妙想 MCP 工具（`mcp__mx-ds-mcp-stdio__mx_*`）是否在工具列表里？（定性检索与港股财务的关键通道）
   缺席时：定性检索/筹码分布/行业估值水位走降级链，且必须在报告显式标注「妙想 MCP 缺席，
   已走降级路径」（呼应 SKILL.md Phase 1 工具检查硬门禁，禁止静默跳过）
3. curl 可用？（`curl --version` 0.3 秒即知）
4. python 可用？（脚本是否跑通即知）

把结果记在心里（如"有 curl + python，无 WebSearch"）。后续所有定性搜索路径都依据
这个探测结果选择，不要每条搜索都重探。

## 定性搜索纪律（MANDATORY — 违反任何一条都是效率事故）

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
6. **429/限流是硬停止信号**：任一工具返回 429 或明确额度耗尽提示，立即停止当前路径整条降级链切下一级（细则与"全部 429"应对见 data-sources.md「429 / 限流硬停止规则」）。
7. **搜索页抓取硬上限（仅当 WebSearch 和 E7 都不可用时的最后手段）**：单份报告搜索页 WebFetch ≤ 5 次，每次必须换查询词，抓完立即解析不再回抓。
8. **禁止静默降级**：任何降级必须同时满足 ① 已尝试 ≥2 种获取路径 ② 报告中明确标注降级原因。**禁止把"未检查"伪装成"通过"**——如"✓ API未触发"这类写法（芯原股份实证：应收/存货周转数据缺失被标成 ✓，读者误以为检查通过）。数据缺失时用三态标注：✓=真通过 / ✗=真恶化 / △=数据不足（写明缺了几期）。

## Step 1.1：定性研究（仅补 API 盲区，按环境路径执行）

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
python "<技能目录>\scripts\em_fetch.py" [代码] --search="关键词1,关键词2"
WebFetch(http://basic.10jqka.com.cn/[代码]/company.html)   # 公司概况
WebFetch(http://basic.10jqka.com.cn/[代码]/event.html)     # 治理红旗数据（质押/减持/关联交易）
WebFetch(http://basic.10jqka.com.cn/[代码]/operate.html)   # 项目进展
```

## 审计意见 = 必查项（MANDATORY）

审计意见（供 L4 红灯 a 判定，已不在 1D 红旗清单）不能停留在"需查年报"标注——那只是待办描述，不是结果。必须实际查证后填写：

0. A股首选：**em_fetch.py 已用 tushare `fina_audit` 自动填**（脚本审计意见输出直接给结论），
   脚本显示 ✓/✗ 时直接采用；显示 △ 或港股时走下述手工路径
1. 妙想 MCP（如在工具列表）：`mx_finance_search_notice(query="[公司名] 年度报告 审计意见")`——
   实测可直接命中审计报告原文段落
2. 或：E7 搜 `[公司名] 年报 审计意见`（或 `[公司名] 标准无保留意见`），
   或 WebFetch 巨潮年报公告页 `http://www.cninfo.com.cn/new/disclosure/stock?stockCode={code}`
3. 年报 PDF 封面/审计报告首页即注明意见类型（标准无保留 / 保留 / 无法表示 / 否定）
4. 查到 → 填实际结论（"✓ 标准无保留意见" 或 "✗ 保留意见"，接入 L4 红灯 a 判定）
5. 查不到（尝试 ≥2 种路径后）→ 填 `△ 审计意见 未查证（已尝试[X]路径）`，禁止直接沿用"需查年报"默认行

## Step 1.2：卖方深度深挖（预期差档位A专用）

E5 已给出一致 EPS 和目标价（档位B）。若要升级档位A（具体假设对照）：

有 WebSearch 时 `WebSearch(query="[Company Name] 券商研报 关键假设 [年份]")`；
有妙想 MCP 时 `mx_finance_search_news(query="[公司名] 券商研报 关键假设 盈利预测 [年份]")`；
预期修订方向（"近30天上调X家/下调Y家"）：`mx_finance_search_news(query="[公司名] 近一个月 盈利预测 上调 下调 评级变动")`；
前两者都无时用 E7 搜"研报"或在
`data.eastmoney.com/report/zw_stock.jshtml?infocode=...` 研报页找假设。

找到具体假设必须记录来源（券商名+日期）；找不到就停在档位B，禁止编造。

## Step 1.3：委派子代理（极少用，定性调研禁止委派）

**定性调研一律在主会话内完成**（子代理脱离技能上下文会退化为抓搜索页，见上方纪律）。
委派仅允许边界清晰的**机械子任务**（下载指定公告 PDF 并提取某张表、抓取指定 URL 列表的结构化字段），
且 prompt 必须逐字写入工具限制：

```
你只能使用：curl（东方财富 API）、WebFetch（仅已知 URL）、Read。
禁止：mcporter、r.jina.ai/s.jina.ai、抓取搜索引擎结果页、加载 agent-reach 技能、
      WebSearch（本环境不可用，不要尝试）。
遇到 429 或任何限流/额度提示：立即停止当前路径并返回已有结果，不要硬挺。
```

## Research Checklist（进入评分前逐项核对；标注首选来源）

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
