"""Prepare a local, randomized two-video impairment study.

Run with consented participants; this script only creates the material.  It
does not simulate human ratings or claim a P.910 compliant study by itself.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path


HTML = """<!doctype html>
<html lang=\"pt-BR\"><head><meta charset=\"utf-8\"><title>Comparação cega de vídeo</title>
<style>body{font:16px system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem;background:#101720;color:#f4f7fb}
main{display:grid;grid-template-columns:1fr 1fr;gap:1rem}video{width:100%;background:#000}button,select,input{font:inherit;padding:.5rem;margin:.3rem}
small{color:#aab}fieldset{margin-top:1rem}label{display:block;margin:.5rem}</style></head><body>
<h1>Comparação cega</h1><p>Observe o mesmo trecho em A e B. A ordem é aleatória; use os controles comuns.
Classifique a diferença perceptual que notou. Não inspecione nomes de arquivo ou código da página.</p>
<main><section><h2>A</h2><video id=\"a\" src=\"A.mp4\" muted playsinline></video></section>
<section><h2>B</h2><video id=\"b\" src=\"B.mp4\" muted playsinline></video></section></main>
<button id=\"play\">Reproduzir / pausar</button><button id=\"back\">−1 s</button><button id=\"forward\">+1 s</button>
<fieldset><legend>Resposta</legend><label>Participante (código anônimo) <input id=\"participant\" required></label>
<label>Diferença perceptual <select id=\"impairment\"><option value=\"1\">1 · imperceptível</option><option value=\"2\">2 · quase imperceptível</option>
<option value=\"3\">3 · perceptível, não incômoda</option><option value=\"4\">4 · incômoda</option><option value=\"5\">5 · muito incômoda</option></select></label>
<label>Preferência <select id=\"preference\"><option value=\"same\">Sem preferência</option><option value=\"A\">A</option><option value=\"B\">B</option></select></label>
<label>Observações <input id=\"notes\" maxlength=\"250\"></label><button id=\"save\">Baixar resposta CSV</button></fieldset>
<small>O operador deve guardar a chave de randomização fora do alcance dos participantes. Esta página não envia respostas à rede.</small>
<script>
const a=document.querySelector('#a'),b=document.querySelector('#b');
document.querySelector('#play').onclick=()=>{if(a.paused){b.currentTime=a.currentTime;Promise.all([a.play(),b.play()]).catch(()=>{})}else{a.pause();b.pause()}};
document.querySelector('#back').onclick=()=>{a.pause();b.pause();a.currentTime=b.currentTime=Math.max(0,a.currentTime-1)};
document.querySelector('#forward').onclick=()=>{a.pause();b.pause();a.currentTime=b.currentTime=Math.min(a.duration||1,a.currentTime+1)};
a.ontimeupdate=()=>{if(Math.abs(a.currentTime-b.currentTime)>.08)b.currentTime=a.currentTime};
document.querySelector('#save').onclick=()=>{const p=document.querySelector('#participant').value.trim();if(!p){alert('Informe um código anônimo');return}
const fields=[p,document.querySelector('#impairment').value,document.querySelector('#preference').value,document.querySelector('#notes').value,new Date().toISOString()];
const row=fields.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',');
const blob=new Blob(['participant,impairment,preference,notes,submitted_at\\n'+row+'\\n'],{type:'text/csv'});
const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download='rating-'+p.replace(/[^a-zA-Z0-9_-]/g,'')+'.csv';link.click();URL.revokeObjectURL(link.href)};
</script></body></html>"""


def prepare(original: Path, marked: Path, output: Path, seed: int = 2026) -> dict:
    if not original.is_file() or not marked.is_file():
        raise FileNotFoundError("os dois vídeos devem existir")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("diretório de saída deve estar vazio")
    output.mkdir(parents=True, exist_ok=True)
    marked_side = random.Random(seed).choice(("A", "B"))
    shutil.copyfile(marked, output / f"{marked_side}.mp4")
    shutil.copyfile(original, output / f"{'B' if marked_side == 'A' else 'A'}.mp4")
    (output / "index.html").write_text(HTML, encoding="utf-8")
    key = {"seed": seed, "marked_side": marked_side, "original": str(original), "marked": str(marked), "protocol": "paired single-stimulus local pilot; participant consent and P.910 study design remain human tasks"}
    (output / "operator-key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
    return key


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--marked", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    print(json.dumps(prepare(args.original, args.marked, args.output, args.seed), ensure_ascii=False, indent=2))
