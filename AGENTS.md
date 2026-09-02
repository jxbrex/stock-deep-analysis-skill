# stock-deep-analysis 仓库守则

本仓库是 stock-deep-analysis skill 的唯一源真相。已部署的运行副本位于
`C:\Users\rexji\.agents\skills\stock-deep-analysis`，它是只读的输出端：
任何会话中都不得直接读写、编辑、删除其中的文件（该目录已设只读属性，
不要试图解除——`scripts/deploy.ps1` 会在部署时自行处理）。

## 修订流程（固定顺序）

1. 在仓库内修改源文件
2. 运行回归测试（scripts/test_*、golden 快照）
3. 更新 CHANGELOG.md
4. 经用户确认后 commit（git 操作必须先征得用户同意）
5. 部署：先 `powershell -File scripts\deploy.ps1` 预览，确认后加 `-Go` 执行

## 目录约定

- `handoffs/`：每轮版本交接文档（v4.1 起），写完归档不再修改；`deploy.ps1` 排除清单
  已排除该目录（skill 运行副本不携带维护史）。交接文档以仓库内为权威，仓库外
  `_skill_repo` 目录已停止使用。

## 禁止事项

- 禁止对部署目录做任何写操作
- 禁止擅自 `git reset` / `git checkout` / `git commit` / `git push`
- 运行产物（HTML 报告、fill JSON、抓取数据等）一律写入 `artifacts/`
  （已 gitignore）或仓库外目录，不要散落在仓库根
