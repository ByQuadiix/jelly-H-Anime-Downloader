/*
 * H!Anime Downloader – Jellyfin-Web-Erweiterung
 * Wird vom Plugin (ueber FileTransformation) in index.html eingebunden.
 * Fuegt einen Menueeintrag in die Seitenleiste ein und oeffnet ein Overlay mit
 * Download-Formular und Warteschlange. Alle Aufrufe laufen ueber das Plugin
 * (/HAnimeDownloader/api/...) und sind damit durch die Jellyfin-Anmeldung geschuetzt.
 */
(function () {
    'use strict';

    if (window.__hanimeDownloaderLoaded) return;
    window.__hanimeDownloaderLoaded = true;

    var API = 'HAnimeDownloader/api/';
    var POLL_MS = 2000;
    var state = { open: false, timer: null, config: null, resolved: null, busy: false };
    var els = {};

    // ---------------------------------------------------------------- Helfer
    function el(tag, props, children) {
        var node = document.createElement(tag);
        if (props) {
            Object.keys(props).forEach(function (key) {
                if (key === 'class') node.className = props[key];
                else if (key === 'text') node.textContent = props[key];
                else if (key.indexOf('on') === 0) node.addEventListener(key.slice(2), props[key]);
                else node.setAttribute(key, props[key]);
            });
        }
        (children || []).forEach(function (child) {
            if (child) node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
        });
        return node;
    }

    function icon(name) {
        return el('span', { class: 'material-icons', 'aria-hidden': 'true', text: name });
    }

    function request(method, path, body) {
        var client = window.ApiClient;
        if (!client) return Promise.reject(new Error('Jellyfin-Client nicht bereit'));
        var options = { type: method, url: client.getUrl(API + path), dataType: 'json' };
        if (body !== undefined) {
            options.data = JSON.stringify(body);
            options.contentType = 'application/json';
        }
        return client.ajax(options).catch(function (response) {
            // ApiClient wirft bei HTTP-Fehlern die Response; Fehlertext des Backends auslesen.
            if (response && typeof response.json === 'function') {
                return response.json().then(
                    function (data) { throw new Error(data.detail || data.title || ('HTTP ' + response.status)); },
                    function () { throw new Error('HTTP ' + response.status); }
                );
            }
            throw response instanceof Error ? response : new Error('Anfrage fehlgeschlagen');
        });
    }

    // ------------------------------------------------------------------- UI
    function buildPanel() {
        els.url = el('input', { type: 'url', class: 'hdl-input', placeholder: 'Serien- oder Folgen-URL einfuegen', autocomplete: 'off' });
        els.resolveBtn = el('button', { class: 'hdl-btn hdl-primary', type: 'button', onclick: onResolve, text: 'Analysieren' });
        els.message = el('div', { class: 'hdl-message', role: 'status' });
        els.form = el('div', { class: 'hdl-form hdl-hidden' });
        els.queue = el('div', { class: 'hdl-queue' });

        els.url.addEventListener('keydown', function (ev) { if (ev.key === 'Enter') onResolve(); });

        var header = el('div', { class: 'hdl-header' }, [
            el('h2', { text: 'H!Anime Downloader' }),
            el('button', { class: 'hdl-btn hdl-icon', type: 'button', title: 'Schliessen', 'aria-label': 'Schliessen', onclick: closePanel }, [icon('close')])
        ]);

        els.panel = el('div', { class: 'hdl-panel', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'H!Anime Downloader' }, [
            header,
            el('div', { class: 'hdl-body' }, [
                el('div', { class: 'hdl-row' }, [els.url, els.resolveBtn]),
                els.message,
                els.form,
                el('div', { class: 'hdl-subhead' }, [
                    el('h3', { text: 'Warteschlange' }),
                    el('button', { class: 'hdl-btn', type: 'button', onclick: onClear, text: 'Fertige entfernen' })
                ]),
                els.queue
            ])
        ]);
        els.overlay = el('div', { class: 'hdl-overlay hdl-hidden' }, [els.panel]);
        els.overlay.addEventListener('mousedown', function (ev) { if (ev.target === els.overlay) closePanel(); });
        document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape' && state.open) closePanel(); });
        document.body.appendChild(els.overlay);
    }

    function setMessage(text, isError) {
        els.message.textContent = text || '';
        els.message.className = 'hdl-message' + (isError ? ' hdl-error' : '');
    }

    function renderForm(resolved) {
        els.form.textContent = '';
        var cfg = state.config || { qualities: ['best'], defaultQuality: 'best' };

        els.series = el('input', { class: 'hdl-input', type: 'text', value: resolved.series || '' });
        els.season = el('input', { class: 'hdl-input hdl-narrow', type: 'number', min: '0', max: '99', value: '1' });
        els.quality = el('select', { class: 'hdl-input hdl-narrow' }, cfg.qualities.map(function (q) {
            var opt = el('option', { value: q, text: q === 'best' ? 'Beste' : q + 'p' });
            if (q === cfg.defaultQuality) opt.selected = true;
            return opt;
        }));

        var list = el('div', { class: 'hdl-episodes' });
        els.rows = resolved.episodes.map(function (ep) {
            var check = el('input', { type: 'checkbox' });
            check.checked = true;
            var number = el('input', { class: 'hdl-input hdl-num', type: 'number', min: '0', max: '9999', value: String(ep.number) });
            var title = el('input', { class: 'hdl-input', type: 'text', value: ep.title || '' });
            list.appendChild(el('label', { class: 'hdl-ep' }, [check, number, title]));
            return { ep: ep, check: check, number: number, title: title };
        });

        var toggle = el('button', { class: 'hdl-btn', type: 'button', text: 'Alle an/aus', onclick: function () {
            var all = els.rows.every(function (r) { return r.check.checked; });
            els.rows.forEach(function (r) { r.check.checked = !all; });
        } });

        els.startBtn = el('button', { class: 'hdl-btn hdl-primary', type: 'button', text: 'Download starten', onclick: onStart });

        els.form.appendChild(el('div', { class: 'hdl-fields' }, [
            el('label', {}, ['Serienname', els.series]),
            el('label', {}, ['Staffel', els.season]),
            el('label', {}, ['Qualitaet', els.quality])
        ]));
        els.form.appendChild(el('div', { class: 'hdl-subhead' }, [
            el('h3', { text: resolved.episodes.length + (resolved.episodes.length === 1 ? ' Folge' : ' Folgen') }),
            toggle
        ]));
        els.form.appendChild(list);
        els.form.appendChild(el('div', { class: 'hdl-row hdl-end' }, [els.startBtn]));
        els.form.classList.remove('hdl-hidden');
    }

    function renderQueue(jobs) {
        els.queue.textContent = '';
        if (!jobs.length) {
            els.queue.appendChild(el('div', { class: 'hdl-empty', text: 'Keine Downloads.' }));
            return;
        }
        jobs.forEach(function (job) {
            var active = job.status === 'queued' || job.status === 'downloading' || job.status === 'processing';
            var label = {
                queued: 'Wartet', downloading: 'Laedt', processing: 'Verarbeitet',
                done: 'Fertig', error: 'Fehler', cancelled: 'Abgebrochen'
            }[job.status] || job.status;
            var name = job.series + ' – S' + pad(job.season) + 'E' + pad(job.episode) + (job.title ? ' – ' + job.title : '');
            var meta = [label];
            if (job.status === 'downloading') {
                meta.push(job.progress.toFixed(1) + ' %');
                if (job.speed) meta.push(job.speed);
                if (job.eta) meta.push('ETA ' + job.eta);
            }
            if (job.user) meta.push(job.user);

            var bar = el('div', { class: 'hdl-bar' }, [el('div', { class: 'hdl-fill hdl-' + job.status })]);
            bar.firstChild.style.width = Math.max(0, Math.min(100, job.progress)) + '%';

            var action = active
                ? el('button', { class: 'hdl-btn hdl-icon', type: 'button', title: 'Abbrechen', 'aria-label': 'Abbrechen', onclick: function () { act('POST', 'jobs/' + job.id + '/cancel'); } }, [icon('stop')])
                : el('button', { class: 'hdl-btn hdl-icon', type: 'button', title: 'Entfernen', 'aria-label': 'Entfernen', onclick: function () { act('DELETE', 'jobs/' + job.id); } }, [icon('delete')]);

            els.queue.appendChild(el('div', { class: 'hdl-job' }, [
                el('div', { class: 'hdl-jobmain' }, [
                    el('div', { class: 'hdl-jobname', text: name }),
                    bar,
                    el('div', { class: 'hdl-jobmeta', text: meta.join(' · ') }),
                    job.error ? el('div', { class: 'hdl-jobmeta' + (job.status === 'error' ? ' hdl-error' : ''), text: job.error }) : null
                ]),
                action
            ]));
        });
    }

    function pad(n) { return String(n).padStart(2, '0'); }

    // ------------------------------------------------------------- Aktionen
    function onResolve() {
        var url = els.url.value.trim();
        if (!url || state.busy) return;
        state.busy = true;
        els.resolveBtn.disabled = true;
        els.form.classList.add('hdl-hidden');
        setMessage('Analysiere …');
        request('POST', 'resolve', { url: url }).then(function (resolved) {
            state.resolved = resolved;
            setMessage('');
            renderForm(resolved);
        }).catch(function (err) {
            setMessage(err.message, true);
        }).then(function () {
            state.busy = false;
            els.resolveBtn.disabled = false;
        });
    }

    function onStart() {
        var selected = els.rows.filter(function (r) { return r.check.checked; });
        var series = els.series.value.trim();
        if (!series) return setMessage('Bitte einen Seriennamen angeben.', true);
        if (!selected.length) return setMessage('Bitte mindestens eine Folge auswaehlen.', true);
        els.startBtn.disabled = true;
        request('POST', 'jobs', {
            series: series,
            season: parseInt(els.season.value, 10) || 1,
            quality: els.quality.value,
            episodes: selected.map(function (r) {
                return { url: r.ep.url, title: r.title.value.trim(), number: parseInt(r.number.value, 10) || 0 };
            })
        }).then(function () {
            setMessage(selected.length + ' Download(s) eingereiht.');
            els.form.classList.add('hdl-hidden');
            els.url.value = '';
            refresh();
        }).catch(function (err) {
            setMessage(err.message, true);
        }).then(function () { els.startBtn.disabled = false; });
    }

    function onClear() { act('POST', 'jobs-clear'); }

    function act(method, path) {
        request(method, path).then(refresh).catch(function (err) { setMessage(err.message, true); });
    }

    function refresh() {
        if (!state.open) return Promise.resolve();
        return request('GET', 'jobs').then(renderQueue).catch(function (err) {
            els.queue.textContent = '';
            els.queue.appendChild(el('div', { class: 'hdl-empty hdl-error', text: 'Downloader nicht erreichbar: ' + err.message }));
        });
    }

    function openPanel() {
        if (!els.overlay) buildPanel();
        state.open = true;
        els.overlay.classList.remove('hdl-hidden');
        document.body.classList.add('hdl-noscroll');
        if (!state.config) {
            request('GET', 'config').then(function (cfg) { state.config = cfg; }).catch(function () { /* Anzeige in der Queue */ });
        }
        refresh();
        state.timer = window.setInterval(refresh, POLL_MS);
        window.setTimeout(function () { els.url.focus(); }, 50);
    }

    function closePanel() {
        state.open = false;
        els.overlay.classList.add('hdl-hidden');
        document.body.classList.remove('hdl-noscroll');
        window.clearInterval(state.timer);
    }

    // ------------------------------------------------- Menue-Integration
    function ensureMenuEntries() {
        var drawer = document.querySelector('.mainDrawer-scrollContainer');
        if (drawer && !drawer.querySelector('.hdl-nav')) {
            var link = el('a', { class: 'navMenuOption lnkMediaFolder hdl-nav', href: '#', onclick: function (ev) { ev.preventDefault(); openPanel(); } }, [
                el('span', { class: 'material-icons navMenuOptionIcon', 'aria-hidden': 'true', text: 'download' }),
                el('span', { class: 'navMenuOptionText', text: 'H!Anime Downloader' })
            ]);
            drawer.appendChild(link);
        }
        var headerRight = document.querySelector('.headerRight');
        if (headerRight && !headerRight.querySelector('.hdl-headerbtn')) {
            var btn = el('button', {
                class: 'headerButton headerButtonRight paper-icon-button-light hdl-headerbtn',
                type: 'button', title: 'H!Anime Downloader', 'aria-label': 'H!Anime Downloader',
                onclick: openPanel
            }, [icon('download')]);
            headerRight.insertBefore(btn, headerRight.firstChild);
        }
    }

    var scheduled = false;
    function scheduleEnsure() {
        if (scheduled) return;
        scheduled = true;
        window.requestAnimationFrame(function () { scheduled = false; ensureMenuEntries(); });
    }

    function injectStyles() {
        var css = [
            '.hdl-hidden{display:none!important}',
            '.hdl-noscroll{overflow:hidden}',
            '.hdl-overlay{position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,.7);display:flex;align-items:flex-start;justify-content:center;overflow:auto;padding:4vh 12px}',
            '.hdl-panel{width:100%;max-width:880px;background:#202020;color:#eee;border-radius:8px;box-shadow:0 10px 40px rgba(0,0,0,.6);font-size:15px}',
            '.hdl-header{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid #333}',
            '.hdl-header h2{margin:0;font-size:1.3em}',
            '.hdl-body{padding:16px}',
            '.hdl-row{display:flex;gap:8px;align-items:center}',
            '.hdl-end{justify-content:flex-end;margin-top:12px}',
            '.hdl-input{background:#111;color:#eee;border:1px solid #444;border-radius:4px;padding:8px 10px;font:inherit;min-width:0;flex:1;box-sizing:border-box}',
            '.hdl-input:focus{outline:2px solid #00a4dc;border-color:#00a4dc}',
            '.hdl-narrow{flex:0 0 110px;width:110px}',
            '.hdl-num{flex:0 0 72px;width:72px}',
            '.hdl-btn{background:#383838;color:#eee;border:0;border-radius:4px;padding:8px 14px;font:inherit;cursor:pointer}',
            '.hdl-btn:hover{background:#4a4a4a}.hdl-btn:disabled{opacity:.5;cursor:default}',
            '.hdl-primary{background:#00a4dc;color:#fff}.hdl-primary:hover{background:#0b8fbd}',
            '.hdl-icon{padding:6px;display:inline-flex;align-items:center;justify-content:center;background:transparent}',
            '.hdl-message{min-height:1.4em;margin:8px 0;color:#aaa}',
            '.hdl-error{color:#ff6b6b}',
            '.hdl-fields{display:flex;gap:12px;flex-wrap:wrap}',
            '.hdl-fields label{display:flex;flex-direction:column;gap:4px;font-size:.85em;color:#aaa}',
            '.hdl-fields label:first-child{flex:1 1 240px}',
            '.hdl-subhead{display:flex;align-items:center;justify-content:space-between;margin:16px 0 8px}',
            '.hdl-subhead h3{margin:0;font-size:1.05em}',
            '.hdl-episodes{max-height:300px;overflow:auto;border:1px solid #333;border-radius:4px;padding:6px}',
            '.hdl-ep{display:flex;gap:8px;align-items:center;padding:3px 0}',
            '.hdl-job{display:flex;gap:8px;align-items:center;padding:8px 0;border-bottom:1px solid #2e2e2e}',
            '.hdl-jobmain{flex:1;min-width:0}',
            '.hdl-jobname{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
            '.hdl-jobmeta{font-size:.8em;color:#999;margin-top:2px;word-break:break-word}',
            '.hdl-bar{height:6px;background:#333;border-radius:3px;margin-top:6px;overflow:hidden}',
            '.hdl-fill{height:100%;background:#00a4dc;transition:width .4s}',
            '.hdl-fill.hdl-done{background:#4caf50}.hdl-fill.hdl-error{background:#e53935}.hdl-fill.hdl-cancelled{background:#777}',
            '.hdl-empty{color:#888;padding:12px 0}'
        ].join('\n');
        var style = document.createElement('style');
        style.id = 'hdl-styles';
        style.textContent = css;
        document.head.appendChild(style);
    }

    function init() {
        injectStyles();
        ensureMenuEntries();
        new MutationObserver(scheduleEnsure).observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
