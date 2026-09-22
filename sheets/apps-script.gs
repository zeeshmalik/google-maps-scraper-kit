/**
 * Google Maps Scraper Kit — Google Sheets receiver (free, no Google Cloud project needed).
 *
 * Paste this into Extensions → Apps Script of the Google Sheet you want leads in, set SECRET
 * below, then Deploy → New deployment → Web app (Execute as: Me, Who has access: Anyone).
 * Put the web app URL + SECRET in your .env as SHEETS_WEBHOOK_URL / SHEETS_SECRET.
 * Full steps: SETUP.md → "Export to Google Sheets".
 *
 * Request body (JSON), sent by scripts/to_sheets.py:
 *   { "secret": "...", "tab": "Leads", "headers": ["title", ...], "rows": [["Cafe X", ...], ...],
 *     "dedupe": true }
 */

// CHANGE THIS to a long random string, and use the same value for SHEETS_SECRET in .env.
// Anyone with the web app URL + this secret can append rows to your sheet.
var SECRET = 'change-me';

// Columns that identify a business for de-duplication (used when present in the headers).
var KEY_COLUMNS = ['title', 'address'];

function doPost(e) {
  var lock = LockService.getScriptLock();
  lock.waitLock(30000);  // serialize concurrent pushes so rows don't interleave
  try {
    var body = JSON.parse(e.postData.contents);
    if (SECRET === 'change-me') return reply({ ok: false, error: 'Set SECRET in the Apps Script first.' });
    if (body.secret !== SECRET) return reply({ ok: false, error: 'Bad secret.' });

    var headers = body.headers || [];
    var rows = body.rows || [];
    if (!headers.length) return reply({ ok: false, error: 'No headers.' });

    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var name = String(body.tab || 'Leads').slice(0, 100);
    var sheet = ss.getSheetByName(name) || ss.insertSheet(name);

    // New/empty tab → write the header row. Existing tab → add any new columns to the right.
    var existing = [];
    if (sheet.getLastRow() === 0) {
      sheet.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight('bold');
      sheet.setFrozenRows(1);
      existing = headers.slice();
    } else {
      existing = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0].map(String);
      headers.forEach(function (h) {
        if (existing.indexOf(h) === -1) {
          existing.push(h);
          sheet.getRange(1, existing.length).setValue(h).setFontWeight('bold');
        }
      });
    }

    // Re-map incoming rows onto the sheet's column order.
    var idx = headers.map(function (h) { return existing.indexOf(h); });
    var out = rows.map(function (r) {
      var line = existing.map(function () { return ''; });
      r.forEach(function (v, i) { line[idx[i]] = v == null ? '' : String(v); });
      return line;
    });

    // Optional de-dupe against rows already in the tab (and within this batch).
    var skipped = 0;
    var keyIdx = KEY_COLUMNS.map(function (k) { return existing.indexOf(k); })
                            .filter(function (i) { return i !== -1; });
    if (body.dedupe !== false && keyIdx.length) {
      var seen = {};
      if (sheet.getLastRow() > 1) {
        sheet.getRange(2, 1, sheet.getLastRow() - 1, existing.length).getValues().forEach(function (r) {
          seen[keyOf(r, keyIdx)] = true;
        });
      }
      out = out.filter(function (r) {
        var k = keyOf(r, keyIdx);
        if (seen[k]) { skipped++; return false; }
        seen[k] = true;
        return true;
      });
    }

    if (out.length) {
      var range = sheet.getRange(sheet.getLastRow() + 1, 1, out.length, existing.length);
      // Plain-text format so scraped values like "+1 512…" or "=…" are never parsed as formulas.
      range.setNumberFormat('@').setValues(out);
    }
    return reply({ ok: true, tab: name, added: out.length, skipped: skipped, url: ss.getUrl() });
  } catch (err) {
    return reply({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

function keyOf(row, keyIdx) {
  return keyIdx.map(function (i) { return String(row[i]).trim().toLowerCase(); }).join('|');
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
