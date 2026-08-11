# fill-data JSON 契约（render_report.py 输入规范）

渲染流程：模型把全部分析内容写成一个 JSON 文件 → `python render_report.py fill.json`
→ 脚本完成评分计算 + 占位符替换 + 校验 + 自动命名输出。**模型不需要碰 HTML 文件本身。**

## 顶层字段

| 字段 | 必填 | 说明 |
|------|:----:|------|
| `company` | ✓ | 公司名（如 "宝丰能源"） |
| `code` | ✓ | 代码（如 "600989"；港股 5 位数字如 "06082"） |
| `date` | ✓ | 报告日期 YYYY-MM-DD |
| `subtitle` | ✓ | 副标题（行业标签 · 一句话定位） |
| `scores` | ✓ | **研究层** 9 维得分对象：`{"1A":8.0,"1B":7.0,"1C":8.0,"1D":8.0,"1E":7.0,"2A":5.5,"3A":7.5,"3B":8.0,"3C":7.0}`（v2.0：无 2B/2C/4A/4B/4C） |
| `weights` | 可选 | 研究层维度权重覆盖（分型调整时用），9 项之和必须=100 |
| `timing_scores` | ✓ | **时机层**得分对象：`{"2C":2.5,"2B":6.0}`（筹码/技术） |
| `timing_weights` | 可选 | 时机层权重覆盖，默认 `{"2C":67,"2B":33}`，和必须=100 |
| `yellow_deductions` | ✓ | **黄灯扣分明细**数组：`[{"label":"关联交易占比过高","points":0.6}, ...]`；无扣分填 `[]` |
| `red_flag` | 条件 | **红灯标记**：命中红灯填具体项（如 "审计意见非标：无法表示意见"），未命中省略或填 `""` |
| `thesis_html` | ✓ | Hero 一句话结论（含 `<span class="scenario-pess/base/opt">` 三情景价） |
| `price` / `mcap` / `pe_ttm` | ✓ | Hero 指标卡数值（纯数字字符串） |
| `price_sub_html` / `mcap_sub` / `pe_sub` | ✓ | 指标卡 sub 行（可含 `<span class="up/down">`） |
| `horizon` | ✓ | 目标价时间维度（如 "12个月"） |
| `target_range` / `target_sub_html` | ✓ | 目标价区间卡 |
| `conclusion_html` | ✓ | 00 核心结论正文（HTML 片段，**开头放双轨判词卡**——研究分×时机分判定） |
| `p0_html` | ✓ | P0 关键利润驱动（含分型声明+敏感性表+info-card） |
| `l1_html` … `l3_html` | ✓ | L1-L3 研究层评分正文片段 |
| `l4_html` | ✓ | **L4 风险双层**正文片段（红灯 checklist + 黄灯扣分表 + Pre-mortem 卡） |
| `valuation_method` / `stock_type` | ✓ | 05 卡片头（如 "PE历史时段匹配法" / "周期股"） |
| `valuation_html` | ✓ | 05 正文（三情景表+校准逻辑+三指标卡条） |
| `gap_tier` / `gap_html` | ✓ | 06 预期差（档位 A/B/C + 正文） |
| `peers_meta` / `peers_html` | ✓ | 07 同业对比 |
| `cycle_html` | 条件 | 08 周期规律；**空字符串或省略 → 整张卡片自动删除** |
| `cycle_meta` | 条件 | 08 触发条件说明 |
| `next_review` / `dash_html` | ✓ | 10 跟踪仪表盘 |
| `position_html` | ✓ | 11 仓位与时机决策（**先时机判定小表（2B/2C 分析），再双输入仓位映射表**） |
| `top_icon` | 可选 | 顶部色块单字（默认取 company 首字） |
| `gen_time` | 可选 | 默认用 date |
| `calib_note` | 可选 | 免责声明后缀（如 "PE估值经历史时段匹配法回测校准"） |

## 片段内 HTML 骨架（模型在 fragment 里照用）

**维度块（L1-L4 每个维度一个）：**
```html
<div class="dim-block">
  <div class="dim-header">
    <span class="dim-name">1A 赛道与宏观</span>
    <span class="dim-weight">7%</span>
    <span class="score-line" style="margin-left:auto;margin-bottom:0;"><span class="badge badge-green">8.0</span></span>
  </div>
  <p>分析正文……</p>
  <div class="verdict">一句话判词。</div>
</div>
```

**徽章色规则**：≥7.0 → `badge-green`；4.0-6.9 → `badge-orange`；<4.0 → `badge-red`。

**层小结（每层末尾）**：`<div class="layer-summary"><strong>L1小结：</strong>……</div>`

**L4 扣分行**：`<span class="deduction">−3 扣分原因……</span>`

**盈利质量红旗行**（1D 财务健康，五项检查）：每行用三态 span 包裹行首（✓绿 / ✗红 / △橙）：

```html
<span class="flag-ok">✓ 利润现金含量</span>（最低 1.20，五年均 >1）<br>
<span class="flag-bad">✗ 应收账款周转</span> 恶化（12→16 天，+33%）<br>
<span class="flag-na">△ 毛利率</span> 35.1%（待与同业对照）
```

**提示卡**：`.info-card`（蓝/逻辑说明）`.warning-card`（橙/警示）`.danger-card`（红/致命警告+pre-mortem）

**数据来源标注**：`<span class="source">数据来源：……</span>`（每张数据表下方必须有）

**表格**：`<div class="table-scroll"><table>…</table></div>`，数字列 `<td class="num">`，居中列 `<td class="center">`。
**表头必须与数据列同对齐**：数字列表头 `<th class="num">`、居中列表头 `<th class="center">`（与对应 `<td>` 同规则）；
纯文字列表头保持默认左对齐，不要加类。
**渲染器已加对齐自动修正**（按列统计 td 类给 th 配对，行头 th/rowspan/colspan 均处理）——
模型写错表头类不再影响最终输出，但仍建议按规则写对（保持 fragment 自描述）。
**宽表首列冻结**（≥5 列的数据表，如 07 同业当前指标表必用）：`<table class="freeze-first">`——窄屏横向滚动时首列常驻。

**数字千位符**：金额/户数类数值 ≥1000 必须带千位符（`2,949.2 亿`、`9,536.8 亿`、`188,153 户`）；
年份（2025）、PE/PB 倍数、百分比、股价、EPS、评分**不加**。em_fetch 输出已带千位符，fragment 手写数字照此规则。

**估值-质量矩阵**（07 同业对比）：`<table class="matrix-table">`，表头**不用加任何类**（模板 CSS 强制表头/表体一律居中），目标公司格用 `class="target"`：

```html
<table class="matrix-table">
  <thead><tr><th>ROE \ PE</th><th>低PE(&lt;12x)</th><th>中PE(12-20x)</th><th>高PE(&gt;20x)</th></tr></thead>
  <tbody>
    <tr><td><strong>高ROE(&gt;15%)</strong></td><td>—</td><td>—</td><td>同业A(16%/40x)</td></tr>
    <tr><td><strong>中ROE(8-15%)</strong></td><td class="target">目标公司(9%/11x)</td><td>同业B(11%/15x)</td><td>同业C(11%/21x)</td></tr>
    <tr><td><strong>低ROE(&lt;8%)</strong></td><td>—</td><td>—</td><td>—</td></tr>
  </tbody>
</table>
```

## 评分计算规则（脚本执行，模型不要手算）

- **研究层（L1/L2/L3）**：层分 = Σ(维度分×权重) ÷ 层权重；不考虑风险研究分 = Σ(维度分×权重) ÷ 100
- **研究分（最终）** = 不考虑风险研究分 − 黄灯扣分合计（`yellow_deductions` 的 points 求和）
- **时机分** = Σ(时机维度分×权重) ÷ 100（2C 筹码 67% + 2B 技术 33%）
- 研究层/时机层权重总和各自≠100 → 脚本报错拒绝渲染
- scores 缺研究层维度 → 脚本报错列出缺失键
- 徽章色脚本自动按分数分配，模型无需关心汇总表；双轨判定词（`VERDICT_DUAL`）脚本按
  研究分×时机分阈值自动生成（红灯优先）

## 输出

- 自动命名：`{company}_{code}_{研究分}_{date}.html`，写在 fill JSON 同目录
- 残留 `{{...}}` 或 `【...】` → 脚本报错退出，报告不生成
- 章节片段为空 → 脚本警告列出（CYCLE_HTML 除外，空=删章节）
