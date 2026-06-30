/**
 * gmail-ingest.gs — feed labeled Gmail into the obagent pipeline, via Drive.
 *
 * Runs as a time-driven Apps Script (script.google.com), authorized with your
 * own Gmail + Drive scopes — so there are NO credentials anywhere on the NAS.
 * Each firing:
 *   1. takes a script lock (no overlapping runs)
 *   2. finds threads labeled `obagent/inbox`
 *   3. for each *not-yet-processed* message: routes it to a document type, renders
 *      the body to a PDF and pulls every (non-inline) attachment, and writes them
 *      into  consume/<Type>/  on Drive (e.g. consume/Receipts/)
 *   4. dequeues the thread (-obagent/inbox +obagent/ingested)
 *
 * The consume folder is the Drive side of the NAS consume inbox (Synology Cloud
 * Sync, two-way). obagent's normal `consume` ingests <Type>/ files and MOVES them
 * out, so the local delete propagates back up and drains the Drive folder. Email
 * therefore rides the existing inbox — no dedicated folder, no extra obagent wiring.
 *
 * Dedup is the per-message processed-id set (PROP_KEY), NOT the labels — Gmail
 * labels are thread-level, so a reply re-surfaces a thread and we must skip the
 * messages already exported. The label swap only keeps each search() batch small.
 * See plan-email-ingest.md → "Dedup — robust design".
 *
 * SETUP: paste into a new Apps Script project, set the CONSUME_FOLDER_ID script
 * property (Project Settings → Script Properties) to your Drive consume/ folder id,
 * add a time-driven trigger on ingestEmail() (~every 15 min), authorize when
 * prompted. Keeping the id in a script property (not a code const) keeps this
 * deploy-specific value out of the public repo and survives re-pasting the code.
 */

// ── Config ──────────────────────────────────────────────────────────────────
const FOLDER_ID_PROP  = 'CONSUME_FOLDER_ID';   // script property: id of the Drive consume/ folder (parent of the per-type subdirs)
const SEARCH_QUERY    = 'label:obagent/inbox';  // threads to process (nested label — full path is obagent/inbox)
const LABEL_INBOX     = 'obagent/inbox';        // removed when a thread is done (dequeue)
const LABEL_DONE      = 'obagent/ingested';     // added when a thread is done (audit trail)

// Per-type routing: a message whose "<from> <subject>" matches the receipt pattern
// goes to consume/Receipts/; everything else falls through to DEFAULT_TYPE
// (consume/Documents/). The folder name must match obagent's vault subdir. Edit freely.
const ROUTING_RULES = [
  { type: 'Receipts', pattern: /receipt|invoice|order (confirmation|#)|your order/i },
];
const DEFAULT_TYPE = 'Documents';

const MAX_THREADS    = 25;   // per run — bounds work under the ~6-min execution cap
const MAX_IDS        = 400;  // processed-message-id ring buffer (PropertiesService caps a value at 9 KB)
const PROP_KEY       = 'PROCESSED_IDS';
const SUBJECT_MAXLEN = 120;  // cap the subject portion of a filename

// ── Entry point — set the time-driven trigger on THIS function ───────────────
function ingestEmail() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(0)) {
    console.log('another run holds the lock — skipping');
    return;
  }
  try {
    run_();
  } finally {
    lock.releaseLock();
  }
}

function run_() {
  const folderId = PropertiesService.getScriptProperties().getProperty(FOLDER_ID_PROP);
  if (!folderId) {
    throw new Error('Set the ' + FOLDER_ID_PROP + ' script property (Project Settings → '
      + 'Script Properties) to the Drive consume/ folder id.');
  }
  const consumeFolder = DriveApp.getFolderById(folderId);
  const processed = loadProcessed_();          // Set<string> of message ids, insertion-ordered
  const threads = GmailApp.search(SEARCH_QUERY, 0, MAX_THREADS);

  let exported = 0;
  for (const thread of threads) {
    try {
      for (const message of thread.getMessages()) {
        const id = message.getId();
        if (processed.has(id)) continue;        // primary dedup — already exported

        exportMessage_(message, consumeFolder); // body PDF + attachments → consume/<Type>/
        processed.add(id);
        saveProcessed_(processed);              // persist incrementally: a crash only risks the in-flight message
        exported++;
      }
      // Whole thread done: dequeue it. (Only here — a mid-thread failure leaves
      // obagent/inbox on, so the next run retries and the id-set skips what's done.)
      dequeue_(thread);
    } catch (err) {
      // One bad thread must not stall the batch. It keeps obagent/inbox and retries.
      console.error('thread "' + safeSubject_(thread) + '" failed: ' + err);
    }
  }
  console.log('done — ' + exported + ' message(s) exported from ' + threads.length + ' thread(s)');
}

// ── Per-message export ───────────────────────────────────────────────────────
function exportMessage_(message, consumeFolder) {
  const prefix = filenamePrefix_(message);                     // "2026-06-28 0930 - ACME invoice"
  const folder = subfolder_(consumeFolder, typeFor_(message)); // consume/Receipts, consume/Documents, ...

  // Body → PDF (basic fidelity; the real document is usually the attachment, but
  // for many receipts the body IS the receipt). Always produced — body-PDF dedup
  // rests entirely on the id-set since getAs() is not byte-stable, so obagent's
  // sha backstop can't catch a re-render.
  const html = message.getBody() || '';
  const bodyPdf = Utilities.newBlob(html, 'text/html', prefix + '.html')
    .getAs('application/pdf')
    .setName(prefix + '.pdf');
  folder.createFile(bodyPdf);

  // Attachments — exclude inline images (signatures, logos) so they don't each
  // become a note. Keep each attachment's native name + extension (a .jpg invoice
  // must stay a .jpg for OCR — do NOT force .pdf).
  const attachments = message.getAttachments({ includeInlineImages: false });
  for (const att of attachments) {
    const name = prefix + ' - ' + sanitize_(att.getName());
    folder.createFile(att.copyBlob().setName(name));
  }
}

// ── Routing ──────────────────────────────────────────────────────────────────
function typeFor_(message) {
  const hay = (message.getFrom() || '') + ' ' + (message.getSubject() || '');
  for (const rule of ROUTING_RULES) {
    if (rule.pattern.test(hay)) return rule.type;
  }
  return DEFAULT_TYPE;
}

function subfolder_(parent, name) {
  const existing = parent.getFoldersByName(name);
  return existing.hasNext() ? existing.next() : parent.createFolder(name);
}

// ── Filenames ────────────────────────────────────────────────────────────────
function filenamePrefix_(message) {
  const stamp = Utilities.formatDate(message.getDate(), Session.getScriptTimeZone(), 'yyyy-MM-dd HHmm');
  let subject = sanitize_(message.getSubject() || '(no subject)');
  if (subject.length > SUBJECT_MAXLEN) subject = subject.slice(0, SUBJECT_MAXLEN).trim();
  return stamp + ' - ' + subject;
}

function sanitize_(name) {
  return String(name)
    .replace(/[\/\\:*?"<>|\x00-\x1f]/g, ' ') // filesystem-unfriendly + control chars
    .replace(/\s+/g, ' ')
    .trim() || 'untitled';
}

function safeSubject_(thread) {
  try { return thread.getFirstMessageSubject() || '(no subject)'; }
  catch (e) { return '(unknown)'; }
}

// ── Label dequeue ────────────────────────────────────────────────────────────
function dequeue_(thread) {
  const inbox = GmailApp.getUserLabelByName(LABEL_INBOX);
  let done = GmailApp.getUserLabelByName(LABEL_DONE);
  if (!done) done = GmailApp.createLabel(LABEL_DONE);
  if (inbox) thread.removeLabel(inbox);
  thread.addLabel(done);
}

// ── Processed-id set (PropertiesService) ─────────────────────────────────────
function loadProcessed_() {
  const raw = PropertiesService.getScriptProperties().getProperty(PROP_KEY);
  if (!raw) return new Set();
  try { return new Set(JSON.parse(raw)); }
  catch (e) { return new Set(); }
}

function saveProcessed_(set) {
  let ids = Array.from(set);
  if (ids.length > MAX_IDS) ids = ids.slice(-MAX_IDS); // ring buffer: keep the most recent
  PropertiesService.getScriptProperties().setProperty(PROP_KEY, JSON.stringify(ids));
}
