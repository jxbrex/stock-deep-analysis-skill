# 部署脚本：仓库 -> 部署目录（唯一同步入口，请在 commit 之后运行）
# 用法：
#   powershell -File scripts\deploy.ps1        # 预览（dry-run）
#   powershell -File scripts\deploy.ps1 -Go    # 实际部署，结束后恢复部署目录只读
param([switch]$Go)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $env:USERPROFILE '.agents\skills\stock-deep-analysis'
$xd = @('.git', '__pycache__', 'artifacts', '.backup-pre-v48')

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
