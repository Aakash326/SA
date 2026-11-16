"""Stage 9: results/ext_listen.html — human ratings for the multilingual TTS extension.

Per clip: naturalness, prosody, pronunciation (1-5, same anchors as the Gemini rubric) or 'can't judge'
(for languages the listener does not speak), plus a verdict per content target. The Gemini scores for a clip are
revealed only after all three ratings for that clip are entered. Export -> results/ext_listening_filled.csv.
"""
import csv
import html
import json

from common import RESULTS, ROOT

prompts = [p for p in csv.DictReader(open(ROOT / 'templates' / 'ext_tts_prompts.csv', encoding='utf-8-sig')) if p['planted'] == 'false']
judge = {r['case_id']: r for r in json.loads((RESULTS / 'ext_tts_judge.json').read_text(encoding='utf-8'))}
NAMES = {'en': 'English', 'hi': 'Hindi', 'te': 'Telugu', 'ta': 'Tamil', 'kn': 'Kannada', 'mr': 'Marathi'}


def rating(case, dim):
    opts = ''.join(f'<label><input type="radio" name="{case}-{dim}" value="{v}">{v}</label>' for v in ('1', '2', '3', '4', '5', 'n/a'))
    return f'<div class="rate"><span>{dim}</span>{opts}</div>'


blocks = []
for p in prompts:
    j = judge.get(p['case_id'], {})
    targets = json.loads(p['targets_json'])
    trows = ''.join(f'''<tr data-case="{p['case_id']}" data-target="{t['id']}"><td>{html.escape(t['written'])}</td><td>{html.escape(t['must_hear'])}</td>
        <td>{''.join(f'<label><input type="radio" name="{p["case_id"]}-t-{t["id"]}" value="{v}">{v}</label>' for v in ('pass', 'fail', 'unclear'))}</td></tr>'''
                    for t in targets)
    reveal = html.escape(json.dumps(dict(naturalness=j.get('naturalness_1to5'), prosody=j.get('prosody_1to5'),
                                         pronunciation=j.get('pronunciation_1to5'),
                                         targets={t['id']: t['result'] for t in j.get('targets', [])},
                                         artifacts=j.get('artifacts'), heard=j.get('heard')), ensure_ascii=False))
    blocks.append(f'''<section data-case="{p['case_id']}" data-lang="{p['language']}"><h2>{p['case_id']}
      <small>{NAMES[p['language']]} · voice {p['voice_id']} · {p['kind']}</small></h2>
      <p class="text">{html.escape(p['text'])}</p><audio controls preload="none" src="ext_tts/{p['case_id']}.wav"></audio>
      {rating(p['case_id'], 'naturalness')}{rating(p['case_id'], 'prosody')}{rating(p['case_id'], 'pronunciation')}
      <table><tr><th>Target</th><th>Acceptable</th><th>Verdict</th></tr>{trows}</table>
      <input class="note" placeholder="notes (artifacts, wrong language, pauses…)">
      <details class="judge" data-reveal="{reveal}"><summary>Gemini (shown after your 3 ratings)</summary><pre></pre></details></section>''')

page = f'''<!doctype html><html><head><meta charset="utf-8"><title>TTS Extension Listening</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
:root{{--bg:#fbfbfa;--fg:#1d1d1b;--muted:#6b6b66;--line:#ddd;--card:#fff;--accent:#2457c5}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--fg:#ecece8;--muted:#a3a39c;--line:#333;--card:#1f1f1d;--accent:#7aa2ff}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1000px;padding:16px}}
section{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin:14px 0}}
h2{{margin:0 0 4px;font-size:16px}} small{{color:var(--muted);font-weight:400}} .text{{font-size:18px;margin:6px 0}}
.rate{{margin:6px 0}} .rate span{{display:inline-block;width:110px;color:var(--muted)}} .rate label{{margin-right:10px}}
table{{border-collapse:collapse;width:100%;font-size:14px;margin-top:6px}} td,th{{border-top:1px solid var(--line);padding:5px;text-align:left}}
input.note{{width:100%;box-sizing:border-box;margin-top:6px;background:transparent;color:var(--fg);border:1px solid var(--line);border-radius:4px;padding:4px}}
.judge{{margin-top:6px;color:var(--muted)}} pre{{white-space:pre-wrap;font-size:13px}}
#bar{{position:sticky;top:0;background:var(--bg);padding:8px 0;display:flex;gap:12px;flex-wrap:wrap;align-items:center}}
button{{background:var(--accent);color:#fff;border:0;border-radius:6px;padding:9px 14px;font-size:15px;cursor:pointer}}
select,#listener{{background:transparent;color:var(--fg);border:1px solid var(--line);border-radius:4px;padding:4px}}
</style></head><body>
<h1>TTS extension — human ratings</h1>
<p>Rate each clip <b>before</b> opening the Gemini panel. Anchors: 1 severe problems · 2 substantial · 3 noticeable issues but understandable ·
4 mostly natural, minor issues · 5 natural and clear. Use <b>n/a</b> for a language you cannot judge. Naturalness = human-like voice;
prosody = stress, rhythm, pauses, question intonation; pronunciation = native-like for that language.</p>
<div id="bar"><label>Listener <input id="listener" value="R1" size="4"></label>
<label>Show <select id="lang"><option value="">all languages</option>{''.join(f'<option value="{k}">{v}</option>' for k, v in NAMES.items())}</select></label>
<button id="dl">Download CSV</button><span id="count"></span></div>
{''.join(blocks)}
<script>
const KEY='smallest-ext-listen-v1';
const st=()=>{{try{{return JSON.parse(localStorage.getItem(KEY)||'{{}}')}}catch(e){{return{{}}}}}};
function save(){{const s={{}};document.querySelectorAll('input[type=radio]:checked').forEach(r=>s[r.name]=r.value);
 document.querySelectorAll('section').forEach(x=>s['n:'+x.dataset.case]=x.querySelector('.note').value);
 try{{localStorage.setItem(KEY,JSON.stringify(s))}}catch(e){{}};upd()}}
function upd(){{let done=0;document.querySelectorAll('section').forEach(x=>{{const c=x.dataset.case;
 const ok=['naturalness','prosody','pronunciation'].every(d=>x.querySelector(`input[name="${{c}}-${{d}}"]:checked`));
 const j=x.querySelector('.judge');if(ok){{done++;j.querySelector('pre').textContent=JSON.stringify(JSON.parse(j.dataset.reveal),null,1)}}
 else{{j.open=false;j.querySelector('pre').textContent='rate the clip first'}}}});
 document.getElementById('count').textContent=done+' / '+document.querySelectorAll('section').length+' clips rated'}}
const s=st();for(const k in s){{if(k.startsWith('n:')){{const x=document.querySelector(`section[data-case="${{k.slice(2)}}"]`);if(x)x.querySelector('.note').value=s[k]}}
 else{{const r=document.querySelector(`input[name="${{k}}"][value="${{s[k]}}"]`);if(r)r.checked=true}}}}
document.addEventListener('change',save);document.addEventListener('input',save);upd();
document.getElementById('lang').onchange=e=>document.querySelectorAll('section').forEach(x=>x.style.display=!e.target.value||x.dataset.lang===e.target.value?'':'none');
document.getElementById('dl').onclick=()=>{{const q=v=>'"'+String(v??'').replace(/"/g,'""')+'"';const L=document.getElementById('listener').value;
 const out=[['listener','case_id','naturalness','prosody','pronunciation','target_id','target_verdict','notes'].join(',')];
 document.querySelectorAll('section').forEach(x=>{{const c=x.dataset.case,g=d=>(x.querySelector(`input[name="${{c}}-${{d}}"]:checked`)||{{}}).value||'';
  const ts=[...x.querySelectorAll('tr[data-target]')];const base=[L,c,g('naturalness'),g('prosody'),g('pronunciation')];
  ts.forEach(tr=>{{const v=(x.querySelector(`input[name="${{c}}-t-${{tr.dataset.target}}"]:checked`)||{{}}).value||'';
   out.push([...base,tr.dataset.target,v,x.querySelector('.note').value].map(q).join(','))}})}});
 const b=new Blob(['\\ufeff'+out.join('\\n')],{{type:'text/csv'}});const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='ext_listening_filled.csv';a.click()}};
</script></body></html>'''
(RESULTS / 'ext_listen.html').write_text(page, encoding='utf-8')
print('results/ext_listen.html', len(prompts), 'clips')
