"""Stage 2: copy the selected licensed clips, verify format, write templates/clips.csv."""
import csv
import json
import shutil
import subprocess

from common import ROOT, sha256, wav_info

GNANI = ROOT.parent / 'gnani'
# clip_id -> (new id, api language, critical slots)
PICK = {
    'CL-EN-01': ('EN01', 'en', ['blood types']), 'CL-EN-02': ('EN02', 'en', ['nbc', 'tulsa']),
    'CL-EN-03': ('EN03', 'en', ['pearl brewing company']), 'CL-EN-04': ('EN04', 'en', ['kathy beale']),
    'NUM-EN-01': ('EN05', 'en', ['1499', 'switzerland']), 'NUM-EN-03': ('EN06', 'en', ['60']),
    'CL-HI-01': ('HI01', 'hi', ['चित्रम']), 'CL-HI-02': ('HI02', 'hi', ['महाभारत']),
    'CL-HI-04': ('HI03', 'hi', ['पाकिस्तान', 'राष्ट्रपति']), 'CL-HI-05': ('HI04', 'hi', ['दहेज']),
    'NUM-HI-01': ('HI05', 'hi', ['2015']), 'DS-FIN-HI-04': ('HI06', 'hi', ['स्टेट बैंक', 'मुख्यालय']),
    'CL-TE-01': ('TE01', 'te', ['కృష్ణా']), 'CL-TE-02': ('TE02', 'te', ['హైదరాబాద్', 'మెట్రో']),
    'CL-TE-03': ('TE03', 'te', ['నీరు']), 'CL-TE-04': ('TE04', 'te', ['న్యూమొనియాను']),
    'EXP-NUM-TE-06': ('TE05', 'te', ['2011']), 'DS-FIN-TE-04': ('TE06', 'te', ['2015']),
    'DS-CS-HI-01': ('CS01', 'hi', ['bandwidth', 'download']), 'DS-CS-HI-03': ('CS02', 'hi', ['else if', 'syntax']),
    'DS-CS-HI-05': ('CS03', 'hi', ['tutorial', 'arguments', 'main function']),
    'DS-CS-HI-08': ('CS04', 'hi', ['tasks pane']), 'DS-CS-HI-10': ('CS05', 'hi', ['manual break option', 'click']),
    'DS-CS-HI-12': ('CS06', 'hi', ['text', 'document', 'file']),
    'NS-01': ('NS01', 'en', []), 'NS-02': ('NS02', 'en', []), 'EXP-NS-03': ('NS03', 'en', []),
}
COHORT = {'EN': 'english', 'HI': 'hindi', 'TE': 'telugu', 'CS': 'code_switch_hi_en', 'NS': 'no_speech'}

source = {}
for manifest in ('data/asr_manifest.csv', 'data/next/asr_dataset_replacement.csv'):
    for row in csv.DictReader(open(GNANI / manifest, encoding='utf-8-sig')):
        source.setdefault(row['clip_id'], row)

rows = []
(ROOT / 'clips').mkdir(exist_ok=True)
for old, (new, lang, slots) in PICK.items():
    src = source[old]
    target = ROOT / 'clips' / f'{new}.wav'
    shutil.copyfile(GNANI / src['input_path'], target)
    info = wav_info(target.read_bytes())
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries',
                            'stream=sample_rate,channels,sample_fmt,codec_name', '-of', 'json', str(target)],
                           capture_output=True, text=True)
    stream = json.loads(probe.stdout)['streams'][0]
    assert (stream['sample_rate'], stream['channels'], stream['sample_fmt']) == ('16000', 1, 's16'), (new, stream)
    assert sha256(target) == src['input_sha256'], f'{new}: hash differs from the source manifest'
    origin = src.get('reference_origin') or src.get('reference_status', '')
    rows.append(dict(
        clip_id=new, path=f'clips/{new}.wav', language=lang, api_language=lang, split='baseline',
        cohort=COHORT[new[:2]], reference=src['reference_transcript'],
        reference_status='listener_confirmed' if 'confirmed by listener' in origin else
        ('empty_by_construction' if new.startswith('NS') else
         ('reference_revised_listener_confirmed' if src['human_reference_verified'] == 'true' else 'dataset_text_unverified')),
        reference_origin=origin, speaker_id=src['speaker_id'] or 'none', condition='clean' if not new.startswith('NS') else 'no_speech',
        critical_slots=json.dumps(slots, ensure_ascii=False), source_clip_id=old, source=src['source_dataset'],
        source_ref=src.get('source_ref', ''), license=src['license_or_consent'], sha256=sha256(target),
        duration_s=info['duration_s'], sample_rate=info['sample_rate'], channels=info['channels'], bits=info['bits']))

(ROOT / 'templates').mkdir(exist_ok=True)
with open(ROOT / 'templates' / 'clips.csv', 'w', newline='', encoding='utf-8-sig') as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)

for cohort in COHORT.values():
    part = [r for r in rows if r['cohort'] == cohort]
    print(f"{cohort:20} clips={len(part)} speakers={len({r['speaker_id'] for r in part})} "
          f"seconds={sum(r['duration_s'] for r in part):.1f} "
          f"status={sorted({r['reference_status'] for r in part})}")
