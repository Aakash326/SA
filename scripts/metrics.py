"""Custom Levenshtein scoring shared by the assignment runner and metric tests.

Raw = NFC + case folding + collapsed whitespace. Normalized also maps Unicode
digits, removes punctuation, and preserves decimal/time separators and minus signs.
CER includes spaces; CER without spaces is reported separately. Empty references
have undefined WER/CER and are evaluated as no-speech controls, outside speech WER.
"""
import unicodedata


def normalize(text, *, raw=False):
    text = " ".join(unicodedata.normalize('NFC', str(text)).casefold().split())
    if raw:
        return text
    text = text.replace('−', '-')
    text = ''.join(str(unicodedata.digit(c)) if c.isdigit() and unicodedata.digit(c, None) is not None else c for c in text)
    out = []
    for i, c in enumerate(text):
        prev, nxt = (text[i-1] if i else ''), (text[i+1] if i+1 < len(text) else '')
        keep = c in '%₹' or unicodedata.category(c)[0] in 'LNM' or c.isspace()
        keep |= c in '.:' and prev.isdigit() and nxt.isdigit()
        keep |= c == '-' and nxt.isdigit() and not prev.isalnum()
        out.append(c if keep else ' ')
    return ' '.join(''.join(out).split())


def edit_counts(ref, hyp):
    n, m = len(ref), len(hyp)
    dp = [[i+j if i*j == 0 else 0 for j in range(m+1)] for i in range(n+1)]
    for i in range(1, n+1):
        for j in range(1, m+1):
            dp[i][j] = min(dp[i-1][j]+1, dp[i][j-1]+1, dp[i-1][j-1]+(ref[i-1] != hyp[j-1]))
    i, j = n, m
    counts = dict(substitutions=0, deletions=0, insertions=0)
    while i or j:
        if i and j and dp[i][j] == dp[i-1][j-1]+(ref[i-1] != hyp[j-1]):
            counts['substitutions'] += int(ref[i-1] != hyp[j-1]); i -= 1; j -= 1
        elif i and dp[i][j] == dp[i-1][j]+1:
            counts['deletions'] += 1; i -= 1
        else:
            counts['insertions'] += 1; j -= 1
    return {**counts, 'edits': dp[n][m]}


def score(reference, hypothesis, *, raw=False):
    ref, hyp = normalize(reference, raw=raw), normalize(hypothesis, raw=raw)
    words, chars = edit_counts(ref.split(), hyp.split()), edit_counts(ref, hyp)
    rns, hns = ref.replace(' ', ''), hyp.replace(' ', '')
    return dict(reference_normalized=ref, hypothesis_normalized=hyp,
                ref_word_count=len(ref.split()), word_edits=words['edits'],
                ref_char_count=len(ref), char_edits=chars['edits'],
                nospace_ref_chars=len(rns), nospace_char_edits=edit_counts(rns, hns)['edits'],
                substitutions=words['substitutions'], deletions=words['deletions'], insertions=words['insertions'],
                wer=words['edits']/len(ref.split()) if ref else None,
                cer=chars['edits']/len(ref) if ref else None,
                false_transcription=bool(hyp) if not ref else None,
                no_speech_inserted_words=len(hyp.split()) if not ref else None)


def corpus(rows):
    speech = [r for r in rows if int(r['ref_word_count']) > 0 and r.get('scoring_eligible', True)]
    def ratio(edits, total):
        denom = sum(int(r[total]) for r in speech)
        return sum(int(r[edits]) for r in speech)/denom if denom else None
    return dict(speech_clips=len(speech), reference_words=sum(int(r['ref_word_count']) for r in speech),
                word_edits=sum(int(r['word_edits']) for r in speech),
                wer=ratio('word_edits', 'ref_word_count'), cer=ratio('char_edits', 'ref_char_count'),
                cer_no_spaces=ratio('nospace_char_edits', 'nospace_ref_chars'))
