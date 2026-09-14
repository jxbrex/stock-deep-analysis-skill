# -*- coding: utf-8 -*-
"""test_deploy_meta.py — deploy.ps1 元数据守卫（v4.11.2 BOM 事故固化）

BOM 断言：PowerShell 5.1 对无 BOM 的 .ps1 按系统 ANSI 代码页解码，中文脚本中的
字节序列会产生歧义引号/括号 → ParserError（v4.11.2 实证：编辑 deploy.ps1 后
BOM 丢失 → MissingEndCurlyBrace，预览直接失败）。任何编辑 deploy.ps1 的工具
都可能剥掉 BOM，本断言把回归钉在 pytest 里。

排除清单断言：/XD golden + /XF 六项（v4.11.2 扩充）是部署体积 -43% 的载体，
参数被误删时此处报警。
"""
import os

DEPLOY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy.ps1")


def test_deploy_ps1_has_utf8_bom():
    with open(DEPLOY, "rb") as f:
        head = f.read(3)
    assert head == b"\xef\xbb\xbf", (
        "deploy.ps1 丢失 UTF-8 BOM——PowerShell 5.1 将按 ANSI 解码中文脚本并 "
        "ParserError（v4.11.2 事故实录）。恢复方法：编辑器另存为 UTF-8 with BOM。"
    )


def test_deploy_exclusion_lists_present():
    with open(DEPLOY, encoding="utf-8-sig") as f:
        src = f.read()
    for token in ("golden", "test_*.py", "conftest.py", "CHANGELOG.md",
                  "README.md", "AGENTS.md", "deploy.ps1", "/XF"):
        assert token in src, f"deploy.ps1 排除清单缺 {token}（v4.11.2 扩充项被误删？）"
    assert src.count("/XF") >= 2, "dry-run 与 -Go 两处 robocopy 都应有 /XF"
