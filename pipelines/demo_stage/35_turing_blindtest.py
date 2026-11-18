"""图灵维盲测板生成器 (STRICT_PROTOCOL_V2 图灵 PASS 前置实证).

协议 (ChatGPT 终审裁定):
- 20-30 张授权真实乳品商业摄影 + 本管线 CG 图 + 对照 CG 图
- >=20 名独立评审, 随机呈现, 不告知来源
- 记录 真/CG 判断 + 置信度 + 识别依据
- 核心指标: 识别准确率 vs 50% 随机基线 + 置信区间

用法:
  python3 35_turing_blindtest.py --real <真实图目录> --cg <CG图目录> --out output/turing/
生成:
  output/turing/blind_board.html   随机化盲测板 (localStorage 记票, 导出 CSV)
  output/turing/manifest.json      刺激集清单 (shuffle seed 记录)
"""
import argparse
import base64
import json
import os
import random


def b64(p):
    with open(p, "rb") as f:
        return base64.b64encode(f.read()).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", required=True)
    ap.add_argument("--cg", required=True)
    ap.add_argument("--out", default="output/turing")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    items = []
    for d, lab in ((args.real, "real"), (args.cg, "cg")):
        for f in sorted(os.listdir(d)):
            if f.lower().endswith((".png", ".jpg", ".jpeg")):
                items.append({"file": os.path.join(d, f), "label": lab})
    assert sum(i["label"] == "real" for i in items) >= 10, "真实样本需 >=10"
    rnd = random.Random(args.seed)
    rnd.shuffle(items)
    for i, it in enumerate(items):
        it["idx"] = i
        it["b64"] = b64(it["file"])
    manifest = [{"idx": it["idx"], "file": it["file"], "label": it["label"]} for it in items]
    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump({"seed": args.seed, "items": manifest}, f, indent=1)
    html = HTML.replace("__ITEMS__", json.dumps([{k: it[k] for k in ("idx", "label", "b64")} for it in items]))
    with open(os.path.join(args.out, "blind_board.html"), "w") as f:
        f.write(html)
    print(f"[TURING] {len(items)} stimuli -> {args.out}/blind_board.html")


HTML = """<!doctype html><meta charset=utf-8><title>乳品商业图 真/CG 盲测</title>
<style>body{font:14px/1.5 system-ui;margin:0;background:#111;color:#eee}
#wrap{max-width:760px;margin:0 auto;padding:24px}img{width:100%;border-radius:8px}
button{font:inherit;padding:10px 22px;margin:6px;border:1px solid #555;border-radius:8px;background:#222;color:#eee;cursor:pointer}
button:hover{background:#333}.bar{height:6px;background:#333;border-radius:3px;margin:12px 0}
.bar>i{display:block;height:100%;background:#7a5;border-radius:3px}textarea{width:100%;height:60px;background:#222;color:#eee;border:1px solid #555;border-radius:8px}</style>
<div id=wrap><h2>真/CG 盲测</h2><p>下图为真实拍摄还是 CG 渲染？请给判断、置信度(1-5)、识别依据。</p>
<div class=bar><i id=prog style=width:0></i></div><p id=pos></p>
<img id=img alt=""><div>
<button onclick=v('real')>真实拍摄</button><button onclick=v('cg')>CG 渲染</button></div>
<p>置信度 <select id=conf><option>1</option><option>2</option><option selected>3</option><option>4</option><option>5</option></select></p>
<textarea id=why placeholder="识别依据（可选）"></textarea>
<p><button onclick=fin()>导出 CSV</button></p></div>
<script>const ITEMS=__ITEMS__;let i=0;const rec=[];
function show(){if(i>=ITEMS.length){document.getElementById('wrap').innerHTML='<h2>完成</h2><p>请导出 CSV。</p>';return}
const it=ITEMS[i];document.getElementById('img').src='data:image/png;base64,'+it.b64;
document.getElementById('pos').textContent=`第 ${i+1}/${ITEMS.length} 张`;
document.getElementById('prog').style.width=(100*i/ITEMS.length)+'%';document.getElementById('why').value=''}
function v(ans){rec.push({idx:ITEMS[i].idx,ans,conf:+document.getElementById('conf').value,why:document.getElementById('why').value});i++;show()}
function fin(){const rows=[['idx','ans','conf','why']].concat(rec.map(r=>[r.idx,r.ans,r.conf,r.why.replace(/,/g,';')]));
const csv=rows.map(r=>r.join(',')).join('\\n');const a=document.createElement('a');
a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download='turing_results.csv';a.click()}
show()</script>"""


if __name__ == "__main__":
    main()
