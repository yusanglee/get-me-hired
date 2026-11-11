// Generic resume renderer: JSON resume document -> ATS-safe .docx (no tables, columns, text boxes, headers).
// Usage: NODE_PATH=<dir with the docx package> node tools/resume.js <resume.json> <out.docx>
//
// The JSON is built by engine/resume.py (render_payload): { name, bio, contact: [lines], summary,
// experience: [{ role, dates, company, location, scope, bullets: [] }], skills, education: [{ school, degree, years }],
// extra_sections: [{ heading, text }], design: { ...tokens } }.
// Every design value comes from tools/design.js: templates/design.json, overridden by the payload's design
// (the workspace design.json). The defaults are templates/design.json.
const { Document, Packer, Paragraph, TextRun, AlignmentType, BorderStyle,
        LevelFormat, Tab, TabStopType, convertInchesToTwip } = require('docx');
const fs = require('fs');
const { load, tw, hp, lines, hex } = require('./design');

const R = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = process.argv[3];
const T = load(R.design);
const F = { head: T.fonts.heading, body: T.fonts.body };
const C = Object.fromEntries(Object.entries(T.colors).map(([k, v]) => [k, hex(v)]));
const S = Object.fromEntries(Object.entries(T.sizes_pt).map(([k, v]) => [k, hp(v)]));
const SP = Object.fromEntries(Object.entries(T.spacing_pt).map(([k, v]) => [k, tw(v)]));
const LINE = lines(T.line_height);
const SEP = T.separator;
const on = (x) => (x ? true : undefined);   // leave formatting off the run when a token turns it off
const cs = (pt) => (pt ? tw(pt) : undefined);
const RIGHT_DATES = T.dates.align === 'right';
const TABS = RIGHT_DATES ? [{ type: TabStopType.RIGHT, position: tw(T.dates.tab_pt) }] : undefined;

// Dates sit on a right tab stop, or inline after the separator.
const dated = (runs, text, size) => RIGHT_DATES
  ? [...runs, new TextRun({ children: [new Tab()] }), new TextRun({ text, size, font: F.body, color: C.muted })]
  : [...runs, new TextRun({ text: SEP + text, size, font: F.body, color: C.muted })];

// Bold is weight only, no colour shift: **span** inside any text.
const rich = (text, { size = S.body, font = F.body, color = C.text } = {}) =>
  text.split(/(\*\*[^*]+\*\*)/g).filter(Boolean).map(seg =>
    seg.startsWith('**')
      ? (T.bold.inline ? new TextRun({ text: seg.slice(2, -2), bold: true, size, font, color: C.text })
                       : new TextRun({ text: seg.slice(2, -2), size, font, color }))
      : new TextRun({ text: seg, size, font, color }));

const sectionHeading = (t) => new Paragraph({
  spacing: { before: SP.section_before, after: SP.section_after },
  border: T.section_rule.show
    ? { bottom: { style: BorderStyle.SINGLE, size: Math.round(T.section_rule.weight_pt * 8), color: C.rule, space: T.section_rule.gap_pt } }
    : undefined,
  children: [new TextRun({ text: t, bold: on(T.bold.section), size: S.section, font: F.head, color: C.section, characterSpacing: cs(T.letter_spacing_pt.section) })],
});

const roleLine = (role, dates) => new Paragraph({
  spacing: { before: SP.role_before, after: 0 }, tabStops: TABS, keepNext: true,
  children: dated([new TextRun({ text: role, bold: on(T.bold.role), size: S.role, font: F.body, color: C.text })], dates, S.body),
});

const companyLine = (company, location) => new Paragraph({
  spacing: { before: 0, after: SP.company_after }, keepNext: true,
  children: [
    new TextRun({ text: company, size: S.body, font: F.body, italics: on(T.italic.company), color: C.text }),
    new TextRun({ text: `${SEP}${location}`, size: S.body, font: F.body, italics: on(T.italic.company), color: C.muted }),
  ],
});

const scopeLine = (t) => new Paragraph({
  spacing: { before: 0, after: SP.scope_after, line: LINE }, keepNext: true, children: rich(t, { color: C.secondary }),
});

const bullet = (t) => new Paragraph({
  numbering: { reference: 'rb', level: 0 }, spacing: { before: 0, after: SP.bullet_after }, children: rich(t),
});

const c = [];
c.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: SP.name_after },
  children: [new TextRun({ text: R.name, bold: on(T.bold.name), size: S.name, font: F.head, color: C.name, characterSpacing: cs(T.letter_spacing_pt.name) })] }));
if (R.bio) c.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: SP.bio_after },
  children: [new TextRun({ text: R.bio, size: S.body, font: F.head, color: C.muted })] }));
R.contact.forEach((line, i) => c.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: i < R.contact.length - 1 ? SP.contact_between : 0 },
  children: [new TextRun({ text: line, size: S.contact, font: F.body, color: C.secondary })] })));
c.push(sectionHeading('EXECUTIVE SUMMARY'));
c.push(new Paragraph({ spacing: { after: SP.summary_after, line: LINE }, children: rich(R.summary) }));
c.push(sectionHeading('PROFESSIONAL EXPERIENCE'));
for (const x of R.experience) {
  c.push(roleLine(x.role, x.dates));
  c.push(companyLine(x.company, x.location));
  if (x.scope) c.push(scopeLine(x.scope));
  x.bullets.forEach(t => c.push(bullet(t)));
}
c.push(sectionHeading('SKILLS'));
c.push(new Paragraph({ spacing: { after: SP.skills_after, line: LINE }, children: rich(R.skills) }));
c.push(sectionHeading('EDUCATION'));
// Text width in points, from Helvetica/Arial advance widths (1/1000 em, ASCII 32..126; anything else 600).
// Bold runs count 7% wider and the total gets a 3% margin, so an estimate errs toward "won't fit".
const W = [278,278,355,556,556,889,667,191,333,333,389,584,278,333,278,278,556,556,556,556,556,556,556,556,556,556,278,278,584,584,584,556,
  1015,667,667,722,722,667,611,778,722,278,500,667,556,833,722,778,667,778,722,667,611,722,667,944,667,667,611,278,278,278,469,556,
  333,556,556,500,556,556,278,556,556,222,222,500,222,833,556,556,556,556,333,500,278,556,500,722,500,500,500,334,260,334,584];
const textPt = (t, pt, bold) => 1.03 * (bold ? 1.07 : 1) * pt *
  [...String(t)].reduce((a, ch) => a + (ch.charCodeAt(0) >= 32 && ch.charCodeAt(0) <= 126 ? W[ch.charCodeAt(0) - 32] : 600), 0) / 1000;
const MIN_GAP_PT = 12;
// "school · degree" plus the right-aligned dates on one line, or does the line need to be split?
const eduFits = (school, degree, years) => !RIGHT_DATES ||
  textPt(school, T.sizes_pt.body, T.bold.school) + textPt(`${SEP}${degree}`, T.sizes_pt.body, false) +
  textPt(years, T.sizes_pt.body, false) + MIN_GAP_PT <= T.dates.tab_pt;

R.education.forEach(({ school, degree, years }, i) => {
  const after = i < R.education.length - 1 ? SP.education_between : 0;
  if (eduFits(school, degree, years)) {
    c.push(new Paragraph({ spacing: { after }, tabStops: TABS, children: dated([
      new TextRun({ text: school, bold: on(T.bold.school), size: S.body, font: F.body, color: C.text }),
      new TextRun({ text: `${SEP}${degree}`, size: S.body, font: F.body, color: C.muted }),
    ], years, S.body) }));
  } else {   // too long for one line: school and dates on line 1, the degree on its own line 2
    c.push(new Paragraph({ spacing: { after: 0 }, tabStops: TABS, keepNext: true, children: dated([
      new TextRun({ text: school, bold: on(T.bold.school), size: S.body, font: F.body, color: C.text }),
    ], years, S.body) }));
    c.push(new Paragraph({ spacing: { after }, children: [
      new TextRun({ text: degree, size: S.body, font: F.body, color: C.muted }),
    ] }));
  }
});
for (const s of R.extra_sections || []) {
  c.push(sectionHeading(s.heading));
  c.push(new Paragraph({ spacing: { after: 0, line: LINE }, children: rich(s.text) }));
}

const M = T.page.margins_pt;
const doc = new Document({
  numbering: { config: [{ reference: 'rb', levels: [{
    level: 0, format: LevelFormat.BULLET, text: T.bullet.glyph, alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: convertInchesToTwip(T.bullet.indent_in), hanging: convertInchesToTwip(T.bullet.hanging_in) } } },
  }]}]},
  sections: [{ properties: { page: {
    size: { width: convertInchesToTwip(T.page.width_in), height: convertInchesToTwip(T.page.height_in) },
    margin: { top: tw(M.top), right: tw(M.right), bottom: tw(M.bottom), left: tw(M.left) } } }, children: c }],
});

Packer.toBuffer(doc).then(b => { fs.writeFileSync(out, b); console.log('written ' + out); });
