#!/usr/bin/env python
"""拉取 NVIDIA USDCraft-10K 的**零售子集** (2026-11-25)。

**为什么拉它**: 本仓实测把跨域缺口压到"商品长什么样" (合成商品是无纹理白盒, 真实商品有
包装/纹理/几何)。USDCraft-10K 是现成的商品几何源: 10,000 个带关节 USD 资产 / 1,000 个类目,
其中带贴图 (一张标签 decal) 的 1,726 个; 零售类目里带贴图的只有 211 个 —— 所以只拉
**零售 + 带贴图**这批 (~199 个对象, ~240 MB), 不拉全量。

**它与仓内 bootstrap 贴图互补**: bootstrap 给的是"盒子上的印刷包装"(主视觉/营养表/条码),
USDCraft 给的是"真实商品几何 + 标签 decal"(瓶/罐/杯/箱)。两者分别对应内容缺口的
"表面"与"几何/种类"两个成分。

许可: apache-2.0 (需署名, 见 assets/usdcraft/ATTRIBUTION.md)。

用法:
    python pipelines/shelf_sdg/58_fetch_usdcraft.py --limit 200
    python pipelines/shelf_sdg/58_fetch_usdcraft.py --dry-run
"""
import argparse
import csv
import hashlib
import json
import os
import sys
import time
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(BASE, "assets", "usdcraft")
REPO = "nvidia/USDCraft-10K"
API = "https://huggingface.co/api/datasets/" + REPO
RES = "https://huggingface.co/datasets/" + REPO + "/resolve/main/"

# "货架上会卖的东西" 的关键词 (类目名小写匹配)
RETAIL_KEYS = ("bottle", "can", "jar", "mug", "box", "carton", "tube", "bag", "tin",
               "cup", "pitcher", "dispenser", "container", "kettle", "thermos",
               "tumbler", "flask", "canister", "jug", "packag", "jerry", "decanter",
               "carafe", "bowl", "basket", "tray", "crate", "bucket", "caddy")


def _get(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def _manifest_rows():
    """下载 manifest.csv (10,000 行) 并缓存到本地。"""
    cache = os.path.join(OUT, "manifest.csv")
    os.makedirs(OUT, exist_ok=True)
    if not os.path.exists(cache):
        raw = _get(RES + "manifest.csv", timeout=300)
        with open(cache, "wb") as fh:
            fh.write(raw)
    with open(cache, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _files_of(path):
    url = API + "/tree/main/" + path + "?recursive=true&expand=true"
    return json.loads(_get(url).decode("utf-8"))


def select(rows, want_textured=True, retail_only=True):
    out = []
    for r in rows:
        if retail_only and not any(k in r["category"].lower() for k in RETAIL_KEYS):
            continue
        if want_textured and r["has_textures"] != "true":
            continue
        out.append(r)
    return out


def download_object(r, keep=(".usdc", ".png", ".json")):
    """下载一个对象的全部文件 (usd + 贴图 + meta), 返回 (文件数, 字节数)。"""
    base = os.path.join(OUT, r["path"])
    tree = _files_of(r["path"])
    n, total = 0, 0
    for x in tree:
        if x.get("type") != "file":
            continue
        rel = x["path"].split(r["path"] + "/", 1)[-1]
        if not rel.endswith(keep):
            continue
        dst = os.path.join(base, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst) and os.path.getsize(dst) == (x.get("size") or 0):
            n += 1
            total += x.get("size") or 0
            continue
        data = _get(RES + x["path"])
        with open(dst, "wb") as fh:
            fh.write(data)
        n += 1
        total += len(data)
    return n, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200, help="最多拉多少个对象")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--all-textured", action="store_true",
                    help="不限于零售类目, 拉所有带贴图的对象")
    args = ap.parse_args()

    rows = _manifest_rows()
    sel = select(rows, retail_only=not args.all_textured)
    sel = sel[:args.limit]
    print(f"[USDC] manifest {len(rows)} 行 -> 选中 {len(sel)} 个带贴图的零售对象")
    if args.dry_run:
        for r in sel[:10]:
            print("   ", r["object_id"], r["category"], r["path"])
        return 0

    t0 = time.time()
    total = 0
    got = []
    for i, r in enumerate(sel, 1):
        try:
            n, b = download_object(r)
            total += b
            got.append({"object_id": r["object_id"], "category": r["category"],
                        "title": r["title"], "path": r["path"], "files": n,
                        "bytes": b,
                        "has_textures": r["has_textures"],
                        "physics_type": r["physics_type"],
                        "prompt": r["prompt"][:400]})
        except Exception as e:
            print(f"[USDC] 失败 {r['object_id']}: {type(e).__name__}: {e}")
        if i % 20 == 0:
            print(f"[USDC] {i}/{len(sel)} 累计 {total/1048576:.1f} MB "
                  f"({(time.time()-t0)/60:.1f} min)")
    man = {"source": f"huggingface.co/datasets/{REPO}",
           "license": "apache-2.0",
           "fetched_at": time.strftime("%Y-%m-%d"),
           "n_objects": len(got),
           "total_bytes": total,
           "selection": ("零售类目 + has_textures=true"
                          if not args.all_textured else "所有 has_textures=true"),
           "objects": got}
    with open(os.path.join(OUT, "usdcraft_subset.json"), "w", encoding="utf-8") as fh:
        json.dump(man, fh, ensure_ascii=False, indent=2)
    h = hashlib.sha256()
    for r in sorted(got, key=lambda x: x["object_id"]):
        h.update(r["object_id"].encode())
    with open(os.path.join(OUT, "ATTRIBUTION.md"), "w", encoding="utf-8") as fh:
        fh.write(
            "# USDCraft-10K 子集 (署名)\n\n"
            f"- 来源: huggingface.co/datasets/{REPO} (NVIDIA)\n"
            "- 许可: apache-2.0\n"
            "- 论文: USDCraft — Geometrically Grounded Programmatic Modeling of "
            "Articulated 3D Assets for Simulation (arXiv:2610.11322)\n"
            f"- 本地子集: {len(got)} 个对象, {total/1048576:.1f} MB, "
            f"对象 id 指纹 sha256={h.hexdigest()[:16]}\n"
            "- 用途: 本仓的\"合成商品长什么样\"内容干预实验 (商品几何 + 标签 decal)\n")
    print(f"[USDC] 完成: {len(got)} 个对象, {total/1048576:.1f} MB -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
