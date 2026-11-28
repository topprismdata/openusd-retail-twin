---
description: CI math has exactly one home. `T_CRIT_95` and `ci95_t` are defined once, in `pipelines/common/protocol.py`. Import them; never copy the table into an arm or summary script.
condition: "T_CRIT_95\\s*=|def\\s+ci95_t\\s*\\(|\\b12\\.706\\b"
scope: tool:edit(**/pipelines/shelf_sdg/*.py), tool:write(**/pipelines/shelf_sdg/*.py), tool:edit(**/pipelines/commercial/*.py), tool:write(**/pipelines/commercial/*.py), tool:edit(**/pipelines/ecommerce/*.py), tool:write(**/pipelines/ecommerce/*.py), tool:edit(**/pipelines/pack_dieline/*.py), tool:write(**/pipelines/pack_dieline/*.py), tool:edit(**/pipelines/demo_stage/*.py), tool:write(**/pipelines/demo_stage/*.py), tool:edit(**/pipelines/topprism_virtual/*.py), tool:write(**/pipelines/topprism_virtual/*.py)
interruptMode: never
repeatMode: after-gap
agents: main
---
[单一真源提醒] 你在这个包里重新定义了一份 CI 临界值或 `ci95_t`。

本仓的 CI 数学只有一个家：`pipelines/common/protocol.py`（`T_CRIT_95`、`ci95_t`）。
历史教训：9 个 arm 脚本曾各自带一份拷贝，其中一份的 df 键错了一位，CI 区间静默偏了——
两个来源不一致时，谁也说不清哪个是对的。

正确做法：
```python
from pipelines.common.protocol import ci95_t, T_CRIT_95  # noqa: E402
```

如果你确实要改临界值本身，改 `pipelines/common/protocol.py`，并让所有调用方跟着它走。
