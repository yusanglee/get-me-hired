// Font probe: one small .docx per font (regular, bold and italic runs), so a PDF conversion shows which fonts
// LibreOffice really embeds. Usage: NODE_PATH=<dir with docx> node tools/font_probe.js <out_dir> <font> [<font> ...]
// Writes <out_dir>/<n>.docx for the n-th font (0-based).
const { Document, Packer, Paragraph, TextRun } = require('docx');
const fs = require('fs');
const path = require('path');

const [outDir, ...fonts] = process.argv.slice(2);
const sample = 'Product Manager 2024 - Present grew repeat purchases 40% across 12 markets';
Promise.all(fonts.map((font, i) => Packer.toBuffer(new Document({ sections: [{ children: [
  new Paragraph({ children: [new TextRun({ text: sample, font, size: 20 })] }),
  new Paragraph({ children: [new TextRun({ text: sample, font, size: 20, bold: true })] }),
  new Paragraph({ children: [new TextRun({ text: sample, font, size: 20, italics: true })] }),
] }] })).then(b => fs.writeFileSync(path.join(outDir, `${i}.docx`), b)))).then(() => console.log('ok'));
