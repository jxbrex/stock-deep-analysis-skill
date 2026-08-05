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
| `scores` | ✓ | 14 维得分对象：`{"1A": 8.0, "1B": 7.0, ..., "4C": 6.0}` |
| `weights` | 可选 | 维度权重覆盖（分型调整时用），14 项之和必须=100 |
| `thesis_html` | ✓ | Hero 一句话结论（含 `<span class="scenario-pess/base/opt">` 三情景价） |
| `price` / `mcap` / `pe_ttm` | ✓ | Hero 指标卡数值（纯数字字符串） |
| `price_sub_html` / `mcap_sub` / `pe_sub` | ✓ | 指标卡 sub 行（可含 `<span class="up/down">`） |
| `horizon` | ✓ | 目标价时间维度（如 "12个月"） |
| `target_range` / `target_sub_html` | ✓ | 目标价区间卡 |
| `conclusion_html` | ✓ | 00 核心结论正文（HTML 片段） |
| `p0_html` | ✓ | P0 关键利润驱动（含分型声明+敏感性表+info-card） |
| `l1_html` … `l4_html` | ✓ | 四层评分正文片段 |
| `valuation_method` / `stock_type` | ✓ | 05 卡片头（如 "PE历史时段匹配法" / "周期股"） |
| `valuation_html` | ✓ | 05 正文（三情景表+校准逻辑+三指标卡条） |
| `gap_tier` / `gap_html` | ✓ | 06 预期差（档位 A/B/C + 正文） |
| `peers_meta` / `peers_html` | ✓ | 07 同业对比 |
| `cycle_html` | 条件 | 08 周期规律；**空字符串或省略 → 整张卡片自动删除** |
| `cycle_meta` | 条件 | 08 触发条件说明 |
| `next_review` / `dash_html` | ✓ | 10 跟踪仪表盘 |
| `position_html` | ✓ | 11 仓位映射 |
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

**提示卡**：`.info-card`（蓝/逻辑说明）`.warning-card`（橙/警示）`.danger-card`（红/致命警告+pre-mortem）

**数据来源标注**：`<span class="source">数据来源：……</span>`（每张数据表下方必须有）

**表格**：`<div class="table-scroll"><table>…</table></div>`，数字列 `<td class="num">`，居中列 `<td class="center">`

## 评分计算规则（脚本执行，模型不要手算）

- 层分 = Σ(维度分×权重) ÷ 层权重；总分 = Σ(维度分×权重) ÷ 100
- 权重总和≠100 → 脚本报错拒绝渲染
- scores 缺维度 → 脚本报错列出缺失键
- 徽章色脚本自动按分数分配，模型无需关心汇总表

## 输出

- 自动命名：`{company}_{code}_{总分}_{date}.html`，写在 fill JSON 同目录
- 残留 `{{...}}` 或 `【...】` → 脚本报错退出，报告不生成
- 章节片段为空 → 脚本警告列出（CYCLE_HTML 除外，空=删章节）
