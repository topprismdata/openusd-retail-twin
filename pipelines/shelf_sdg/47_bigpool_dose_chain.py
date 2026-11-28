#!/usr/bin/env python
"""大池剂量-反应链 (2026-11-24): 把"160 张以上从未测过"这个缺口补上。

背景
----
README 里明写着一条未闭合项: **"160 张以上仍未测"** —— 合成剂量-反应只测到 160 张,
而按框量算, 要顶替 5% 真实标注 (411 张 x 147 框 = 60,417 框) 需要 **2,769 张**合成
(2,769 x 21.8 框 = 60,364 框)。此前判"不可行"是因为渲染只能跑 CPU: 2,609 张 x 38.7 秒
= 28 机时。GPU 通路修好后 (GTX 1050 Ti / OPTIX, 18 秒/图) 降到 **13 机时**, 该实验
从"不可行"变成"可行"。

设计 (剂量轴必须干净)
--------------------
1. **重新渲染一个大池** (num_images=2800 -> 700 场景 -> train 2240 / val 560), 配方
   与 R1 对照集**逐参数相同** (seed 42 / val_ratio 0.2 / images_per_scene 4 /
   split_mode scene / samples 64 / cam 1.0 / lens 28 / misalign 0.10 / bays 1)。
2. **剂量档全部取自这一个大池** (嵌套子集, 与 32 号脚本同法: 同一个 shuffle 种子 ->
   40 ⊂ 80 ⊂ 160 ⊂ 320 ⊂ 640 ⊂ 1280 ⊂ 2240)。
   为什么不能沿用旧池的 40/80/160 档: `assign_scene_splits()` 是在**全部场景上贪心**
   分配的, 场景数一变划分就变 -> 旧池的 160 张 train **不保证**是新池 train 的子集,
   两个池混用就不是单变量了。所以 40/80/160 三档也要在新池里重跑。
3. 每个 (剂量, 预算) 格点独立训练, 评测集 = 真实 test (与四臂一致, 不变)。

为什么值得做
------------
这是"合成能不能替代手工标注"这个**核心负结论**的边界所在。当前只能说"在 160 张以内
合成补不回缺口"; 若在 2,769 张 (框量等效) 档上缺口依然不补回, 负结论就从"小剂量区间"
升级为"**在框量等效的剂量上仍然不补回**"——那才是能写进论文的强结论。反之若某个更高
剂量档开始补回缺口, 那就必须改写结论。

用法:
    python pipelines/shelf_sdg/47_bigpool_dose_chain.py --stage render
    python pipelines/shelf_sdg/47_bigpool_dose_chain.py --stage train --doses 40,160,640 --fracs 0.05
"""
import argparse
import glob
import os
import json
import shutil
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.runtime_env import blender_command  # noqa: E402

BENCH = os.path.join(BASE, "output", "benchmark")
BIG_POOL = os.path.join(BENCH, "sdg_bigpool")      # 4 类源
BIG_SINGLE = os.path.join(BENCH, "synth_bigpool")  # 单类化 (丢 class 1)
LOG = os.path.join(BENCH, "bigpool_dose_chain.log")

NUM_IMAGES = 2800
RECIPE = {"seed": 42, "val_ratio": 0.2, "images_per_scene": 4, "split_mode": "scene",
          "samples": 64, "cam_mult": 1.0, "lens": 28.0, "misalign": 0.10, "bays": 1}
# 剂量档。**0 档 (无合成) 是剂量轴的锚点**, 必须在本池里跑一遍:
#   * 0 档没有合成名单, 汇总脚本只能靠"产物里记的池身份"判断它属于哪个池 (21 号现在
#     会为 0 档也记 synth_pool) -> 不在本池跑, 这条曲线就没有自己的基准;
#   * 复用老池的 0 档看着省事, 但那是另一次运行 -> 曲线里混进了跨运行差异。
#   代价只有 6 个格点 (2 预算 x 3 seed), 换来"同池同代码同一天"的内部一致性。
DOSES = [0, 40, 80, 160, 320, 640, 1280, 2240]
SEEDS = [42, 43, 44]
FRACS = [0.05, 0.02]

ENV = dict(os.environ)
ENV.setdefault("SKU110K_ROOT", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K"))
ENV.setdefault("SKU110K_YAML", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K", "SKU-110K.yaml"))
# 渲染与训练**串行** (链是先渲完再训), GPU 空闲 -> 用 GPU (18 s/图 vs CPU 38.7 s/图)。
if os.environ.get("SDG_RENDER_DEVICE", "").strip().lower() == "cpu":
    ENV["FORCE_CPU_RENDER"] = "1"
else:
    ENV.pop("FORCE_CPU_RENDER", None)
    ENV["CYCLES_DEVICE"] = ENV.get("CYCLES_DEVICE", "OPTIX")


def log(m):
    line = f"[BIGPOOL {time.strftime('%m-%d %H:%M:%S')}] {m}"
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def render_bigpool():
    """渲大池 (GPU)。已渲完则跳过 (可续跑)。"""
    n_done = len(glob.glob(os.path.join(BIG_POOL, "images", "train", "*.png"))) + \
        len(glob.glob(os.path.join(BIG_POOL, "images", "val", "*.png")))
    if n_done >= NUM_IMAGES:
        log(f"大池已存在 ({n_done} 张), 跳过渲染")
        return True
    log(f"渲大池: {NUM_IMAGES} 张 -> {BIG_POOL} (GPU 约 {NUM_IMAGES*18/3600:.1f} 机时)")
    cmd = blender_command() + [
        "-b", "-P", os.path.join(BASE, "pipelines/shelf_sdg/02_shelf_sdg_inspector.py"), "--",
        "--num-images", str(NUM_IMAGES),
        "--seed", str(RECIPE["seed"]),
        "--val-ratio", str(RECIPE["val_ratio"]),
        "--images-per-scene", str(RECIPE["images_per_scene"]),
        "--split-mode", RECIPE["split_mode"],
        "--samples", str(RECIPE["samples"]),
        "--cam-mult", str(RECIPE["cam_mult"]),
        "--lens", str(RECIPE["lens"]),
        "--misalign", str(RECIPE["misalign"]),
        "--bays", str(RECIPE["bays"]),
        # 断点续渲 (2026-11-24): 这一批要渲 2800 张 (约 10 机时), 中途崩一次就全废。
        # --resume 会保留已渲好的图、只补缺的; 它先核对上次落盘的
        # dataset_summary.json 里"这批图是用什么参数渲的", 参数不一致就拒绝续渲
        # (免得把两批不同配方的图拼成一批)。首次运行没有那份文件, 行为等同普通运行。
        "--resume",
        "--out", BIG_POOL]
    log("RUN " + " ".join(cmd[1:]))
    t0 = time.time()
    r = subprocess.run(cmd, env=ENV, cwd=BASE,
                       stdout=open(os.path.join(BENCH, "bigpool_render.log"), "a", encoding="utf-8", errors="ignore"),
                       stderr=subprocess.STDOUT)
    log(f"渲染结束 (退出码 {r.returncode}, {(time.time()-t0)/60:.1f} min)")
    return r.returncode == 0


def to_single():
    """4 类 -> 单类 (丢 class 1 = OOS gap), 与 14/43 号同逻辑。"""
    for split in ("train", "val"):
        isrc = os.path.join(BIG_POOL, "images", split)
        lsrc = os.path.join(BIG_POOL, "labels", split)
        idst = os.path.join(BIG_SINGLE, "images", split)
        ldst = os.path.join(BIG_SINGLE, "labels", split)
        os.makedirs(idst, exist_ok=True)
        os.makedirs(ldst, exist_ok=True)
        if not os.path.isdir(isrc):
            continue
        for f in os.listdir(isrc):
            shutil.copy2(os.path.join(isrc, f), os.path.join(idst, f))
            t = os.path.join(lsrc, f.replace(".png", ".txt"))
            lines = []
            if os.path.exists(t):
                for ln in open(t, encoding="utf-8"):
                    p = ln.split()
                    if len(p) == 5 and p[0] != "1":
                        lines.append("0 " + " ".join(p[1:]))
            with open(os.path.join(ldst, f.replace(".png", ".txt")), "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + ("\n" if lines else ""))
    with open(os.path.join(BIG_SINGLE, "dataset.yaml"), "w", encoding="utf-8") as fh:
        fh.write(f"path: {BIG_SINGLE}\ntrain: images/train\nval: images/val\n"
                 f"nc: 1\nnames: [product]\n")
    n = len(glob.glob(os.path.join(BIG_SINGLE, "images", "train", "*.png")))
    log(f"单类化完成: {BIG_SINGLE} train={n}")
    return n


def pool_manifest():
    """大池的身份清单 (写进日志与链产物) —— 剂量轴单变量性的凭据。

    剂量轴各档必须来自**同一个池**; 21 号脚本现在会把 synth_pool (路径 + 图像名单
    sha256) 记进每个格点产物, 31 号据此归池。这里再落一份独立的清单, 便于事后核对
    "这批大池到底是哪一批图"。
    """
    import hashlib
    d = os.path.join(BIG_SINGLE, "images", "train")
    names = sorted(f for f in os.listdir(d) if f.lower().endswith(".png")) \
        if os.path.isdir(d) else []
    h = hashlib.sha256()
    h.update(os.path.abspath(d).encode("utf-8"))
    for n_ in names:
        h.update(n_.encode("utf-8"))
    man = {"pool": "bigpool", "dir": os.path.abspath(d), "n_images": len(names),
           "names_sha256": h.hexdigest(),
           "recipe": RECIPE, "num_images": NUM_IMAGES,
           "note": ("大池是**独立渲染**的池 (与历史 160 张主池不同) -> 剂量轴不能与旧池的档位"
                    "混用; 31 号脚本按 synth_pool 归池。")}
    p = os.path.join(BENCH, "bigpool_manifest.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(man, fh, ensure_ascii=False, indent=2)
    log(f"大池清单 -> {p} (train {len(names)} 张, sha {man['names_sha256'][:12]})")
    return man


def train(doses, seeds, fracs):
    synth_dir = os.path.join(BIG_SINGLE, "images", "train")
    pool_manifest()
    # 2026-11-25: **剂量从大到小跑**。理由: 整条链算下来约 226 机时 (每格从头训,
    # 训练时间随 (真实预算 + 剂量) 线性涨, 2240 档单格 ≈ 2.4 h), 而**最有信息量的
    # 是高剂量端** (2240 张 ≈ 框量等效于 5% 真实标注, 也就是"合成能不能替代手工标注"
    # 这个核心负结论的边界)。原来的升序会让决定性格点排在最后 24 h -> 链被叫停时
    # 手里什么都没有。降序不改变任何协议 (同一批格点、同一套命令), 只改执行顺序:
    # 先把决定性的格点跑出来, 砍范围的决定就变成"最后再定", 而不是"已经晚了"。
    doses = sorted(doses, reverse=True)
    for frac in fracs:
        for seed in seeds:
            for dose in doses:
                out = os.path.join(BENCH, f"budget_real{frac:g}_synth{dose}_big_s{seed}.json")
                if os.path.exists(out):
                    log(f"SKIP frac={frac:g} dose={dose} seed={seed} (已存在)")
                    continue
                cmd = [sys.executable, os.path.join(BASE, "pipelines/shelf_sdg/21_annotation_budget.py"),
                       "--fracs", f"{frac:g}", "--synth", str(dose),
                       "--epochs", "10", "--select", "last",
                       "--budget-seed", "20261120", "--seed", str(seed),
                       "--run-tag", f"big_s{seed}", "--synth-dir", synth_dir,
                       # 2026-11-25: **禁止静默降 batch**。上一轮链在第一条训练上
                       # 实际跑的是 batch=2/workers=1 (内存守卫降级) -> 剂量曲线会与
                       # 已发布的 batch=4 数字不可比。渲大池已结束, 机器上不再有
                       # Blender 那种 15 GB 级占用。
                       # 2026-11-25 10:40 再修: 阈值 14 GB 在"同时跑着纹理渲染"的
                       # 机器上永远不满足 (可用内存 11.6 GB) -> 每格白等 30 min,
                       # 一天下来 25 格就烧掉 12 h。batch=4 单跑实测峰值 RSS ~2.5 GB,
                       # 8 GB 阈值 = 3 倍余量, 与"这次跑需要多少"对得上 (守卫阈值是
                       # 需求量的代理, 不是"机器忙不忙"的代理)。内存不够时**拒跑而不是
                       # 改协议**, 链会等一会儿再重试。
                       "--strict-protocol", "--mem-need-gb", "8"]
                log(f"RUN frac={frac:g} dose={dose} seed={seed}")
                t0 = time.time()
                # 2026-11-25: 子进程输出**逐格点落自己的日志**, 不再用 capture_output
                # 吞在内存里 —— 上一轮链在第一条训练上被杀, 连崩溃原因都没留下
                # (父进程被硬杀, 没有 traceback)。现在每个格点都有
                # output/benchmark/bigpool_dose_<frac>_<dose>_s<seed>.log 可查。
                run_log = os.path.join(BENCH, f"bigpool_dose_{frac:g}_{dose}_s{seed}.log")
                r = subprocess.run(cmd, env=ENV, cwd=BASE,
                                   stdout=open(run_log, "w", encoding="utf-8", errors="ignore"),
                                   stderr=subprocess.STDOUT)
                # 内存守卫拒跑 (并发训练占内存) -> 等 10 分钟重试, 最多 3 次;
                # 宁可等, 也不要为了"跑完"而改协议。
                for attempt in range(3):
                    if r.returncode == 0:
                        break
                    try:
                        txt = open(run_log, encoding="utf-8", errors="ignore").read()
                    except OSError:
                        txt = ""
                    if "MEM-GUARD(strict)" not in txt:
                        break
                    log(f"  内存不够, 等 10 min 重试 ({attempt+1}/3)")
                    time.sleep(600)
                    r = subprocess.run(cmd, env=ENV, cwd=BASE,
                                       stdout=open(run_log, "w", encoding="utf-8", errors="ignore"),
                                       stderr=subprocess.STDOUT)
                if r.returncode != 0:
                    log(f"  !! 退出码 {r.returncode} (见 {run_log})")
                else:
                    log(f"  完成 {(time.time()-t0)/60:.1f} min (见 {run_log})")
                    # 每跑完一格就刷新一次剂量曲线汇总 (31 号): 否则曲线里的"池收录的
                    # 格点清单"会停在上一格, 文档闸门 (28 号 [11b]) 会把**正在收尾**的
                    # 格点判成"曲线被漏掉" —— 2026-11-25 20:55 实测踩到: 2% 预算的
                    # dose=640 格点刚跑完, 曲线还没收录它, 闸门就红了。
                    # 31 号只读产物、只写汇总, 失败不影响链本身。
                    try:
                        # 注意: **不要**加 --pool-manifest —— 那样 31 号只汇总大池一个,
                        # 历史池 (legacy) 的格点会从报告里消失, 闸门 [11b] 反而会报
                        # "14 个格点没被收录"。默认行为会同时保留所有池 ✓。
                        _cmd = [sys.executable, os.path.join(BASE, "pipelines/shelf_sdg/31_dose_response.py")]
                        _rr = subprocess.run(_cmd, env=ENV, cwd=BASE,
                                             capture_output=True, text=True, timeout=900)
                        log(f"  曲线汇总刷新: 退出码 {_rr.returncode}")
                    except Exception as e:
                        log(f"  曲线汇总刷新失败 ({type(e).__name__}: {e}) —— 不影响链")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=("render", "single", "train", "all"), default="all")
    ap.add_argument("--doses", default=",".join(str(d) for d in DOSES))
    ap.add_argument("--seeds", default=",".join(str(s) for s in SEEDS))
    ap.add_argument("--fracs", default=",".join(str(f) for f in FRACS))
    args = ap.parse_args()
    doses = [int(x) for x in args.doses.split(",") if x.strip()]
    seeds = [int(x) for x in args.seeds.split(",") if x.strip()]
    fracs = [float(x) for x in args.fracs.split(",") if x.strip()]

    if args.stage in ("render", "all"):
        if not render_bigpool():
            raise SystemExit("[BIGPOOL] 渲染失败")
    if args.stage in ("single", "all"):
        to_single()
    if args.stage in ("train", "all"):
        train(doses, seeds, fracs)
    log("=== 大池剂量链结束 ===")


if __name__ == "__main__":
    main()
