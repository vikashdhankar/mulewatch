# MuleWatch for cyber police: how a case moves

This guide is for officers using the command center. It follows one case from the moment an ad is found to the
moment it is linked to an FIR.

MuleWatch prepares leads, drafts and evidence. **It never acts on its own**: every notice, letter and
certificate is a draft for an authorised officer to check, complete and sign, and every flag needs a person to
verify it.

---

## 1. Who can do what

| Role | Typical user | Can |
|---|---|---|
| **Analyst** | Data analyst, constable on the monitoring desk | See cases, record verdicts (Confirm fraud / False positive), add to the watchlist, check posts. Phone and account numbers appear partly hidden (`98•••••736`). |
| **Investigating Officer (IO)** | SI / ASI handling cases | Everything an analyst can, plus: take cases, move them through the workflow, see full numbers and complaint details, import complaints, draft notices and letters, download evidence. |
| **Supervisor** | SHO / ACP / SP | Everything an IO can, plus: assign cases to anyone, add and disable officers, read and export the audit log, get the daily brief. |

Supervisors add officers on the **Officers** page. A new officer gets a temporary password and must choose their
own at first sign-in. Disabling an account or changing a role signs that person out everywhere.

The demo accounts (`analyst`, `io`, `sho`, password `mule@2026`) are for trying the system. A banner reminds
supervisors while they are active; disable them before real use (or start with `MW_DEMO_USERS=0`).

---

## 2. The case lifecycle

```
NEW ──▶ VERIFIED ──▶ NOTICE DRAFTED ──▶ NOTICE SENT ──▶ CONTENT REMOVED ──▶ LINKED TO FIR
 │         │               │                (3 h clock)          │
 └─────────┴───────────────┴──────────▶ CLOSED – NO ACTION ◀─────┘
```

| Status | Meaning | How it is set |
|---|---|---|
| **New** | Found by MuleWatch, not looked at yet | Automatically |
| **Verified** | An IO has checked the ad and it needs action | *Mark verified* |
| **Notice drafted** | A takedown or preservation notice has been prepared | Automatically when a takedown/preservation draft is downloaded from a Verified case, or by hand |
| **Notice sent** | The notice has been filed (Sahyog portal) | *Mark notice sent* — **starts the 3-hour clock** |
| **Content removed** | The platform removed the content | *Mark content removed*; MuleWatch then watches for it to come back |
| **Linked to FIR** | Part of a registered case | *Mark linked to FIR* (enter the FIR number first) |
| **Closed – no action** | Not actionable | From any open stage; can be reopened |

On the case page, **Case workflow** shows the steps, who the case is assigned to, the FIR number, the police
station and free-text case notes. An IO can *Take this case*; a supervisor assigns from a list.

Find work with the filters on **Cases**: *Open cases*, *Assigned to me*, *Linked to complaints*, and the sort
*Recruiters first*.

---

## 3. Triage: what to look at first

* **Linked to complaints** — the ad uses a phone number, UPI ID, account or handle that appears in a victim complaint.
  These cases are scored at least 90 and show the money lost.
* **Recruiter priority** (0–100) — bulk recruiters and resellers rank above a person selling one account (often a
  victim themselves). Signals: recruiting account holders, commission or per-account pay, agents/bulk, many ads by
  the same author, ring size, several different contact numbers, complaint links.
* **Back after takedown** — content linked to a case that was removed, seen again afterwards. Consider acting on the
  account rather than the post.
* **Seller rings** — posts linked by the same phone/UPI/handle, near-identical text or the same image.

---

## 4. Victim complaints (NCRP / 1930)

**Victim complaints → Import complaints** (IO and above).

1. Export complaints from your system as CSV or Excel. Any column layout works.
2. Upload it. MuleWatch suggests what each column is; check the dropdowns. Columns about the victim (name, mobile,
   address) are left on *Don't import* and there is no field to map them to.
3. Import. Re-importing the same complaints is safe: they are skipped by complaint number.

What is stored: the complaint date, amount and district in readable form (for statistics); everything else
encrypted. Suspect identifiers are stored only as keyed hashes, which is how ads are matched without decrypting.
Analysts see that a case is linked and the amount; complaint numbers and details are visible to IOs and supervisors,
and each view is recorded in the audit log.

The encryption key is in `backend/data/keys/`. **Back it up with the database**; without it the complaints can't
be read. A supervisor can delete an import (and all its complaints) when it is no longer needed.

Try it with `docs/samples/sample_ncrp_complaints.csv` (made-up data that matches the demo forum's seller rings).

---

## 5. Legal drafts

On the case page, **Legal drafts** (IO and above):

| Draft | Use |
|---|---|
| Takedown notice | Notice under Section 79(3)(b) IT Act to the platform, to file on the **Sahyog** portal. Linked High/Critical posts on the same platform are listed on the same notice. |
| Data preservation request | Asks the platform to preserve the account's records and logs for 180 days (Rule 3(1)(g)) before a formal request for disclosure. |
| Request to the bank | Letter to the nodal officer of each bank or payment app involved: KYC, statements, access logs, linked accounts, and a lien on the disputed amount for linked complaints. |
| Section 63 BSA certificate | Certificate for the captured records under Section 63(4) of the Bharatiya Sakshya Adhiniyam, 2023, with Part A (officer) and Part B (expert, with SHA-256 hashes). |

Each draft opens in an editor in **English or Hindi**. Fields to fill or confirm are marked `[[ … ]]` and
counted at the top; they are highlighted in yellow in the downloaded file. Download **Word** to edit further or
**PDF** to print. Every file carries the watermark *"DRAFT — to be reviewed and signed by the authorised officer"*
and every download is recorded with the file's hash.

The legal references in the templates are a starting point. Confirm the applicable sections, the authorised
signatory and the takedown timeline before sending. Two points to note:

* A **debit freeze** needs a Magistrate's order under Section 107 BNSS (Bombay High Court, 20 Nov 2025); the bank
  letter asks only for information, review and a lien on disputed amounts.
* The Supreme Court upheld Section 63(4) BSA in May 2026 but left open exactly who may sign Part B.

To change the standard wording for your unit, copy a template from `backend/app/templates/legal/` to
`backend/data/templates/legal/` and edit the copy (see the README in that folder).

---

## 6. The takedown clock

When a case is marked **Notice sent**, a clock starts for the platform's removal window (3 hours under the IT Rules
amendment notified in February 2026; change `TAKEDOWN_WINDOW_HOURS` in `.env` if the rule changes).

* The case page and the command center show the time left.
* 30 minutes before the end, an alert goes to the dashboard, the unit's Telegram alert chat, the assigned officer
  and supervisors (if they linked Telegram).
* If the window runs out without removal, an *overdue* alert goes out once: escalate or record non-compliance.
* When the case is marked **Content removed**, the clock stops and records whether the platform met the window.
  The daily brief shows each platform's average removal time.

In the demo, **Remove via forum API** on a Charcha forum post plays the platform's part: the post is hidden on the
forum and the case moves to *Content removed*.

---

## 7. Banks, UPI and jurisdiction

**Banks and payment apps** groups the case's financial identifiers by the institution that can act on them:

* **IFSC** → bank and branch (city, district, state) from the bundled list of about 1.8 lakh branches. Refresh it
  with `cd backend && ../.venv/bin/python -m app.banks --update`.
* **UPI ID** → the app and its sponsor bank (e.g. `@ybl` → PhonePe / Yes Bank). The sponsor bank can tell which
  account, at any bank, the UPI ID is linked to. The map is in `backend/app/refdata/upi_handles.json`; check it
  against NPCI's list from time to time.
* **Account number** → grouped with the IFSC from the same post, if there is exactly one.

**Suggested jurisdiction** names a district and its cyber police station, from the IFSC branch district and places
named in the ad (district names, towns, localities, Hindi names, and short forms in handles such as `_jpr`). It is
always approximate. Each mobile number also gets the **telecom circle** its series was first allotted to
(`backend/app/refdata/phone_series.json`, about 2,000 four-digit series). A number from outside the Rajasthan
circle suggests routing through I4C or that state's cyber cell. Ported numbers make this a weak signal, so it is
shown as a hint and never decides the district.

**District map** shows High/Critical cases per Rajasthan district (41 districts after the December 2024
reorganisation), and how many case mobile numbers come from each telecom circle. The map tiles need internet; the
district list works offline.

---

## 8. Evidence and chain of custody

For every captured post MuleWatch stores, under `backend/data/evidence/MW-<case>/`:

* `capture.txt` — the text as observed, with platform, URL, author and capture time (UTC and IST)
* `page.html` — the page as the server returned it
* the attached image
* a full-page **screenshot** of High/Critical cases with a public URL, if Playwright is installed

Each file's SHA-256 is recorded at capture. The **Evidence** panel re-checks the files and shows *unchanged since
capture* (or which file changed). **Evidence pack (ZIP)** gives you all files, the evidence report, a draft Section
63 certificate, `manifest.json` with every hash and `chain_of_custody.csv` (every capture, view and export of the
case from the audit log). Check a file with `sha256sum` (Windows: `certutil -hashfile <file> SHA256`).

---

## 9. Audit log

**Audit log** (supervisors) lists sign-ins (and failed attempts), case views, searches, verdicts, status changes,
assignments, complaint imports and views, draft and evidence exports, user changes and system captures, with
filters by officer, action and case, and CSV export.

Each entry includes the hash of the one before it. The page checks the whole chain on load: *Chain intact* means
no entry was changed or removed; otherwise it shows where the chain breaks. The database itself refuses to update
or delete audit entries.

---

## 10. Daily brief and Telegram

**Daily brief** (supervisors): one page in English or Hindi with new and critical cases, cases linked to complaints
and the amount, active rings, notices sent, content removed, overdue takedowns, reappearances, each platform's
removal times, the top open cases by recruiter priority, the most-seen identifiers and cases by district.
Choose a district to get a brief for that district's cases only (for an SHO or district SP); the scheduled brief
covers all districts.

It is sent automatically at `DAILY_BRIEF_TIME` (IST, default 09:00) through the Telegram bot to every supervisor
who has linked Telegram. To link: **your name → My account → Link Telegram**, then send `/officer <code>` to
the bot. Officers who link Telegram also get takedown-clock alerts for cases assigned to them.

---

## 11. Bulk link check and Hindi

**Bulk link check** (any officer): paste links collected from complaints, patrolling, tips or other units, one per
line, or upload a TXT, CSV or Excel file. Words on the same line as a link (a complaint number, where it was found)
are kept as the officer's note and shown in the case. Links are opened one at a time in the background, exactly as
**Check a post** does; links that are already cases are reported as such instead of being added again. The list
page shows progress and the High/Critical results, and when the list is done one Telegram summary goes to the
unit's alert chat and to the officer who started it. Any officer can stop their own list; IOs and supervisors can
stop any list.

**Hindi**: the **EN / हिं** switch in the top bar (and on the sign-in page) changes every screen to Hindi; the choice
is remembered in that browser. Legal drafts and the daily brief have their own language choice. Reasons and notes
that the detection engine writes for each case stay in English. Translations live in
`frontend/scripts/hi_source.py`; edit there and run it to regenerate `frontend/src/hi.json`, then rebuild.

---

## 12. Settings (`.env`)

| Setting | Default | |
|---|---|---|
| `MW_DEMO_USERS` | `1` | Create the demo accounts on first start |
| `SESSION_HOURS` | `12` | How long a sign-in lasts |
| `MW_INGEST_KEY` | empty | Key the Chrome extension uses to submit posts |
| `TAKEDOWN_WINDOW_HOURS` / `TAKEDOWN_WARN_MINUTES` | `3` / `30` | Removal window and early warning |
| `DAILY_BRIEF_TIME` / `DAILY_BRIEF_LANG` / `DAILY_BRIEF_TELEGRAM` | `09:00` / `en` / `1` | Daily brief schedule |
| `MW_SCREENSHOTS` | `1` | Full-page screenshots when Playwright is installed |
| `BULK_MAX_LINKS` / `BULK_PAUSE_SECONDS` | `500` / `1.5` | Links per bulk list, and the pause between links |
| `MW_SECRET` / `MW_DATA_KEY` | generated | Session signing key and complaint encryption key (otherwise in `backend/data/keys/`) |
