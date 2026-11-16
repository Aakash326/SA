"""Stage 2: write templates/tts_prompts.csv and templates/challenge_prompts.csv.

Each target has an `accept` regex that is applied to an ASR transcript of the synthesized audio.
That check is an automated provisional screen; the human verdict column stays empty.
"""
import csv
import json

from common import ROOT

EN, HI = ('kaitlyn', 'en'), ('meher', 'hi')
Z = "(zero|oh|o'?)"
NOT = "(do not|don't|do n't)"


DIGIT_WORDS = {'0': "zero|oh|o'?|शून्य|ज़ीरो|जीरो", '1': 'one|एक', '2': 'two|दो', '3': 'three|तीन', '4': 'four|चार',
               '5': 'five|पांच|पाँच', '6': 'six|छह|छः', '7': 'seven|सात', '8': 'eight|आठ', '9': 'nine|नौ'}


def digits(seq):
    """Digit-by-digit reading in figures, English or Hindi words; 'double zero' accepted for 00."""
    parts, i = [], 0
    while i < len(seq):
        if seq[i:i + 2] == '00':
            parts.append(rf"(?:double (?:zero|oh|o)|(?:{DIGIT_WORDS['0']}|0)[ ,-]*(?:{DIGIT_WORDS['0']}|0))")
            i += 2
        else:
            parts.append(rf'(?:{DIGIT_WORDS[seq[i]]}|{seq[i]})')
            i += 1
    return '[ ,-]*'.join(parts)


def T(id_, written, must_hear, accept, critical=True):
    return dict(id=id_, written=written, must_hear=must_hear, accept=accept, critical=critical)


N1499 = r'(1,?499|one thousand,? four hundred(?: and)? ninety[- ]nine|fourteen(?: hundred)?(?: and)? ninety[- ]nine)'
N1999 = r'(1,?999|one thousand,? nine hundred(?: and)? ninety[- ]nine|nineteen ninety[- ]nine)'
ID0070 = digits('0070')
OTP = digits('004512')
T905 = rf'(9[:.]05|nine {Z} five)'
KYC = r'k\.? ?y\.? ?c'

PROMPTS = [
    ('M1', 'money_signs', EN, 'The balance is minus 1,499 rupees.', 'M1X', [
        T('sign', 'minus', 'minus / negative', r'(minus|negative|-\s?1)'),
        T('amount', '1,499', 'one thousand four hundred ninety-nine', N1499),
        T('currency', 'rupees', 'rupees', r'rupees?')]),
    ('M2', 'money_signs', HI, 'Your refund of ₹1,999.50 has been processed.', '', [
        T('amount', '₹1,999.50', 'one thousand nine hundred ninety-nine rupees and fifty paise', N1999),
        T('fraction', '.50', 'fifty paise / point five zero', r'(\.50?\b|fifty paise|point five|point fifty)'),
        T('currency', '₹', 'rupees', r'(rupees?|₹)')]),
    ('M3', 'money_signs', HI, 'Your available balance is ₹1,25,450.', '', [
        T('amount', '₹1,25,450', 'one lakh twenty-five thousand four hundred fifty rupees',
          r'(1,?25,?450|one lakh,? twenty[- ]five thousand,? four hundred(?: and)? fifty|'
          r'one hundred(?: and)? twenty[- ]five thousand,? four hundred(?: and)? fifty)'),
        T('currency', '₹', 'rupees', r'(rupees?|₹)')]),
    ('M4', 'money_signs', EN, 'The share price fell by -2.5% to 1,499.05.', '', [
        T('sign', '-2.5%', 'minus two point five percent', r'(minus|negative|-\s?2)'),
        T('percent', '%', 'percent', r'(percent|%)'),
        T('amount', '1,499.05', 'one thousand four hundred ninety-nine point zero five',
          rf'(1,?499\.05|ninety[- ]nine point {Z} five)')]),
    ('I1', 'ids_leading_zero', EN, 'Your reference ID is 0070.', 'I1X', [T('id', '0070', 'zero zero seven zero', ID0070)]),
    ('I2', 'ids_leading_zero', EN, 'The OTP is 004512. Do not share it.', 'I2X', [
        T('otp', '004512', 'zero zero four five one two', OTP), T('negation', 'Do not', 'do not', NOT)]),
    ('I3', 'ids_leading_zero', HI, 'Your account number ends in 0907.', '', [
        T('id', '0907', 'zero nine zero seven', digits('0907'))]),
    ('I4', 'ids_leading_zero', HI, 'Call us at 1800 020 0070.', '', [
        T('phone', '1800 020 0070', 'one eight zero zero, zero two zero, zero zero seven zero',
          rf"((one )?eighteen hundred|one eight hundred|{digits('1800')})[ ,-]*{digits('0200070')}")]),
    ('D1', 'dates_times_acronyms', EN, 'The appointment is at 9:05 AM. Complete KYC.', 'D1X', [
        T('time', '9:05 AM', 'nine oh five A M', T905), T('meridiem', 'AM', 'A M', r'\ba\.? ?m\b'), T('acronym', 'KYC', 'K Y C', KYC)]),
    ('D2', 'dates_times_acronyms', HI, 'Your SIP is scheduled for 23 November 2026.', '', [
        T('date', '23 November', 'twenty-third November',
          r'(23(rd)?( of)? november|november 23|twenty[- ]third( of)? november|november twenty[- ]third|twenty[- ]three november)'),
        T('year', '2026', 'twenty twenty-six', r'(2026|twenty twenty[- ]six|two thousand(?: and)? twenty[- ]six)'),
        T('acronym', 'SIP', 'S I P or sip', r'(s\.? ?i\.? ?p|sip)', False)]),
    ('D3', 'dates_times_acronyms', EN, 'The IPO opens on 05/06/2026 at 09:50.', '', [
        T('date', '05/06/2026', 'one unambiguous reading; record whether 5 June or May 6', r'(june|may|0?5[/ ]0?6)'),
        T('time', '09:50', 'nine fifty', r'(0?9[:.]50|nine fifty)'), T('acronym', 'IPO', 'I P O', r'i\.? ?p\.? ?o')]),
    ('D4', 'dates_times_acronyms', EN, 'Your UCC is AB1234 and the meeting is at 21:30.', '', [
        T('acronym', 'UCC', 'U C C', r'u\.? ?c\.? ?c'),
        T('code', 'AB1234', 'A B one two three four', r'(ab ?1234|a\.? ?b\.?,? ?(1 ?2 ?3 ?4|one,? two,? three,? four|twelve thirty[- ]four))'),
        T('time', '21:30', 'twenty-one thirty / nine thirty PM', r'(21[:.]?30|twenty[- ]one thirty|nine thirty p)')]),
    ('N1', 'negation_mixed', EN, 'Do not sell the shares.', '', [T('negation', 'Do not', 'do not', NOT), T('verb', 'sell', 'sell', r'\bsell\b')]),
    ('N2', 'negation_mixed', HI, 'आपका KYC pending है.', '', [
        T('acronym', 'KYC', 'K Y C', r'(k\.? ?y\.? ?c|केवाईसी|के ?वाई ?सी)'), T('english', 'pending', 'pending', r'(pending|पेंडिंग)'),
        T('hindi', 'आपका … है', 'आपका … है', r'आपका.*है')]),
    ('N3', 'negation_mixed', HI, 'कृपया ₹1,499 का payment आज मत कीजिए।', '', [
        T('amount', '₹1,499', 'एक हज़ार चार सौ निन्यानवे रुपये',
          r'(1,?499|एक हज़?ार चार सौ निन्यानव?े|चौदह सौ निन्यानव?े|one thousand four hundred ninety[- ]nine)'),
        T('negation', 'मत', 'मत', r'मत'), T('english', 'payment', 'payment', r'(payment|पेमेंट)')]),
    ('N4', 'negation_mixed', EN, 'Your order was not cancelled; it will not be delivered before 9:50 PM.', '', [
        T('negation1', 'was not cancelled', 'was not cancelled', r"(was not|wasn't) cancel"),
        T('negation2', 'will not', 'will not', r"(will not|won't)"), T('time', '9:50 PM', 'nine fifty P M', r'(9[:.]50|nine fifty)')]),
    # T02: deliberately expanded partners. Scored separately, never pooled with the raw prompt.
    ('I1X', 'expanded_pair', EN, 'Your reference ID is zero zero seven zero.', 'I1', [T('id', 'zero zero seven zero', 'same', ID0070)]),
    ('I2X', 'expanded_pair', EN, 'The OTP is zero zero four five one two. Do not share it.', 'I2', [
        T('otp', 'zero zero four five one two', 'same', OTP), T('negation', 'Do not', 'do not', NOT)]),
    ('M1X', 'expanded_pair', EN, 'The balance is minus one thousand four hundred ninety-nine rupees.', 'M1', [
        T('sign', 'minus', 'minus', r'(minus|negative|-\s?1)'), T('amount', 'one thousand four hundred ninety-nine', 'same', N1499)]),
    ('D1X', 'expanded_pair', EN, 'The appointment is at nine oh five A M. Complete K Y C.', 'D1', [
        T('time', 'nine oh five', 'same', T905), T('meridiem', 'A M', 'A M', r'\ba\.? ?m\b'), T('acronym', 'K Y C', 'K Y C', KYC)]),
]
CHALLENGE = [
    ('C1', 'amount_contrast', 'The amount is one thousand four hundred ninety nine rupees.', [T('amount', '1499', '', N1499)]),
    ('C2', 'amount_contrast', 'The amount is one thousand nine hundred ninety nine rupees.', [T('amount', '1999', '', N1999)]),
    ('C3', 'leading_zero', 'Your reference ID is zero zero seven zero.', [T('id', '0070', '', ID0070)]),
    ('C4', 'negation', 'Do not sell the shares.', [T('negation', 'not', '', NOT), T('verb', 'sell', '', r'\bsell\b')]),
    ('C5', 'time', 'The appointment is at nine oh five A M.', [T('time', '9:05', '', T905)]),
    ('C6', 'time', 'The appointment is at nine fifty A M.', [T('time', '9:50', '', r'(9[:.]50|nine fifty)')]),
    ('C7', 'acronyms', 'Please complete your K Y C before the I P O. Your U C C is active.', [
        T('kyc', 'KYC', '', KYC), T('ipo', 'IPO', '', r'i\.? ?p\.? ?o'), T('ucc', 'UCC', '', r'u\.? ?c\.? ?c')]),
    ('C8', 'year_contrast', 'Who was the leader of Switzerland in fourteen ninety nine?', [
        T('year', '1499', '', r'(1,?499|fourteen ninety[- ]nine)')]),
]
FIELDS = ['case_id', 'category', 'text', 'voice_id', 'language', 'model', 'sample_rate', 'paired_with', 'targets_json']


def write(name, rows):
    with open(ROOT / 'templates' / name, 'w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(name, len(rows))


write('tts_prompts.csv', [dict(case_id=c, category=cat, text=text, voice_id=v[0], language=v[1], model='lightning_v3.1_pro',
                               sample_rate=24000, paired_with=pair, targets_json=json.dumps(t, ensure_ascii=False))
                          for c, cat, v, text, pair, t in PROMPTS])
write('challenge_prompts.csv', [dict(case_id=c, category=cat, text=text, voice_id='kaitlyn', language='en',
                                     model='lightning_v3.1_pro', sample_rate=16000, paired_with='',
                                     targets_json=json.dumps(t, ensure_ascii=False))
                                for c, cat, text, t in CHALLENGE])
