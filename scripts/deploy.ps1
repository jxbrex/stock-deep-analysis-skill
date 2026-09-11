# 部署脚本：仓库 -> 部署目录（唯一同步入口，请在 commit 之后运行）
# 用法：
#   powershell -File scripts\deploy.ps1        # 预览（dry-run）
#   powershell -File scripts\deploy.ps1 -Go    # 实际部署，结束后恢复部署目录只读
param([switch]$Go)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $env:USERPROFILE '.agents\skills\stock-deep-analysis'
$xd = @('.git', '__pycache__', 'artifacts', 'handoffs')

# 文档超长行闸（v4.10.1）：单行 >1500 字符会触发 v4.9.2 立案的 Read 截断陷阱，warn-only
function Test-DocLines {
    $bad = 0
    Get-ChildItem (Join-Path $repo 'references\*.md'), (Join-Path $repo 'SKILL.md'), (Join-Path $repo 'CHANGELOG.md') | ForEach-Object {
        $f = $_.FullName; $n = 0
        Get-Content $f | ForEach-Object { $n++; if ($_.Length -gt 1500) { Write-Host "  超长行 $($_.Length) 字符: $f 行 $n"; $bad++ } }
    }
    if ($bad -gt 0) { Write-Host "提示：文档超长行 $bad 处（>1500 字符，v4.9.2 截断陷阱立案阈值），建议拆行后再部署。" }
}
Test-DocLines

if (-not $Go) {
    robocopy $repo $dest /MIR /L /XD $xd /NJH | Out-Null
    $rc = $LASTEXITCODE
    if ($rc -ge 8) { Write-Host "robocopy 预览失败 (code $rc)"; exit 1 }
    if ($rc -eq 0) { Write-Host '预览完成：部署目录已是最新，无需变更。' }
    else { Write-Host "预览完成：有变更待部署 (code $rc)。确认无误后运行: powershell -File scripts\deploy.ps1 -Go" }
    exit 0
}

attrib -R "$dest\*" /S /D | Out-Null
robocopy $repo $dest /MIR /XD $xd /NFL /NDL | Out-Null
$rc = $LASTEXITCODE
if ($rc -ge 8) { Write-Host "robocopy 部署失败 (code $rc)，只读未恢复"; exit 1 }
attrib +R "$dest\*" /S /D | Out-Null
Write-Host '部署完成，部署目录已恢复只读。'
exit 0
