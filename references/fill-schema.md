# fill-data JSON 契约（render_report.py 输入规范）

渲染流程：模型把全部分析内容写成一个 JSON 文件 → `python render_report.py fill.json`
→ 脚本完成评分计算 + 占位符替换 + 校验 + 自动命名输出。**模型不需要碰 HTML 文件本身。**

## JSON 书写硬规则（违反即解析失败）

- **禁止裸反斜杠**：fragment 里任何 `\` 在 JSON 字符串中必须写成 `\\`（`\ `、`\P` 等都是非法转义）。
  表头、分隔符一律用全角 `＼` 或 `/`，从源头避开反斜杠（见 07 矩阵示例）。
- 字符串内换行用 `\n`，不要直接回车；双引号用 `\"` 或改用中文引号「」。
- 写完后可用 `python -c "import json;json.load(open('fill.json',encoding='utf-8'))"` 自检。
- render_report.py 已带非法转义自动修复（兜底+告警），但不保证覆盖所有写法，仍以写对为准。

## 顶层字段

| 字段 | 必填 | 说明 |
|------|:----:|------|
| `company` | ✓ | 公司名（如 "宝丰能源"） |
| `code` | ✓ | 代码（如 "600989"；港股 5 位数字如 "06082"） |
| `date` | ✓ | 报告日期 YYYY-MM-DD |
| `subtitle` | ✓ | 副标题（行业标签 · 一句话定位） |
| `scores` | ✓ | **研究层** 9 维得分对象：`{"1A":8.0,"1B":7.0,"1C":8.0,"1D":8.0,"1E":7.0,"2A":5.5,"3A":7.5,"3B":8.0,"3C":7.0}`（v2.0：无 2B/2C/4A/4B/4C） |
| `weights` | 可选 | 研究层维度权重覆盖（分型调整时用），9 项之和必须=100 |
| `timing_scores` | ✓ | **时机层**得分对象：`{"筹码面":2.5,"技术面":6.0}`（旧键名 2C/2B 渲染器仍兼容并告警） |
| `timing_weights` | 可选 | 时机层权重覆盖，默认 `{"筹码面":67,"技术面":33}`，和必须=100 |
| `yellow_deductions` | ✓ | **黄灯扣分明细**数组：`[{"label":"关联交易占比过高","points":0.6}, ...]`；无扣分填 `[]` |
| `red_flag` | 条件 | **红灯标记**：命中红灯填具体项（如 "审计意见非标：无法表示意见"），未命中省略或填 `""` |
| `thesis_html` | ✓ | Hero 一句话结论（含 `<span class="scenario-pess/base/opt">` 三情景价） |
| `price` / `mcap` / `pe_ttm` | ✓ | Hero 指标卡数值（纯数字字符串） |
| `price_sub_html` / `mcap_sub` / `pe_sub` | ✓ | 指标卡 sub 行（可含 `<span class="up/down">`） |
| `horizon` | ✓ | 目标价时间维度（如 "12个月"） |
| `target_range` / `target_sub_html` | ✓ | 目标价区间卡 |
| `conclusion_html` | ✓ | 00 核心结论正文（HTML 片段，**开头放双轨判词卡**——研究分×时机分判定；命中红灯 → 首部 `.danger-card`；红旗命中≥2 项 → `.danger-card` 置顶"利润真实性存疑"；显著情绪/筹码风险 → `.warning-card`） |
| `p0_html` | ✓ | P0 关键利润驱动（含分型声明+敏感性表+info-card） |
| `l1_html` … `l3_html` | ✓ | L1-L3 研究层评分正文片段（1D 含红旗五项三态表+财务年表；L2 得分注明"由 05 中枢与分位推导"；L3 开头 `<ul>` 列 2-3 条已确认事实） |
| `l4_html` | ✓ | **L4 风险双层**正文片段（红灯 checklist + 黄灯扣分表 + Pre-mortem 卡） |
| `valuation_method` / `stock_type` | ✓ | 05 卡片头（如 "PE历史时段匹配法" / "周期股"） |
| `scenarios` | ✓ | **三情景结构化数据**（脚本生成 05 顶部"目标价走廊"图；**缺失=图不生成+渲染器警告**）：`[{"key":"pess","label":"悲观","low":294,"high":331},{"key":"base","label":"基础","low":442,"high":502},{"key":"opt","label":"乐观","low":562,"high":648}]`；现价自动取 `price`，中枢/涨跌幅脚本计算 |
| `valuation_html` | ✓ | 05 正文（三情景表+校准逻辑+三指标卡条） |
| `gap_tier` / `gap_html` | ✓ | 06 预期差（档位 A/B/C + 正文；卖方假设必须带来源；**末尾一句话总结**：比卖方更乐观/悲观/一致 + 证伪时修正方向） |
| `peers_meta` / `peers_html` | ✓ | 07 同业对比（当前指标表+趋势表+`.conclusion-box` 3-5 条结论；目标公司列 `style="color:#4a6fa5;font-weight:700;"`） |
| `peers_plot` | ✓ | **估值-质量散点图数据**（脚本生成 07 顶部 SVG 散点，替代 3×3 表格矩阵；**缺失=图不生成+渲染器警告**，仅同业数据实在凑不齐时才允许省略并手写 matrix-table 兜底）：`{"points":[{"name":"宁德时代","roe":24.7,"pe":21.3,"target":true},{"name":"比亚迪","roe":15.1,"pe":29.8}],"pe_bands":[15,25],"roe_bands":[8,15]}`；bands 可省（默认 PE 15/25、ROE 8/15），直接给数组亦可 |
| `cycle_html` | 条件 | 08 周期规律（阶段拆解表 + `.conclusion-box` 可复用规律）；**空字符串或省略 → 整张卡片自动删除** |
| `cycle_meta` | 条件 | 08 触发条件说明 |
| `next_review` / `dash_html` | ✓ | 10 跟踪仪表盘（跟踪指标表+触发条件表；**回测模式第一段固定为旧触发条件核对表**；末尾复盘占位提示指向 SKILL.md 6.5/6.6） |
| `position_html` | ✓ | 11 仓位与时机决策（**先时机判定小表（技术面/筹码面分析），再双输入仓位映射表**；时机判定小表无需手动加类，渲染器自动补 `timing-table`——除末列"依据"外不换行。**跨股对比**（条件触发，见 SKILL.md 输出要点）附加在本字段末尾） |
| `top_icon` | 可选 | 顶部色块单字（默认取 company 首字） |
| `gen_time` | 可选 | 默认用 date |
| `calib_note` | 可选 | 免责声明后缀（如 "PE估值经历史时段匹配法回测校准"） |
| `prev` | 回测必填 | **回测模式上版锚点**：`{"date":"2026-08-08","research":7.87,"timing":5.50,"target_range":"396-832"}`；填入即进入回测模式（文件名自动加"复盘"，Hero 自动生成对比条，差值脚本计算） |
| `review_html` | 回测必填 | **R 回测复盘章节**正文（复盘四格表 + 新财报关键数据 vs 原假设对比表）；prev 与 review_html 必须成对出现，缺一则渲染器告警。**禁止另存独立 `_复盘.md`**——复盘内容只进 R 章节 |

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

**L4 扣分行**：`<span class="deduction">−3 扣分原因……</span>`（`.deduction` 是块级元素，**两条之间不要加 `<br>`**，渲染器会直接隐藏这种多余换行；四类顺序固定 a→b→c→d，乱序会触发渲染器告警）

**盈利质量红旗行**（1D 财务健康，五项检查）：每行用三态 span 包裹行首（✓绿 / ✗红 / △橙）：

```html
<span class="flag-ok">✓ 利润现金含量</span>（最低 1.20，五年均 >1）<br>
<span class="flag-bad">✗ 应收账款周转</span> 恶化（12→16 天，+33%）<br>
<span class="flag-na">△ 毛利率</span> 35.1%（待与同业对照）
```

**提示卡**：`.info-card`（蓝/逻辑说明）`.warning-card`（橙/警示）`.danger-card`（红/致命警告+pre-mortem）

**变更高亮 `.rev`**（回测模式专属，淡黄底）：只标三类——**评分变化**（旧→新+一句原因）、
**被验证/被证伪的关键假设**、**新增重大变量**。用法：行内 `<span class="rev">2026E净利 930→985亿</span>`，
表格整格 `<td class="rev">`。满屏高亮=没高亮，宁缺毋滥。

**指标卡条**（05 三指标卡、Hero 数据卡同款骨架；**内层类名是 `label`/`value`/`sub`，
不要自创 metric-label/metric-value——渲染器虽会归一，但写对才是自描述**）：

```html
<div class="metric-row">
  <div class="metric-card">
    <div class="label">年化中枢期望收益</div>
    <div class="value up">+21.0%</div>
    <div class="sub">基础中值 472 ÷ 现价 390.4 − 1（12个月）</div>
  </div>
  <div class="metric-card">
    <div class="label">赔率（上行/下行）</div>
    <div class="value">2.32</div>
    <div class="sub">(614−461.6)÷(461.6−396)；&gt;1.5 为良好不对称</div>
  </div>
  <div class="metric-card">
    <div class="label">情景离散度</div>
    <div class="value down">46.8%</div>
    <div class="sub">(乐观中值−悲观中值)÷现价；&gt;60% 高发散降仓一档</div>
  </div>
</div>
```

`value` 着色：正收益/利多 `class="value up"`（绿），负值/利空 `class="value down"`（红），中性不加。

**数据来源标注**：`<span class="source">数据来源：……</span>`（每张数据表下方必须有）

**表格**：`<div class="table-scroll"><table>…</table></div>`，数字列 `<td class="num">`，居中列 `<td class="center">`。
**表头必须与数据列同对齐**：数字列表头 `<th class="num">`、居中列表头 `<th class="center">`（与对应 `<td>` 同规则）；
纯文字列表头保持默认左对齐，不要加类。
**渲染器已加对齐自动修正**（按列统计 td 类给 th 配对，行头 th/rowspan/colspan 均处理）——
模型写错表头类不再影响最终输出，但仍建议按规则写对（保持 fragment 自描述）。
**数值列（num 列）内的 td 也会被统一**：数字/含数字短值/短标记（如"基础""12个月"）统一右对齐；
全文字行（如"核心业务"行）与长文格（含句读或超 4 字纯文字，如"触发条件"）去类左对齐。
模型最省心的做法：**数据格一律不加类，交给渲染器**。
**宽表首列冻结**（≥5 列的数据表，如 07 同业当前指标表必用）：`<table class="freeze-first">`——窄屏横向滚动时首列常驻。

**数字千位符**：金额/户数类数值 ≥1000 必须带千位符（`2,949.2 亿`、`9,536.8 亿`、`188,153 户`）；
年份（2025）、PE/PB 倍数、百分比、股价、EPS、评分**不加**。em_fetch 输出已带千位符，fragment 手写数字照此规则。

**估值-质量散点图**（07 同业对比）：填顶层 `peers_plot` 字段，脚本生成直角坐标系散点图
（横轴 PE、纵轴 ROE，每家同业一个精确点位，目标公司钢蓝高亮，3×3 分带背景）。
**坐标/刻度/标签位置全部由脚本计算，模型不要手写 SVG 或估算像素。**
**已填 `peers_plot` 就不要再写 matrix-table**——两图并存冗余，渲染器检测到会直接删除手写九宫格并告警。

**估值-质量矩阵表（兜底）**：仅当 `peers_plot` 无法给出（如同业数据不全）时，
在 `peers_html` 里写 `<table class="matrix-table">` 3×3 表格，表头**不用加任何类**，目标公司格用 `class="target"`：

```html
<table class="matrix-table">
  <thead><tr><th>ROE＼PE</th><th>低PE(&lt;12x)</th><th>中PE(12-20x)</th><th>高PE(&gt;20x)</th></tr></thead>
  <tbody>
    <tr><td><strong>高ROE(&gt;15%)</strong></td><td>—</td><td>—</td><td>同业A(16%/40x)</td></tr>
    <tr><td><strong>中ROE(8-15%)</strong></td><td class="target">目标公司(9%/11x)</td><td>同业B(11%/15x)</td><td>同业C(11%/21x)</td></tr>
    <tr><td><strong>低ROE(&lt;8%)</strong></td><td>—</td><td>—</td><td>—</td></tr>
  </tbody>
</table>
```

**3年趋势表**（07 同业对比）：方向标注**一律用文字**（升/降/缓升/缓降/大升/大降/平），
**不用单个箭头**（↑↓ 不直观）。幅度约定：|Δ|<0.5pct → 平；0.5-2pct → 缓升/缓降；
2-5pct → 升/降；>5pct → 大升/大降。方向词用 `<span class="up/down">` 着色，
**颜色按指标语义**（ROE/毛利率/净利率：升绿降红；负债率：降绿升红）：

```html
<tr><td>ROE变化</td><td>22.1%→20.0%（<span class="down">缓降</span>）</td><td>13.1%→19.4%（<span class="up">升</span>）</td><td>…</td></tr>
<tr><td>负债率变化</td><td>70.6%→61.9%（<span class="up">降</span>）</td><td>60.4%→64.2%（<span class="down">升</span>）</td><td>…</td></tr>
```

**估值三情景**（05）：开头由脚本按顶层 `scenarios` 字段自动渲染「目标价走廊」图（竖向柱：
x 轴=悲观/基础/乐观三列，与三情景表列方向一致；y 轴=价格，现价水平虚线，柱顶标注中枢值与涨跌幅），
是本章视觉锚点；其后 `valuation_html` 正文按"三情景表 → 校准逻辑 → 三指标卡条"展开。

**三情景对比表**（**统一纵向列排列**——指标在行、情景在列，参照中国移动报告；
表格加 `class="scenario-table"`：首列指标名不换行）：
数值行 `<td class="num">`，纯文字行（时间维度/触发条件）不加类，情景列表头 `th class="center"`：

```html
<div class="table-scroll"><table class="scenario-table">
  <thead><tr><th>指标</th><th class="center">悲观情景</th><th class="center">基础情景</th><th class="center">乐观情景</th></tr></thead>
  <tbody>
    <tr><td>时间维度</td><td class="center">12个月</td><td class="center">12个月</td><td class="center">12-24个月</td></tr>
    <tr><td>触发条件</td><td>……</td><td>……</td><td>……</td></tr>
    <tr><td>2026E净利</td><td class="num">1,300 亿（-5.2%）</td><td class="num">1,350 亿（-1.5%）</td><td class="num">1,400 亿（+2.1%）</td></tr>
    <tr><td>EPS</td><td class="num">6.00</td><td class="num">6.23</td><td class="num">6.46</td></tr>
    <tr><td>PE</td><td class="num">17x</td><td class="num">15x</td><td class="num">14x</td></tr>
    <tr><td>目标价</td><td class="num">……</td><td class="num">……</td><td class="num">……</td></tr>
    <tr><td>较现价</td><td class="num">……</td><td class="num">……</td><td class="num">……</td></tr>
  </tbody>
</table></div>
```
（禁止把情景放成行、指标放成列——统一指标纵列、情景横排。
**渲染器已加方向自动校正**：检测到"情景在行"的旧写法会自动转置并告警，但仍建议按骨架写对。）

## 评分计算规则（脚本执行，模型不要手算）

- **研究层（L1/L2/L3）**：层分 = Σ(维度分×权重) ÷ 层权重；不考虑风险研究分 = Σ(维度分×权重) ÷ 100
- **研究分（最终）** = 不考虑风险研究分 − 黄灯扣分合计（`yellow_deductions` 的 points 求和）
- **时机分** = Σ(时机维度分×权重) ÷ 100（筹码面 67% + 技术面 33%）
- 研究层/时机层权重总和各自≠100 → 脚本报错拒绝渲染
- scores 缺研究层维度 → 脚本报错列出缺失键
- 徽章色脚本自动按分数分配，模型无需关心汇总表；双轨判定词（`VERDICT_DUAL`）脚本按
  研究分×时机分阈值自动生成（红灯优先）

## 输出

- 自动命名：`{company}-{code}-{研究分}-{时机分}-{date}.html`，写在 fill JSON 同目录；
  回测模式（填了 `prev`）自动变为 `{company}-{code}-{研究分}-{时机分}-复盘-{date}.html`
- 残留 `{{...}}` 或 `【...】` → 脚本报错退出，报告不生成
- 章节片段为空 → 脚本警告列出（CYCLE_HTML 除外，空=删章节）
