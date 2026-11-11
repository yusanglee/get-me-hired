"""The tracker dashboard: one self-contained HTML page generated from tracker.csv (report.html).

Opens from disk with no server and no network: CSS and JS are inline and the rows are embedded as JSON
(escaped so no tracker text can close the script tag or become markup; the page renders text with
textContent). Filters (status, company, location with a Remote toggle, source, tier, minimum fit,
applied-date range), free-text search, sortable columns and a visible-row count; summary tiles follow
the filters. Roles on hold (tracker.holds, read from the reviewed CSVs) get their own On hold section and tile;
the company filter and search apply to them, and a hold of 14+ days is flagged "held a while". Last-used filters are kept in localStorage when the browser allows it.

    from engine.dashboard import render
    html = render(rows, today='2026-10-21', fits={id: (fit, tier)}, vault='/path/to/vault', gaps_html='', holds=[...])
"""
import csv, datetime, glob, html, json, os, re, urllib.parse

RESPONDED = {'assessment', 'interviewing', 'offer', 'accepted', 'declined', 'rejected'}


def scores(vault):
    """{role id: (fit, tier)} from the vault's queue: scored-*.csv (newest wins), then reviewed-*.csv for roles
    no scored file has (a role picked from the review page can carry its fit only there)."""
    q = os.path.join(os.path.expanduser(vault or ''), 'Pipeline', 'queue')
    out, reviewed = {}, {}
    for kind, dest in (('scored', out), ('reviewed', reviewed)):
        for p in sorted(glob.glob(os.path.join(q, f'{kind}-*.csv')), key=os.path.getmtime):
            with open(p, encoding='utf-8', newline='') as fh:
                for r in csv.DictReader(fh):
                    try:
                        dest[r['id']] = (int(float(r.get('fit') or '')), r.get('tier', ''))
                    except (KeyError, ValueError):
                        pass
    return {**reviewed, **out}


def _days(a, b):
    try:
        return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat((a or '')[:10])).days
    except ValueError:
        return None


def row_data(rows, today, fits=None, vault=None, quiet_days=10, stale_days=60, max_followups=2):
    """The rows as the page needs them (short keys, computed flags)."""
    from .tracker import OPEN, last_touch
    fits = fits or {}
    out = []
    for r in rows:
        fit, tier = fits.get(r.get('id') or '', (None, ''))
        quiet = _days(last_touch(r), today)
        sent = len((r.get('followups') or '').split())
        status = r.get('status') or 'applied'
        folder = r.get('folder') or ''
        path = folder if os.path.isabs(folder) else os.path.join(os.path.expanduser(vault or ''), folder)
        li = (r.get('linkedin_interest') or '').split()
        out.append({
            'd': r.get('date_applied', ''), 'c': r.get('company', ''), 't': r.get('title', ''),
            'l': r.get('location', ''), 's': status, 'sd': r.get('status_date', ''), 'src': r.get('source', ''),
            'u': r.get('url', '') if re.match(r'https?://', r.get('url') or '') else '',
            'f': 'file://' + urllib.parse.quote(path) if folder and vault and os.path.isdir(path) else '',
            'fit': fit, 'tier': tier or '',
            'li': li[0] if li else '', 'lic': (r.get('linkedin_connect') or '').count(' sent: '),
            'due': bool(status in OPEN - {'offer'} and sent < max_followups and quiet is not None and quiet >= quiet_days),
            'stale': bool(status == 'applied' and quiet is not None and quiet >= stale_days),
            'n': r.get('notes', ''),
        })
    return out


def _json(data):
    """JSON safe inside <script>: no '<', '>' or '&' survives to close the tag or start markup."""
    return (json.dumps(data, ensure_ascii=False, separators=(',', ':'))
            .replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
            .replace('\u2028', '\\u2028').replace('\u2029', '\\u2029'))


def hold_data(holds, fits=None):
    """The holds as the page needs them (short keys; the folder as a file:// link)."""
    fits = fits or {}
    out = []
    for h in holds or []:
        fit, tier = fits.get(h.get('id') or '', (None, ''))
        if fit is None:
            try:
                fit = int(float(h.get('fit') or ''))
            except ValueError:
                pass
        out.append({'c': h.get('company', ''), 't': h.get('title', ''), 'l': h.get('location', ''), 'fit': fit, 'tier': tier or '',
                    'since': h.get('since', ''), 'days': h.get('days'), 'old': bool(h.get('old')), 'n': h.get('note', ''),
                    'u': h.get('url', '') if re.match(r'https?://', h.get('url') or '') else '',
                    'f': 'file://' + urllib.parse.quote(h['folder']) if h.get('folder') else ''})
    return out


def render(rows, today=None, fits=None, vault=None, gaps_html='', title='Applications', holds=None):
    today = today or datetime.date.today().isoformat()
    data = row_data(rows, today, fits, vault)
    generated = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    return (PAGE.replace('__TITLE__', html.escape(title)).replace('__GENERATED__', html.escape(generated))
            .replace('__GAPS__', gaps_html or '').replace('__DATA__', _json({'today': today, 'rows': data, 'holds': hold_data(holds, fits)})))


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title><style>
:root{--bg:#fbfbf9;--panel:#ffffff;--fg:#1d1d1b;--muted:#6b6b66;--line:#e4e3de;--accent:#2f5d50;--accent-bg:#e3eee9;
--warn:#8a5a00;--warn-bg:#fbf0d9;--bad:#9b2c2c;--bad-bg:#f8e5e3;--good:#2f5d50;--good-bg:#e3eee9}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--panel:#1c1c1a;--fg:#ecebe6;--muted:#9a9993;--line:#2e2e2b;
--accent:#8fc1ae;--accent-bg:#20302a;--warn:#e7b65c;--warn-bg:#332710;--bad:#ef9a92;--bad-bg:#3a1f1d;--good:#8fc1ae;--good-bg:#20302a}}
*{box-sizing:border-box}body{background:var(--bg);color:var(--fg);font:15px/1.45 -apple-system,system-ui,"Segoe UI",sans-serif;margin:0;padding:24px 16px}
main{max-width:1200px;margin:0 auto}h1{font-size:22px;margin:0 0 2px}p.sub{color:var(--muted);margin:0 0 18px;font-size:13px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:18px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.tile b{display:block;font-size:24px;font-variant-numeric:tabular-nums;line-height:1.2}.tile span{color:var(--muted);font-size:12px}
.filters{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px;margin-bottom:12px;display:grid;gap:10px}
.row{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center}
label{font-size:12px;color:var(--muted);display:flex;flex-direction:column;gap:3px}
input,select,button{font:inherit;font-size:14px;color:var(--fg);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:5px 8px}
input[type=search]{flex:1 1 240px;min-width:0}label.inline{flex-direction:row;align-items:center;gap:6px;font-size:14px;color:var(--fg)}
.chips{display:flex;flex-wrap:wrap;gap:6px}.chip{border-radius:999px;padding:3px 10px;cursor:pointer;font-size:13px}
.chip[aria-pressed=true]{background:var(--accent);border-color:var(--accent);color:var(--bg)}button.link{border:none;background:none;color:var(--accent);padding:0;cursor:pointer}
.count{color:var(--muted);font-size:13px;margin:0 0 6px}
table{width:100%;border-collapse:collapse;font-size:14px;background:var(--panel);border:1px solid var(--line);border-radius:10px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px;white-space:nowrap;background:var(--panel)}#t th{cursor:pointer;user-select:none;position:sticky;top:0}
th[aria-sort=ascending]::after{content:" \2191"}th[aria-sort=descending]::after{content:" \2193"}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}td.nw{white-space:nowrap}
a{color:var(--accent)}.muted{color:var(--muted)}.pill{display:inline-block;border-radius:999px;padding:1px 8px;font-size:12px;white-space:nowrap}
.p-applied{background:var(--line)}.p-interviewing,.p-assessment,.p-offer,.p-accepted{background:var(--good-bg);color:var(--good)}
.p-rejected,.p-declined,.p-withdrawn,.p-no_response{background:var(--bad-bg);color:var(--bad)}.flag{background:var(--warn-bg);color:var(--warn)}
.wrap{overflow-x:auto}td.n{text-align:right;font-variant-numeric:tabular-nums}h2{font-size:18px;margin:32px 0 4px}table.heat td.h{text-align:center;font-variant-numeric:tabular-nums;min-width:36px}
.empty{padding:24px;text-align:center;color:var(--muted)}
@media (max-width:700px){#t thead,#h thead{display:none}#t,#t tbody,#t tr,#t td,#h,#h tbody,#h tr,#h td{display:block;width:100%}
#t tr,#h tr{border-bottom:1px solid var(--line);padding:6px 0}#t td,#h td{border:none;padding:2px 10px}
#t td[data-label]::before,#h td[data-label]::before{content:attr(data-label) ": ";color:var(--muted);font-size:12px}td.num{text-align:left}}
</style></head><body><main>
<h1>__TITLE__</h1><p class="sub">Generated __GENERATED__ from tracker.csv and the reviewed picks (holds). Filters run in this page; nothing is sent anywhere.</p>
<div class="tiles" id="tiles"></div>
<div class="filters">
 <div class="row"><input type="search" id="q" placeholder="Search company, role, location, notes" aria-label="Search">
  <button id="reset">Reset filters</button></div>
 <div class="chips" id="statuses" role="group" aria-label="Status"></div>
 <div class="row">
  <label>Company<select id="company"></select></label>
  <label>Location<select id="loc"></select></label>
  <label class="inline"><input type="checkbox" id="remote">Remote only</label>
  <label>Source<select id="source"></select></label>
  <label>Tier<select id="tier"></select></label>
  <label>Min fit<input type="number" id="fit" min="0" max="100" step="1" style="width:80px"></label>
  <label>Applied from<input type="date" id="from"></label>
  <label>to<input type="date" id="to"></label>
 </div>
</div>
<p class="count" id="count" aria-live="polite"></p>
<table id="t"><thead><tr>
 <th data-k="d">Applied</th><th data-k="c">Company</th><th data-k="t">Role</th><th data-k="l">Location</th>
 <th data-k="s">Status</th><th data-k="sd">Since</th><th data-k="fit" class="num">Fit</th><th data-k="li">LinkedIn</th>
 <th data-k="src">Source</th><th data-k="f">Materials</th></tr></thead><tbody id="body"></tbody></table>
<section id="holds"><h2>On hold</h2><p class="sub">Roles you put on hold in a review, not applied to yet. They leave this list once
applied (tracker) or passed in a later review. Company and search filters apply; holds of 14+ days are flagged.</p>
<p class="count" id="hcount" aria-live="polite"></p>
<div class="wrap"><table id="h"><thead><tr><th>Held since</th><th>Company</th><th>Role</th><th>Location</th><th class="num">Fit</th>
 <th>Note</th><th>Materials</th></tr></thead><tbody id="hbody"></tbody></table></div></section>
__GAPS__
</main>
<script type="application/json" id="data">__DATA__</script>
<script>
(function(){
var D=JSON.parse(document.getElementById('data').textContent), R=D.rows, H=D.holds||[], KEY='gmh-dashboard-filters';
var $=function(id){return document.getElementById(id)};
var ORDER=['applied','assessment','interviewing','offer','accepted','declined','rejected','withdrawn','no_response'];
var RESP={assessment:1,interviewing:1,offer:1,accepted:1,declined:1,rejected:1};
function cities(l){return (l||'').split(' \u00b7 ')[0].split('; ').filter(function(x){return x&&x.indexOf('Remote')!==0})}
function isRemote(l){return /remote/i.test(l||'')}
function uniq(a){var s={},o=[];a.forEach(function(x){if(x&&!s[x]){s[x]=1;o.push(x)}});return o.sort(function(a,b){return a.localeCompare(b)})}
function opts(sel,vals,label){sel.textContent='';var o=document.createElement('option');o.value='';o.textContent=label;sel.appendChild(o);
 vals.forEach(function(v){var e=document.createElement('option');e.value=v;e.textContent=v;sel.appendChild(e)})}
opts($('company'),uniq(R.map(function(r){return r.c}).concat(H.map(function(h){return h.c}))),'All companies');
opts($('loc'),uniq([].concat.apply([],R.map(function(r){return cities(r.l)}))),'All locations');
opts($('source'),uniq(R.map(function(r){return r.src})),'All sources');
opts($('tier'),uniq(R.map(function(r){return r.tier})).concat(['(none)']),'All tiers');
var present=ORDER.filter(function(s){return R.some(function(r){return r.s===s})});
var st={q:'',statuses:[],company:'',loc:'',remote:false,source:'',tier:'',fit:'',from:'',to:'',sort:'d',dir:-1};
try{var saved=JSON.parse(localStorage.getItem(KEY)||'null');if(saved)for(var k in st)if(k in saved)st[k]=saved[k]}catch(e){}
present.forEach(function(s){var b=document.createElement('button');b.className='chip';b.type='button';b.textContent=s.replace('_',' ');
 b.dataset.s=s;b.addEventListener('click',function(){var i=st.statuses.indexOf(s);if(i<0)st.statuses.push(s);else st.statuses.splice(i,1);draw()});
 $('statuses').appendChild(b)});
var F={q:'q',company:'company',loc:'loc',source:'source',tier:'tier',fit:'fit',from:'from',to:'to'};
Object.keys(F).forEach(function(k){var el=$(F[k]);el.value=st[k];el.addEventListener('input',function(){st[k]=el.value;draw()})});
$('remote').checked=st.remote;$('remote').addEventListener('change',function(){st.remote=$('remote').checked;draw()});
$('reset').addEventListener('click',function(){st.q=st.company=st.loc=st.source=st.tier=st.fit=st.from=st.to='';st.statuses=[];st.remote=false;
 Object.keys(F).forEach(function(k){$(F[k]).value=''});$('remote').checked=false;draw()});
document.querySelectorAll('#t th').forEach(function(th){th.addEventListener('click',function(){var k=th.dataset.k;
 if(st.sort===k)st.dir=-st.dir;else{st.sort=k;st.dir=(k==='d'||k==='sd'||k==='fit')?-1:1}draw()})});
function keep(r){
 if(st.statuses.length&&st.statuses.indexOf(r.s)<0)return false;
 if(st.company&&r.c!==st.company)return false;
 if(st.loc&&cities(r.l).indexOf(st.loc)<0)return false;
 if(st.remote&&!isRemote(r.l))return false;
 if(st.source&&r.src!==st.source)return false;
 if(st.tier&&(st.tier==='(none)'?r.tier:r.tier!==st.tier))return false;
 if(st.fit!==''&&!(r.fit!==null&&r.fit>=Number(st.fit)))return false;
 if(st.from&&r.d<st.from)return false;if(st.to&&r.d>st.to)return false;
 if(st.q){var q=st.q.toLowerCase();if([r.c,r.t,r.l,r.n,r.s,r.src].join(' ').toLowerCase().indexOf(q)<0)return false}
 return true}
function cmp(a,b){var x=a[st.sort],y=b[st.sort];if(x===null||x===undefined||x==='')return 1;if(y===null||y===undefined||y==='')return -1;
 return (typeof x==='number'?x-y:String(x).localeCompare(String(y)))*st.dir}
function td(row,label,text,cls){var c=document.createElement('td');if(label)c.dataset.label=label;if(cls)c.className=cls;
 if(text!==undefined&&text!==null)c.textContent=String(text);row.appendChild(c);return c}
function link(cell,href,text){var a=document.createElement('a');a.href=href;a.textContent=text;a.rel='noopener noreferrer';
 if(/^https?:/.test(href))a.target='_blank';cell.appendChild(a)}
function pill(cell,text,cls){var s=document.createElement('span');s.className='pill '+cls;s.textContent=text;cell.appendChild(s)}
function tile(label,value,note){var d=document.createElement('div');d.className='tile';var b=document.createElement('b');b.textContent=value;
 var s=document.createElement('span');s.textContent=label+(note?' \u00b7 '+note:'');d.appendChild(b);d.appendChild(s);$('tiles').appendChild(d)}
function draw(){
 try{localStorage.setItem(KEY,JSON.stringify(st))}catch(e){}
 document.querySelectorAll('#statuses .chip').forEach(function(b){b.setAttribute('aria-pressed',st.statuses.indexOf(b.dataset.s)>=0)});
 document.querySelectorAll('#t th').forEach(function(th){th.setAttribute('aria-sort',th.dataset.k===st.sort?(st.dir>0?'ascending':'descending'):'none')});
 var rows=R.filter(keep).sort(cmp), n=rows.length;
 var cnt=function(f){return rows.filter(f).length};
 var resp=cnt(function(r){return RESP[r.s]});
 $('tiles').textContent='';
 tile('applications',n);tile('interviewing',cnt(function(r){return r.s==='interviewing'||r.s==='assessment'||r.s==='offer'}),'incl. assessments, offers');
 tile('rejected',cnt(function(r){return r.s==='rejected'}));tile('response rate',n?Math.round(100*resp/n)+'%':'\u2013',resp+' of '+n+' heard back');
 tile('follow-ups due',cnt(function(r){return r.due}),'10+ quiet days');tile('stale',cnt(function(r){return r.stale}),'60+ days at applied');
 var held=H.filter(keepHold),old=held.filter(function(h){return h.old}).length;
 tile('on hold',held.length,old?old+' held 14+ days':'not applied yet');
 drawHolds(held);
 $('count').textContent='Showing '+n+' of '+R.length+' application'+(R.length===1?'':'s');
 var body=$('body');body.textContent='';
 if(!n){var tr=document.createElement('tr'),c=td(tr,'',R.length?'No applications match these filters.':'No applications yet. They appear here once tracker.csv has rows.','empty');
  c.colSpan=10;body.appendChild(tr);return}
 rows.forEach(function(r){var tr=document.createElement('tr');
  td(tr,'Applied',r.d,'nw');td(tr,'Company',r.c);
  var role=td(tr,'Role');if(r.u)link(role,r.u,r.t);else role.textContent=r.t;
  td(tr,'Location',r.l||'\u2013',r.l?'':'muted');
  var s=td(tr,'Status');pill(s,r.s.replace('_',' '),'p-'+r.s);if(r.due){s.appendChild(document.createTextNode(' '));pill(s,'follow up','flag')}
  if(r.stale){s.appendChild(document.createTextNode(' '));pill(s,'stale','flag')}
  td(tr,'Since',r.sd,'nw');td(tr,'Fit',r.fit===null?'\u2013':r.fit+(r.tier?' '+r.tier:''),'num');
  td(tr,'LinkedIn',(r.li?r.li.replace('_',' '):'\u2013')+(r.lic?' \u00b7 '+r.lic+' sent':''),r.li?'':'muted');
  td(tr,'Source',r.src);var m=td(tr,'Materials');if(r.f)link(m,r.f,'folder');else{m.textContent='\u2013';m.className='muted'}
  body.appendChild(tr)})}
function keepHold(h){
 if(st.company&&h.c!==st.company)return false;
 if(st.q){var q=st.q.toLowerCase();if([h.c,h.t,h.l,h.n,'hold'].join(' ').toLowerCase().indexOf(q)<0)return false}
 return true}
function drawHolds(held){
 $('holds').hidden=!H.length;if(!H.length)return;
 $('hcount').textContent='Showing '+held.length+' of '+H.length+' hold'+(H.length===1?'':'s');
 var body=$('hbody');body.textContent='';
 if(!held.length){var tr=document.createElement('tr'),c=td(tr,'','No holds match these filters.','empty');c.colSpan=7;body.appendChild(tr);return}
 held.forEach(function(h){var tr=document.createElement('tr');
  var s=td(tr,'Held since',h.since+(h.days!==null&&h.days!==undefined?' \u00b7 '+h.days+'d':''),'nw');
  if(h.old){s.appendChild(document.createTextNode(' '));pill(s,'held a while','flag')}
  td(tr,'Company',h.c);var role=td(tr,'Role');if(h.u)link(role,h.u,h.t);else role.textContent=h.t;
  td(tr,'Location',h.l||'\u2013',h.l?'':'muted');td(tr,'Fit',h.fit===null||h.fit===undefined?'\u2013':h.fit+(h.tier?' '+h.tier:''),'num');
  td(tr,'Note',h.n||'\u2013',h.n?'':'muted');
  var m=td(tr,'Materials');if(h.f)link(m,h.f,'folder');else{m.textContent='no folder';m.className='muted'}
  body.appendChild(tr)})}
draw()})();
</script></body></html>"""
