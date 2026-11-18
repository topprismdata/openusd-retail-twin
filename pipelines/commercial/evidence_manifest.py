#!/usr/bin/env python3
"""P0-B 证据清单 v2 (联合结论第三条): SHA-256 三键 + 环境取证 + IPTC 映射。

三键分离(不得互相替代):
  artifact_sha256   最终交付文件字节身份
  render_spec_sha256 规范化场景参数身份(sorted-key JSON)
  asset_tree_sha256  全部依赖资产及其版本身份
环境取证: Blender/Cycles 版本、平台、色彩管理、渲染设备类别。
IPTC 2025.1 映射: 纯 Cycles 渲染 → Digital Source Type = 数字创建/渲染,
AI 字段留空(不是生成式AI产物, 不得伪标); 商品/包装/审批关系字段缺外部系统,
标 NOT_MEASURED 并留 null —— UNKNOWN 不虚构。

用法: python3 evidence_manifest.py --render <png> --manifest <json> --spec <json> [--out <json>]
"""
import argparse, hashlib, json, os, platform, subprocess, sys, time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def asset_tree():
    """assets/ 全树: sorted(relpath, sha256) → 树哈希。"""
    root = os.path.join(REPO, "assets")
    entries = []
    for dirpath, _, files in os.walk(root):
        for fn in sorted(files):
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, REPO)
            entries.append((rel.replace(os.sep, "/"), sha256_file(p)))
    entries.sort()
    payload = json.dumps(entries, ensure_ascii=False).encode("utf-8")
    return sha256_bytes(payload), len(entries)


def blender_env():
    code = (
        "import bpy, sys, os\n"
        "print('BLENDER_VER', bpy.app.version_string)\n"
        "print('CYCLES_DEV', bpy.context.preferences.addons.get('cycles') and "
        "bpy.context.preferences.addons['cycles'].preferences.compute_device_type)\n"
        "print('OCIO', os.environ.get('OCIO', 'builtin'))\n"
        "print('PY', sys.version.split()[0])\n"
    )
    try:
        p = subprocess.run([BLENDER, "-b", "--python-expr", code],
                           capture_output=True, text=True, timeout=120)
        env = {}
        for line in p.stdout.splitlines():
            for key in ("BLENDER_VER", "CYCLES_DEV", "OCIO", "PY"):
                if line.startswith(key + " "):
                    env[key] = line.split(" ", 1)[1].strip()
        return env
    except Exception as e:
        return {"error": str(e)[:120]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    spec_canon = json.dumps(json.load(open(a.spec)), sort_keys=True,
                            ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    tree_hash, n_assets = asset_tree()
    env = blender_env()
    base = json.load(open(a.manifest))

    out = {
        "schema": "evidence-manifest/2.0",
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "generation_method": "CGI",          # 纯Cycles渲染, 非生成式AI
        "hashes": {
            "artifact_sha256": sha256_file(a.render),
            "render_spec_sha256": sha256_bytes(spec_canon),
            "asset_tree_sha256": tree_hash,
            "asset_tree_n": n_assets,
            "legacy_md5_note": "历史冻结件沿用md5仅作兼容引用, 不作完整性承诺",
        },
        "environment": {
            "blender": env.get("BLENDER_VER", "UNKNOWN"),
            "cycles_device_type": env.get("CYCLES_DEV", "UNKNOWN"),
            "ocio": env.get("OCIO", "builtin"),
            "python": env.get("PY", "UNKNOWN"),
            "platform": platform.platform(),
            "repro_class": "PERCEPTUAL_EQUIVALENT",   # 金属采样残差已证: 非逐字节
        },
        "render_params": {k: base.get(k) for k in
                          ("resolution", "samples", "camera", "lights",
                           "color", "world_strength", "spec_sha")},
        "iptc_2025_1": {
            "digital_source_type": "digital_creation_render",
            "ai_system_used": None,
            "ai_system_version_used": None,
            "ai_prompt_information": None,
            "note": "纯Cycles渲染无生成式AI参与, AI字段留空不得伪标",
        },
        "product_relationship": {
            "sku_id": None, "gtin": None,
            "artwork_version": None, "approval_id": None, "release_scope": None,
            "status": "NOT_MEASURED",
            "note": "需外部商品资料/Artwork审批系统, 仓库内不存在, 禁止虚构",
        },
    }
    dest = a.out or os.path.splitext(a.render)[0] + "_evidence.json"
    json.dump(out, open(dest, "w"), ensure_ascii=False, indent=2)
    print("evidence manifest →", dest)
    print("  artifact_sha256  ", out["hashes"]["artifact_sha256"][:16], "…")
    print("  render_spec_sha  ", out["hashes"]["render_spec_sha256"][:16], "…")
    print("  asset_tree_sha   ", out["hashes"]["asset_tree_sha256"][:16], "…",
          "(%d files)" % n_assets)
    print("  environment      ", out["environment"]["blender"],
          "/", out["environment"]["cycles_device_type"], "/", out["environment"]["repro_class"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
