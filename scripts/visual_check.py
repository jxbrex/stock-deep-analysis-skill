#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""visual_check.py — 渲染后视觉审计门禁（v4.11.3，advisory v1）

    python scripts/visual_check.py <报告.html>            # 双视口审计（1280/390）
    python scripts/visual_check.py <报告.html> --shots    # 同时输出桌面/移动 PNG
    python scripts/visual_check.py <报告.html> --widths=1280,768,390

检查项（借 lieflat-cards render.py 的测量思路，适配长页报告）：
  ① 页面级横向溢出（scrollWidth > innerWidth）
  ② 元素溢出 body 内容盒右缘（.plot-wrap/.table-scroll 内元素豁免——故意横向滚动）
  ③ 单行槽位折行（Range.getClientRects > 1）：槽位清单见 SLOT_SELECTORS
  ④ clipped（scrollHeight > clientHeight 且 overflow 非 visible，豁免同上）

退出码：0=干净或浏览器缺席（跳过不卡交付）/ 1=发现问题。
debt: 孤字检测（单字独占一行，Rain 清单项）v1 未做——需逐行 Range 分析，误判率高，
      现阶段靠 stage-driver 显示宽 ≤48 等槽位契约在源头防。
只依赖 Chrome/Edge 与 Python 标准库。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "google-chrome",
    "chromium",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

# 单行槽位：该一行放下的短值，折行即内容或数据问题（对应 fill-schema「槽位契约」节）
SLOT_SELECTORS = [
    ".section-title",
    ".hero-track .s-value",
    ".hero-data-strip .d-value",
    ".metric-card .value",
    ".trig-cond",
    ".drv-elastic",
    ".stage-name",
    ".stage-meta",
    ".badge",
]

# 测量 JS：注入页面，把结果写进 #visual-check-report 节点
MEASURE_JS = """
<script id="visual-check-measure">
window.addEventListener('load', () => setTimeout(() => {
  const label = (el) => el.tagName.toLowerCase() +
    (el.className && typeof el.className === 'string'
      ? '.' + el.className.trim().split(/\\s+/).join('.') : '');
  const exempt = (el) => el.closest('.plot-wrap, .table-scroll, .toc-side');
  const out = { vw: window.innerWidth, docH: document.documentElement.scrollHeight,
                hscroll: false, spills: [], wrapped: [], clipped: [] };
  if (document.documentElement.scrollWidth > window.innerWidth + 1) out.hscroll = true;

  const body = document.body.getBoundingClientRect();
  const style = getComputedStyle(document.body);
  const limit = body.right - parseFloat(style.paddingRight || 0);

  const spillSet = new Set();
  for (const el of document.body.querySelectorAll('*')) {
    if (el.tagName === 'CANVAS' || el.tagName === 'SCRIPT' || el.tagName === 'STYLE') continue;
    if (exempt(el)) continue;
    const cs = getComputedStyle(el);
    if (cs.position === 'fixed' || cs.position === 'absolute') continue;
    const copy = (el.textContent || '').trim();
    if (!copy) continue;
    const r = el.getBoundingClientRect();
    if (!r.width && !r.height) continue;
    const over = r.right - limit;
    if (over > 2) spillSet.add(el);
  }
  // 父子同溢只报最深节点（避免一行问题刷出一串祖先）
  for (const el of spillSet) {
    let deepest = true;
    for (const other of spillSet) {
      if (other !== el && el.contains(other)) { deepest = false; break; }
    }
    if (deepest) {
      const r = el.getBoundingClientRect();
      out.spills.push({ sel: label(el), px: Math.round(r.right - limit),
                        text: (el.textContent || '').trim().slice(0, 30) });
    }
  }
  out.spills = out.spills.slice(0, 8);

  for (const sel of %SLOTS%) {
    // 移动端跳过 .section-title：meta 已落下一行，标题只可能因自身过长（26 字标题 >
    // 358px 内容盒）自然折行——那是内容问题（valuation_method 该短），不是版面挤压
    if (out.vw < 768 && sel === '.section-title') continue;
    for (const el of document.querySelectorAll(sel)) {
      const copy = (el.textContent || '').trim();
      if (!copy) continue;
      const range = document.createRange();
      range.selectNodeContents(el);
      // 按垂直重叠聚类行数：同一视觉行的内联分片（不同字号基线对齐，如 21px 值 + 12px
      // 单位，top 差 8px）垂直区间必然重叠；换行的分片才不重叠（宁德时代 Hero d-value
      // 误报 2 行实证——getClientRects 按分片计数、按 top 去重都区分不了字号差）
      const lines = [];
      for (const r of range.getClientRects()) {
        const hit = lines.find(L => r.top < L.bottom && r.bottom > L.top);
        if (hit) { hit.top = Math.min(hit.top, r.top); hit.bottom = Math.max(hit.bottom, r.bottom); }
        else { lines.push({ top: r.top, bottom: r.bottom }); }
      }
      range.detach();
      if (lines.length > 1) out.wrapped.push({ sel, lines: lines.length, text: copy.slice(0, 30) });
    }
  }
  out.wrapped = out.wrapped.slice(0, 8);

  for (const el of document.body.querySelectorAll('*')) {
    if (exempt(el)) continue;
    const hidden = el.scrollHeight - el.clientHeight;
    if (hidden > 2 && getComputedStyle(el).overflow !== 'visible') {
      out.clipped.push({ sel: label(el), px: hidden });
    }
  }
  out.clipped = out.clipped.slice(0, 8);

  const sink = document.createElement('div');
  sink.id = 'visual-check-report';
  sink.textContent = JSON.stringify(out);
  document.body.appendChild(sink);
}, 400));
</script>
"""

REPORT_RE = re.compile(r'<div id="visual-check-report">(.*?)</div>', re.S)


def find_chrome(explicit: str | None):
    if explicit:
        return explicit
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    return None


def chrome_run(chrome: str, page: Path, work: Path, ready, *flags: str) -> str:
    """无头跑 Chrome/Edge 直到 ready(stdout) 满足（有的构建干完活不退场，轮询不等退出）。"""
    profile = Path(tempfile.mkdtemp(prefix="visual-check-", dir=work))
    log = profile / "stdout.txt"
    deadline = time.time() + 60
    with open(log, "wb") as sink:
        proc = subprocess.Popen(
            [chrome, "--headless=new", f"--user-data-dir={profile}",
             "--virtual-time-budget=6000", "--hide-scrollbars",
             "--force-color-profile=srgb", "--no-first-run", "--no-default-browser-check",
             "--no-sandbox", "--disable-extensions", "--disable-gpu",
             *flags, page.resolve().as_uri()],
            stdout=sink, stderr=subprocess.DEVNULL)
        try:
            while time.time() < deadline:
                out = log.read_text(encoding="utf-8", errors="replace")
                if ready(out):
                    return out
                if proc.poll() is not None:
                    return log.read_text(encoding="utf-8", errors="replace")
                time.sleep(0.25)
            return log.read_text(encoding="utf-8", errors="replace")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def measure(chrome: str, html: str, work: Path, width: int) -> dict:
    page = work / f"measure-{width}.html"
    snippet = MEASURE_JS.replace("%SLOTS%", json.dumps(SLOT_SELECTORS))
    page.write_text(html.replace("</body>", snippet + "</body>", 1)
                    if "</body>" in html else html + snippet, encoding="utf-8")
    dom = chrome_run(chrome, page, work,
                     lambda out: REPORT_RE.search(out) is not None,
                     f"--window-size={width},2000", "--dump-dom")
    match = REPORT_RE.search(dom)
    if not match:
        return {"vw": width, "docH": 0, "hscroll": False, "spills": [],
                "wrapped": [], "clipped": [], "error": "测量超时/失败"}
    payload = (match.group(1).replace("&quot;", '"').replace("&amp;", "&")
               .replace("&lt;", "<").replace("&gt;", ">"))
    return json.loads(payload)


def shoot(chrome: str, source: Path, work: Path, width: int, height: int, dest: Path):
    dest = dest.resolve()   # Chrome 把相对截图路径解析到自己的 cwd（user-data-dir），
                            # 相对路径会写到别处——先绝对化（复盘截图失踪实证）
    dest.unlink(missing_ok=True)
    chrome_run(chrome, source, work,
               lambda _out: dest.exists() and dest.stat().st_size > 0,
               f"--screenshot={dest}", f"--window-size={width},{min(height, 16000)}",
               "--force-device-scale-factor=1")
    return dest.exists()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path, help="渲染产出的报告 HTML")
    ap.add_argument("--shots", action="store_true", help="同时输出桌面/移动 PNG（报告同目录）")
    ap.add_argument("--widths", default="1280,390", help="逗号分隔视口宽度（默认 1280,390）")
    ap.add_argument("--chrome", default=None, help="Chrome/Edge 路径")
    args = ap.parse_args()

    if not args.source.exists():
        sys.exit(f"文件不存在: {args.source}")

    chrome = find_chrome(args.chrome)
    if not chrome:
        print("未找到 Chrome/Edge，视觉审计跳过（不阻塞交付）")
        return 0

    html = args.source.read_text(encoding="utf-8")
    widths = [int(w) for w in args.widths.split(",") if w.strip()]
    total = 0
    reports = []
    with tempfile.TemporaryDirectory(prefix="visual-check-") as tmp:
        work = Path(tmp)
        for w in widths:
            r = measure(chrome, html, work, w)
            reports.append(r)
            problems = []
            if r.get("error"):
                print(f"⚠️ @{w}px 测量失败：{r['error']}（本视口跳过）", file=sys.stderr)
                continue
            if r["hscroll"]:
                problems.append("页面横向溢出（scrollWidth > 视口宽）")
            for s in r["spills"]:
                problems.append(f"溢出右缘 {s['px']}px — {s['sel']} “{s['text']}”")
            for s in r["wrapped"]:
                problems.append(f"单行槽位折成 {s['lines']} 行 — {s['sel']} “{s['text']}”"
                                "（槽位契约：该一行放下，缩短文案）")
            for c in r["clipped"]:
                problems.append(f"内容被裁切 {c['px']}px — {c['sel']}")
            total += len(problems)
            if problems:
                print(f"@{w}px：{len(problems)} 个问题")
                for p in problems:
                    print(f"  {p}")
            else:
                print(f"@{w}px：无问题")

        if args.shots:
            for r, w in zip(reports, widths):
                if not r.get("docH"):
                    continue
                dest = args.source.with_name(
                    f"{args.source.stem}-{'desktop' if w >= 768 else 'mobile'}.png")
                if shoot(chrome, args.source, work, w, r["docH"], dest):
                    print(f"  wrote {dest.name}  {w}x{r['docH']}")
                else:
                    print(f"⚠️ @{w}px 截图失败（{dest.name} 未生成）", file=sys.stderr)

    if total:
        print(f"\n共 {total} 个视觉问题——逐条消解后再交付（槽位折行=缩短文案；"
              "溢出=检查长串 nowrap/长数字；裁切=不要用 overflow 藏字）")
        return 1
    print("\n视觉审计通过：无溢出/折行/裁切。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
