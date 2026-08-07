# stock-deep-analysis — 个股四层深度分析技能

基于四层评分框架的个股深度分析 ZCode 技能，生成单文件 HTML 研究报告。

> ⚠️ 本技能产出的报告为 AI 生成的研究笔记，不构成投资建议。

## 功能

- **四层评分框架**：L1 公司本质(35%) / L2 市场时机(25%) / L3 未来预期(20%) / L4 风险评估(20%)，
  14 个加权维度，L4 采用扣分制
- **股票分型**：周期股 / 稳定价值金融 / 稳健成长 / 快速成长 / 未盈利管线 / 困境反转，
  分型自动调整权重与估值方法
- **三情景估值**：悲观/基础/乐观 + 历史时段匹配 PE 校准 + 年化中枢收益/赔率/离散度三指标
- **预期差拆解**：与卖方一致预期的分歧逐项对照（A/B/C 三档降级）
- **盈利质量红旗**：现金含量/应收/存货/毛利率异常/审计意见五项检查（三态标注，禁伪装通过）
- **治理混合制评分**：质押/关联交易/减持/年龄/处罚量化清单 + ±1 判断调整
- **跟踪仪表盘**：关键指标 + 触发条件 + 复盘四格表校准
- **数据获取**：**tushare 优先、东方财富公开 API 自动兜底**双通道（em_fetch.py 内置）：
  行情/K线/财务/股东户数/券商预测/审计意见/主营构成；tushare token 自动发现
  （`TUSHARE_TOKEN` 环境变量 > ZCode config 的 `mcp.servers.tushare.url`），无需手工传入；
  A 股 + 港股（5 位代码自动识别），东财 E7 站内搜索作为无 WebSearch 环境的定性搜索路径
- **妙想 MCP 模型直调层**（可选，东财官方免费 AI 数据服务）：港股财务首选
  （`mx_hk_finance_data`）、定性检索主力（`mx_finance_search_news`/`notice` 研报观点与公告）、
  大宗商品价格（`mx_macro_data`）；自然语言接口，指标名存在漂移，只做模型直调不进脚本

## 目录结构

```
stock-deep-analysis/
├── SKILL.md                    # 技能主体：工作流 + 评分框架 + 数据纪律
├── references/
│   ├── data-sources.md         # 东方财富 API 端点手册 + 港股支持矩阵 + 降级链
│   └── fill-schema.md          # fill→render 工作流的 JSON 契约
├── scripts/
│   ├── em_fetch.py             # 一键取数（E1-E7 全端点，A股/港股）
│   └── render_report.py        # fill JSON → 最终 HTML（评分计算+占位符替换+校验）
└── assets/
    └── report-template.html    # 报告模板（唯一 CSS 权威版本）
```

## 报告生成流程（fill→render）

1. 调研取数：`python em_fetch.py [代码] --peers=... --search="关键词"`
2. 四层评分 + 三情景估值（分析在主会话完成）
3. 写 fill-data JSON（契约见 `references/fill-schema.md`）
4. 渲染：`python render_report.py _fill_[代码].json`
   ——评分表、徽章色、文件名（含综合得分）全部脚本计算，零拼装 token

## 安装

将 `stock-deep-analysis/` 目录放入 ZCode 技能目录：
- 用户级：`~/.agents/skills/` 或 `~/.zcode/skills/`
- 项目级：`<project>/.zcode/skills/` 或 `<project>/.agents/skills/`

依赖：Python 3.8+、curl（Windows 10+ 自带）。

## 免责声明

本技能及产出的所有报告仅供个人研究学习使用，不构成任何投资建议。
数据来自公开接口，可能存在延迟、缺失或错误；投资决策请以官方披露为准。
