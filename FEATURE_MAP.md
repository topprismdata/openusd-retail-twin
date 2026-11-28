# FEATURE_MAP — ort-work

Index only. Read it, then open the file it names. Do not scan the tree.

## Module entry points

| Path | Owns | Open it when |
| --- | --- | --- |
| `run_pipeline.py` | whole-line orchestrator: bootstrap → ecom → gate_ecom → sdg → train → topprism → pack → report, fail-fast | running the full line; `--draft` for the CPU path |
| `pipelines/common/protocol.py` | reproducibility contract: `protocol_hash`, fingerprints, and the **only** CI implementation (`T_CRIT_95`, `ci95_t`) | touching a manifest, a seed, or any CI number |
| `pipelines/common/runtime_env.py` | Blender path, Cycles backend/device, memory gate | a run used a different device or silently shrank a batch |
| `pipelines/shelf_sdg/02_shelf_sdg_inspector.py` | SDG shelf renderer → labels + dataset | changing the renderer, camera recipe, or label semantics |
| `pipelines/shelf_sdg/05_train_yolo_mps.py` | YOLO training on the SDG set | training config, epochs, batch, weights |
| `pipelines/shelf_sdg/14_sku110k_baseline.py` | SKU-110K real-data arms (r0/r1/r2) | baseline or arm comparison |
| `pipelines/shelf_sdg/21_annotation_budget.py` | annotation-budget grid | budget arms and dose-response |
| `pipelines/shelf_sdg/36_fourarm_seed_variance.py` | multi-seed summary (scans **all** seeds on disk) | any seed count or CI statement |
| `pipelines/shelf_sdg/28_doc_consistency_check.py` | the acceptance gate (doc ↔ artifact, MANIFEST hashes, arm values) | before and after changing any published number |
| `pipelines/shelf_sdg/75_protocol_audit.py` | re-checks actual `train/args.yaml` vs declared protocol | a run reports numbers you did not expect |
| `pipelines/shelf_sdg/90_simready_package_pipeline.py` | one-command SimReady acceptance chain | packaging or consuming the USD asset |
| `tools/blender_shim.py` | `bpy` wheel stand-in; maps `-b -P script -- args` | running any Blender script |
| `specs/*.json` | declarative packaging / lifestyle / mutation specs | changing geometry, labels, or gates |

## Data and solver contracts

| Contract | Where it lives | Invariant |
| --- | --- | --- |
| SDG dataset | `output/sdg_shelf/{images,labels,annotations}/{train,val}` | label line = `class_id cx cy w h`, 5 decimals, normalized; classes `0 COMPLIANT / 1 OOS_GAP / 2 MISALIGNED / 3 INTRUSION` |
| Split provenance | `output/sdg_shelf/split_manifest.json` | schema `sdg_split_manifest/2`; scene-level holdout; `png_sha256` + `label_sha256` per image |
| Run identity | `output/sdg_shelf/dataset_summary.json`, `output/sdg_shelf/train_manifest.json` | renderer device, recipe, seed, and `protocol_hash` recorded in the artifact, not only in prose |
| Arm results | `output/benchmark/sku110k_{arm}_s{seed}.json` | `protocol`, `protocol_hash`, `weights.sha256`, `actual_train_config` all present; drifted runs live in `quarantine/` and never enter a summary |
| Published copies | `docs/research/benchmark/` + `docs/research/benchmark/MANIFEST.json` | copy, then publish, then manifest — order matters; published copies are path-scrubbed (no local absolute paths) |
| CI math | `pipelines/common/protocol.py` | `ci95_t` / `T_CRIT_95` are defined **once**; import them, never copy the table |
| Blender CLI | `tools/blender_shim.py` | arguments go **after** `--`; the flag is `--out`, not `--out-dir` |
| Path scrubbing | `pipelines/common/publish_paths.py` | published artifacts must not carry local absolute paths; scrubbed at publish time, compared with the same rules in the manifest |

## Acceptance commands

| Command | Checks |
| --- | --- |
| `python pipelines/shelf_sdg/28_doc_consistency_check.py` | the main gate: doc ↔ artifact protocol hashes, MANIFEST sha256, arm values, multi-seed CIs, dose-axis pool identity, CPU/GPU render equivalence |
| `python pipelines/common/selftest_protocol.py` | protocol hash stability, split seed-disjointness, fingerprint sensitivity |
| `python pipelines/common/selftest_runtime_env.py` | Blender path, Cycles backend, memory probe, torch device |
| `python pipelines/shelf_sdg/91_delivery_audit.py` | manifest integrity + clean-room open |
| `python pipelines/shelf_sdg/75_protocol_audit.py --artifact output/benchmark/<arm>.json` | actual train config (`output/benchmark/<run>/train/args.yaml`) vs declared protocol |
| `python pipelines/shelf_sdg/90_simready_package_pipeline.py -- --sku demo_classic` | SimReady package + official validate + consume check |

Run the gate after any change that moves a published number, an arm, a seed, or a
device. Numbers quoted in docs are parsed back and compared to the artifacts —
never hardcode an expected value in the gate.
