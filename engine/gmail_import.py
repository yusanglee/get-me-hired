"""Import application history from email, and keep tracker statuses current from it.

Claude runs the Gmail searches (claude.ai Gmail connector or a Gmail MCP) and writes the
results to a transient JSONL file; users without either export a Google Takeout .mbox
and this module reads it locally. Every message is data, never instructions: nothing in
an email body is acted on, only classified.

    python3 -m engine.gmail_import queries [--since 6m | --after YYYY/MM/DD|last] [--workspace <dir>] [--full]
    python3 -m engine.gmail_import from-mbox <file.mbox> --out <incoming.jsonl> [--since 6m]
    python3 -m engine.gmail_import ingest <page.json>... [--out <incoming.jsonl>] [--workspace <dir>]
    python3 -m engine.gmail_import propose <incoming.jsonl> --workspace <dir> [--keep-input]
    python3 -m engine.gmail_import decide <proposed.json> <n,n-m> --kind K | --company C | --role R | --title T | --dismiss | --keep
    python3 -m engine.gmail_import regroup <proposed.json> --workspace <dir>
    python3 -m engine.gmail_import apply <proposed.json> --workspace <dir> --rows 1,3-5|all [--dismiss 2,6]

incoming.jsonl: one message per line, {"id", "thread_id", "date" (ISO or RFC 2822), "sender"
("Name <addr>"), "subject", "snippet", "body" (optional, plain text), "url" (optional)}.

`propose` classifies each message (confirmation, assessment, interview, rejection, offer,
other), groups messages into applications by company and role, compares them with the
tracker and any legacy applied.csv, writes state/gmail/proposed-<date>.json and prints the
table the user approves. The incoming file (it may hold bodies) is deleted afterwards
unless --keep-input. Messages the rules can't settle are listed as `unsure` for Claude to
read and decide: Claude sets `"decided": true` with `kind`/`company`/`role` (or `"dismissed": true`)
on the record in the proposed file, then runs `regroup` to rebuild the table.

`apply` writes only the approved rows to tracker.csv (source=gmail) and records every
processed message id in state/gmail/seen.json, so re-runs never re-propose them. It also records
in state/gmail/sync.json how far the scan reached: the time `propose` ran, or the day of the oldest
message still left undecided. `queries --workspace` then searches only from there (from the UTC day of the scan minus 24 hours, less one more day for timezone slack, as after:YYYY/MM/DD);
`--full` searches the whole window again. Only
extracted fields and message ids are stored, never email bodies.
"""
import argparse, datetime, email, email.policy, email.utils, json, mailbox, os, re, sys
from . import tracker
from .job_key import job_key, norm_company
from .profile import load_config

ATS_DOMAINS = [
    'greenhouse.io', 'greenhouse-mail.io', 'ashbyhq.com', 'lever.co', 'myworkday.com', 'myworkdayjobs.com',
    'smartrecruiters.com', 'icims.com', 'jobvite.com', 'workable.com', 'workablemail.com', 'bamboohr.com',
    'rippling.com', 'rippling-ats.com', 'taleo.net', 'teamtailor.com', 'teamtailor-mail.com', 'successfactors.com',
    'eightfold.ai', 'applytojob.com', 'jazzhr.com', 'recruitee.com', 'breezy.hr', 'dover.com', 'gem.com',
    'pinpointhq.com', 'avature.net', 'oraclecloud.com', 'wellfound.com', 'hire.withgoogle.com',
]
# ATS hosts whose subdomains are the ATS's own (appreview.gem.com, ats.rippling.com), never the employer's.
SHARED_ATS = ['gem.com', 'greenhouse.io', 'greenhouse-mail.io', 'ashbyhq.com', 'lever.co', 'oraclecloud.com', 'workablemail.com',
              'smartrecruiters.com', 'rippling.com', 'rippling-ats.com', 'teamtailor-mail.com']
BOARD_SENDERS = {'jobs-noreply@linkedin.com': 'linkedin', 'indeedapply@indeed.com': 'indeed', 'noreply@indeed.com': 'indeed'}
# Job-adjacent mail that is not about an application's status.
NOISE = re.compile(r'\b(security code|verification code|verify your (email|account)|apply now to|complete your application|'
                   r'keep track of your application|jobs? similar to|is hiring|jobs? you may be|jobs picked for you|'
                   r'top jobs|saved jobs|job alert|new jobs?\b|recommended jobs?|reset your password)', re.I)

CONFIRM_SUBJECTS = ['thank you for applying', 'thanks for applying', 'application received', 'we received your application',
                    'your application', 'application submitted', 'thank you for your application', 'thank you for your interest',
                    'application confirmation', 'your application was sent']

KINDS = ['offer', 'rejection', 'interview', 'assessment', 'confirmation']
RULES = {
    'offer': r"\b(pleased to (extend|offer)|extend (you )?an offer|offer letter|offer of employment|verbal offer)\b",
    'rejection': (r"\b(unfortunately|not (to )?(move|moving) forward|move forward with other candidates|moving forward with other candidates|"
                  r"decided to (pursue|proceed with|move forward with) other|other candidates whose|not (been )?selected|"
                  r"will not be (moving|proceeding)|won'?t be (moving|proceeding)|position has (been|now been) filled|"
                  r"no longer (under consideration|considering)|we have decided not to|decided not to (proceed|move)|"
                  r"not a (fit|match) at this time|regret to inform|filled the (position|role))\b"),
    'interview': (r"\b(schedule (an|a|your|the|some) (interview|call|chat|time|conversation|phone screen)|interview (invitation|request|confirmation|confirmed)|"
                  r"invite you to (an |a )?(interview|conversation|chat|call)|phone screen|recruiter (call|screen|chat)|let['’]s (chat|talk|connect)|"
                  r"(phone|video|zoom) call to (chat|talk|discuss)|confirmed for (your|a|an|the) (video |phone |virtual |zoom )?(interview|call|screen|chat)|"
                  r"(share|send) (me |us )?your availability|availability for (a|an) (call|interview|chat)|"
                  r"next (step|round) (is|will be) (a|an)|onsite interview|virtual onsite|panel interview|calendly\.com|goodtime\.io)\b"),
    'assessment': (r"\b(assessment|coding challenge|take[- ]home|hackerrank|codesignal|codility|case study|work sample|"
                   r"skills test|written exercise)\b"),
    'confirmation': (r"\b(thank(s| you)( so much)? for (applying|your application|submitting your application)|application (has been |was )?(received|submitted)|"
                     r"(we('ve| have)|we) received your application|your application (was sent|has been sent|to|for)|"
                     r"successfully (applied|submitted)|thank you for your interest in (joining|working)|received your resume|"
                     r"application is in\b|application (has been|was) (received|submitted))\b"),
}
RX = {k: re.compile(v, re.I) for k, v in RULES.items()}
# In a confirmation, "we'll reach out to schedule an interview" is boilerplate, not an invite.
# Rejections often open this way, with the verdict cut off past the snippet; Claude reads the mail.
WEAK_REJECTION = re.compile(r"\bafter (careful|thoughtful) (consideration|review)\b", re.I)
# "Update on your Brightwater application": a status mail whose verdict is in the body.
STATUS_UPDATE = re.compile(r"\b(update|news) (on|about|regarding) your\b|\byour [\w&.' -]{1,40} (application|candidacy)\s*$|"
                           r"^(re: )?regarding your (application|candidacy)\b", re.I)
# Mail about an application whose verdict may sit past the snippet: never dropped as "other", sent to unsure.
APP_CONTEXT = re.compile(r"\b(applications?|applying|applied|candidacy|interest in)\b", re.I)
# "decided to move forward" with no object: with other candidates, or with you? Only the body says.
OPEN_MOVE_FORWARD = re.compile(r"\bdecided to (move|moving) forward\W*$", re.I)
MAYBE_VERDICT = re.compile(r"\b(mov(e|ing) forward|your interest in\b.{0,80}\b(role|position|opportunity|opening))\b", re.I)


def cut_off(snippet):
    """A search snippet that stops mid-sentence: ends on a word or comma, or with an ellipsis."""
    s = (snippet or '').strip()
    return bool(s) and (s.endswith(('...', '…')) or bool(re.search(r"[\w,;:'’-]$", s)))
IF_FUTURE = re.compile(r"\b(if (your|you|we|there)|should (your|we|there)|in the event|once we|we will (reach out|be in touch|contact))\b[^.]{0,160}$", re.I)

GENERIC_NAMES = re.compile(r'^(greenhouse|lever|ashby|workday|icims|jobvite|workable|smartrecruiters|rippling|teamtailor|bamboohr|'
                           r'no[- ]?reply|noreply|do[- ]?not[- ]?reply|careers?|jobs?|recruiting|talent|hiring|linkedin|indeed|'
                           r'notifications?|team|hr|people)$', re.I)
NAME_SUFFIX = re.compile(r'\s*(?:[-|,·]\s*)?\b(hiring team|recruiting team|recruitment team|talent acquisition( team)?|talent team|'
                         r'careers?( team)?|recruiting|recruitment|people team|people ops|jobs|hr|hiring|talent|team|via \w+|'
                         r'@ ?\w+)\s*$', re.I)
PERSON_AT = re.compile(r'^[A-Z][a-z]+(?: [A-Z][a-z]+)? (?:at|from|@) (?P<co>.+)$')
SUBJ_COMPANY = [
    re.compile(r'^(?P<co>[A-Z0-9][\w&.\' +-]{1,40}?) \| '),
    re.compile(r'(?i:applying|application|applied) (?i:to|at|with) (?P<co>[A-Z0-9][\w&.\' +-]{1,40}?)(?:[!.,:|\-–—(]|\s+for\b|$)'),
    re.compile(r'(?i:interest) in (?:joining |working (?:at|with) )?(?P<co>[A-Z0-9][\w&.\' +-]{1,40}?)(?:[!.,:|\-–—(]|\s+for\b|$)'),
    re.compile(r'your application was sent to (?P<co>[A-Z0-9][\w&.\' +-]{1,40}?)\s*$', re.I),
    re.compile(r'\bat (?P<co>[A-Z0-9][\w&.\' +-]{1,40}?)\s*(?:[!.|(]|$)'),
    re.compile(r'(?i:update|news) (?i:on|about|regarding) your (?P<co>[A-Z0-9][\w&.\' +-]{1,40}?) (?i:application|candidacy)\b'),
]
# "Pellucid Inc. Interview Confirmation", "Jordan Rivera | Quarry Recruiter Screen Confirmation": checked before SUBJ_COMPANY,
# whose "X | " pattern would take the candidate's own name.
INTERVIEW_SUBJ = re.compile(r"(?:^|\| )(?!(?:Your|Final|Virtual|Onsite|On-site|Phone|Video|Zoom|Technical|First|Second|Third|Next|"
                            r"Upcoming|Panel|Interview|Recruiter)\b)(?P<co>[A-Z0-9][\w&.' +-]{1,40}?) "
                            r"(?:Interview|Recruiter Screen|Phone Screen|Recruiter Call)s? (?:Confirm|Invit|Request|Schedul)")
TITLE_LIKE = re.compile(r'\b(manager|director|engineer|designer|analyst|scientist|lead|head of|specialist|officer|chief of staff|position|role)\b', re.I)
_R = r"(?P<role>[A-Z][\w&/,.:'()+ —–-]{3,110}?)"
ROLE = [
    re.compile(r'(?:position|role) of ' + _R + r'(?: at | with |\s*[!.|]|$)'),
    re.compile(r'\b(?:for|to|in) (?:the|our) (?:position of |role of )?' + _R + r' (?:position|role|opening|opportunity|job)\b'),
    re.compile(r'(?:application|applying|applied) (?:for|to) (?:the |our )?' + _R + r'(?: (?:position|role|opening)| at | with |[!.|]|$)'),
    re.compile(r'(?i:received|submitted) for ' + _R + r'(?:\s*[!.|]|$)'),
    re.compile(r'^(?:thanks|thank you) for applying to ' + _R + r'$', re.I),
    re.compile(r'^' + _R + r' (?:at|@) [A-Z]'),
]
ROLE_WORD = re.compile(r'\b(manager|director|head|lead|chief|engineer|designer|analyst|scientist|specialist|associate|officer|'
                       r'partner|strategist|architect|consultant|coordinator|president|principal|staff|operations|product)\b', re.I)
# Words too common in a title list to count as role words on their own.
PACK_WORD_SKIP = {'senior', 'junior', 'the', 'and', 'for', 'with', 'of', 'to', 'at', 'in', 'sr', 'jr', 'new', 'lead'}


def pack_role_words(workspace):
    """Extra role words from the workspace pack's own title list (titles.targets, titles.board_queries).
    Empty when there is no pack or it can't be read: the built-in lists then apply unchanged."""
    try:
        with open(os.path.join(os.path.expanduser(workspace), 'pack.json'), encoding='utf-8') as fh:
            titles = (json.load(fh).get('titles') or {})
    except (OSError, ValueError, AttributeError, TypeError):
        return []
    phrases = [x for k in ('targets', 'board_queries') for x in (titles.get(k) or []) if isinstance(x, str)]
    words = {w for ph in phrases for w in re.findall(r'[a-z]{4,}', ph.lower())} - PACK_WORD_SKIP
    return sorted(w for w in words if not ROLE_WORD.search(w))


def with_words(rx, extra):
    """The role-word regex `rx` (TITLE_LIKE or ROLE_WORD) widened by the pack's words."""
    if not extra:
        return rx
    assert rx.pattern.endswith(r')\b')
    return re.compile(rx.pattern[:-3] + '|' + '|'.join(re.escape(w) for w in extra) + r')\b', rx.flags)


# ---- input ----

def _date(s):
    if not s:
        return ''
    try:
        return datetime.date.fromisoformat(str(s)[:10]).isoformat()
    except ValueError:
        pass
    try:
        return email.utils.parsedate_to_datetime(s).date().isoformat()
    except (TypeError, ValueError):
        return ''


def parse_sender(sender):
    name, addr = email.utils.parseaddr(sender or '')
    return name.strip().strip('"'), addr.lower()


def is_ats(addr):
    dom = addr.split('@')[-1]
    return any(dom == d or dom.endswith('.' + d) for d in ATS_DOMAINS)


def read_incoming(path):
    out = []
    for line in open(path, encoding='utf-8'):
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def since_date(since, today=None):
    today = today or datetime.date.today()
    m = re.fullmatch(r'(\d+)([dmy])', since or '6m')
    n, unit = int(m.group(1)), m.group(2)
    return today - datetime.timedelta(days=n * {'d': 1, 'm': 31, 'y': 366}[unit])


def queries(since='6m', after=None):
    """Gmail searches to run; results are unioned by message id."""
    when = f'after:{after}' if after else f'newer_than:{since}'
    ats = ' OR '.join(ATS_DOMAINS)
    subj = ' OR '.join(f'"{s}"' for s in CONFIRM_SUBJECTS if s != 'your application')
    return [
        f'{when} from:({ats})',
        f'{when} subject:({subj})',
        f'{when} subject:"your application" -from:(linkedin.com)',
        f'{when} from:jobs-noreply@linkedin.com subject:"your application was sent"',
        f'{when} from:(indeed.com OR indeedapply@indeed.com) subject:(application OR applied)',
        f'{when} ("not moving forward" OR "move forward with other candidates" OR "regret to inform" OR "unfortunately") '
        f'(application OR candidacy OR position OR role) -category:promotions',
        f'{when} ("schedule an interview" OR "phone screen" OR "your availability" OR "interview invitation" OR "offer letter" '
        f'OR "let\'s chat" OR "phone call to chat" OR "video interview") (position OR role OR candidacy OR application) -category:promotions',
        f'{when} subject:("interview confirmation" OR "interview confirmed" OR "recruiter screen" OR "phone screen") -category:promotions',
    ]


def from_mbox(path, since='6m', today=None):
    """Job-related messages from a Takeout .mbox, in the incoming.jsonl shape."""
    cutoff = since_date(since, today).isoformat()
    out = []
    for msg in mailbox.mbox(path, factory=lambda f: email.message_from_binary_file(f, policy=email.policy.default)):
        d = _date(msg.get('Date'))
        if d and d < cutoff:
            continue
        sender, subject = str(msg.get('From') or ''), str(msg.get('Subject') or '')
        _, addr = parse_sender(sender)
        body = ''
        part = msg.get_body(preferencelist=('plain', 'html')) if hasattr(msg, 'get_body') else None
        if part is not None:
            try:
                body = part.get_content()
            except (LookupError, ValueError):
                body = ''
            if part.get_content_type() == 'text/html':
                body = re.sub(r'<[^>]+>', ' ', body)
        text = f'{subject}\n{body[:3000]}'
        if not (is_ats(addr) or addr in BOARD_SENDERS or any(RX[k].search(text) for k in KINDS)):
            continue
        mid = str(msg.get('Message-ID') or '').strip('<> ') or f'mbox-{len(out)}'
        out.append({'id': mid, 'thread_id': mid, 'date': d, 'sender': sender, 'subject': subject,
                    'snippet': re.sub(r'\s+', ' ', body[:200]), 'body': body[:6000]})
    return out


# ---- classification ----

def _hits(kind, text):
    """Matches for a kind, ignoring 'we'll reach out to schedule an interview'-style boilerplate."""
    out = []
    for m in RX[kind].finditer(text):
        if kind in ('interview', 'assessment') and IF_FUTURE.search(text[max(0, m.start() - 200):m.start()]):
            continue
        out.append(m.group(0))
    return out


def classify(msg):
    """{'kind', 'confidence' (high|low), 'reason'} from rules on subject, snippet and body."""
    subject = msg.get('subject') or ''
    text = '\n'.join(filter(None, [subject, msg.get('snippet'), msg.get('body')]))
    _, addr = parse_sender(msg.get('sender'))
    if NOISE.search(subject):
        return {'kind': 'other', 'confidence': 'high', 'reason': 'job alert or account mail'}
    hits = {k: _hits(k, text) for k in KINDS}
    job_sender = is_ats(addr) or addr in BOARD_SENDERS
    has_body = bool(msg.get('body'))
    for k in ('offer', 'rejection', 'interview', 'assessment'):
        if hits[k]:
            conf = 'high' if (job_sender or hits['confirmation'] or k == 'offer' or has_body or
                              (k == 'interview' and _hits(k, subject))) else 'low'
            if k == 'rejection' and re.search(r'unfortunately', hits[k][0], re.I) and len(hits[k]) == 1 and not job_sender:
                conf = 'low'  # "unfortunately" alone, outside an ATS mail, is weak evidence
            return {'kind': k, 'confidence': conf, 'reason': hits[k][0]}
    if not has_body and OPEN_MOVE_FORWARD.search(msg.get('snippet') or ''):
        return {'kind': 'other', 'confidence': 'low', 'reason': "'decided to move forward' cut off; the verdict is in the body"}
    m = WEAK_REJECTION.search(text)
    if m:
        return {'kind': 'rejection', 'confidence': 'low', 'reason': m.group(0) + '; the verdict is in the body'}
    if hits['confirmation'] and not has_body and re.search(r'following up|update on your|regarding your application', subject, re.I):
        return {'kind': 'confirmation', 'confidence': 'low', 'reason': 'a follow-up; the verdict is in the body'}
    if hits['confirmation']:
        # A bare "Thank you for your interest" subject is often a rejection whose verdict is in the body.
        weak = not has_body and re.search(r'\binterest\b|your application\s*$|following up|update on your', subject, re.I) and not \
            re.search(r'applying|received|submitted|was sent', text, re.I)
        # "Thank You for Your Interest in X" whose snippet stops mid-sentence: "thank you for applying" opens
        # rejections too, so unless it says the application was received, the verdict may be past the cut.
        weak = weak or (not has_body and re.search(r'\binterest\b', subject, re.I) and cut_off(msg.get('snippet')) and not
                        re.search(r'received|submitted|was sent', text, re.I))
        return {'kind': 'confirmation', 'confidence': 'low' if weak else 'high', 'reason': hits['confirmation'][0]}
    if STATUS_UPDATE.search(subject):
        return {'kind': 'other', 'confidence': 'low', 'reason': 'a status update; the verdict is in the body'}
    if job_sender and addr not in BOARD_SENDERS:  # job-board mail without a status phrase is an alert or digest
        return {'kind': 'other', 'confidence': 'low', 'reason': 'job-system sender, no status phrase'}
    if APP_CONTEXT.search('\n'.join(filter(None, [subject, msg.get('snippet')]))):
        m = MAYBE_VERDICT.search(text)
        if m:
            return {'kind': 'other', 'confidence': 'low', 'reason': f"'{m.group(0)}' about an application; the verdict may be in the body"}
        if not has_body and cut_off(msg.get('snippet')):
            return {'kind': 'other', 'confidence': 'low', 'reason': 'about an application, snippet cut off; the verdict may be in the body'}
    return {'kind': 'other', 'confidence': 'high', 'reason': 'no job-application signal'}


def _clean_company(s, title_like=TITLE_LIKE):
    s = re.sub(r'\s+', ' ', (s or '')).strip(' -–—|,.:!"\'')
    for _ in range(3):
        s2 = NAME_SUFFIX.sub('', s).strip(' -–—|,.:')
        if s2 == s:
            break
        s = s2
    s = re.sub(r'^(the|team|join)\s+', '', s, flags=re.I)
    return '' if (not s or GENERIC_NAMES.match(s) or title_like.search(s) or len(s) > 45) else s


def extract_company(msg, title_like=TITLE_LIKE):
    name, addr = parse_sender(msg.get('sender'))
    subject = msg.get('subject') or ''
    m = PERSON_AT.match(name)
    if m:
        co = _clean_company(m.group('co'), title_like)
        if co:
            return co, 'sender'
    co = _clean_company(name, title_like)
    if co and addr not in BOARD_SENDERS and (is_ats(addr) or not re.search(r'\s', name) or NAME_SUFFIX.search(name)):
        return co, 'sender'
    for rx in [INTERVIEW_SUBJ] + SUBJ_COMPANY:
        m = rx.search(subject)
        if m and _clean_company(m.group('co'), title_like):
            return _clean_company(m.group('co'), title_like), 'subject'
    dom = addr.split('@')[-1]
    local = addr.split('@')[0]
    if dom.endswith('myworkday.com') and local not in ('no-reply', 'noreply', 'donotreply'):
        return local.replace('-', ' ').replace('_', ' ').title(), 'address'
    sub = dom.split('.')[0]
    shared = any(dom == d or dom.endswith('.' + d) for d in SHARED_ATS)
    if is_ats(addr) and not shared and dom not in ATS_DOMAINS and sub not in ('us', 'eu', 'mail', 'hire', 'jobs', 'app', 'no-reply', 'greenhouse', 'lever', 'ashbyhq'):
        return sub.replace('-', ' ').title(), 'address'
    body = msg.get('body') or msg.get('snippet') or ''
    for rx in SUBJ_COMPANY[1:]:
        m = rx.search(body[:600])
        if m and _clean_company(m.group('co'), title_like):
            return _clean_company(m.group('co'), title_like), 'body'
    if co and not is_ats(addr) and addr not in BOARD_SENDERS:
        return co, 'sender?'
    labels = [x for x in dom.split('.') if x not in ('com', 'co', 'io', 'net', 'org', 'jobs', 'mail', 'careers', 'us', 'tv', 'xyz', 'ai')]
    if labels and not is_ats(addr) and addr not in BOARD_SENDERS and not re.search(r'gmail|yahoo|outlook|hotmail|icloud', dom):
        return labels[-1].title(), 'domain?'  # e.g. no-reply@acme.com; a guess, so it goes to unsure
    return '', ''


def extract_role(msg, role_word=ROLE_WORD):
    for field in ('subject', 'snippet', 'body'):
        text = (msg.get(field) or '')[:1500]
        for rx in ROLE:
            for m in rx.finditer(text):
                role = re.sub(r'\s*\((?:ID|Req|R)[:# ]?[^)]*\)', '', m.group('role'))
                role = re.sub(r'\s+', ' ', role).strip(' -–—,.:')
                if re.search(r'(?<!\bSr)(?<!\bJr)(?<!\bSt)\.\s+[A-Z]| for | your | and (for|will)\b| will | you\b| we |applying|application', role):
                    continue  # ran across a sentence boundary
                if role_word.search(role) and len(role.split()) <= 12:
                    return role
    return ''


# ---- grouping and proposal ----

STATUS_OF = {'confirmation': 'applied', 'assessment': 'assessment', 'interview': 'interviewing', 'offer': 'offer',
             'rejection': 'rejected'}


GENERIC_CO = {'group', 'studios', 'labs', 'technologies', 'holdings', 'global', 'usa', 'jv', 'the', 'and', 'company', 'careers'}


def same_company(a, b):
    """Loose company match on whole words: 'Learnly' ~ 'Learnly + Skillshop', 'Fernbrook' ~ 'Fern Brook
    Holdings', 'Globex' ~ 'Streamly & Globex Studios', 'Hooli' ~ 'The Gavin Hooli Company'.
    'Meta' does not match 'Metabase'."""
    ta = [t for t in norm_company(a).split('-') if t and t not in GENERIC_CO]
    tb = [t for t in norm_company(b).split('-') if t and t not in GENERIC_CO]
    if not ta or not tb:
        return False
    if ta == tb:
        return True

    def joined_prefix(x, y):  # 'warnerbros' == 'warner' + 'bros'
        acc = ''
        for t in y:
            acc += t
            if acc == ''.join(x):
                return True
        return False
    if joined_prefix(ta, tb) or joined_prefix(tb, ta):
        return True
    sa, sb = set(ta), set(tb)
    small, big = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    return small <= big and all(len(t) > 2 for t in small)


def _match_existing(company, role, existing):
    """The tracked application this mail belongs to: by job_key, else the only one at that company."""
    if role:
        k = job_key(company, role)
        for r in existing:
            if r['job_key'] == k or (same_company(r['company'], company) and job_key('x', r['title']) == job_key('x', role)):
                return r
    same = [r for r in existing if same_company(r['company'], company)]
    if len(same) == 1 and (not role or not existing_title_conflicts(same[0]['title'], role)):
        return same[0]
    return None


def existing_title_conflicts(a, b):
    """Two titles that are clearly different roles (no shared distinctive word)."""
    stop = {'senior', 'sr', 'staff', 'principal', 'lead', 'product', 'manager', 'the', 'and', 'of', 'i', 'ii', 'iii', '-', ','}
    wa = {w for w in re.findall(r'[a-z]+', a.lower()) if w not in stop}
    wb = {w for w in re.findall(r'[a-z]+', b.lower()) if w not in stop}
    return bool(wa and wb and not wa & wb)


def existing_rows(workspace, cfg):
    rows = []
    for r in tracker.read(tracker.path_of(workspace)):
        rows.append({**r, 'job_key': r.get('job_key') or job_key(r['company'], r['title']), 'where': 'tracker'})
    have = {r['job_key'] for r in rows}
    for p in tracker.legacy_applied(cfg):
        for r in tracker.read(p):
            if r.get('company') and r.get('title') and job_key(r['company'], r['title']) not in have:
                rows.append({'company': r['company'], 'title': r['title'], 'id': r.get('id', ''),
                             'date_applied': r.get('date_applied', ''), 'status': 'applied',
                             'job_key': job_key(r['company'], r['title']), 'where': 'applied.csv'})
    return rows


def _workspace_cfg(ws):
    p = os.path.join(ws, 'config.json')
    return load_config(p) if os.path.exists(p) else load_config({})


def records(messages, seen=(), extra_words=()):
    """Classify and extract each new message. Returns (records, skipped_seen); records hold
    extracted fields only (subject trimmed), never bodies."""
    by_id, skipped = {}, 0
    title_like, role_word = with_words(TITLE_LIKE, extra_words), with_words(ROLE_WORD, extra_words)
    for m in messages:
        if m['id'] in seen:
            skipped += 1
        elif m['id'] not in by_id:
            by_id[m['id']] = m
    out = []
    for m in sorted(by_id.values(), key=lambda m: _date(m.get('date'))):
        c = classify(m)
        if c['kind'] == 'other' and c['confidence'] == 'high':
            continue
        company, how = extract_company(m, title_like)
        out.append({'id': m['id'], 'thread_id': m.get('thread_id', ''), 'date': _date(m.get('date')),
                    'url': m.get('url') or (f"https://mail.google.com/mail/u/0/#all/{m['thread_id']}" if m.get('thread_id') else ''),
                    'subject': (m.get('subject') or '')[:140], 'kind': c['kind'], 'confidence': c['confidence'],
                    'reason': c['reason'], 'company': company, 'company_from': how, 'role': extract_role(m, role_word)})
    return out, skipped


def settled(rec):
    """A record that can go into the table: decided by Claude, or confidently classified with a company."""
    if rec.get('decided'):
        return rec.get('kind') in STATUS_OF and bool(rec.get('company'))
    return rec['confidence'] == 'high' and rec['kind'] in STATUS_OF and bool(rec['company']) and \
        rec['company_from'] not in ('sender?', 'domain?')


def group(recs, existing, today=None):
    apps, unsure = {}, []
    for rec in sorted(recs, key=lambda r: r['date']):
        if rec.get('dismissed'):
            continue
        if not settled(rec):
            if not (rec.get('decided') and rec.get('kind') == 'other'):
                unsure.append(rec)
            continue
        company, role = rec['company'], rec.get('role', '')
        hit = _match_existing(company, role, existing)
        if not hit:  # the only application at this company so far in this run, if the roles don't conflict
            same = [k for k, a in apps.items() if same_company(a['company'], company)]
            if len(same) == 1 and (not role or not apps[same[0]]['title']):
                app = apps[same[0]]
                app['title'] = app['title'] or role
                app['messages'].append(rec)
                continue
        key = hit['job_key'] if hit else (job_key(company, role) if role else f'{norm_company(company)}_?')
        app = apps.setdefault(key, {'company': hit['company'] if hit else company, 'title': hit['title'] if hit else role,
                                    'job_key': key, 'existing': hit.get('where') if hit else '',
                                    'existing_status': hit.get('status', '') if hit else '', 'messages': [],
                                    'candidates': [] if (hit or role) else
                                    [r['title'] for r in existing if same_company(r['company'], company)]})
        if not app['title'] and role:
            app['title'] = role
        app['messages'].append(rec)
    rows = []
    for app in apps.values():
        msgs = app['messages']
        confirms = [x['date'] for x in msgs if x['kind'] == 'confirmation']
        status, status_date = '', ''
        for x in msgs:
            s = STATUS_OF.get(x['kind'])
            if s and tracker.advance(status, status_date, s, x['date']):
                status, status_date = s, x['date']
        if app['existing']:
            cur = app['existing_status'] or 'applied'
            action = 'update' if status and status != cur and tracker.advance(cur, '', status, status_date) else 'no change'
        elif app.get('candidates'):
            action = 'which?'  # role unknown and several tracked applications at this company
        else:
            action = 'add'
        rows.append({**app, 'date_applied': min(confirms) if confirms else '', 'status': status or 'applied',
                     'status_date': status_date, 'action': action, 'gmail_ids': ' '.join(x['id'] for x in msgs)})
    rows.sort(key=lambda r: (r['action'] == 'no change', r['date_applied'] or r['status_date']))
    for i, r in enumerate(rows, 1):
        r['n'] = i
    return rows, unsure


def propose(messages, workspace, today=None):
    ws = os.path.expanduser(workspace)
    recs, skipped = records(messages, load_seen(ws), pack_role_words(ws))
    rows, unsure = group(recs, existing_rows(ws, _workspace_cfg(ws)))
    return {'created': (today or datetime.date.today()).isoformat(), 'scanned_at': _now_utc(), 'rows': rows, 'unsure': unsure,
            'skipped_seen': skipped, 'messages': len(recs)}


def regroup(prop, workspace):
    """Rebuild the table after Claude settles unsure records (sets decided: true plus kind, company,
    role; or dismissed: true) or corrects a row's title (edit the row's messages' role)."""
    ws = os.path.expanduser(workspace)
    recs = [m for r in prop['rows'] for m in r['messages']] + prop.get('unsure', [])
    for r in prop['rows']:
        if r.get('title'):
            for m in r['messages']:
                m['role'] = m.get('role') or r['title']
    rows, unsure = group(recs, existing_rows(ws, _workspace_cfg(ws)))
    dismissed = [m for m in prop.get('unsure', []) if m.get('dismissed')] + prop.get('dismissed', [])
    return {**prop, 'rows': rows, 'unsure': unsure, 'dismissed': dismissed}


TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates', 'gmail-summary.md')
DEFAULT_TEMPLATE = {
    'propose': ('## Updates to tracked applications ({n_updates})\n{updates}\n\n## New applications ({n_new})\n{new}\n\n'
                '## Ignored, dismissed and unsure ({n_ignored})\n{ignored}\n\n## Counts by resulting status\n{counts}'),
    'apply': 'tracker.csv: {added} added, {updated} updated, {unchanged} unchanged\n\n## Counts by new status\n{counts}',
}


def layout(part):
    """One part ('propose' or 'apply') of templates/gmail-summary.md; built-in text when the file is missing."""
    try:
        with open(TEMPLATE, encoding='utf-8') as fh:
            text = fh.read()
    except OSError:
        return DEFAULT_TEMPLATE[part]
    m = re.search(r'<!-- %s -->\n(.*?)<!-- (?:apply|end) -->' % part, text, re.S)
    return m.group(1).strip('\n') if m else DEFAULT_TEMPLATE[part]


def fill(template, **values):
    for k, v in values.items():  # plain replacement: table text may hold braces
        template = template.replace('{' + k + '}', str(v))
    return template


def counts_by_status(rows):
    """'rejected 2, interviewing 1, applied 3' in lifecycle order, or 'none'."""
    n = {}
    for r in rows:
        n[r['status']] = n.get(r['status'], 0) + 1
    order = list(STATUS_OF.values())
    return ', '.join(f'{s} {n[s]}' for s in sorted(n, key=lambda s: order.index(s) if s in order else len(order))) or 'none'


def _row_lines(rows):
    if not rows:
        return '(none)'
    lines = ['| # | Action | Company | Role | Status | Applied | Evidence |', '|---|---|---|---|---|---|---|']
    for r in rows:
        ev = '; '.join(f"[{x['kind']} {x['date']}]({x['url']})" if x['url'] else f"{x['kind']} {x['date']}" for x in r['messages'][:4])
        title = r['title'] or ('**role unknown**: one of ' + '; '.join(r['candidates']) if r.get('candidates') else '**role unknown**')
        lines.append(f"| {r['n']} | {r['action']} | {r['company']} | {title} | {r['status']} "
                     f"{r['status_date']} | {r['date_applied']} | {ev} |")
    return '\n'.join(lines)


def table(prop):
    """Updates to tracked rows, new applications, then ignored/dismissed/unsure, then counts by resulting status."""
    rows = prop['rows']
    updates = [r for r in rows if r['existing'] and r['action'] == 'update']
    new = [r for r in rows if r['action'] in ('add', 'which?')]
    quiet = [r for r in rows if r not in updates and r not in new]
    ignored = []
    if quiet:
        ignored.append('Tracked, nothing to change:\n\n' + _row_lines(quiet))
    if prop['unsure']:
        ignored.append('Unsure (read each one, then `gmh gmail settle <proposed> u<n> --kind <k> --company <c> --role <r>` '
                       'or `--dismiss`; several at once with `--file`):\n'
                       + '\n'.join(f"- u{i} {u['date']} {u['company'] or '?'}: \"{u['subject']}\" ({u['kind']}, {u['reason']}) "
                                   f"{u['url']}" for i, u in enumerate(prop['unsure'], 1)))
    if prop.get('dismissed'):
        ignored.append('Dismissed:\n' + '\n'.join(f"- {u['date']} {u.get('company') or '?'}: \"{u['subject']}\" {u.get('url', '')}"
                                                  for u in prop['dismissed']))
    return fill(layout('propose'), n_updates=len(updates), updates=_row_lines(updates), n_new=len(new), new=_row_lines(new),
                n_ignored=len(quiet) + len(prop['unsure']) + len(prop.get('dismissed') or []),
                ignored='\n\n'.join(ignored) or '(none)', counts=counts_by_status(rows))


def apply_summary(res, rows):
    """The closing text of `apply`: counts, then the new status of each approved row."""
    return fill(layout('apply'), added=res['added'], updated=res['updated'], unchanged=res['unchanged'],
                counts=counts_by_status(rows))


# ---- ingest (saved Gmail connector pages -> incoming.jsonl) ----

def _first(d, *keys):
    for k in keys:
        if d.get(k) not in (None, ''):
            return d[k]
    return ''


def _sender(v):
    if isinstance(v, dict):
        name, addr = _first(v, 'name', 'displayName'), _first(v, 'email', 'address')
        return f'{name} <{addr}>' if name and addr else str(addr or name)
    return str(v or '')


def _when(v):
    """ISO date or RFC 2822 string kept as is; epoch milliseconds/seconds turned into an ISO date."""
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit() and len(v) >= 10):
        n = float(v)
        n = n / 1000 if n > 1e11 else n
        return datetime.datetime.fromtimestamp(n, datetime.timezone.utc).date().isoformat()
    return str(v or '')


def _page_threads(obj):
    """Threads in one saved page, a list of pages, or a list of threads."""
    if isinstance(obj, list):
        return [t for x in obj for t in _page_threads(x)]
    if not isinstance(obj, dict):
        return []
    for key in ('threads', 'results', 'items'):
        if isinstance(obj.get(key), list):
            return [t for x in obj[key] for t in _page_threads(x)]
    return [obj] if (obj.get('id') or obj.get('threadId') or obj.get('messages')) else []


def thread_messages(thread):
    """incoming.jsonl messages (extracted fields only; no bodies) from one connector thread."""
    tid = str(_first(thread, 'id', 'threadId', 'thread_id'))
    t_url = _first(thread, 'viewUrl', 'url')
    msgs = thread.get('messages') if isinstance(thread.get('messages'), list) and thread['messages'] else [thread]
    out = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        mid = str(_first(m, 'id', 'messageId', 'message_id') or tid)
        out.append({'id': mid, 'thread_id': str(_first(m, 'threadId', 'thread_id') or tid or mid),
                    'date': _when(_first(m, 'date', 'internalDate', 'receivedAt') or _first(thread, 'date', 'internalDate')),
                    'sender': _sender(_first(m, 'sender', 'from') or _first(thread, 'sender', 'from')),
                    'subject': str(_first(m, 'subject') or _first(thread, 'subject')),
                    'snippet': str(_first(m, 'snippet', 'preview') or _first(thread, 'snippet')),
                    'url': str(_first(m, 'viewUrl', 'url') or t_url)})
    return out


def ingest(paths, out):
    """Union saved search_threads pages by message id into `out` (kept if it exists). Returns
    (thread count, new thread count): new = threads not already in `out`."""
    have = read_incoming(out) if os.path.exists(out) else []
    old_threads = {m.get('thread_id') or m['id'] for m in have}
    by_id = {m['id']: m for m in have}
    threads = set()
    for p in paths:
        with open(p, encoding='utf-8') as fh:
            data = json.load(fh)
        for t in _page_threads(data):
            for m in thread_messages(t):
                by_id[m['id']] = {**by_id.get(m['id'], {}), **{k: v for k, v in m.items() if v}}
                threads.add(m['thread_id'])
    if os.path.dirname(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8', newline='\n') as fh:
        for m in by_id.values():
            fh.write(json.dumps(m, ensure_ascii=False) + '\n')
    return len(threads | old_threads), len(threads - old_threads)


# ---- decide (edit proposal rows by number) ----

def decide(prop, workspace, rows_spec, kind=None, company=None, role=None, title=None, dismiss=False, keep=False):
    """Edit numbered rows of the proposal and rebuild the table. Returns (new proposal, [(old number, new
    row or None when dismissed)]). The rebuild renumbers rows, so the old number is returned too."""
    if kind is not None and kind != 'other' and kind not in STATUS_OF:
        raise ValueError(f"unknown kind {kind!r}; use one of: {', '.join(KINDS)}, other")
    nums = parse_rows(rows_spec, len(prop['rows']))
    bad = sorted(nums - {r['n'] for r in prop['rows']})
    if not nums or bad:
        raise ValueError(f"no such row: {', '.join(map(str, bad)) or rows_spec!r}; rows are 1-{len(prop['rows'])}")
    prop = json.loads(json.dumps(prop))  # work on a copy
    prop.setdefault('dismissed', [])
    touched = []
    for r in prop['rows']:
        if r['n'] not in nums:
            continue
        msgs = r['messages']
        touched.append((r['n'], [m['id'] for m in msgs], bool(dismiss or kind == 'other')))
        if dismiss or kind == 'other':
            for m in msgs:
                m['dismissed'] = True
                prop['dismissed'].append({k: m.get(k, '') for k in ('id', 'thread_id', 'date', 'url', 'subject', 'kind', 'company')})
            continue
        if kind:  # the message that sets the row's status
            drive = next((m for m in reversed(msgs) if STATUS_OF.get(m['kind']) == r['status'] and m['date'] == r['status_date']), msgs[-1])
            drive['kind'] = kind
        for m in msgs:
            if company:
                m['company'], m['company_from'] = company, 'user'
            if role or title:
                m['role'] = role or title
            if keep or kind or company or role or title:
                m['decided'] = True
        if role or title:
            r['title'] = role or title
    prop = regroup(prop, workspace)
    changed = []
    for old, ids, gone in touched:
        row = None if gone else next((x for x in prop['rows'] if set(ids) & set(x['gmail_ids'].split())), None)
        changed.append((old, row))
    return prop, changed


def _unsure_index(prop, ref):
    """An unsure record by its table label (u3, or 3) or its message id. Returns its index in prop['unsure']."""
    ref = str(ref).strip()
    n = ref[1:] if ref[:1].lower() == 'u' else ref
    if n.isdigit() and 1 <= int(n) <= len(prop['unsure']):
        return int(n) - 1
    for i, u in enumerate(prop['unsure']):
        if u['id'] == ref:
            return i
    raise ValueError(f"no unsure mail {ref!r}; they are u1-u{len(prop['unsure'])} (or a message id)")


def settle(prop, workspace, decisions):
    """Settle unsure mail without hand-editing the proposed file. Each decision: {'u': 'u3' | 3 | '<message id>',
    'kind': <kind or other>, 'company': ..., 'role': ...} or {'u': ..., 'dismiss': true}. A kind other than 'other'
    needs a company. Every decision is checked first; on any problem nothing changes (ValueError lists them all).
    Only the given fields are stored, never mail text. Returns the regrouped proposal."""
    prop = json.loads(json.dumps(prop))  # work on a copy
    problems, plan = [], []
    for d in decisions:
        if not isinstance(d, dict) or 'u' not in d:
            problems.append(f'not a decision (needs "u"): {d!r}')
            continue
        try:
            i = _unsure_index(prop, d['u'])
        except ValueError as e:
            problems.append(str(e))
            continue
        kind = d.get('kind')
        if d.get('dismiss'):
            if kind or d.get('company') or d.get('role'):
                problems.append(f"{d['u']}: dismiss stands alone")
        elif kind is None:
            problems.append(f"{d['u']}: needs a kind or dismiss")
        elif kind != 'other' and kind not in STATUS_OF:
            problems.append(f"{d['u']}: unknown kind {kind!r}; use one of: {', '.join(KINDS)}, other")
        elif kind != 'other' and not (d.get('company') or prop['unsure'][i].get('company')):
            problems.append(f"{d['u']}: a {kind} needs a company")
        plan.append((i, d))
    if problems:
        raise ValueError('; '.join(problems))
    for i, d in plan:
        u = prop['unsure'][i]
        if d.get('dismiss') or d.get('kind') == 'other':
            u['dismissed'] = True
            continue
        u.update(decided=True, kind=d['kind'])
        if d.get('company'):
            u['company'], u['company_from'] = str(d['company']).strip(), 'claude'
        if d.get('role'):
            u['role'] = str(d['role']).strip()
    return regroup(prop, workspace)


# ---- apply ----

def load_seen(ws):
    p = os.path.join(ws, 'state', 'gmail', 'seen.json')
    return set(json.load(open(p, encoding='utf-8'))) if os.path.exists(p) else set()


def _now_utc():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def save_seen(ws, ids, scanned_through=None):
    d = os.path.join(ws, 'state', 'gmail')
    os.makedirs(d, exist_ok=True)
    json.dump(sorted(load_seen(ws) | set(ids)), open(os.path.join(d, 'seen.json'), 'w', encoding='utf-8', newline='\n'), indent=0)
    if scanned_through:  # the next scan starts here
        json.dump({'last_run': scanned_through, 'updated': _now_utc()}, open(os.path.join(d, 'sync.json'), 'w', encoding='utf-8', newline='\n'), indent=1)


def last_run(ws):
    """When the last applied scan reached, as an aware datetime (UTC), or None."""
    p = os.path.join(os.path.expanduser(ws), 'state', 'gmail', 'sync.json')
    if not os.path.exists(p):
        return None
    v = json.load(open(p, encoding='utf-8')).get('last_run')
    if not v:
        return None
    dt = datetime.datetime.fromisoformat(v) if 'T' in v else datetime.datetime.fromisoformat(v + 'T00:00:00')
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


def scanned_through(prop, approved, dismissed, seen=frozenset()):
    """How far the next scan can skip: the time this scan ran, pulled back to the day of the oldest
    message still waiting for a decision, so a row left open is found again next time."""
    end = prop.get('scanned_at') or (prop['created'] + 'T00:00:00+00:00')
    pending = [m['date'] for r in prop['rows'] if r['n'] not in approved | dismissed for m in r['messages']
               if m['id'] not in seen]
    pending += [u['date'] for u in prop.get('unsure', []) if not u.get('dismissed') and not u.get('decided')
                and u['id'] not in seen]
    pending = [d for d in pending if d]
    if pending and min(pending) < end[:10]:
        return min(pending) + 'T00:00:00+00:00'
    return end


def after_query(ws, overlap_hours=24):
    """The date for Gmail's `after:YYYY/MM/DD` (the form the Gmail connector honors; `after:<epoch>` silently
    returns nothing there). Gmail's date operators are day-granular, inclusive of the named day, in the
    account's timezone, which we don't know. So start from the UTC day of (last scan - overlap) and step back
    one more day: that covers any offset up to UTC+/-14h and mail delivered late. Message ids already
    processed are skipped anyway, so the extra overlap costs nothing."""
    lr = last_run(ws)
    if not lr:
        return None
    day = (lr - datetime.timedelta(hours=overlap_hours)).astimezone(datetime.timezone.utc).date()
    return (day - datetime.timedelta(days=1)).strftime('%Y/%m/%d')


def parse_rows(spec, n_max):
    if not spec:
        return set()
    if spec == 'all':
        return set(range(1, n_max + 1))
    out = set()
    for part in spec.split(','):
        a, _, b = part.strip().partition('-')
        out |= set(range(int(a), int(b or a) + 1))
    return out


def apply(prop, workspace, rows_spec, dismiss_spec=''):
    """Write the approved rows; mark approved and dismissed rows' messages as seen."""
    ws = os.path.expanduser(workspace)
    approve = parse_rows(rows_spec, len(prop['rows']))
    dismiss = parse_rows(dismiss_spec, len(prop['rows']))
    path = tracker.path_of(ws)
    tracker.init(path)
    current = tracker.read(path)
    before = {id(r): r.get('status') for r in current}
    result, seen = {'added': 0, 'updated': 0, 'unchanged': 0}, []
    approved = []
    for r in prop['rows']:
        if r['n'] in approve:
            if not r.get('title'):
                raise SystemExit(f"row {r['n']} ({r['company']}) has no role; set its title in the proposed file first"
                                 + (f" (tracked there: {'; '.join(r['candidates'])})" if r.get('candidates') else ''))
            item = {'company': r['company'], 'title': r['title'], 'status': r['status'], 'status_date': r['status_date'],
                    'date_applied': r['date_applied'], 'source': 'gmail', 'gmail_ids': r['gmail_ids'], 'job_key': r['job_key']
                    if not r['job_key'].endswith('_?') else ''}
            result[tracker.upsert(current, item)] += 1
            approved.append(r)
            seen += r['gmail_ids'].split()
        elif r['n'] in dismiss:
            seen += r['gmail_ids'].split()
    seen += [u['id'] for u in prop.get('dismissed', [])]
    changed = [r for r in current if before.get(id(r)) != r.get('status')]  # only rows this approval moved on
    result['approved'] = approved  # the rows written, for the counts by new status
    result['moves'] = tracker.move_folders(changed, tracker.vault_of(ws))
    tracker.write(path, current)
    save_seen(ws, seen, scanned_through(prop, approve, dismiss, load_seen(ws) | set(seen)))
    return result


def _load(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def _save(path, obj):
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)


def _row_text(r):
    return f"#{r['n']} {r['action']} | {r['company']} | {r['title'] or 'role unknown'} | {r['status']} {r['status_date']}"


def main(argv=None):
    ap = argparse.ArgumentParser(prog='engine.gmail_import')
    sub = ap.add_subparsers(dest='cmd', required=True)
    ws_default = os.environ.get('GMH_WORKSPACE')
    q = sub.add_parser('queries')
    q.add_argument('--since', default='6m')
    q.add_argument('--after', help="YYYY/MM/DD, or 'last' for where the last applied scan reached")
    q.add_argument('--full', action='store_true', help='ignore the last scan and search the whole --since window')
    q.add_argument('--workspace', default=ws_default)
    mb = sub.add_parser('from-mbox')
    mb.add_argument('mbox')
    mb.add_argument('--out', required=True)
    mb.add_argument('--since', default='6m')
    ig = sub.add_parser('ingest', help='saved Gmail connector search_threads results -> incoming.jsonl')
    ig.add_argument('pages', nargs='+')
    ig.add_argument('--out', help='default: <workspace>/state/gmail/incoming.jsonl')
    ig.add_argument('--workspace', default=ws_default)
    ig.add_argument('--json', action='store_true')
    pr = sub.add_parser('propose')
    pr.add_argument('incoming')
    pr.add_argument('--workspace', default=ws_default)
    pr.add_argument('--keep-input', action='store_true')
    pr.add_argument('--json', action='store_true')
    rg = sub.add_parser('regroup')
    rg.add_argument('proposed')
    rg.add_argument('--workspace', default=ws_default)
    rg.add_argument('--json', action='store_true')
    dc = sub.add_parser('decide', help='edit numbered rows of a proposal')
    dc.add_argument('proposed')
    dc.add_argument('rows', help='row numbers: 3 | 1,3 | 2-5')
    dc.add_argument('--workspace', default=ws_default)
    dc.add_argument('--json', action='store_true')
    how = dc.add_argument_group('what to change (at least one)')
    how.add_argument('--kind', help=', '.join(KINDS) + ', other (other = not an application: dismissed)')
    how.add_argument('--company')
    how.add_argument('--role')
    how.add_argument('--title', help='the role as it goes in the tracker')
    how.add_argument('--dismiss', action='store_true', help='drop the row for good (its mail is marked seen on apply)')
    how.add_argument('--keep', action='store_true', help='confirm the row as proposed')
    st = sub.add_parser('settle', help='settle unsure mail (u1, u2 ... in the table) without editing the proposed file')
    st.add_argument('proposed')
    st.add_argument('unsure', nargs='?', help='u<n> from the table, or a message id')
    st.add_argument('--kind', help=', '.join(KINDS) + ', other (other = not about an application: dismissed)')
    st.add_argument('--company')
    st.add_argument('--role')
    st.add_argument('--dismiss', action='store_true')
    st.add_argument('--file', help='JSON list of decisions: [{"u": "u1", "kind": "rejection", "company": "...", '
                                   '"role": "..."}, {"u": "u2", "dismiss": true}]')
    st.add_argument('--workspace', default=ws_default)
    st.add_argument('--json', action='store_true')
    ay = sub.add_parser('apply')
    ay.add_argument('proposed')
    ay.add_argument('--workspace', default=ws_default)
    ay.add_argument('--rows', default='')
    ay.add_argument('--dismiss', default='')
    ay.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    if a.cmd == 'queries':
        after = a.after
        if after == 'last' or (after is None and not a.full and a.workspace and last_run(a.workspace)):
            after = after_query(a.workspace) if a.workspace else None
            if not after:
                sys.exit('no earlier scan recorded in state/gmail/sync.json; run the history import first')
            print(f'# continuing from the last scan ({last_run(a.workspace).isoformat()}, minus overlap)', file=sys.stderr)
        print('\n'.join(queries(a.since, after)))
    elif a.cmd == 'from-mbox':
        msgs = from_mbox(a.mbox, a.since)
        with open(a.out, 'w', encoding='utf-8', newline='\n') as fh:
            for m in msgs:
                fh.write(json.dumps(m, ensure_ascii=False) + '\n')
        print(f'{len(msgs)} job-related messages -> {a.out}')
    elif a.cmd == 'ingest':
        out = a.out or (os.path.join(os.path.expanduser(a.workspace), 'state', 'gmail', 'incoming.jsonl') if a.workspace else None)
        if not out:
            sys.exit('--out (or --workspace / $GMH_WORKSPACE) is required')
        out = os.path.abspath(out)
        try:
            n, new = ingest(a.pages, out)
        except (OSError, ValueError) as e:
            sys.exit(f'cannot read a page: {e}')
        if a.json:
            print(json.dumps({'threads': n, 'new': new, 'out': out}))
        else:
            print(f'{n} threads ({new} new) -> {out}')
        if not n:
            sys.exit(1)
    elif a.cmd == 'propose':
        if not a.workspace:
            sys.exit('--workspace (or $GMH_WORKSPACE) is required')
        prop = propose(read_incoming(a.incoming), a.workspace)
        d = os.path.join(os.path.expanduser(a.workspace), 'state', 'gmail')
        os.makedirs(d, exist_ok=True)
        out = os.path.abspath(os.path.join(d, f"proposed-{prop['created']}.json"))
        _save(out, prop)
        if not a.keep_input:
            os.remove(a.incoming)
        if a.json:
            print(json.dumps({**prop, 'path': out}, ensure_ascii=False))
        else:
            print(table(prop))
            print(f"\n{prop['messages']} messages, {len(prop['rows'])} applications, {len(prop['unsure'])} unsure, "
                  f"{prop['skipped_seen']} already processed -> {out}")
    elif a.cmd == 'regroup':
        prop = regroup(_load(a.proposed), a.workspace)
        _save(a.proposed, prop)
        print(json.dumps(prop, ensure_ascii=False) if a.json else table(prop))
    elif a.cmd == 'decide':
        if not a.workspace:
            sys.exit('--workspace (or $GMH_WORKSPACE) is required')
        if not (a.kind or a.company or a.role or a.title or a.dismiss or a.keep):
            ap.error('decide needs one of --kind, --company, --role, --title, --dismiss, --keep')
        if a.dismiss and (a.kind or a.company or a.role or a.title or a.keep):
            ap.error('--dismiss stands alone')
        try:
            prop, changed = decide(_load(a.proposed), a.workspace, a.rows, kind=a.kind, company=a.company, role=a.role,
                                   title=a.title, dismiss=a.dismiss, keep=a.keep)
        except ValueError as e:
            ap.error(str(e))
        _save(a.proposed, prop)
        if a.json:
            print(json.dumps([{'was': old, 'row': row} for old, row in changed], ensure_ascii=False))
        else:
            for old, row in changed:
                print(f'was #{old}: dismissed' if row is None else (f'was #{old} -> {_row_text(row)}' if row['n'] != old else _row_text(row)))
            print('Rows are renumbered after each change; `gmh gmail regroup` shows the current table.')
    elif a.cmd == 'settle':
        if not a.workspace:
            sys.exit('--workspace (or $GMH_WORKSPACE) is required')
        if bool(a.file) == bool(a.unsure):
            ap.error('settle takes one unsure mail (u<n>) or --file, not both')
        if a.file:
            try:
                decisions = _load(a.file)
            except (OSError, ValueError) as e:
                sys.exit(f'cannot read {a.file}: {e}')
            if not isinstance(decisions, list):
                sys.exit(f'{a.file}: expected a JSON list of decisions')
        else:
            decisions = [{'u': a.unsure, 'kind': a.kind, 'company': a.company, 'role': a.role, 'dismiss': a.dismiss}]
        try:
            prop = settle(_load(a.proposed), a.workspace, decisions)
        except ValueError as e:
            sys.exit(f'nothing settled: {e}')
        _save(a.proposed, prop)
        print(json.dumps(prop, ensure_ascii=False) if a.json else table(prop))
    else:
        if not a.workspace:
            sys.exit('--workspace (or $GMH_WORKSPACE) is required')
        res = apply(_load(a.proposed), a.workspace, a.rows, a.dismiss)
        approved = res.pop('approved')
        if a.json:
            print(json.dumps({**res, 'counts': {s: sum(1 for r in approved if r['status'] == s) for s in {r['status'] for r in approved}}},
                             ensure_ascii=False, default=str))
        else:
            print(apply_summary(res, approved))
            for m in res['moves']:
                print(tracker.describe_move(m))


if __name__ == '__main__':
    main()
