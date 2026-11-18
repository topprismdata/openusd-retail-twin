# Scan Blueberry — attribution

Extracted asset: `blueberry.blend` (mesh `ScanBlueberry`, material `ScanBlueberryMat`,
packed 2048² baseColor / normal / metallicRoughness).

Source work (CC-BY-4.0, commercial use allowed, **author must be credited**):

> This work is based on "A bowl of berries"
> (https://sketchfab.com/3d-models/a-bowl-of-berries-2e198e82d83d440e857d3a2251e767d8)
> by ¡Jacques (https://sketchfab.com/iJacques)
> licensed under CC-BY-4.0 (http://creativecommons.org/licenses/by/4.0/)

Original license text: `assets/sf_models/berries/license.txt`.

## What was changed

Only the **Blueberry** part is used (`Sphere.037_Blueberry_0`, 30172 verts / 53504 polys).
The bowl, strawberries and blackberries from the same pack are **not** used.

Processing (`extract_scan_berry.py`, offline one-shot):
1. `matrix_world` baked into the mesh — the glTF parent scale made the world bbox
   ≈ 996518 mm (~1 km), which would otherwise render a kilometre-wide sphere.
2. Normalised to **unit radius** (max XY radius = 1.0) with `zmin = 0`; callers scale it
   to the real berry radius (~10 mm).
3. Textures packed into the `.blend` so the library has no external path dependency.

Runtime loads it via `bpy.data.libraries.load` (data API) — deliberately **not**
`bpy.ops.import_scene.gltf`, which pollutes active/selected objects mid-pipeline.

## Where the credit must appear

Any published render/deliverable that includes this asset must carry the credit line
above (e.g. asset credits section of the delivery doc / product page).