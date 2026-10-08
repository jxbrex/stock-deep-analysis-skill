#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_visual_check.py — visual_check 浏览器发现与跳过路径回归（全离线，不启动浏览器）

覆盖 v5.5.2 审计发现：--chrome 显式坏路径原先原样直通 → Popen 抛 FileNotFoundError；
修法 find_chrome 显式分支先验存在性，坏路径返回 None 走统一跳过。main() 无浏览器时
print 跳过语并返回 0（不卡交付）也在此钉住。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import visual_check


def test_find_chrome_explicit_existing(tmp_path):
    """显式 --chrome 路径存在 → 原样直通（既有契约不动）。"""
    fake = tmp_path / "chrome.exe"
    fake.write_bytes(b"")
    assert visual_check.find_chrome(str(fake)) == str(fake)


def test_find_chrome_explicit_missing(tmp_path):
    """显式 --chrome 坏路径 → None（走统一跳过，不再让 Popen 抛 FileNotFoundError）。"""
    assert visual_check.find_chrome(str(tmp_path / "no-such-chrome.exe")) is None


def test_find_chrome_all_candidates_missing(monkeypatch):
    """候选清单全灭（本机无 Chrome/Edge）→ None。"""
    monkeypatch.setattr(visual_check, "CHROME_CANDIDATES", [])
    assert visual_check.find_chrome(None) is None


def test_main_without_browser_skips(monkeypatch, tmp_path, capsys):
    """main() 无浏览器：print 跳过语 + 返回 0（跳过不卡交付）。"""
    page = tmp_path / "r.html"
    page.write_text("<html><body><p>x</p></body></html>", encoding="utf-8")
    monkeypatch.setattr(visual_check, "find_chrome", lambda explicit=None: None)
    monkeypatch.setattr(sys, "argv", ["visual_check.py", str(page)])
    assert visual_check.main() == 0
    assert "跳过" in capsys.readouterr().out
