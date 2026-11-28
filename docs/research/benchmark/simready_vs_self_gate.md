# 官方 SimReady 验证器 vs 本仓自研资产闸: 差异报告

生成时间: 2026-11-28T00:01:13 · 脚本: `pipelines/shelf_sdg/84_simready_vs_self_gate.py`

官方工具: **simready-validate 2026.10.0** (许可 Apache-2.0) · 运行环境: 隔离 venv (Temp/srvenv) —— 官方 wheel 需要 usd-core, 不装进训练 venv

## 一句话结论

> 自研闸里 **atlas 间隙/重叠/gutter** 与 **glTF 发布目标** 两项官方工具不管 -> 官方工具不能替代自研闸, 只能**叠加**一层 USD 侧合规校验; 自研闸守的是渲染/发布面, 官方验的是仿真面。

## 官方验证结果 (逐资产 x profile)

| 资产 | profile | 版本 | 结果 | 失败 feature | 阻断失败 | feature 数 | 耗时 |
|---|---|---|---|---|---|---|---|
| ours | Assembly | 0.1.0 | **FAIL** | 7 | 7 | 8 | 0.11s |
| ours | Material | 1.0.0 | **FAIL** | 3 | 3 | 6 | 0.233s |
| ours | NuRec | 1.0.0 | **FAIL** | 2 | 2 | 2 | 0.035s |
| ours | Open-Taxonomy-ADE20K | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.022s |
| ours | Open-Taxonomy-COCO | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.026s |
| ours | Open-Taxonomy-Cityscapes | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.023s |
| ours | Open-Taxonomy-ImageNet1K | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.03s |
| ours | Open-Taxonomy-PascalVOC | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.024s |
| ours | Open-Taxonomy-SUNRGBD | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.023s |
| ours | Package | - | **UNAVAILABLE** | 0 | 0 | - | -s |
| ours | Package-Candidate | 1.3.0 | **FAIL** | 2 | 2 | 2 | 0.016s |
| ours | Package-NoBOM | - | **UNAVAILABLE** | 0 | 0 | - | -s |
| ours | Robot-Assembly | 0.1.0 | **FAIL** | 5 | 5 | 7 | 0.058s |
| ours | Robot-Body | 4.0.0 | **FAIL** | 30 | 26 | 36 | 0.292s |
| ours | Robot-Gripper | 4.0.0 | **FAIL** | 32 | 29 | 39 | 0.258s |
| ours | Robotics-Prop | 5.0.0 | **FAIL** | 22 | 19 | 27 | 0.232s |
| usdcraft_a | Assembly | 0.1.0 | **FAIL** | 5 | 5 | 8 | 0.062s |
| usdcraft_a | Material | 1.0.0 | **PASS** | 2 | 0 | 6 | 0.112s |
| usdcraft_a | NuRec | 1.0.0 | **FAIL** | 1 | 1 | 2 | 0.029s |
| usdcraft_a | Open-Taxonomy-ADE20K | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.032s |
| usdcraft_a | Open-Taxonomy-COCO | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.035s |
| usdcraft_a | Open-Taxonomy-Cityscapes | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.033s |
| usdcraft_a | Open-Taxonomy-ImageNet1K | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.029s |
| usdcraft_a | Open-Taxonomy-PascalVOC | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.038s |
| usdcraft_a | Open-Taxonomy-SUNRGBD | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.029s |
| usdcraft_a | Package | - | **UNAVAILABLE** | 0 | 0 | - | -s |
| usdcraft_a | Package-Candidate | 1.3.0 | **PASS** | 0 | 0 | 2 | 0.009s |
| usdcraft_a | Package-NoBOM | - | **UNAVAILABLE** | 0 | 0 | - | -s |
| usdcraft_a | Robot-Assembly | 0.1.0 | **FAIL** | 3 | 2 | 7 | 0.064s |
| usdcraft_a | Robot-Body | 4.0.0 | **FAIL** | 24 | 8 | 36 | 0.46s |
| usdcraft_a | Robot-Gripper | 4.0.0 | **FAIL** | 25 | 7 | 39 | 0.469s |
| usdcraft_a | Robotics-Prop | 5.0.0 | **FAIL** | 17 | 4 | 27 | 0.467s |
| usdcraft_b | Assembly | 0.1.0 | **FAIL** | 6 | 5 | 8 | 0.075s |
| usdcraft_b | Material | 1.0.0 | **PASS** | 2 | 0 | 6 | 0.195s |
| usdcraft_b | NuRec | 1.0.0 | **FAIL** | 1 | 1 | 2 | 0.036s |
| usdcraft_b | Open-Taxonomy-ADE20K | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.034s |
| usdcraft_b | Open-Taxonomy-COCO | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.034s |
| usdcraft_b | Open-Taxonomy-Cityscapes | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.047s |
| usdcraft_b | Open-Taxonomy-ImageNet1K | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.045s |
| usdcraft_b | Open-Taxonomy-PascalVOC | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.039s |
| usdcraft_b | Open-Taxonomy-SUNRGBD | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.035s |
| usdcraft_b | Package | - | **UNAVAILABLE** | 0 | 0 | - | -s |
| usdcraft_b | Package-Candidate | 1.3.0 | **PASS** | 0 | 0 | 2 | 0.013s |
| usdcraft_b | Package-NoBOM | - | **UNAVAILABLE** | 0 | 0 | - | -s |
| usdcraft_b | Robot-Assembly | 0.1.0 | **FAIL** | 4 | 4 | 7 | 0.062s |
| usdcraft_b | Robot-Body | 4.0.0 | **FAIL** | 26 | 16 | 36 | 4.009s |
| usdcraft_b | Robot-Gripper | 4.0.0 | **FAIL** | 28 | 20 | 39 | 3.964s |
| usdcraft_b | Robotics-Prop | 5.0.0 | **FAIL** | 19 | 4 | 27 | 3.926s |
| usdcraft_c | Assembly | 0.1.0 | **FAIL** | 5 | 5 | 8 | 0.085s |
| usdcraft_c | Material | 1.0.0 | **FAIL** | 3 | 1 | 6 | 0.232s |
| usdcraft_c | NuRec | 1.0.0 | **FAIL** | 1 | 1 | 2 | 0.053s |
| usdcraft_c | Open-Taxonomy-ADE20K | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.051s |
| usdcraft_c | Open-Taxonomy-COCO | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.052s |
| usdcraft_c | Open-Taxonomy-Cityscapes | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.056s |
| usdcraft_c | Open-Taxonomy-ImageNet1K | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.053s |
| usdcraft_c | Open-Taxonomy-PascalVOC | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.051s |
| usdcraft_c | Open-Taxonomy-SUNRGBD | 0.1.0 | **FAIL** | 2 | 2 | 3 | 0.055s |
| usdcraft_c | Package | - | **UNAVAILABLE** | 0 | 0 | - | -s |
| usdcraft_c | Package-Candidate | 1.3.0 | **PASS** | 0 | 0 | 2 | 0.014s |
| usdcraft_c | Package-NoBOM | - | **UNAVAILABLE** | 0 | 0 | - | -s |
| usdcraft_c | Robot-Assembly | 0.1.0 | **FAIL** | 3 | 2 | 7 | 0.096s |
| usdcraft_c | Robot-Body | 4.0.0 | **FAIL** | 25 | 8 | 36 | 0.743s |
| usdcraft_c | Robot-Gripper | 4.0.0 | **FAIL** | 26 | 8 | 39 | 0.739s |
| usdcraft_c | Robotics-Prop | 5.0.0 | **FAIL** | 18 | 5 | 27 | 0.693s |

> `UNAVAILABLE` = 官方执行不可用 (checker ERROR / profile 未解析), **不是** measured failure; `ERROR` = 调用本身报错。两者都不许读成"资产不合规"。

## 本仓资产被官方点名的具体 requirement (可直接排期)

| profile | feature | requirement | 官方原话 |
|---|---|---|---|
| Assembly | `CAP027_Connections.0-1-0` | `com.nvidia.simready.CN.001` | Assembly default prim '/Product' has no 'Connections' Scope. |
| Assembly | `CAP027_Connections.0-1-0` | `com.nvidia.simready.CN.008` | Assembly default prim '/Product' does not author 'simready:mate:assemblyType'. |
| Assembly | `CAP027_Connections.0-1-0` | `com.nvidia.simready.CN.012` | Assembly default prim '/Product' has kind 'component'; it must be 'assembly'. |
| Assembly | `CAP029_ConnectionJoint.0-1-0` | `com.nvidia.simready.CN.001` | Assembly default prim '/Product' has no 'Connections' Scope. |
| Assembly | `CAP029_ConnectionJoint.0-1-0` | `com.nvidia.simready.CN.008` | Assembly default prim '/Product' does not author 'simready:mate:assemblyType'. |
| Assembly | `CAP029_ConnectionJoint.0-1-0` | `com.nvidia.simready.CN.012` | Assembly default prim '/Product' has kind 'component'; it must be 'assembly'. |
| Assembly | `CAP029_ConnectionJoint.MuJoCo.0-1-0` | `com.nvidia.simready.CN.001` | Assembly default prim '/Product' has no 'Connections' Scope. |
| Assembly | `CAP029_ConnectionJoint.MuJoCo.0-1-0` | `com.nvidia.simready.CN.008` | Assembly default prim '/Product' does not author 'simready:mate:assemblyType'. |
| Assembly | `CAP029_ConnectionJoint.MuJoCo.0-1-0` | `com.nvidia.simready.CN.012` | Assembly default prim '/Product' has kind 'component'; it must be 'assembly'. |
| Assembly | `CAP029_ConnectionJoint.Newton.0-1-0` | `com.nvidia.simready.CN.001` | Assembly default prim '/Product' has no 'Connections' Scope. |
| Assembly | `CAP029_ConnectionJoint.Newton.0-1-0` | `com.nvidia.simready.CN.008` | Assembly default prim '/Product' does not author 'simready:mate:assemblyType'. |
| Assembly | `CAP029_ConnectionJoint.Newton.0-1-0` | `com.nvidia.simready.CN.012` | Assembly default prim '/Product' has kind 'component'; it must be 'assembly'. |
| Assembly | `CAP029_ConnectionJoint.PhysX.0-1-0` | `com.nvidia.simready.CN.001` | Assembly default prim '/Product' has no 'Connections' Scope. |
| Assembly | `CAP029_ConnectionJoint.PhysX.0-1-0` | `com.nvidia.simready.CN.008` | Assembly default prim '/Product' does not author 'simready:mate:assemblyType'. |
| Assembly | `CAP029_ConnectionJoint.PhysX.0-1-0` | `com.nvidia.simready.CN.012` | Assembly default prim '/Product' has kind 'component'; it must be 'assembly'. |
| Assembly | `FET003_RigidBody.0-2-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Assembly | `FET004_Multibody.0-2-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Material | `CAP000_Core.0-2-0` | `com.nvidia.simready.NP.005` | Exactly one USD file is allowed in the intermediate folder 'demo_classic' (the main asset file). Found 3: Product.usda, geometry.usdc, materials.usda |
| Material | `CAP031_SelfContainedPackage.0-1-0` | `com.nvidia.usd.AA.001` | Dependent Reference "../../../assets/textures/demo_classic_albedo.png" (resolved to "assets\textures\demo_classic_albedo.png") is outside of the asset root. |
| Material | `CAP033_SimReadyPackage.0-4-0` | `com.nvidia.simready.SR.002` | No thumbnail found at output/usd/demo_classic/.thumbs/256x256/Product.usda.png for SimReady asset <output/usd/demo_classic/Product.usda> |
| Material | `CAP033_SimReadyPackage.0-4-0` | `com.nvidia.simready.SR.004` | Required metadata fields are missing: author, asset_name, asset_type, asset_license, category, source_file, usd_date_generated, qcode, rigid_body_count, asset_extents, mass. Fields may be authored in root-layer customLayerData (including SimReady_Metadata) and/or the same-directory sidecar JSON. |
| Material | `CAP033_SimReadyPackage.0-4-0` | `com.nvidia.usd.AA.001` | Dependent Reference "../../../assets/textures/demo_classic_albedo.png" (resolved to "assets\textures\demo_classic_albedo.png") is outside of the asset root. |
| NuRec | `CAP000_Core.0-2-0` | `com.nvidia.simready.NP.005` | Exactly one USD file is allowed in the intermediate folder 'demo_classic' (the main asset file). Found 3: Product.usda, geometry.usdc, materials.usda |
| NuRec | `FET012_GaussianSplat.0-1-0` | `com.nvidia.simready.SPL.001` | No 'ParticleField3DGaussianSplat' prim found. FET_012 requires the asset's visual representation to be a 3D Gaussian Splat. |
| NuRec | `FET012_GaussianSplat.0-1-0` | `com.nvidia.simready.UN.006` | Stage has upAxis of 'Y', not 'Z'. |
| NuRec | `FET012_GaussianSplat.0-1-0` | `com.nvidia.usd.AA.001` | Dependent Reference "../../../assets/textures/demo_classic_albedo.png" (resolved to "assets\textures\demo_classic_albedo.png") is outside of the asset root. |
| Open-Taxonomy-ADE20K | `CAP000_Core.0-1-0` | `com.nvidia.simready.NP.005` | Exactly one USD file is allowed in the intermediate folder 'demo_classic' (the main asset file). Found 3: Product.usda, geometry.usdc, materials.usda |
| Open-Taxonomy-ADE20K | `CAP000_Core.0-1-0` | `com.nvidia.simready.NP.006` | Asset 'Product' has no metadata. Metadata must be stored in custom layer data as 'SimReady_Metadata' or a sidecar JSON file. |
| Open-Taxonomy-ADE20K | `CAP000_Core.0-1-0` | `com.nvidia.simready.SR.001` | Required metadata fields are missing: SimReady_Metadata, asset_name, asset_type, source_file, usd_date_generated. Fields must be authored directly in the root layer's customLayerData. |
| Open-Taxonomy-ADE20K | `FET011_SemanticLabels.0-2-0` | `com.nvidia.simready.SL.001` | Unlabeled prim: no SemanticsLabelsAPI semantics found on the prim, its ancestors, its bound material, or its GeomSubsets. |
| Open-Taxonomy-COCO | `CAP000_Core.0-1-0` | `com.nvidia.simready.NP.005` | Exactly one USD file is allowed in the intermediate folder 'demo_classic' (the main asset file). Found 3: Product.usda, geometry.usdc, materials.usda |
| Open-Taxonomy-COCO | `CAP000_Core.0-1-0` | `com.nvidia.simready.NP.006` | Asset 'Product' has no metadata. Metadata must be stored in custom layer data as 'SimReady_Metadata' or a sidecar JSON file. |
| Open-Taxonomy-COCO | `CAP000_Core.0-1-0` | `com.nvidia.simready.SR.001` | Required metadata fields are missing: SimReady_Metadata, asset_name, asset_type, source_file, usd_date_generated. Fields must be authored directly in the root layer's customLayerData. |
| Open-Taxonomy-COCO | `FET011_SemanticLabels.0-2-0` | `com.nvidia.simready.SL.001` | Unlabeled prim: no SemanticsLabelsAPI semantics found on the prim, its ancestors, its bound material, or its GeomSubsets. |
| Open-Taxonomy-Cityscapes | `CAP000_Core.0-1-0` | `com.nvidia.simready.NP.005` | Exactly one USD file is allowed in the intermediate folder 'demo_classic' (the main asset file). Found 3: Product.usda, geometry.usdc, materials.usda |
| Open-Taxonomy-Cityscapes | `CAP000_Core.0-1-0` | `com.nvidia.simready.NP.006` | Asset 'Product' has no metadata. Metadata must be stored in custom layer data as 'SimReady_Metadata' or a sidecar JSON file. |
| Open-Taxonomy-Cityscapes | `CAP000_Core.0-1-0` | `com.nvidia.simready.SR.001` | Required metadata fields are missing: SimReady_Metadata, asset_name, asset_type, source_file, usd_date_generated. Fields must be authored directly in the root layer's customLayerData. |
| Open-Taxonomy-Cityscapes | `FET011_SemanticLabels.0-2-0` | `com.nvidia.simready.SL.001` | Unlabeled prim: no SemanticsLabelsAPI semantics found on the prim, its ancestors, its bound material, or its GeomSubsets. |
| Open-Taxonomy-ImageNet1K | `CAP000_Core.0-1-0` | `com.nvidia.simready.NP.005` | Exactly one USD file is allowed in the intermediate folder 'demo_classic' (the main asset file). Found 3: Product.usda, geometry.usdc, materials.usda |
| Open-Taxonomy-ImageNet1K | `CAP000_Core.0-1-0` | `com.nvidia.simready.NP.006` | Asset 'Product' has no metadata. Metadata must be stored in custom layer data as 'SimReady_Metadata' or a sidecar JSON file. |
| Open-Taxonomy-ImageNet1K | `CAP000_Core.0-1-0` | `com.nvidia.simready.SR.001` | Required metadata fields are missing: SimReady_Metadata, asset_name, asset_type, source_file, usd_date_generated. Fields must be authored directly in the root layer's customLayerData. |
| Open-Taxonomy-ImageNet1K | `FET011_SemanticLabels.0-2-0` | `com.nvidia.simready.SL.001` | Unlabeled prim: no SemanticsLabelsAPI semantics found on the prim, its ancestors, its bound material, or its GeomSubsets. |
| Open-Taxonomy-PascalVOC | `CAP000_Core.0-1-0` | `com.nvidia.simready.NP.005` | Exactly one USD file is allowed in the intermediate folder 'demo_classic' (the main asset file). Found 3: Product.usda, geometry.usdc, materials.usda |
| Open-Taxonomy-PascalVOC | `CAP000_Core.0-1-0` | `com.nvidia.simready.NP.006` | Asset 'Product' has no metadata. Metadata must be stored in custom layer data as 'SimReady_Metadata' or a sidecar JSON file. |
| Open-Taxonomy-PascalVOC | `CAP000_Core.0-1-0` | `com.nvidia.simready.SR.001` | Required metadata fields are missing: SimReady_Metadata, asset_name, asset_type, source_file, usd_date_generated. Fields must be authored directly in the root layer's customLayerData. |
| Open-Taxonomy-PascalVOC | `FET011_SemanticLabels.0-2-0` | `com.nvidia.simready.SL.001` | Unlabeled prim: no SemanticsLabelsAPI semantics found on the prim, its ancestors, its bound material, or its GeomSubsets. |
| Open-Taxonomy-SUNRGBD | `CAP000_Core.0-1-0` | `com.nvidia.simready.NP.005` | Exactly one USD file is allowed in the intermediate folder 'demo_classic' (the main asset file). Found 3: Product.usda, geometry.usdc, materials.usda |
| Open-Taxonomy-SUNRGBD | `CAP000_Core.0-1-0` | `com.nvidia.simready.NP.006` | Asset 'Product' has no metadata. Metadata must be stored in custom layer data as 'SimReady_Metadata' or a sidecar JSON file. |
| Open-Taxonomy-SUNRGBD | `CAP000_Core.0-1-0` | `com.nvidia.simready.SR.001` | Required metadata fields are missing: SimReady_Metadata, asset_name, asset_type, source_file, usd_date_generated. Fields must be authored directly in the root layer's customLayerData. |
| Open-Taxonomy-SUNRGBD | `FET011_SemanticLabels.0-2-0` | `com.nvidia.simready.SL.001` | Unlabeled prim: no SemanticsLabelsAPI semantics found on the prim, its ancestors, its bound material, or its GeomSubsets. |
| Package-Candidate | `CAP031_SelfContainedPackage.0-1-0` | `com.nvidia.usd.AA.001` | Dependent Reference "../../../assets/textures/demo_classic_albedo.png" (resolved to "assets\textures\demo_classic_albedo.png") is outside of the asset root. |
| Package-Candidate | `CAP033_SimReadyPackage.0-4-0` | `com.nvidia.simready.SR.002` | No thumbnail found at output/usd/demo_classic/.thumbs/256x256/Product.usda.png for SimReady asset <output/usd/demo_classic/Product.usda> |
| Package-Candidate | `CAP033_SimReadyPackage.0-4-0` | `com.nvidia.simready.SR.004` | Required metadata fields are missing: author, asset_name, asset_type, asset_license, category, source_file, usd_date_generated, qcode, rigid_body_count, asset_extents, mass. Fields may be authored in root-layer customLayerData (including SimReady_Metadata) and/or the same-directory sidecar JSON. |
| Package-Candidate | `CAP033_SimReadyPackage.0-4-0` | `com.nvidia.usd.AA.001` | Dependent Reference "../../../assets/textures/demo_classic_albedo.png" (resolved to "assets\textures\demo_classic_albedo.png") is outside of the asset root. |
| Robot-Assembly | `CAP027_Connections.0-1-0` | `com.nvidia.simready.CN.001` | Assembly default prim '/Product' has no 'Connections' Scope. |
| Robot-Assembly | `CAP027_Connections.0-1-0` | `com.nvidia.simready.CN.008` | Assembly default prim '/Product' does not author 'simready:mate:assemblyType'. |
| Robot-Assembly | `CAP027_Connections.0-1-0` | `com.nvidia.simready.CN.012` | Assembly default prim '/Product' has kind 'component'; it must be 'assembly'. |
| Robot-Assembly | `CAP029_ConnectionJoint.0-1-0` | `com.nvidia.simready.CN.001` | Assembly default prim '/Product' has no 'Connections' Scope. |
| Robot-Assembly | `CAP029_ConnectionJoint.0-1-0` | `com.nvidia.simready.CN.008` | Assembly default prim '/Product' does not author 'simready:mate:assemblyType'. |
| Robot-Assembly | `CAP029_ConnectionJoint.0-1-0` | `com.nvidia.simready.CN.012` | Assembly default prim '/Product' has kind 'component'; it must be 'assembly'. |
| Robot-Assembly | `FET003_RigidBody.0-2-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Assembly | `FET004_Multibody.0-2-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Assembly | `FET004_Multibody.0-2-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Assembly | `FET022_DrivenJoints.0-2-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Assembly | `FET022_DrivenJoints.0-2-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Body | `CAP000_Core.0-2-0` | `com.nvidia.simready.NP.005` | Exactly one USD file is allowed in the intermediate folder 'demo_classic' (the main asset file). Found 3: Product.usda, geometry.usdc, materials.usda |
| Robot-Body | `CAP000_Core.Isaac.0-2-0` | `com.nvidia.simready.NP.005` | Exactly one USD file is allowed in the intermediate folder 'demo_classic' (the main asset file). Found 3: Product.usda, geometry.usdc, materials.usda |
| Robot-Body | `CAP000_Core.MuJoCo.0-2-0` | `com.nvidia.simready.NP.005` | Exactly one USD file is allowed in the intermediate folder 'demo_classic' (the main asset file). Found 3: Product.usda, geometry.usdc, materials.usda |
| Robot-Body | `CAP000_Core.Newton.0-2-0` | `com.nvidia.simready.NP.005` | Exactly one USD file is allowed in the intermediate folder 'demo_classic' (the main asset file). Found 3: Product.usda, geometry.usdc, materials.usda |
| Robot-Body | `CAP000_Core.Newton.0-2-0` | `com.nvidia.simready.RV.004` | Default prim </Product> must declare a 'Newton' physics runtime variant set. |
| Robot-Body | `CAP000_Core.PhysX.0-2-0` | `com.nvidia.simready.NP.005` | Exactly one USD file is allowed in the intermediate folder 'demo_classic' (the main asset file). Found 3: Product.usda, geometry.usdc, materials.usda |
| Robot-Body | `CAP003_RigidBody.MuJoCo.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Body | `CAP004_Multibody.MuJoCo.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Body | `CAP004_Multibody.MuJoCo.0-1-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Body | `CAP004_Multibody.RobotMuJoCo.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Body | `CAP004_Multibody.RobotMuJoCo.0-1-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Body | `CAP022_DrivenJoints.MuJoCo.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Body | `CAP022_DrivenJoints.MuJoCo.0-1-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Body | `CAP024_BaseArticulation.Newton.0-1-0` | `com.nvidia.simready.NEWTON.BA.001` | Newton articulation configuration requires exactly one UsdPhysics.ArticulationRootAPI prim; found 0. |
| Robot-Body | `CAP031_SelfContainedPackage.0-1-0` | `com.nvidia.usd.AA.001` | Dependent Reference "../../../assets/textures/demo_classic_albedo.png" (resolved to "assets\textures\demo_classic_albedo.png") is outside of the asset root. |
| Robot-Body | `CAP033_SimReadyPackage.0-4-0` | `com.nvidia.simready.SR.002` | No thumbnail found at output/usd/demo_classic/.thumbs/256x256/Product.usda.png for SimReady asset <output/usd/demo_classic/Product.usda> |
| Robot-Body | `CAP033_SimReadyPackage.0-4-0` | `com.nvidia.simready.SR.004` | Required metadata fields are missing: author, asset_name, asset_type, asset_license, category, source_file, usd_date_generated, qcode, rigid_body_count, asset_extents, mass. Fields may be authored in root-layer customLayerData (including SimReady_Metadata) and/or the same-directory sidecar JSON. |
| Robot-Body | `CAP033_SimReadyPackage.0-4-0` | `com.nvidia.usd.AA.001` | Dependent Reference "../../../assets/textures/demo_classic_albedo.png" (resolved to "assets\textures\demo_classic_albedo.png") is outside of the asset root. |
| Robot-Body | `FET001_MinimalPlaceableVisual.1-0-1` | `com.nvidia.simready.UN.006` | Stage has upAxis of 'Y', not 'Z'. |
| Robot-Body | `FET001_MinimalPlaceableVisual.1-0-1` | `com.nvidia.usd.AA.001` | Dependent Reference "../../../assets/textures/demo_classic_albedo.png" (resolved to "assets\textures\demo_classic_albedo.png") is outside of the asset root. |
| Robot-Body | `FET003_RigidBody.0-2-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Body | `FET003_RigidBody.Newton.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Body | `FET003_RigidBody.PhysX.0-4-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Body | `FET004_Multibody.0-2-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Body | `FET004_Multibody.0-2-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Body | `FET004_Multibody.Newton.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Body | `FET004_Multibody.Newton.0-1-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Body | `FET004_Multibody.PhysX.0-4-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Body | `FET004_Multibody.PhysX.0-4-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Body | `FET004_Multibody.RobotNewton.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Body | `FET004_Multibody.RobotNewton.0-1-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Body | `FET008_ObjectForward.0-1-0` | `com.nvidia.simready.UN.006` | Stage has upAxis of 'Y', not 'Z'. |
| Robot-Body | `FET008_ObjectForward.0-1-0` | `com.nvidia.usd.AA.001` | Dependent Reference "../../../assets/textures/demo_classic_albedo.png" (resolved to "assets\textures\demo_classic_albedo.png") is outside of the asset root. |
| Robot-Body | `FET009_MaterialCoverage.0-1-0` | `com.nvidia.simready.VM.MAT.001` | GPrim '/Product/Carton_demo_classic/CapLip_demo_classic/Cylinder_001' does not have a material binding |
| Robot-Body | `FET022_DrivenJoints.0-2-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Body | `FET022_DrivenJoints.0-2-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Body | `FET022_DrivenJoints.Isaac.0-2-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Body | `FET022_DrivenJoints.Isaac.0-2-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Body | `FET022_DrivenJoints.PhysX.0-2-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Body | `FET022_DrivenJoints.PhysX.0-2-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Body | `FET022_DrivenJoints.Newton.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Body | `FET022_DrivenJoints.Newton.0-1-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Gripper | `CAP000_Core.0-2-0` | `com.nvidia.simready.NP.005` | Exactly one USD file is allowed in the intermediate folder 'demo_classic' (the main asset file). Found 3: Product.usda, geometry.usdc, materials.usda |
| Robot-Gripper | `CAP000_Core.MuJoCo.0-2-0` | `com.nvidia.simready.NP.005` | Exactly one USD file is allowed in the intermediate folder 'demo_classic' (the main asset file). Found 3: Product.usda, geometry.usdc, materials.usda |
| Robot-Gripper | `CAP000_Core.Newton.0-2-0` | `com.nvidia.simready.NP.005` | Exactly one USD file is allowed in the intermediate folder 'demo_classic' (the main asset file). Found 3: Product.usda, geometry.usdc, materials.usda |
| Robot-Gripper | `CAP000_Core.Newton.0-2-0` | `com.nvidia.simready.RV.004` | Default prim </Product> must declare a 'Newton' physics runtime variant set. |
| Robot-Gripper | `CAP000_Core.PhysX.0-2-0` | `com.nvidia.simready.NP.005` | Exactly one USD file is allowed in the intermediate folder 'demo_classic' (the main asset file). Found 3: Product.usda, geometry.usdc, materials.usda |
| Robot-Gripper | `CAP003_RigidBody.MuJoCo.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Gripper | `CAP004_Multibody.MuJoCo.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Gripper | `CAP004_Multibody.MuJoCo.0-1-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Gripper | `CAP004_Multibody.RobotMuJoCo.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Gripper | `CAP004_Multibody.RobotMuJoCo.0-1-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Gripper | `CAP022_DrivenJoints.MuJoCo.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Gripper | `CAP022_DrivenJoints.MuJoCo.0-1-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Gripper | `CAP024_BaseArticulation.Newton.0-1-0` | `com.nvidia.simready.NEWTON.BA.001` | Newton articulation configuration requires exactly one UsdPhysics.ArticulationRootAPI prim; found 0. |
| Robot-Gripper | `CAP028_Gripper.MuJoCo.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Gripper | `CAP028_Gripper.MuJoCo.0-1-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Gripper | `CAP031_SelfContainedPackage.0-1-0` | `com.nvidia.usd.AA.001` | Dependent Reference "../../../assets/textures/demo_classic_albedo.png" (resolved to "assets\textures\demo_classic_albedo.png") is outside of the asset root. |
| Robot-Gripper | `CAP033_SimReadyPackage.0-4-0` | `com.nvidia.simready.SR.002` | No thumbnail found at output/usd/demo_classic/.thumbs/256x256/Product.usda.png for SimReady asset <output/usd/demo_classic/Product.usda> |
| Robot-Gripper | `CAP033_SimReadyPackage.0-4-0` | `com.nvidia.simready.SR.004` | Required metadata fields are missing: author, asset_name, asset_type, asset_license, category, source_file, usd_date_generated, qcode, rigid_body_count, asset_extents, mass. Fields may be authored in root-layer customLayerData (including SimReady_Metadata) and/or the same-directory sidecar JSON. |
| Robot-Gripper | `CAP033_SimReadyPackage.0-4-0` | `com.nvidia.usd.AA.001` | Dependent Reference "../../../assets/textures/demo_classic_albedo.png" (resolved to "assets\textures\demo_classic_albedo.png") is outside of the asset root. |
| Robot-Gripper | `FET001_MinimalPlaceableVisual.1-0-1` | `com.nvidia.simready.UN.006` | Stage has upAxis of 'Y', not 'Z'. |
| Robot-Gripper | `FET001_MinimalPlaceableVisual.1-0-1` | `com.nvidia.usd.AA.001` | Dependent Reference "../../../assets/textures/demo_classic_albedo.png" (resolved to "assets\textures\demo_classic_albedo.png") is outside of the asset root. |
| Robot-Gripper | `FET003_RigidBody.0-2-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Gripper | `FET003_RigidBody.Newton.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Gripper | `FET003_RigidBody.PhysX.0-4-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Gripper | `FET004_Multibody.0-2-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Gripper | `FET004_Multibody.0-2-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Gripper | `FET004_Multibody.Newton.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Gripper | `FET004_Multibody.Newton.0-1-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Gripper | `FET004_Multibody.PhysX.0-4-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Gripper | `FET004_Multibody.PhysX.0-4-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Gripper | `FET004_Multibody.RobotNewton.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Gripper | `FET004_Multibody.RobotNewton.0-1-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Gripper | `FET004_Multibody.RobotPhysX.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Gripper | `FET004_Multibody.RobotPhysX.0-1-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Gripper | `FET009_MaterialCoverage.0-1-0` | `com.nvidia.simready.VM.MAT.001` | GPrim '/Product/Carton_demo_classic/CapLip_demo_classic/Cylinder_001' does not have a material binding |
| Robot-Gripper | `FET022_DrivenJoints.0-2-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Gripper | `FET022_DrivenJoints.0-2-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Gripper | `FET022_DrivenJoints.Isaac.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Gripper | `FET022_DrivenJoints.Isaac.0-1-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Gripper | `FET022_DrivenJoints.PhysX.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Gripper | `FET022_DrivenJoints.PhysX.0-1-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Gripper | `FET022_DrivenJoints.Isaac.0-2-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Gripper | `FET022_DrivenJoints.Isaac.0-2-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Gripper | `FET022_DrivenJoints.PhysX.0-2-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Gripper | `FET022_DrivenJoints.PhysX.0-2-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Gripper | `FET022_DrivenJoints.Newton.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Gripper | `FET022_DrivenJoints.Newton.0-1-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robot-Gripper | `FET028_Gripper.Isaac.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robot-Gripper | `FET028_Gripper.Isaac.0-1-0` | `com.nvidia.simready.RB.MB.001` | Not enough physics rigid bodies found under the default prim. Found 0, expected at least 2. |
| Robotics-Prop | `CAP000_Core.0-2-0` | `com.nvidia.simready.NP.005` | Exactly one USD file is allowed in the intermediate folder 'demo_classic' (the main asset file). Found 3: Product.usda, geometry.usdc, materials.usda |
| Robotics-Prop | `CAP000_Core.MuJoCo.0-2-0` | `com.nvidia.simready.NP.005` | Exactly one USD file is allowed in the intermediate folder 'demo_classic' (the main asset file). Found 3: Product.usda, geometry.usdc, materials.usda |
| Robotics-Prop | `CAP000_Core.Newton.0-2-0` | `com.nvidia.simready.NP.005` | Exactly one USD file is allowed in the intermediate folder 'demo_classic' (the main asset file). Found 3: Product.usda, geometry.usdc, materials.usda |
| Robotics-Prop | `CAP000_Core.PhysX.0-2-0` | `com.nvidia.simready.NP.005` | Exactly one USD file is allowed in the intermediate folder 'demo_classic' (the main asset file). Found 3: Product.usda, geometry.usdc, materials.usda |
| Robotics-Prop | `CAP003_RigidBody.MuJoCo.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robotics-Prop | `CAP004_Multibody.MuJoCo.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robotics-Prop | `CAP031_SelfContainedPackage.0-1-0` | `com.nvidia.usd.AA.001` | Dependent Reference "../../../assets/textures/demo_classic_albedo.png" (resolved to "assets\textures\demo_classic_albedo.png") is outside of the asset root. |
| Robotics-Prop | `CAP033_SimReadyPackage.0-4-0` | `com.nvidia.simready.SR.002` | No thumbnail found at output/usd/demo_classic/.thumbs/256x256/Product.usda.png for SimReady asset <output/usd/demo_classic/Product.usda> |
| Robotics-Prop | `CAP033_SimReadyPackage.0-4-0` | `com.nvidia.simready.SR.004` | Required metadata fields are missing: author, asset_name, asset_type, asset_license, category, source_file, usd_date_generated, qcode, rigid_body_count, asset_extents, mass. Fields may be authored in root-layer customLayerData (including SimReady_Metadata) and/or the same-directory sidecar JSON. |
| Robotics-Prop | `CAP033_SimReadyPackage.0-4-0` | `com.nvidia.usd.AA.001` | Dependent Reference "../../../assets/textures/demo_classic_albedo.png" (resolved to "assets\textures\demo_classic_albedo.png") is outside of the asset root. |
| Robotics-Prop | `FET001_MinimalPlaceableVisual.1-0-1` | `com.nvidia.simready.UN.006` | Stage has upAxis of 'Y', not 'Z'. |
| Robotics-Prop | `FET001_MinimalPlaceableVisual.1-0-1` | `com.nvidia.usd.AA.001` | Dependent Reference "../../../assets/textures/demo_classic_albedo.png" (resolved to "assets\textures\demo_classic_albedo.png") is outside of the asset root. |
| Robotics-Prop | `FET003_RigidBody.0-2-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robotics-Prop | `FET003_RigidBody.Newton.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robotics-Prop | `FET003_RigidBody.PhysX.0-4-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robotics-Prop | `FET004_Multibody.0-2-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robotics-Prop | `FET004_Multibody.Newton.0-1-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robotics-Prop | `FET004_Multibody.PhysX.0-4-0` | `com.nvidia.simready.RB.001` | No physics rigid bodies found under the default prim. |
| Robotics-Prop | `FET008_ObjectForward.0-1-0` | `com.nvidia.simready.AF.001` | /Product must author simready:assetFrame:forwardDirection |
| Robotics-Prop | `FET008_ObjectForward.0-1-0` | `com.nvidia.simready.UN.006` | Stage has upAxis of 'Y', not 'Z'. |
| Robotics-Prop | `FET008_ObjectForward.0-1-0` | `com.nvidia.usd.AA.001` | Dependent Reference "../../../assets/textures/demo_classic_albedo.png" (resolved to "assets\textures\demo_classic_albedo.png") is outside of the asset root. |
| Robotics-Prop | `FET009_MaterialCoverage.0-1-0` | `com.nvidia.simready.VM.MAT.001` | GPrim '/Product/Carton_demo_classic/CapLip_demo_classic/Cylinder_001' does not have a material binding |
| Robotics-Prop | `FET011_SemanticLabels.0-2-0` | `com.nvidia.simready.SL.001` | Unlabeled prim: no SemanticsLabelsAPI semantics found on the prim, its ancestors, its bound material, or its GeomSubsets. |
| Robotics-Prop | `FET011_SemanticLabels.RTX.0-1-0` | `com.nvidia.simready.SL.001` | Unlabeled prim: no SemanticsLabelsAPI semantics found on the prim, its ancestors, its bound material, or its GeomSubsets. |

## 自研闸 (本仓, 82 号脚本现算)

资产 `demo_classic` · 总判据 **PASS**

| 检查 | 判据 | 细节 |
|---|---|---|
| origin_units | PASS | bottom=0.00mm center=(0.0,0.0)mm dims=(48.0,38.0,113.0)mm spec=(48.0, 38.0, 113.0) |
| topology | PASS | ngons=0 nonmanifold_edges=0 tris=188 |
| uv_01 | PASS | uv range [0.0293,0.9961] |
| uv_atlas | PASS | min_gap=32px overlaps=[] gutter_std=5.9 |
| export_targets | PASS | materials=2 mimes=['image/webp'] lights=False size=0.18MB |

## 覆盖面差异 (这是本报告的主体)

| 自研检查 | 内容 | 官方是否覆盖 | 说明 |
|---|---|---|---|
| `origin_units` | 原点落在底面中心 + 尺寸符合规格 (mm) | **部分** | 官方有单位/尺度/原点类 requirement (以 profile 为准); 但官方**不校验具体毫米数是否符合本仓 SKU 规格** |
| `topology` | ngon=0 / 非流形边=0 / 三角面数 <= 100k | **部分** | 官方几何 feature 覆盖三角化与流形类要求; **100k 上限是 Khronos 发布目标, 官方不管** |
| `uv_01` | UV 落在 [0,1] | **部分** | 官方材质/UV feature 覆盖 UV 合法性与绑定 |
| `uv_atlas` | atlas 岛间 >=32px 间隙 + 零重叠 + 16px gutter | **不覆盖** | 这是 **glTF/Khronos atlas 规范**, 与 SimReady profile 无关 -> 官方工具不会替我们查 |
| `export_targets` | 材质数 <=3 / 贴图 mime 限定 / 无灯光 / 文件 <=5MB | **不覆盖** | 这是 **glTF 发布目标**, 与 SimReady profile 无关 -> 官方工具不会替我们查 |

### 只有官方有的那一层

- **物理属性**: mass / inertia / 碰撞代理 / 关节 (profile 依类型而定)
- **语义与元数据**: sem:brand / sem:skuId / sem:productCategory / render:* / phys:*
- **分层 profile**: 按 Profile 选 requirement 集合 (Robotics-Prop / Package / ...)
- **验证回执**: validation receipt (可 --audit 比对上次结果)

## 本轮明确没做的事

- 未跑 simready-benchmark (需 Isaac Sim 6.1 + Linux/Windows x86-64, 本机没有)
- 未跑官方 simready-manage (未安装) —— simready-package 已在 85/86 号跑过 ✓
- 未对全部 200 件 USDCraft 资产跑全量 (只取样例)
- 未安装 usd-profiles-nvidia 的其它 tier wheel (只用默认 catalog)
- 本仓资产的单文件合规包在 86 号脚本里另做 (Package-Candidate 已 PASS) —— 这份差异报告评的是**原始三文件资产** output/usd/demo_classic/Product.usda
