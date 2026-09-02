# 东方财富公开 API 数据获取手册

本手册列出已实测验证的东方财富公开 JSON 接口（免鉴权，仅需 User-Agent 头）。

**数据源优先级（2026-08-07 起）**：`em_fetch.py` 已内置 **tushare 优先、东财兜底**双通道——
tushare 是官方会员 API（口径规范、有限流保护、PE 为标准 TTM），东财野生端点作降级备份。
token 自动发现（环境变量 `TUSHARE_TOKEN` > ZCode config 的 `mcp.servers.tushare.url`），无需手工传入。
tushare 实测权限矩阵（当前会员包）：A股全接口可用，含 `report_rc`（券商预测）、`fina_audit`（审计意见）、
`stk_holdernumber`（股东户数）、`adj_factor`（复权因子）；**无权限**：`news`（新闻快讯）、
`hk_income`/`hk_fina_indicator`（港股财务）。脚本对港股 E3 采取**尝试调用 + 失败自动降级**策略：
先试 tushare 港股接口，无权限/失败时自动 curl 东财 `RPT_HKF10_FN_MAININDICATOR` 兜底
（`em_fetch.py::_em_hkf10_annual_rows`），再不可得才提示模型走妙想 MCP；
**`hk_daily` 限流 1次/分钟** → 脚本已做单次拉全量+缓存复用（E1/E2 共用），手工调用注意间隔。

**妙想 MCP（mx-ds-mcp-stdio，模型直调层，2026-08-07 接入实测）**：东财官方免费 AI 数据服务
（stdio 型，ZCode 经 `npx mcp-remote` 桥接远程端点，认证头 `em_api_key` 作为进程参数传入），
11 个自然语言查询工具。**排障**：若会话工具列表无 `mcp__mx-ds-mcp-stdio__mx_*`，先用 `/mcp` 查连接状态——
HTTP 旧版曾因 ZCode 不携带自定义 headers 而 403 禁用，stdio 版绕开此问题。定位：
① **港股财务首选通道**（`mx_hk_finance_data`，补 tushare `hk_income` 无权限的缺口，实测壁仞 06082 可用）；
② **定性检索主力**（`mx_finance_search_news` 研报观点/评级/目标价、`mx_finance_search_notice` 公告/审计意见，
返回标题+摘要+来源+链接，质量高于 E7 站内搜索）；
③ A股定量第三层兜底（tushare 与东财均失败时）；
④ 新增能力：`mx_macro_data`（大宗商品高频价格，周期股 P0 变量直接数据源）、
`mx_stocks_screener`（可比公司初筛）、`mx_index_block_finance_data`（行业估值水位）、
`mx_ashare_finance_data`（**筹码分布**：tushare `cyq_*` 无权限时查获利比例/平均成本/集中度，实测可用）、
`mx_us_finance_data`（美股，如扩展美股报告）。
**注意**：返回为自然语言接口的半结构化 JSON（中文指标名+带单位值），指标名/口径由 AI 理解层决定、
存在漂移（实测"股东户数"查询被误解析为日度序列）——**不进 em_fetch.py 脚本**，只做模型直调；
脚本通道保持 tushare 固定字段的确定性。工具在 MCP 加载的会话生效（`mcp__mx-ds-mcp-stdio__mx_*`）。

**tushare 新增接口（2026-08-07 接入 em_fetch.py，实测有权限）**：`daily_basic` 历史序列（PE/PB 分位）、
`forecast`（业绩预告）、`express`（业绩快报）、`pledge_stat`/`stk_holdertrade`/`repurchase`（治理包）、
`disclosure_date`（财报披露计划日，给 12 跟踪仪表盘的精确日期）。

结构化数据占比约 80%，搜索仅用于定性信息。

## 通用规则

### secid 转换

| 市场 | secid 前缀 | 示例 |
|------|-----------|------|
| 上交所 (60xxxx/68xxxx) | `1.` | `1.600989`、`1.688981` |
| 深交所 (00xxxx/30xxxx) | `0.` | `0.000001`、`0.300750` |
| 北交所 (8xxxxx/4xxxxx) | `0.` | `0.830799` |

### 调用方式

- Bash: `curl -s "<URL>" -H "User-Agent: Mozilla/5.0" --max-time 15`
- 所有 6 个核心调用**应在同一条消息里并行发出**（多个工具调用），不要串行
- filter 参数中的引号需要 URL 编码：`%22`（如 `(SECUCODE%3D%22600989.SH%22)`）
- 数值缩放：行情接口的价格类字段需 **÷100**；datacenter 接口的财务字段为原始值（元）
- 接口超时/失败 → 重试一次 → 仍失败则该项降级为定性搜索（见 SKILL.md Phase 1 降级链）

---

## E1. 实时行情 + 估值（push2）

```
https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f43,f44,f45,f46,f57,f58,f60,f116,f117,f162,f167,f168,f169,f170
```

| 字段 | 含义 | 换算 |
|------|------|------|
| f43 | 最新价 | ÷100 |
| f44 / f45 / f46 | 最高 / 最低 / 今开 | ÷100 |
| f57 / f58 | 代码 / 名称 | — |
| f60 | 昨收 | ÷100 |
| f116 | 总市值（元） | ÷1亿 得"亿" |
| f117 | 流通市值（元） | ÷1亿 |
| f162 | PE(TTM) | ÷100 |
| f167 | PB | ÷100 |
| f168 | 换手率% | ÷100 |
| f169 / f170 | 涨跌额 / 涨跌幅% | ÷100 |

**覆盖清单项**：当前股价、市值、PE(TTM)、PB（Checklist #1）；
`--out` 落盘另含 pe_band/pe_pct/pe_p25/pe_p75（分位带）、risk_free、div_yield、
**timing**（现价/MA60/MA120/52 周高低，日线序列计算——时机判定小表技术面信号的唯一合法来源）

---

## E2. 历史 K 线（push2his）

```
https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56&klt={klt}&fqt=1&beg={YYYYMMDD}&end={YYYYMMDD}
```

| 参数 | 取值 |
|------|------|
| klt | 101=日线，102=周线，103=月线 |
| fqt | 0=不复权，1=前复权（分析用），2=后复权 |
| fields2 | f51日期 f52开 f53收 f54高 f55低 f56成交量 |

**用法**：
- `klt=103` + beg=5年前 → 历史 PE/价格区间、周期分析（Phase 5）、离散度参照
- `klt=101` + beg=近6个月 → MA60/MA120、近期高低点（技术面）
- PE 历史序列 ≈ 每月收盘价 × 总股本 ÷ 对应时点 TTM 净利（净利从 E3 取）

**覆盖清单项**：历史 PE 区间、关键价位、周期阶段（Checklist #9 #10）；
`pe_history.milestones` 的关键时点 PE（峰值/谷值/典型时段，3-6 个）同源取自本节月线序列

---

## E3. F10 主要财务指标（datacenter，单次调用数据密度最高）

```
https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_F10_FINANCE_MAINFINADATA&columns=ALL&filter=(SECUCODE%3D%22{CODE.SH}%22)&pageNumber=1&pageSize=12&sortTypes=-1&sortColumns=REPORT_DATE
```

pageSize=12 → 最近 12 期（3 年季报）；只看年报可加 `,REPORT_TYPE%3D%22年报%22` 到 filter。

| 字段 | 含义 | 用途 |
|------|------|------|
| REPORT_DATE_NAME | 报告期（如"2025年报"） | — |
| TOTALOPERATEREVE | 营业总收入（元） | 1D |
| PARENTNETPROFIT | 归母净利润（元） | 1D / L3 |
| KCFJCXSYJLR | 扣非净利润（元） | 1D |
| EPSJB / BPS | 每股收益 / 每股净资产 | 估值 |
| ROEJQ | ROE（加权）% | 1D |
| XSMLL / XSJLL | 销售毛利率 / 净利率 % | 1D |
| ZCFZL | 资产负债率 % | 1D |
| NETCASH_OPERATE_PK | 经营现金流净额（元） | 红旗清单 |
| **NCO_NETPROFIT** | 净利润现金含量 | **红旗清单第1项** |
| **YSZKZZTS** | 应收账款周转天数 | **红旗清单第2项**（结合营收增速） |
| **CHZZTS** | 存货周转天数 | **红旗清单第3项** |
| TOTALOPERATEREVETZ / PARENTNETPROFITTZ | 营收/净利同比 % | 趋势 |
| LD / SD | 流动比率 / 速动比率 | 1D |
| ROIC | 投入资本回报率 % | 增量 ROIC 参照 |
| TOTAL_SHARE | 总股本 | 目标价换算 |
| TOTAL_ASSETS_PK | 总资产（元） | 1D |
| RDEXPEND / PRATIO | 研发费用 / 研发占比 | 1C 技术壁垒 |
| STAFF_NUM | 员工数 | 参考 |
| FCFF_FORWARD | 预测自由现金流 | DCF 参考 |

**覆盖清单项**：3-5 年财务全项（Checklist #2）、盈利质量红旗清单全部数据、ROIC、总股本
（单次调用覆盖度最高，必发）

---

## E4. 股东户数（datacenter）

```
https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_HOLDERNUMLATEST&columns=ALL&filter=(SECURITY_CODE%3D%22{CODE}%22)&pageNumber=1&pageSize=8
```

| 字段 | 含义 |
|------|------|
| HOLDER_NUM | 最新股东户数 |
| PRE_HOLDER_NUM | 上期股东户数 |
| HOLDER_NUM_RATIO | 户数变化率 % |
| END_DATE / PRE_END_DATE | 截止日 / 上期截止日 |

pageSize=8 → 近两年户数趋势（筹码面分析需要"趋势"而非单点）

**覆盖清单项**：股东户数及变化趋势（Checklist #7 部分）

---

## E5. 一致预期 + 评级 + 目标价（datacenter）

```
https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_WEB_RESPREDICT&columns=ALL&filter=(SECURITY_CODE%3D%22{CODE}%22)&pageNumber=1&pageSize=1
```

| 字段 | 含义 | 用途 |
|------|------|------|
| RATING_ORG_NUM | 覆盖机构数 | 筹码面 |
| RATING_BUY_NUM / RATING_ADD_NUM / RATING_NEUTRAL_NUM / RATING_REDUCE_NUM | 买入/增持/中性/减持家数 | 筹码面 |
| YEAR1-4 + YEAR_MARK1-4 + EPS1-4 | 各年度一致 EPS（A=实际 E=预测） | **预期差拆解档位B** |
| DEC_AIMPRICEMAX / DEC_AIMPRICEMIN | 券商目标价最高/最低 | **预期差拆解档位B** |
| INDUSTRY_BOARD | 所属行业板块 | 1A |
| CONCEPTINDEX_BOARD | 概念标签（逗号分隔） | 快速定性 |

**卖方隐含净利** = 一致EPS × 总股本（E3 取）→ 与本文利润假设对比，完成档位B拆解。

**覆盖清单项**：分析师评级分布、一致盈利预测、一致目标价（Checklist #11 #12、Step 1.4）

---

## E6. 主营构成（datacenter，分部收入）

```
https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_F10_FN_MAINOP&columns=ALL&filter=(SECUCODE%3D%22{CODE.SH}%22)&pageNumber=1&pageSize=20&sortTypes=-1&sortColumns=REPORT_DATE
```

| 字段 | 含义 |
|------|------|
| MAINOP_TYPE | 1=按行业，2=按产品，3=按地区（分析用 2 或 1） |
| ITEM_NAME | 分部名称 |
| MAIN_BUSINESS_INCOME | 分部收入（元） |
| **MBI_RATIO** | 收入占比（**小数**，0.3177 = 31.77%） |
| **GROSS_RPOFIT_RATIO** | 分部毛利率（**小数**，0.364 = 36.4%） |
| GROSS_PROFIT（脚本归一） | 分部毛利额（元）：tushare 路径取 `bz_profit`（缺则 收入−成本）；东财路径取 MAIN_BUSINESS_RPOFIT（缺则 收入×毛利率 折算）。**分部净利润无公开数据，业务构成图利润口径=毛利** |
| REPORT_NAME / REPORT_DATE | 报告期（同一股票可能多期混排，需按最新 REPORT_DATE 过滤） |

注：tushare `fina_mainbz` 偶发同源改名重复条目（「烯烃产品」与「烯烃」两行收入/成本完全一致，
2026-09-02 宝丰实证）——脚本已按（收入,成本）签名去重，留先发行。

**覆盖清单项**：业务分部收入占比（Checklist #3）

---

## 覆盖矩阵：哪些数据 API 能给，哪些必须搜索

| Research Checklist 项 | 来源 |
|----------------------|------|
| 当前价/市值/PE/PB | **E1** |
| 3-5年财务（营收/净利/ROE/毛利率/负债率/现金流） | **E3** |
| 盈利质量红旗（现金含量/应收/存货/审计意见） | **E3**（审计意见仍需搜索） |
| ROIC / 总股本 | **E3** |
| 股东户数趋势 | **E4** |
| 一致预期/评级/目标价（预期差档位B） | **E5** |
| 历史PE区间/关键价位/周期 | **E2** |
| 主营构成 | **E6**（备选搜索） |
| 护城河/商业模式定性 | 定性搜索（环境自适应） |
| 项目进展（审批/开工/投产） | 定性搜索 |
| 催化剂/重大事件/新闻 | 定性搜索（E7 站内搜索首选） |
| 行业规模与增速 | 定性搜索 |
| 控股股东质押率 | 定性搜索（10jqka event.html 首选，或巨潮公告） |
| 关联交易/减持明细 | 定性搜索（年报/公告） |
| 实控人年龄/继任 | 定性搜索（10jqka company.html） |
| 审计意见类型 | 定性搜索（年报封面即知） |
| 同业可比公司数据 | **E1+E3 对每个 peer 重复调用**（并行） |

> "定性搜索"= 环境自适应路径：有 WebSearch 用 WebSearch；无 WebSearch 用 E7 站内搜索 +
> 10jqka/巨潮已知 URL 的 WebFetch（见 SKILL.md Phase 1 搜索纪律）。

### 估值分四件套取数（`valuation_inputs` 必填，v4.1 起脚本强制计算估值分）

四键各自的取数规则与降级标注要求：

| 键 | 取数规则 | 降级标注 |
|----|---------|---------|
| `pe_ttm` | E1 现价 PE(TTM)，脚本直接给出 | 缺失标"未获取到"，禁编造 |
| `pe_band` | 合理 PE 带 [低,高]，来自历史时段匹配校准（`scoring.md` 估值方法章） | 须写校准逻辑，不是拍脑袋区间 |
| `div_yield` | **近 12 个月现金分红合计 ÷ 现价**（%，税后口径）：A 股分红明细取 tushare `dividend` 或东财 F10 分红记录；A/H 按下方「港股股息税对照表」折算税后 | 分红数据须在 `.source` 标注来源；查不到标"未获取到" |
| `risk_free` | **中国 10 年期国债到期收益率**（%）：优先 tushare / 东财可查渠道 | 查不到时允许手工填最近公开值，并在报告 `.source` 标注来源与日期、注明"估算" |

## 降级链

```
scripts/em_fetch.py（首选：内部 tushare 优先、东财自动兜底，均结构化）
  → 均失败/缺字段 → 妙想 MCP 直查（mx_*_finance_data；港股财务首选通道）
    → 仍无 → 本手册东财手工 curl（特定字段补充，如港股财务 HKF10）
      → 仍无 → 定性查询：有WebSearch用WebSearch；有妙想用 mx_finance_search_news/notice；都无则E7+10jqka已知URL
        → 仍无 → 委派仅限边界清晰机械任务（定性调研禁委派，见SKILL.md Step 1.3）
          → 仍无 → 按 SKILL.md「数据降级与反幻觉」降级规则处理，禁止编造
```
注：搜索引擎结果页（bing/baidu/so.com 等）是**最后手段**，非默认路径。遇 429 见下方硬停规则。

---

## E7. 东方财富站内搜索（无 WebSearch 环境下的"准 WebSearch"）

**首选调用方式**：`em_fetch.py --search="关键词1,关键词2"`（已集成，无需手写接口调用）。

返回结构化 JSON：新闻/研报标题、URL、摘要、日期。`type` 可选 `cmsArticleWebOld`（新闻）、
`cmsResearchWeb`（研报）等。

### 空结果排查顺序（按此走，不要瞎试）

1. **换更短/更通用关键词重试**：去掉限定词（如"紫光股份 收购 新华三"→"新华三"）
2. **换 type 参数**：新闻空 → 试试 `cmsResearchWeb`（研报）
3. **看原始返回结构**：脚本在空结果时自动打印前 500 字符原始返回，检查是
   接口报错（json 结构异常）还是真的无结果（`{"list":[]}`）
4. **仍空 → 降级**：标注"E7 无结果，改用定性搜索替代路径"，不要死磕

### 接口格式（供参考，一般不需要手写）

```
https://search-api-web.eastmoney.com/search/jsonp?cb=cb&param={URL编码的JSON}
```

参数 JSON 结构：
```json
{"uid":"","keyword":"关键词","type":["cmsArticleWebOld"],"client":"web","clientType":"web","clientVersion":"curr","param":{"cmsArticleWebOld":{"searchScope":"default","sort":"default","pageIndex":1,"pageSize":10,"preTag":"","postTag":""}}}
```

返回结构注意：`result[type]` 可能是 `{"list":[...]}` 也可能是直接 `[...]`（已实测两种都存在）。

---

## 港股支持矩阵（港股代码 = 5 位数字，如 01880 / 06082）

脚本 `em_fetch.py` 已自动识别港股（5 位数字 → secid `116.` 前缀），E1/E2 直接可用。
**E3 财务首选妙想 MCP `mx_hk_finance_data` 直查**（模型直调，自然语言查询，实测可用）；
妙想不可用时按下方手工 curl（字段名与 A 股完全不同）。E4/E5/E6 港股不支持。

| 端点 | 港股 | 说明 |
|------|:----:|------|
| E1 行情 | ✅ 脚本自动 | **价格 ÷1000**（f43=52400→52.40 HKD）；比率（PB/换手/涨跌）÷100 同 A 股；**f162=0 表示 PE 缺失**（非真 0），脚本已显示"—" |
| E2 K线 | ✅ 脚本自动 | **港股 K 线是真实价**（53.600），脚本已按 ÷1 处理（A 股 ÷100） |
| E3 财务 | ⚠️ 手工 curl | 端点 `RPT_HKF10_FN_MAININDICATOR`，字段名与 A 股不同（见下方映射表） |
| E4 股东户数 | ❌ | 脚本已输出"港股不支持" |
| E5 一致预期 | ❌ | 实测空返回 → 预期差按档位 C 处理 |
| E6 主营构成 | ❌ | `RPT_HKF10_FN_MAINOP` 报表不存在 → 定性搜索补 |
| E7 搜索 | ✅ 脚本自动 | 关键词驱动，与代码无关 |

**港股 E3 手工取数（一次 curl 约 1 分钟）：**

```
curl -s --max-time 15 -H "User-Agent: Mozilla/5.0" "https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_HKF10_FN_MAININDICATOR&columns=ALL&filter=(SECUCODE%3D%22{CODE}.HK%22)&pageNumber=1&pageSize=10&sortTypes=-1&sortColumns=REPORT_DATE"
```

**字段映射表（HKF10 → 本框架用途）：**

| HKF10 字段 | 含义 | 框架用途 |
|-----------|------|---------|
| OPERATE_INCOME / OPERATE_INCOME_YOY | 营收 / 同比 | 1D 财务表 |
| HOLDER_PROFIT / HOLDER_PROFIT_YOY | 归母净利 / 同比 | 1D 财务表 |
| BASIC_EPS / DILUTED_EPS | 每股收益 | 估值（PE=价格÷EPS） |
| GROSS_PROFIT_RATIO | 毛利率% | 1D 财务表（数值已是百分比） |
| NET_PROFIT_RATIO | 净利率% | 1D 财务表 |
| ROE_AVG / ROE_YEARLY | ROE% | 1D 财务表 |
| DEBT_ASSET_RATIO | 资产负债率% | 1D 财务表 |
| NETCASH_OPERATE | 经营现金流 | 1D（无 NCO_NETPROFIT 现金含量字段） |
| CURRENT_RATIO | 流动比率 | 1D |
| BPS | 每股净资产 | 估值（PB=价格÷BPS） |
| ISSUED_COMMON_SHARES | 总股本 | 目标价换算 |
| TOTAL_ASSETS / TOTAL_LIABILITIES | 总资产 / 总负债 | 1D |
| REPORT_TYPE | 报告期（如"2025年年报"） | 年表行标签 |

**港股注意事项：**
- 应收/存货周转天数港股接口**不提供** → 红旗表按三态标"△ 数据不足"，不得标 ✓
- **现金含量**：HKF10 可得经营现金流（`NETCASH_OPERATE`）与净利时仍须手工算（经营现金流÷净利），
  不得无故标 △；确实 HKF10 与妙想 MCP 两条路径都不可得才允许标 △，并注明已尝试路径
  （与 `scoring.md` 港股豁免段同一口径）
- 亏损公司 PB 可能为负（优先股负债导致净资产为负，壁仞实证）——不是数据错误，报告中说明即可
- 盈利质量红旗：仅毛利率（GROSS_PROFIT_RATIO）可与同业手工核对；审计意见仍是必查项（年报查证）
- 港股 A 股同业对比可用（peers 传 A 股代码即可）

### 港股股息税对照表（A/H 比价与 DDM 必用 · 税率可配置假设）

**所有股息率、DDM 折现、A/H 比价一律用「税后股息」，不用毛股息。** 下表为常见口径的默认
假设，**具体税率以最新税收法规为准**，不同持股主体（个人/机构/港股通/直接持有）税率不同——
报告中必须显式声明持股主体与税率假设，并标注「税率以最新税收法规为准」。

| 持股路径 | 股票类型 | 股息税默认假设 | 税后股息率计算 |
|---------|---------|:------------:|---------------|
| A 股个人持股 >1 年 | A 股 | **0%**（免税） | 毛股息率 × 1 |
| A 股个人持股 1 月-1 年 | A 股 | 10% | 毛股息率 × 0.9 |
| A 股个人持股 ≤1 月 | A 股 | 20% | 毛股息率 × 0.8 |
| 港股通个人 | H 股（注册地内地） | 20% | 毛股息率 × 0.8 |
| 港股通个人 | 红筹股（注册地境外，如中国移动 00941） | **28%** | 毛股息率 × 0.72 |
| 港股直接持有（非港股通） | H 股 / 红筹 | 视持股主体与税收协定 | 单独查证 |

**使用规则：**
1. A/H 比价必须先扣税再比：表观 H 股「便宜 37%」，扣税后可能几乎打平（如中国移动：A 股免税
   4.90% vs H 股红筹 28% 税后约 4.66%）。
2. DDM 的 DPS 用税后值；红利股估值锚（股息率击球区）也用税后股息率。
3. 报告中必须写一句「股息税率为可配置假设，以最新税收法规为准」。

---

## 429 / 限流硬停止规则

任一接口返回 429 或明确的额度耗尽提示：
1. **立即停止当前路径整条降级链**，切到下一级工具/数据源
2. **禁止继续在同一路径堆调用**——紫光子代理 12:12 第一次 429 后又跑 15 分钟到第二次
   429 才停，是严格禁止的"硬挺"
3. 若所有路径均 429：停止取数，用已有数据出"快速评估"版报告，明示"取数被限流中断"

---

## 定性数据源（WebFetch 仅允许用于这些已知 URL）

以下页面结构稳定、信息密度高，是定性搜索找到线索后**精读原文**的合法目标。
除此之外不使用 WebFetch（尤其禁止抓搜索引擎结果页）。

### 同花顺 F10（basic.10jqka.com.cn）

| 页面 | URL 格式 | 内容 |
|------|---------|------|
| 公司概况 | `https://basic.10jqka.com.cn/{code}/company.html` | 主营业务、实控人、高管、历史沿革 |
| 经营分析 | `https://basic.10jqka.com.cn/{code}/operate.html` | 主营构成、产销量、项目进展 |
| 股东研究 | `https://basic.10jqka.com.cn/{code}/holder.html` | 十大股东、机构持仓、股东户数 |
| 重大事项 | `https://basic.10jqka.com.cn/{code}/event.html` | 质押、减持、关联交易、定增、处罚 |

**治理红旗清单的数据优先从 event.html 取**（质押/减持/关联交易）；company.html 取实控人年龄与背景。

### 巨潮资讯（公告原文）

- `http://www.cninfo.com.cn/new/disclosure/stock?stockCode={code}` — 公告列表
- 年报/季报原文 PDF：审计意见（年报封面/审计报告首页）、关联交易明细、减持预披露公告

### 使用规则

1. 先用定性搜索（E7 站内搜索 / WebSearch 若可用）找到线索，确认信息存在后再用 WebFetch 精读上述页面
2. 同一 URL 只抓一次
3. 10jqka 页面偶尔有反爬返回 403 → 换定性搜索结果摘要，不重试超过一次
