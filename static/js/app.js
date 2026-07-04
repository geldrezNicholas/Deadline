/*
 * Alpine component for the whole app.
 *
 * A row looks like:
 *   { id, title, date ("YYYY-MM-DD" or ""), unknownDate, confident }
 *
 * Rows get a stable counter id, used as the x-for key.
 */
document.addEventListener('alpine:init', () => {
  Alpine.data('syllabusApp', () => ({
    // upload state
    file: null,
    fileName: '',
    loading: false,
    error: '',

    // Google Calendar state
    google: { configured: false, connected: false },
    pushing: false,
    pushResult: '',

    init() {
      this.fetchGoogleStatus();
      this.restoreRows();

      // show the result of an OAuth redirect, then clean up the URL
      const params = new URLSearchParams(window.location.search);
      if (params.get('google_error')) {
        this.error = 'Google connection failed: ' + params.get('google_error');
      }
      if (params.has('google') || params.has('google_error')) {
        history.replaceState(null, '', window.location.pathname);
      }
    },

    async fetchGoogleStatus() {
      try {
        const res = await fetch('/auth/google/status');
        if (res.ok) this.google = await res.json();
      } catch { /* stays disconnected */ }
    },

    // progress indicator state: '' (idle), 'upload' (request bytes going
    // out), 'read' (waiting on /extract-text), 'extract' (waiting on
    // /extract-items)
    step: '',
    steps: [
      { key: 'upload',  label: 'Uploading' },
      { key: 'read',    label: 'Reading PDF' },
      { key: 'extract', label: 'Extracting dates' },
    ],

    stepState(key) {
      const order = this.steps.map((s) => s.key);
      const current = order.indexOf(this.step);
      const mine = order.indexOf(key);
      if (mine < current) return 'done';
      if (mine === current) return 'active';
      return 'pending';
    },

    // label for the current step, shown under the scanner
    get stepLabel() {
      const s = this.steps.find((s) => s.key === this.step);
      return s ? s.label + '…' : '';
    },

    // review state
    rows: [],
    nextId: 1,

    get hasRows() {
      return this.rows.length > 0;
    },

    onFileChange(event) {
      const file = event.target.files[0] || null;
      this.file = file;
      this.fileName = file ? file.name : '';
      this.error = '';
      this.rows = [];
    },

    // uploads the PDF via XHR. upload.onload fires once the request body is
    // fully sent, which flips the step from 'upload' to 'read'
    uploadPdf(file) {
      return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/extract-text');
        xhr.responseType = 'json';

        xhr.upload.onload = () => { this.step = 'read'; };

        xhr.onload = () => resolve({ status: xhr.status, data: xhr.response });
        xhr.onerror = () => reject(new Error('network'));

        const body = new FormData();
        body.append('file', file);
        xhr.send(body);
      });
    },

    async submit() {
      if (!this.file) return;

      this.loading = true;
      this.error = '';
      this.rows = [];
      this.step = 'upload';

      try {
        // request 1: upload the PDF, get its text back
        const res1 = await this.uploadPdf(this.file);
        if (res1.status !== 200) {
          this.error = (res1.data && res1.data.error) ||
            `Request failed (${res1.status}).`;
          return;
        }

        // request 2: send the text to Gemini
        this.step = 'extract';
        const res2 = await fetch('/extract-items', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: res1.data.text }),
        });
        const data2 = await res2.json();
        if (!res2.ok) {
          this.error = data2.error || `Request failed (${res2.status}).`;
          return;
        }

        this.rows = (data2.items || []).map((item) => this.toRow(item));
      } catch (err) {
        this.error = 'Could not reach the server. Is the app running?';
      } finally {
        this.loading = false;
        this.step = '';
      }
    },

    // review actions

    toRow(item) {
      return {
        id: this.nextId++,
        title: item.title || '',
        // a null date from the AI pre-ticks the "no date" toggle
        date: item.date || '',
        unknownDate: !item.date,
        // only an explicit false counts as unsure
        confident: item.confident !== false,
      };
    },

    // adds a blank row, same shape as the AI ones
    addRow() {
      this.rows.push({
        id: this.nextId++,
        title: '',
        date: '',
        unknownDate: false,
        confident: true,
      });
    },

    deleteRow(id) {
      this.rows = this.rows.filter((row) => row.id !== id);
    },

    // clears the date whenever "no date" gets ticked
    onUnknownToggle(row) {
      if (row.unknownDate) row.date = '';
    },

    // Google Calendar actions

    // stashes the rows in sessionStorage before leaving for Google's consent
    // page, restoreRows() puts them back on return
    connectGoogle() {
      sessionStorage.setItem('syllabus-rows', JSON.stringify(this.rows));
      window.location.href = '/auth/google/start';
    },

    restoreRows() {
      const saved = sessionStorage.getItem('syllabus-rows');
      if (!saved) return;
      sessionStorage.removeItem('syllabus-rows');
      try {
        const rows = JSON.parse(saved);
        if (Array.isArray(rows) && rows.length) {
          this.rows = rows;
          this.nextId = Math.max(...rows.map((r) => r.id)) + 1;
        }
      } catch { /* corrupt stash, start fresh */ }
    },

    async disconnectGoogle() {
      await fetch('/auth/google/disconnect', { method: 'POST' });
      this.google.connected = false;
      this.pushResult = '';
    },

    async pushToGoogle() {
      if (this.exportProblems.length) return;

      this.pushing = true;
      this.error = '';
      this.pushResult = '';

      try {
        const res = await fetch('/push-to-google', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            items: this.rows.map(({ title, date, unknownDate }) => ({
              title, date, unknownDate,
            })),
          }),
        });
        const data = await res.json();

        if (!res.ok) {
          this.error = data.error || `Push failed (${res.status}).`;
          if (res.status === 401) this.google.connected = false;
          return;
        }

        this.pushResult = `Added ${data.created} event(s) to Google Calendar`
          + (data.skipped ? ` (${data.skipped} undated item(s) skipped, use the .ics for those)` : '')
          + '.';
      } catch {
        this.error = 'Could not reach the server. Is the app running?';
      } finally {
        this.pushing = false;
      }
    },

    // ICS export
    exporting: false,

    // list of validation problems shown under the buttons, empty means ok
    get exportProblems() {
      const problems = [];
      this.rows.forEach((row, i) => {
        if (!row.title.trim()) problems.push(`Row ${i + 1} needs a title.`);
        if (!row.unknownDate && !row.date)
          problems.push(`Row ${i + 1} needs a date (or tick "No date").`);
      });
      return problems;
    },

    async exportIcs() {
      if (this.exportProblems.length) return;

      this.exporting = true;
      this.error = '';

      try {
        const res = await fetch('/generate-ics', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            items: this.rows.map(({ title, date, unknownDate }) => ({
              title, date, unknownDate,
            })),
          }),
        });

        if (!res.ok) {
          const data = await res.json();
          this.error = data.error || `Export failed (${res.status}).`;
          return;
        }

        // downloads the response: blob -> object URL -> click a hidden link
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'syllabus.ics';
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      } catch (err) {
        this.error = 'Could not reach the server. Is the app running?';
      } finally {
        this.exporting = false;
      }
    },
  }));
});
