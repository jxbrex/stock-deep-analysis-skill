#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
em_cache.py — 磁盘缓存原语与分档常量（em_fetch 拆分子模块之一，v4.8.3）

职责：跨进程磁盘缓存的通用 IO（原子写、TTL 判定、键→路径），以及缓存 TTL 分档与
tushare 接口 tier 归类常量。全部原语为纯函数（cache_dir / no_cache 由调用方显式传入），
不持有模块级可变状态——缓存状态（_CACHE_DIR/_NO_CACHE 等）归属宿主 em_fetch.py：
test_em_fetch 按 em_fetch 命名空间 rebind 这些配置须实时生效，故 ts_call/get（读取者）
也留在宿主，仅在调用本模块原语时把当前配置作为参数传入。
"""

import hashlib
import json
import os
import time

# ---------------- 缓存分档常量（宿主 em_fetch.py import 拷贝引用） ----------------
# TTL 分档：行情 2h / 财务 12h / 治理 24h（均远小于数据自身更新周期，陈旧风险可控）；
# EM_FETCH_NO_CACHE=1 全旁路。缓存读写任何失败都静默忽略，绝不阻断取数。
# _CACHE_DIR/_NO_CACHE 状态归属宿主 em_fetch.py（test_em_fetch 按 em_fetch 命名空间 rebind）。
_TTL_QUOTE = 2 * 3600    # 行情（日线收盘级，2h 内唯一风险是盘中跑+收盘后 1h 内重跑，可识别）
_TTL_FIN = 12 * 3600     # 财务（季度更新）
_TTL_GOV = 24 * 3600     # 治理（公告/事件级更新）
_TS_TIER_QUOTE = {"daily", "daily_basic", "adj_factor", "hk_daily", "weekly", "monthly",
                  "index_daily", "stk_factor"}
_TS_TIER_GOV = {"pledge_stat", "stk_holdertrade", "repurchase", "fina_audit", "stock_basic",
                "disclosure_date", "namechange", "stk_holdernumber",
                "top10_holders", "top10_floatholders"}


def dc_path(cache_dir: str, tag: str, key: str) -> str:
    """缓存键 → 磁盘路径（tag 前缀 + key 的 md5 前 16 位）。cache_dir 由调用方传入。"""
    return os.path.join(cache_dir, f"{tag}_{hashlib.md5(key.encode('utf-8')).hexdigest()[:16]}.json")


def dc_read(path: str, ttl: int, no_cache: bool):
    """命中且未过期返回解析值，否则 None。no_cache=旁路开关。"""
    if no_cache:
        return None
    try:
        if time.time() - os.path.getmtime(path) > ttl:
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def dc_write(path: str, val, no_cache: bool, cache_dir: str) -> None:
    """先写临时文件再 replace，避免并发读到写了一半的文件。no_cache=旁路开关。"""
    if no_cache:
        return
    try:
        os.makedirs(cache_dir, exist_ok=True)
        # tmp 名带 PID：并发进程写同一缓存键时互不覆盖（固定 .tmp 会互踩）
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(val, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass
