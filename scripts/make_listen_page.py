"""Stage 4: results/listen.html — human verification of every TTS target.

Open the page in a browser (from the results/ folder so relative audio paths resolve), play each clip,
mark each target Pass / Fail / Unclear, type what was heard when it differs, then press
"Download CSV" and save it as results/listening_filled.csv. build_report.py reads that file.
The automated provisional verdict is shown only after the listener has answered, to avoid anchoring.
"""
import csv
import html
import json

from common import RESULTS

rows = list(csv.DictReader(open(RESULTS / 'screen_tts.csv', encoding='utf-8-sig')))
rows += list(csv.DictReader(open(RESULTS / 'screen_challenge.csv', encoding='utf-8-sig')))
cases = {}
for r in rows:
    folder = 'challenge' if r['case_id'].startswith('C') else 'tts'
    cases.setdefault(r['case_id'], dict(folder=folder, text=r['text'], voice=r['voice_id'], language=r['language'],
                                        category=r['category'], paired=r['paired_with'], targets=[]))
    cases[r['case_id']]['targets'].append(dict(id=r['target_id'], written=r['written'], must_hear=r['must_hear'],
                                               critical=r['critical'], auto=r['automated_provisional']))

blocks = []
for case_id, c in cases.items():
    targets = ''.join(
        f'''<tr data-case="{case_id}" data-target="{html.escape(t['id'])}">
          <td><b>{html.escape(t['id'])}</b>{' <span class="crit">critical</span>' if t['critical'] == 'True' else ''}</td>
          <td>{html.escape(t['written'])}</td><td>{html.escape(t['must_hear'])}</td>
          <td class="choices">{''.join(f'<label><input type="radio" name="{case_id}-{html.escape(t["id"])}" value="{v}">{v}</label>' for v in ('pass', 'fail', 'unclear'))}</td>
          <td><input class="heard" placeholder="what you heard (if different)"></td>
          <td class="auto" data-auto="{t['auto']}">hidden until answered</td></tr>''' for t in c['targets'])
    blocks.append(f'''<section><h2>{case_id} <small>{html.escape(c['category'])} · {c['voice']} · language={c['language']}
      {('· paired with ' + c['paired']) if c['paired'] else ''}</small></h2>
      <p class="text">{html.escape(c['text'])}</p>
      <audio controls preload="none" src="{c['folder']}/{case_id}.wav"></audio>
      <table><tr><th>Target</th><th>Written</th><th>Acceptable reading</th><th>Verdict</th><th>Heard</th><th>Automated (provisional)</th></tr>{targets}</table>
      <textarea class="notes" data-case="{case_id}" placeholder="notes: prosody, wrong language, clipping…"></textarea></section>''')

page = f'''<!doctype html><html><head><meta charset="utf-8"><title>TTS Target Listening</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{{--bg:#fbfbfa;--fg:#1d1d1b;--muted:#6b6b66;--line:#ddd;--card:#fff;--accent:#2457c5}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--fg:#ecece8;--muted:#a3a39c;--line:#333;--card:#1f1f1d;--accent:#7aa2ff}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1100px;padding:16px}}
section{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin:14px 0}}
h2{{margin:0 0 6px;font-size:17px}} small{{color:var(--muted);font-weight:400}} .text{{font-size:18px;margin:6px 0}}
table{{border-collapse:collapse;width:100%;margin-top:8px;font-size:14px}} td,th{{border-top:1px solid var(--line);padding:6px;text-align:left;vertical-align:top}}
.crit{{color:#c0392b;font-size:12px}} .choices label{{margin-right:8px;white-space:nowrap}} input.heard,textarea{{width:100%;box-sizing:border-box;background:transparent;color:var(--fg);border:1px solid var(--line);border-radius:4px;padding:4px}}
textarea{{margin-top:8px;min-height:36px}} .auto{{color:var(--muted)}} button{{background:var(--accent);color:#fff;border:0;border-radius:6px;padding:10px 16px;font-size:15px;cursor:pointer}}
#bar{{position:sticky;top:0;background:var(--bg);padding:8px 0;display:flex;gap:12px;align-items:center;flex-wrap:wrap}}
@media (max-width:700px){{table,tr,td,th{{display:block}} th{{display:none}}}}
</style></head><body>
<h1>TTS target listening sheet</h1>
<p>Listen to each clip once without looking at the automated column. Judge only the listed targets. Mark <b>unclear</b> rather than guessing.
Lightning v3.1 Pro, 24 kHz WAV (round-trip cohort C1–C8: 16 kHz). Generated {len(cases)} clips, {sum(len(c['targets']) for c in cases.values())} targets.</p>
<div id="bar"><label>Listener ID <input id="listener" value="R1" size="4"></label><button id="dl">Download CSV</button><span id="count"></span></div>
{''.join(blocks)}
<script>
const KEY='smallest-tts-listen-v1';
function save(){{const s={{}};document.querySelectorAll('input[type=radio]:checked').forEach(r=>s[r.name]=r.value);
 document.querySelectorAll('tr[data-case]').forEach(tr=>s['h:'+tr.dataset.case+'-'+tr.dataset.target]=tr.querySelector('.heard').value);
 document.querySelectorAll('textarea.notes').forEach(t=>s['n:'+t.dataset.case]=t.value);
 try{{localStorage.setItem(KEY,JSON.stringify(s))}}catch(e){{}} count()}}
function count(){{const total=document.querySelectorAll('tr[data-case]').length,done=document.querySelectorAll('input[type=radio]:checked').length;
 document.getElementById('count').textContent=done+' / '+total+' targets judged'}}
function reveal(tr){{const a=tr.querySelector('.auto');a.textContent=a.dataset.auto}}
try{{const s=JSON.parse(localStorage.getItem(KEY)||'{{}}');for(const k in s){{if(k.startsWith('h:')){{const[c,...t]=k.slice(2).split('-');
 const tr=document.querySelector(`tr[data-case="${{c}}"][data-target="${{t.join('-')}}"]`);if(tr)tr.querySelector('.heard').value=s[k]}}
 else if(k.startsWith('n:')){{const t=document.querySelector(`textarea[data-case="${{k.slice(2)}}"]`);if(t)t.value=s[k]}}
 else{{const r=document.querySelector(`input[name="${{k}}"][value="${{s[k]}}"]`);if(r){{r.checked=true;reveal(r.closest('tr'))}}}}}}}}catch(e){{}}
document.addEventListener('change',e=>{{if(e.target.type==='radio')reveal(e.target.closest('tr'));save()}});
document.addEventListener('input',save);count();
document.getElementById('dl').onclick=()=>{{const q=v=>'"'+String(v).replace(/"/g,'""')+'"';
 const lines=[['listener','case_id','target_id','human_verdict','human_heard','human_notes'].join(',')];
 document.querySelectorAll('tr[data-case]').forEach(tr=>{{const c=tr.dataset.case,t=tr.dataset.target,
  r=tr.querySelector('input[type=radio]:checked');lines.push([document.getElementById('listener').value,c,t,r?r.value:'',
  tr.querySelector('.heard').value,document.querySelector(`textarea[data-case="${{c}}"]`).value].map(q).join(','))}});
 const b=new Blob(['\\ufeff'+lines.join('\\n')],{{type:'text/csv'}});const a=document.createElement('a');
 a.href=URL.createObjectURL(b);a.download='listening_filled.csv';a.click()}};
</script></body></html>'''
(RESULTS / 'listen.html').write_text(page, encoding='utf-8')
print('results/listen.html', len(cases), 'clips', sum(len(c['targets']) for c in cases.values()), 'targets')
