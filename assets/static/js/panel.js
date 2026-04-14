/**
 * TARS Panel Manager — clock, weather, comms log.
 */

class PanelManager {
  constructor() {
    this.clockEl = document.getElementById('clock');
    this.dateEl = document.getElementById('date');
    this.tempEl = document.getElementById('weather-temp');
    this.descEl = document.getElementById('weather-desc');
    this.locEl = document.getElementById('weather-location');
    this.logEl = document.getElementById('log-container');
    this.hintEl = document.getElementById('hint');
    this._lastLogLen = 0;
    this._lastLogHash = '';

    // Update clock every second
    this._updateClock();
    setInterval(() => this._updateClock(), 1000);
  }

  _updateClock() {
    const now = new Date();
    const h = String(now.getHours()).padStart(2, '0');
    const m = String(now.getMinutes()).padStart(2, '0');
    this.clockEl.textContent = h + ':' + m;

    const days = ['SUN','MON','TUE','WED','THU','FRI','SAT'];
    const months = ['JAN','FEB','MAR','APR','MAY','JUN',
                     'JUL','AUG','SEP','OCT','NOV','DEC'];
    this.dateEl.textContent =
      days[now.getDay()] + ' ' +
      months[now.getMonth()] + ' ' +
      String(now.getDate()).padStart(2, '0');
  }

  update(state) {
    // Weather
    if (state.weather) {
      this.tempEl.textContent = state.weather.temp || '--';
      this.descEl.textContent = state.weather.desc ? '  ' + state.weather.desc : '';
      this.locEl.textContent = state.weather.location || '';
    }

    // Hint
    if (state.is_recording) {
      this.hintEl.textContent = 'REC \u2014 speak now...';
      this.hintEl.className = 'recording';
    } else if (state.is_processing) {
      this.hintEl.textContent = 'Processing...';
      this.hintEl.className = 'processing';
    } else {
      this.hintEl.textContent = 'TAP SCREEN TO SPEAK';
      this.hintEl.className = '';
    }

    // Logs — only rebuild if changed
    const logs = state.logs || [];
    const hash = logs.length + (logs.length > 0 ? logs[logs.length - 1].text : '');
    if (hash === this._lastLogHash) return;
    this._lastLogHash = hash;

    // Rebuild log container
    const frag = document.createDocumentFragment();
    for (const entry of logs) {
      const div = document.createElement('div');
      div.className = 'log-line';
      // Color class
      if (entry.text.startsWith('> ')) {
        div.classList.add('log-bright');
      } else if (entry.color === 'bright') {
        div.classList.add('log-bright');
      } else if (entry.color === 'dim') {
        div.classList.add('log-dim');
      } else if (entry.color === 'red') {
        div.classList.add('log-red');
      } else {
        div.classList.add('log-green');
      }
      div.textContent = entry.text;
      frag.appendChild(div);
    }
    this.logEl.innerHTML = '';
    this.logEl.appendChild(frag);
    // Auto-scroll to bottom
    this.logEl.scrollTop = this.logEl.scrollHeight;
  }
}
