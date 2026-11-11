// One-page cover letter .docx whose header matches the resume. Name, contact lines and sign-off come from the profile.
// Usage: NODE_PATH=<dir with docx> node tools/cover_letter.js <in.json> <out.docx>
// in.json: { "name": "JORDAN RIVERA", "signoff": "Jordan Rivera", "contact": ["line", "line"],
//            "company": "...", "date": "October 19, 2026", "paragraphs": ["...", "..."], "design": { ...tokens } }
// Fonts, colors, name and contact sizes are the resume's tokens; the rest is under design.cover_letter (tools/design.js).
const { Document, Packer, Paragraph, TextRun, AlignmentType, convertInchesToTwip } = require('docx');
const fs = require('fs');
const { load, tw, hp, lines, hex } = require('./design');

const inp = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const T = load(inp.design);
const L = T.cover_letter;
const SP = Object.fromEntries(Object.entries(L.spacing_pt).map(([k, v]) => [k, tw(v)]));
const SERIF = T.fonts.heading, SANS = T.fonts.body, DARK = hex(T.colors.text), MED = hex(T.colors.secondary);
const p = (text, opts = {}) => new Paragraph({
  spacing: { after: opts.after ?? SP.paragraph_after, line: lines(L.line_height) }, alignment: opts.align,
  children: [new TextRun({ text, size: opts.size ?? hp(L.body_size_pt), font: opts.font ?? SANS, color: opts.color ?? DARK, bold: opts.bold, characterSpacing: opts.cs })],
});

const children = [
  p(inp.name, { size: hp(T.sizes_pt.name), font: SERIF, color: hex(T.colors.name), bold: T.bold.name ? true : undefined,
    cs: T.letter_spacing_pt.name ? tw(T.letter_spacing_pt.name) : undefined, align: AlignmentType.CENTER, after: SP.name_after }),
  ...inp.contact.map((line, i) => p(line, { size: hp(T.sizes_pt.contact), color: MED, align: AlignmentType.CENTER,
    after: i < inp.contact.length - 1 ? SP.contact_between : SP.header_after })),
  p(inp.date, { after: SP.date_after }),
  p(`Dear ${inp.company} hiring team,`, { after: SP.greeting_after }),
  ...inp.paragraphs.map(t => p(t, { after: SP.paragraph_after })),
  p('Sincerely,', { after: SP.closing_after }),
  p(inp.signoff, { after: 0 }),
];

const M = L.margins_pt;
const doc = new Document({ sections: [{ properties: { page: {
  size: { width: convertInchesToTwip(T.page.width_in), height: convertInchesToTwip(T.page.height_in) },
  margin: { top: tw(M.top), right: tw(M.right), bottom: tw(M.bottom), left: tw(M.left) } } }, children }] });
Packer.toBuffer(doc).then(b => fs.writeFileSync(process.argv[3], b));
