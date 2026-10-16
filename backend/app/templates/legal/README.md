# Legal draft templates

MuleWatch fills these templates for a case and the officer edits the result in the command center before
downloading it as Word or PDF. To change the standard wording for your unit, copy a template to
`backend/data/templates/legal/` (same file name) and edit the copy there: files in that folder take priority
and are not overwritten by updates.

Templates are [Jinja2](https://jinja.palletsprojects.com/). The output uses a small line format:

| Line starts with | Becomes |
|---|---|
| `# ` | Document title (centred, bold) |
| `## ` | Section heading |
| `>> ` | Right-aligned line (reference number, date) |
| `- ` | Bullet point |
| `| a | b |` | Table row; a following `|---|` line makes the row above it a header |
| `~~` | Signature block (each following line until a blank line) |
| anything else | Paragraph (`**bold**` works inside) |

`[[ ... ]]` marks something the officer must fill in or confirm; it is highlighted in yellow in the Word and PDF
files so nothing is sent with a blank.

Files: `takedown_en.j2`, `takedown_hi.j2` (notice to the platform under Section 79(3)(b) IT Act, to be filed
through the Sahyog portal), `preservation_en.j2`, `preservation_hi.j2` (data preservation request),
`bank_en.j2`, `bank_hi.j2` (request to a bank's nodal officer), `bsa63_en.j2`, `bsa63_hi.j2` (certificate
for electronic records under Section 63(4) of the Bharatiya Sakshya Adhiniyam, 2023).

Every draft carries the watermark "DRAFT — to be reviewed and signed by the authorised officer". The legal
references in these templates are a starting point, not legal advice: the officer confirms the applicable
sections, the current takedown timeline and the authorised signatory before anything is sent.
