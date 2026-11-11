"""Map an application-form question to an answer source.

Three layers, checked in order; the first match wins:
1. Exact-label answers the user gave before (answer-bank.md "Exact" entries, and
   stage-5 question files with "ANSWER:" lines).
2. The user's own rules from answer-bank.md ("- `regex` -> kind: answer").
3. GENERIC_RULES below, which never state a fact themselves: they point at
   profile.yaml keys ("@eeo.gender") or computed values ("{start_date}").

A rule whose profile key is empty becomes "ask", so the application stops for the
user instead of guessing. Kinds:
  fixed          enter the answer
  eeo            voluntary self-ID; enter the answer
  rule           computed per role by the caller: SALARY, RELOCATION, RELOCATION_ASSIST, OFFICE, APPLIED_BEFORE
  draft          written per role from approved facts (free text, cover letter)
  consent        a checkbox the user approves once
  required_only  enter only when the field is required, else leave blank
  skip           leave blank
  ask            stop and ask the user (optional fields that would be "ask" are skipped)
"""
import datetime, glob, re
from .profile import full_name, home_display

EE_DECLINE = 'I prefer not to answer'  # Canadian employment-equity answers when the profile gives none
_US_WORD = r'(?:united states|\bu\.?s\.?a?\b)'

# (pattern on the lowercased label, kind, answer). Patterns are generic to any applicant.
GENERIC_RULES = [
    # Canada: sponsorship questions answer from the Canada fields (unset: ask, never the U.S. answer); a question
    # naming both countries needs both known. Employment-equity questions answer from eeo.employment_equity.*
    # and decline when the profile gives none. These come first: the U.S. rules below would otherwise take them.
    (rf'sponsor[^?]*(?:canad[^?]*{_US_WORD}|{_US_WORD}[^?]*canad)|(?:canad[^?]*{_US_WORD}|{_US_WORD}[^?]*canad)[^?]*sponsor',
     'fixed', '{sponsorship_us_or_canada}'),
    (r'sponsor[^?]*canad|canad[^?]*sponsor', 'fixed', '{needs_sponsorship_canada}'),
    (r'(?:employment equity|designated group)[^?]*\bwom[ae]n\b|\bwom[ae]n\b[^?]*(?:employment equity|designated group)',
     'eeo', '{ee_women}'),
    (r'indigenous|aboriginal|first nations|m[eé]tis\b|inuit', 'eeo', '{ee_indigenous}'),
    (r'visible minorit', 'eeo', '{ee_visible_minority}'),
    (r'(?:employment equity|designated group)[^?]*disabilit|disabilit[^?]*(?:employment equity|designated group)',
     'eeo', '{ee_disability}'),
    (r'employment equity|designated group|equity[- ]seeking', 'eeo', '{ee_self_identify}'),
    (r'^if another .*(please )?specify|please specify (in the notes|here)$', 'skip', ''),
    (r'how do you describe your gender', 'eeo', '@eeo.gender'),
    (r'^full legal name', 'fixed', '{full_name}'),
    (r'which location are you applying for', 'required_only', '@home.city'),
    (r"selecting .?yes,?.? you confirm that you do not require", 'fixed', '{no_sponsorship_confirm}'),
    (r'referred to this position by', 'fixed', '@attestations.referred'),
    # "Do you require relocation assistance?" is about a benefit, not about moving: see locations.relocation_assistance
    (r'(require|need|requesting|request)\w*[^?]{0,20} relocation (assistance|support|package|benefit)|relocation (assistance|support|package)[^?]*\?\s*$',
     'rule', 'RELOCATION_ASSIST'),
    (r'willing to relocate|open to relocat', 'rule', 'RELOCATION'),
    (r'total comp', 'fixed', '@preferences.total_comp'),
    (r"^if you answered .?yes|^if yes,|please explain\.?$", 'fixed', 'N/A'),
    (r'portfolio|personal website|case study', 'fixed', '@identity.website'),
    (r'plan to move|planning to move|move out of the state', 'fixed', '@preferences.planning_to_move'),
    (r'government official', 'fixed', '@attestations.government_official'),
    # a title question names a company word too ("current or most recent job title"): match the title first
    (r'(current|present|most recent|previous|last)\b[^?]*\btitle\b|^(job |position )?title (at|with|in) (your )?(current|most recent|previous|last)\b',
     'fixed', '@employment.most_recent.title'),
    (r'(current|present)\s*(\(?or|/)\s*(most recent|previous|last)|most recent (company|employer)|previous employer|last employer', 'fixed', '@employment.most_recent.company'),
    (r'^current (company|employer)|what is your current (company|employer)|name of your current (company|employer)\??$', 'fixed', '{current_employer}'),
    (r'university attended|last university|school attended', 'fixed', '@education.0.school'),
    (r'how did you (first )?hear', 'fixed', '@preferences.how_heard'),
    (r'if you do require .*sponsorship|type of support you may require', 'fixed', '{sponsorship_support}'),
    (r'city and state|city, state', 'fixed', '{home}'),
    (r'hispanic|latinx?\b', 'eeo', '@eeo.hispanic'),
    (r'lgbt', 'eeo', '@eeo.lgbtq'),
    (r'transgender', 'eeo', '@eeo.transgender'),
    (r'disabilit|chronic condition', 'eeo', '@eeo.disability'),
    (r'sexual orientation', 'eeo', '@eeo.sexual_orientation'),
    (r'gender identity|^gender', 'eeo', '@eeo.gender'),
    (r'racial|race|ethnic', 'eeo', '@eeo.race'),
    (r'employment eligible countries', 'fixed', '@work_authorization.eligible_countries'),
    (r'^please indicate .yes. if you have read and agree|may use ai tools to assist', 'consent', ''),
    (r'citizenship|export licens', 'fixed', '@work_authorization.citizenship'),
    (r'\bopt\b|optional practical training|h-1b|h1b|immigration|work visa|permanent resident', 'fixed', '@work_authorization.visa_detail'),
    (r'sponsor', 'fixed', '@work_authorization.needs_sponsorship'),
    (r'if you answered|if yes, or if you are not sure|please elaborate', 'fixed', 'N/A'),
    (r'worked for \w+\?|previously,? worked for', 'fixed', '@attestations.previously_employed'),
    (r'lie detector|attestation|review the linked document|text messages', 'consent', ''),
    (r'relative of a government|close relative|personal/familial|outside business activit', 'ask', ''),
    (r'home address|^zip|postal code|zip code', 'ask', ''),  # entered only when the user says so
    (r'first (&|and) last name|legal first and last', 'fixed', '{full_name}'),
    (r'legal first name', 'fixed', '@identity.first_name'),
    (r'legal last name', 'fixed', '@identity.last_name'),
    (r"today'?s date", 'fixed', '{today}'),
    (r'gpa|less than 3 years out of school', 'required_only', '@education.0.gpa'),
    # either country will do: Yes when authorized in the US or in Canada (the Canada-only rule would answer No)
    (r'canada or (in )?(the )?(united states|u\.?s\.?a?\b)|(united states|u\.?s\.?a?) or (in )?canada', 'fixed', '{us_or_canada}'),
    (r'legally entitled to work in canada|work in canada|(?:legally|lawfully) (?:eligible|entitled|authori[sz]ed)[^?]{0,40}\bcanada|'
     r'eligible[^?]{0,30}(?:employed|employment) in canada', 'fixed', '{authorized_canada}'),
    (r'lawfully work', 'fixed', '@work_authorization.authorized_us'),
    (r'(reside|residing|live) in (this|the) country|currently residing in this country', 'fixed', '@work_authorization.resides_in_country'),
    (r'(state|province).*(reside|live)|(reside|live).*(state|province)|what u\.?s\.? state', 'fixed', '@home.state'),
    (r'within \d+ miles', 'ask', ''),
    (r'still employed with', 'fixed', '@attestations.previously_employed'),
    (r'most recent job title|current job title', 'fixed', '@employment.most_recent.title'),
    (r'highest education|most advanced degree', 'fixed', '@education.0.degree'),
    (r'what university|^school\b|which school|college', 'fixed', '@education.0.school'),
    (r'\bmajor\b(?! life)|field of study', 'fixed', '@education.0.field'),
    (r'employee of|currently an? .*employee|currently a \w+ .*employee|have you worked (at|for)|contract work for|consultant for|been employed by', 'fixed', '@attestations.previously_employed'),
    (r'how did you first learn|where did you first hear', 'fixed', '@preferences.how_heard'),
    (r'willing to work from the office|must be based out of', 'rule', 'OFFICE'),
    (r'marketing communications|sms|whatsapp', 'fixed', '@preferences.marketing_opt_in'),
    (r'years .*(experience|active)|how many years', 'draft', 'YEARS ({years_experience})'),
    (r'^why \w+|how has ai|ai tools|vibe-coded|use ai|explain|describe your|which (of the following|categories)|select all that apply|level of proficiency', 'draft', 'DRAFT'),
    (r'^(legal )?first name', 'fixed', '@identity.first_name'),
    (r'^(legal )?last name', 'fixed', '@identity.last_name'),
    (r'preferred last name', 'required_only', '@identity.last_name'),
    (r'preferred (first )?name', 'required_only', '{preferred_name}'),
    (r'^(full |legal )?name$|^full name', 'fixed', '{full_name}'),
    (r'^email', 'fixed', '@identity.email'),
    (r'^phone', 'fixed', '@identity.phone'),
    (r'linkedin', 'fixed', '@identity.linkedin'),
    (r'github', 'fixed', '@identity.github'),
    (r'^website|portfolio|other website|personal (site|website)', 'fixed', '@identity.website'),
    (r'pronounce', 'skip', ''),
    (r'pronouns?\b', 'fixed', '@identity.pronouns'),
    (r'^resume|resume/cv|^cv\b', 'fixed', 'FILE: tailored resume PDF'),
    (r'^cover letter', 'draft', 'FILE: cover letter (generated per role)'),
    (r'^(current )?location$|^location|current location|city.*(live|reside)|where (do you|are you) (currently )?(live|located|based)', 'fixed', '{home}'),
    (r'salary history|current (base )?(salary|compensation)|most recent (salary|compensation)|previous (salary|compensation)', 'fixed', '@preferences.salary_history'),
    (r'salary|compensation|pay (expectation|range)|expected (total )?(base )?pay', 'rule', 'SALARY'),
    (r'start date|notice period|when (can|could|would) you (start|begin)|available to start|earliest', 'fixed', '{start_date}'),
    (r'sponsor|visa|immigration', 'fixed', '@work_authorization.needs_sponsorship'),
    (r'h-1b|h1b', 'ask', ''),
    (r'authori[sz]ed to work|legally (eligible|authorized)|eligib\w+ to (work|begin)|right to work|work authori', 'fixed', '@work_authorization.authorized_us'),
    (r'18 years|at least 18|age of 18', 'fixed', '@attestations.over_18'),
    (r'non-?compet|non-?solicit|restrictive covenant|agreement that would (preclude|restrict)', 'fixed', '@attestations.non_compete'),
    (r'previously (been )?(employed|worked)|ever (been )?(employed|worked)|former employee|currently (employed|an employee)|current employee|are you a current|worked (for|at) .* before', 'fixed', '@attestations.previously_employed'),
    (r'previously applied|applied (to|for) .* before|have you applied', 'rule', 'APPLIED_BEFORE'),
    (r'relocat', 'rule', 'RELOCATION'),
    (r'hybrid|in[- ]office|in the office|on[- ]?site|days (a|per) week|commut', 'rule', 'OFFICE'),
    (r'travel', 'fixed', '@preferences.travel'),
    (r'how did you (hear|find|learn)|where did you (hear|find)|source', 'fixed', '@preferences.how_heard'),
    (r'referr', 'skip', ''),
    (r'gender', 'eeo', '@eeo.gender'),  # "What gender do you identify as?", eeo[gender]
    (r'veteran|armed forces|military', 'eeo', '@eeo.veteran'),
    (r'^eeo\[', 'eeo', 'Decline to answer'),
    (r'privacy|consent|acknowledg|i (understand|agree|certify|confirm|attest)|by (checking|submitting)|terms', 'consent', ''),
    (r'why .*(interest|join|apply|want|excit)|what (excites|interests) you|why (this|our)|tell us (about|why)|cover note|additional information|anything else|message to the hiring', 'draft', 'DRAFT'),
    (r'future (opportunit|roles|openings)|talent (community|pool)|keep (my|your) (information|profile)', 'fixed', '@preferences.future_opportunities'),
]

# Generic rules matched without "(e.g. ...)" examples (Oct 22) or notes such as "(*NOTE* Visa Sponsorship is not
# available for this position.)" (Oct 26): an authorization question that mentions sponsorship only in a note is
# still an authorization question.
EXAMPLE_BLIND = {r'sponsor|visa|immigration', r'sponsor'}
NOTE_RE = re.compile(r'\s*\(\s*\*?\s*(?:please )?note\b[^()]*\)|(?<=\?)\s*\*?\s*(?:please )?note\b.*$')
KINDS = {'fixed', 'eeo', 'rule', 'draft', 'consent', 'required_only', 'skip', 'ask'}
BANK_RULE = re.compile(r'^\s*-\s+`(.+?)`\s*(?:->|→)\s*([a-z_]+)\s*(?::\s*(.*))?$')
BANK_EXACT = re.compile(r'^\s*-\s+\*\*(.+?)\*\*\s*(?:->|→)\s*(.+)$')
STAGE5 = re.compile(r'^\d+\. \*\*(.+?)\*\* \((.*?)\n(?:.*\n)*?\s+ANSWER:[ \t]*(.*)$', re.M)
ROLE_ID = re.compile(r'(?<![\w-])(?:gh|ab|lv)-[a-z0-9][a-z0-9-]*[a-z0-9]')  # a role id named in an entry's context


def norm_label(label):
    return re.sub(r'\s+', ' ', (label or '').strip())


def load_answer_bank(path):
    """User overrides from answer-bank.md. Two line shapes, anywhere in the file:
        - `regex on the lowercased label` -> kind: answer      (a rule; kind as above)
        - **Exact question label** -> answer                  (exact-label answer)
    Returns (rules, exact)."""
    rules, exact = [], {}
    for n, line in enumerate(open(path, encoding='utf-8'), 1):
        m = BANK_RULE.match(line)
        if m:
            pat, kind, ans = m.group(1), m.group(2), (m.group(3) or '').strip()
            if kind not in KINDS:
                raise ValueError(f'{path}:{n}: unknown kind {kind!r}')
            re.compile(pat)
            rules.append((pat, kind, ans))
            continue
        m = BANK_EXACT.match(line)
        if m:
            exact[norm_label(m.group(1))] = m.group(2).strip()
    return rules, exact


def load_stage5_answers(pattern):
    """Exact-label answers from stage-5 question files ("N. **label** (...)" then "ANSWER: x")."""
    out = {}
    for p in sorted(glob.glob(pattern)):
        for m in STAGE5.finditer(open(p, encoding='utf-8').read()):
            if m.group(3).strip():
                out[norm_label(m.group(1))] = m.group(3).strip()
    return out


def load_stage5_role_answers(pattern):
    """{(role_id, label): answer} for stage-5 entries whose context names role ids, e.g.
    "3. **AI Policy for Interviewers** (gh-brightwater-12: Brightwater: Product Lead)" then "ANSWER: Yes".
    An AI attestation is answered only from these: approved for that role, never reused for another."""
    out = {}
    for p in sorted(glob.glob(pattern)):
        for m in STAGE5.finditer(open(p, encoding='utf-8').read()):
            if m.group(3).strip():
                for rid in ROLE_ID.findall(m.group(2)):
                    out[(rid, norm_label(m.group(1)))] = m.group(3).strip()
    return out


def _either_yes(*vals):
    """'Yes' if any value says yes, 'No' if all say no, else None (ask)."""
    said = [str(v).strip().lower() for v in vals if v not in (None, '')]
    if any(v.startswith('yes') for v in said):
        return 'Yes'
    return 'No' if said and len(said) == len(vals) and all(v.startswith('no') for v in said) else None


# An attestation about the candidate's own use of AI is always the user's call, role by role: it is checked before
# exact-label answers and every rule, so an "I agree" given for one company's form is never reused for another's.
# The company's own use of AI ("we may use AI tools to assist", "AI transcription") is a consent, not this.
AI_WORDS = re.compile(r'\b(ai|a\.i\.|artificial intelligence|generative|genai|llms?|chatgpt)\b', re.I)
AI_ATTEST = re.compile(r'attest|certif|acknowledg|\bagree|\bconfirm|polic(y|ies)|expectations|adhere|permitted|usage|'
                       r'without (the )?(use|help|assistance) of|not to use|will not use|have not used|did not use', re.I)
AI_COMPANY_USE = re.compile(r'\b(we|\w+) may use (ai|a\.i\.|artificial|generative)|with your permission', re.I)


def ai_attestation(label):
    return bool(AI_WORDS.search(label) and AI_ATTEST.search(label) and not AI_COMPANY_USE.search(label))


class Answerer:
    def __init__(self, profile, bank_rules=(), exact=None, today=None, cfg=None, role_exact=None):
        self.prof, self.cfg = profile, cfg or {}
        self.role_exact = dict(role_exact or {})  # (role_id, label) -> answer: per-role approvals (AI attestations)
        self.rules = list(bank_rules) + GENERIC_RULES
        self.exact = dict(exact or {})
        self.today = today or datetime.date.today()

    def tokens(self):
        p, t = self.prof, self.today
        no_sponsor = str(p.get('work_authorization.needs_sponsorship', '')).lower().startswith('no')
        current = p.get('employment.current_employer')
        canada = p.get('work_authorization.authorized_canada') or p.get('work_authorization.canada')
        return {
            'full_name': full_name(p),
            'home': home_display(p),
            'today': t.strftime('%m/%d/%y'),
            'start_date': (t + datetime.timedelta(days=int(p.get('preferences.start_date_days', 14)))).strftime('%m/%d/%Y'),
            'current_employer': current or ('N/A' if p.get('employment.currently_employed') is False else None),
            'no_sponsorship_confirm': 'Yes' if no_sponsor else None,
            'sponsorship_support': 'N/A' if no_sponsor else None,
            'preferred_name': p.get('identity.preferred_name') or p.get('identity.first_name'),
            'years_experience': p.get('employment.years_experience'),
            'us_or_canada': _either_yes(p.get('work_authorization.authorized_us'), canada),
            'authorized_canada': canada,
            'needs_sponsorship_canada': p.get('work_authorization.needs_sponsorship_canada'),
            'sponsorship_us_or_canada': self._sponsorship_us_or_canada(),
            **{f'ee_{k}': p.get(f'eeo.employment_equity.{k}') or EE_DECLINE
               for k in ('women', 'indigenous', 'visible_minority', 'disability', 'self_identify')},
        }

    def _sponsorship_us_or_canada(self):
        """A sponsorship question naming the U.S. and Canada: Yes if either needs it, No if both don't, else None (ask).
        A profile with no Canada answer gives its U.S. answer, as before Canada was supported."""
        us, ca = self.prof.get('work_authorization.needs_sponsorship'), self.prof.get('work_authorization.needs_sponsorship_canada')
        if ca in (None, ''):
            return us
        return _either_yes(*[('yes' if str(v).strip().lower().startswith(('y', 'true')) else 'no') if v not in (None, '') else None
                             for v in (us, ca)])

    def resolve(self, answer):
        """Fill @profile.keys and {tokens}. Returns (text, missing_key_or_None)."""
        if answer.startswith('@'):
            v = self.prof.get(answer[1:])
            return (None, answer[1:]) if v in (None, '') else (str(v) if not isinstance(v, list) else ' / '.join(map(str, v)), None)
        missing = []
        toks = self.tokens()

        def sub(m):
            v = toks.get(m.group(1))
            if v in (None, ''):
                missing.append(m.group(1))
                return m.group(0)
            return str(v)
        text = re.sub(r'\{(\w+)\}', sub, answer)
        return (None, missing[0]) if missing else (text, None)

    def classify(self, label, role=None):
        """-> dict(kind, answer, source). 'source' says which layer answered. role: the role id, for per-role approvals."""
        key = norm_label(label)
        if ai_attestation(label):
            ans = self.role_exact.get((role, key)) if role else None
            if ans:
                return dict(kind='fixed', answer=ans, source='user: approved for this role')
            return dict(kind='ask', answer='', source='AI attestation: the user answers it for each role')
        if key in self.exact:
            return dict(kind='fixed', answer=self.exact[key], source='user: exact label')
        low = label.lower().strip()
        bare = re.sub(r'\s*\((?:e\.g\.|eg\b|i\.e\.|for example|such as)[^()]*\)', '', low)
        bare = NOTE_RE.sub('', bare).strip()
        for i, (pat, kind, ans) in enumerate(self.rules):
            # the sponsorship catch-all ignores examples: "authorized to work (e.g. ... you have a visa)" is not a visa question
            if re.search(pat, bare if pat in EXAMPLE_BLIND else low):
                layer = 'user rule' if i < len(self.rules) - len(GENERIC_RULES) else 'generic rule'
                text, missing = self.resolve(ans) if ans else (ans, None)
                if missing:
                    return dict(kind='ask', answer='', source=f'{layer}: profile has no {missing}')
                return dict(kind=kind, answer=text, source=layer)
        return dict(kind='ask', answer='', source='no rule')

    def answer(self, label, required, role=None):
        """classify() plus the required/optional handling the form filler needs."""
        r = self.classify(label, role)
        if r['kind'] == 'required_only':
            r['kind'] = 'fixed' if required else 'skip'
        if r['kind'] == 'ask' and not required:
            r['kind'] = 'skip'  # optional and uncovered: leave blank
        return r


# ---------- option matching for select / radio questions ----------
APOS = str.maketrans({'’': "'", '‘': "'"})
SYNONYMS = {'male': ('man', 'male', 'cisgender man'), 'female': ('woman', 'female', 'cisgender woman'),
            'non-binary': ('non-binary', 'nonbinary', 'genderqueer')}


def _alternatives(answer):
    """'Caribbean (Black)' or 'Caribbean / Black' -> ['Caribbean', 'Black']: a preferred option, then fallbacks."""
    a = answer.strip()
    m = re.match(r'^(.+?)\s*\((?:else |or )?([^()]+)\)$', a)
    if m:
        return [m.group(1).strip(), m.group(2).strip()]
    return [x.strip() for x in re.split(r'\s+/\s+|;\s*else\s+', a) if x.strip()]


def choose_option(options, label, answer, prof=None):
    """The option text that answers this question, or None when not confident (never a guess)."""
    opts = [o for o in options if o]
    a, lab = (answer or '').strip().translate(APOS), label.lower()
    low = a.lower()
    if a in opts:
        return a

    def first(pred):
        return next((o for o in opts if pred(o.lower().strip().translate(APOS))), None)

    if low == EE_DECLINE.lower():  # the employment-equity default: whichever "prefer not to say" the form words it as
        hit = first(lambda o: re.search(r"prefer not|decline|do not wish|don't wish|choose not|rather not|not to (answer|disclose|say|self)", o))
        if hit:
            return hit

    if len(opts) == 1 and re.match(r"(i acknowledge|i agree|i have read|i understand|yes|thank you)", opts[0].lower()):
        return opts[0]
    if re.match(r'(i acknowledge|i agree|confirmed|accept|yes$)', low) and re.search(r'privacy|acknowledg|agree|polic|notice|statement|review the linked', lab):
        return first(lambda o: re.match(r'(i acknowledge|i agree|i have read|yes)', o))
    race = re.search(r'race|ethnic', lab)

    def only(pred):  # the one option that fits, else None (several fits means the answer is too broad)
        hits = [o for o in opts if pred(o.lower().strip().translate(APOS))]
        return hits[0] if len(hits) == 1 else None

    for alt in _alternatives(a):
        al = alt.lower()
        if race:  # "East Asian" is not "East Asian - Chinese": only the full option, or one that explains it in brackets
            hit = first(lambda o: o == al) or only(lambda o: o.startswith(al + ' ('))
        else:
            hit = first(lambda o: o == al) or first(lambda o: o.startswith(al + ' ') or o.startswith(al + ',') or o.startswith(al + ' ('))
        if hit:
            return hit
        if al in SYNONYMS:
            hit = first(lambda o: any(re.match(rf'{re.escape(s)}\b', o) for s in SYNONYMS[al]))
            if hit:
                return hit
    if race:  # a single option naming the answer ("Black - Caribbean"), never a subgroup of it
        for alt in _alternatives(a):
            al = alt.lower()
            hit = only(lambda o: al in o and not o.startswith(al + ' -'))
            if hit:
                return hit
    if prof is not None and prof.get('home.state') and (low == str(prof.get('home.state')).lower() or low == (home_display(prof) or '').lower()):
        st = str(prof.get('home.state')).lower()
        hit = first(lambda o: o == st or o.endswith(' ' + st) or o == f'(us) {st}')
        if hit:
            return hit
    if re.search(r'veteran|military|armed forces', lab) and ('not' in low or low.startswith('no')):
        return (first(lambda o: 'not a' in o and 'veteran' in o) or first(lambda o: 'never served' in o) or first(lambda o: o.startswith('no')))
    if re.search(r'hear|learn about|find out', lab) or lab.strip() == 'source':
        wants = [low] + [str(x).lower() for x in ((prof.get('preferences.how_heard_fallback') if prof is not None else None) or [])]
        for w in wants:
            hit = None
            if 'careers' in w or 'website' in w:
                hit = (first(lambda o: re.search(r'careers? (page|site|website)|company (website|site)', o) is not None)
                       or first(lambda o: 'website' in o and 'advert' not in o) or first(lambda o: 'job board' in o or 'job site' in o))
            elif 'linkedin' in w:
                hit = first(lambda o: 'linkedin' in o and 'job post' in o) or first(lambda o: o == 'linkedin') or first(lambda o: 'linkedin' in o)
            else:
                hit = first(lambda o: o == w)
            if hit:
                return hit
        return first(lambda o: o == 'other')
    if re.search(r'citizenship|export licens', lab) or lab.startswith('country'):
        country = low.replace('the ', '')
        if country.startswith('united states'):
            return first(lambda o: o in ('united states', 'united states of america', 'usa', 'us') or o.startswith('united states of america') or o.startswith('united states ('))
    if re.search(r'\bopt\b|optional practical', lab) and (low.startswith('no') or low.startswith('n/a')):
        return first(lambda o: o in ('na', 'n/a', 'not applicable')) or first(lambda o: o == 'no')
    if 'pronoun' in lab and '/' in a:
        lead = a.split('/')[0].strip().lower()
        hit = first(lambda o: o.startswith(lead + '/') or o.startswith(lead + ' /') or o == lead)
        if hit:
            return hit
    if low.startswith('i live in') and ' can work from' in low:  # an OFFICE answer -> the affirmative option
        return first(lambda o: o.startswith('yes, i am currently near')) or first(lambda o: o == 'yes')
    if low.startswith('yes') or low.startswith('i live in'):
        # a "Yes" option that also claims where the user lives or that they'd move is right only if the answer says so:
        # "Yes, I already live in the San Francisco Bay Area" is not "Yes, I can work from the SF office ... hybrid"
        lives = low.startswith('i live in') or re.search(r'already live|currently live', low)
        moves = re.search(r'(would|will|willing to|happy to|plan to) relocate', low) and 'not relocate' not in low

        def claims_ok(o):
            if re.search(r'already live|currently live|\bi live\b|\breside\b|currently (based|located)', o) and not lives:
                return False
            return not ('relocat' in o and not moves)
        return (first(lambda o: o == 'yes') or first(lambda o: re.match(r'yes\b', o) is not None and claims_ok(o))
                or (first(lambda o: 'authorized to work for any employer' in o) if 'authoriz' in lab else None))
    if low.startswith('no') or low.startswith('n/a'):
        # a whole word ("No, ...", "None of these apply"): "No" is never "North Carolina" or "Norway"
        return (first(lambda o: o == 'no') or first(lambda o: re.match(r'no(ne)?\b', o) is not None) or first(lambda o: o in ('n/a', 'na'))
                or first(lambda o: re.search(r"\bnever\b|have not previously|i have not|not (currently )?employed|no plans", o) is not None))
    m = re.match(r'^([A-D])\s*\(', a)
    if m:
        return first(lambda o: o.startswith(m.group(1).lower() + '.'))
    for o in sorted(opts, key=len, reverse=True):  # the answer starts with an option's text
        if o.lower().strip() and low.startswith(o.lower().strip().rstrip('.')):
            return o
    # last resort: strong word overlap (typos, trailing punctuation), never below 0.6
    aw = set(_words(a))
    score = lambda o: len(aw & set(_words(o))) / max(1, len(aw | set(_words(o))))
    best = max(opts, key=score, default=None)
    if race and sum(score(o) >= 0.6 for o in opts) > 1:
        return None  # "East Asian" is as close to "East Asian - Chinese" as to "- Japanese": ask
    if best and score(best) >= 0.6:
        return best
    return None


def _words(s):
    return re.sub(r'[^a-z0-9 ]', ' ', (s or '').lower()).split()
