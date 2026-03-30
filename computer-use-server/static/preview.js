// =============================================================================
// Preview SPA — Preact + HTM
// =============================================================================

import { html, render, useState, useEffect, useRef, useCallback, useMemo } from '/static/preact-htm.min.js';
import { icon, fileIcon, fileIconLarge } from '/static/icons.js';
import { BrowserViewer } from '/static/browser-viewer.js';
import { t, LANG } from '/static/locale.js';

const { apiUrl: API_URL, filesBase: FILES_BASE, chatId: CHAT_ID } = window.__CONFIG__;

// =============================================================================
// Utilities
// =============================================================================

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

const _loadedScripts = new Set();
function loadScript(url) {
  if (_loadedScripts.has(url)) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = url;
    s.onload = () => { _loadedScripts.add(url); resolve(); };
    s.onerror = reject;
    document.head.appendChild(s);
  });
}

function normalizePath(path) {
  const parts = path.split('/');
  const result = [];
  for (let i = 0; i < parts.length; i++) {
    if (parts[i] === '.' || parts[i] === '') continue;
    if (parts[i] === '..') { result.pop(); }
    else { result.push(parts[i]); }
  }
  return result.join('/');
}

function parseCSV(text, delimiter) {
  const rows = [];
  let row = [];
  let cell = '';
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (i + 1 < text.length && text[i + 1] === '"') { cell += '"'; i++; }
        else { inQuotes = false; }
      } else { cell += ch; }
    } else {
      if (ch === '"') { inQuotes = true; }
      else if (ch === delimiter) { row.push(cell); cell = ''; }
      else if (ch === '\n') {
        row.push(cell); cell = '';
        if (row.length > 0) rows.push(row);
        row = [];
      } else if (ch !== '\r') { cell += ch; }
    }
  }
  if (cell || row.length > 0) { row.push(cell); rows.push(row); }
  return rows;
}

function showToast(text) {
  const msg = document.createElement('div');
  msg.className = 'toast';
  msg.textContent = text;
  document.body.appendChild(msg);
  setTimeout(() => msg.remove(), 1500);
}

function copyText(text) {
  // Try modern clipboard API first, fallback to execCommand for iframe sandbox
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(text).then(
      () => true,
      () => copyTextFallback(text)
    );
  }
  return Promise.resolve(copyTextFallback(text));
}

function copyTextFallback(text) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.cssText = 'position:fixed;left:-9999px;top:-9999px';
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand('copy'); return true; }
  catch { return false; }
  finally { ta.remove(); }
}

// =============================================================================
// Link interception for HTML previews and Markdown
// =============================================================================

function handleLinkClick(href, resolvedUrl, files, selectedFile, onSelectFile) {
  if (!href) return;
  if (href.startsWith('#')) {
    const targetId = decodeURIComponent(href.substring(1));
    let el = document.getElementById(targetId);
    if (!el) { try { el = document.querySelector(href); } catch(e) {} }
    if (el) el.scrollIntoView({ behavior: 'smooth' });
    return;
  }
  if (href.startsWith('http://') || href.startsWith('https://') || href.startsWith('//')) {
    window.open(href, '_blank', 'noopener');
    return;
  }
  let filePath = null;
  const filesBaseWithSlash = FILES_BASE + '/';
  if (resolvedUrl) {
    try {
      const url = new URL(resolvedUrl, window.location.origin);
      if (url.pathname.startsWith(filesBaseWithSlash)) {
        filePath = decodeURIComponent(url.pathname.substring(filesBaseWithSlash.length));
      }
    } catch(e) {}
  }
  if (!filePath) {
    const currentDir = selectedFile && selectedFile.path.includes('/')
      ? selectedFile.path.substring(0, selectedFile.path.lastIndexOf('/'))
      : '';
    filePath = currentDir ? currentDir + '/' + href : href;
    filePath = normalizePath(filePath);
  }
  if (filePath) {
    filePath = filePath.split('?')[0].split('#')[0];
    let targetFile = files.find(f => f.path === filePath);
    if (!targetFile) {
      const lp = filePath.toLowerCase();
      targetFile = files.find(f => f.path.toLowerCase() === lp);
    }
    if (targetFile) { onSelectFile(targetFile); return; }
  }
  if (resolvedUrl) window.open(resolvedUrl, '_blank', 'noopener');
}

// =============================================================================
// Preview Renderers (imperative DOM — these render into a container ref)
// =============================================================================

async function renderHtmlPreview(container, file) {
  try {
    const resp = await fetch(file.url);
    let text = await resp.text();
    const fileDir = file.path.includes('/') ? file.path.substring(0, file.path.lastIndexOf('/')) : '';
    const baseUrl = fileDir ? FILES_BASE + '/' + fileDir + '/' : FILES_BASE + '/';
    const baseTag = `<base href="${baseUrl}">`;
    const linkInterceptScript = '<scr' + 'ipt>'
      + '(function(){'
      + 'document.addEventListener("click",function(e){'
      + 'var a=e.target.closest("a");'
      + 'if(!a)return;'
      + 'var href=a.getAttribute("href");'
      + 'if(!href)return;'
      + 'e.preventDefault();'
      + 'e.stopPropagation();'
      + 'window.parent.postMessage({'
      + 'type:"iframe-link-click",'
      + 'href:href,'
      + 'resolvedUrl:a.href'
      + '},"*");'
      + '},true);'
      + '})();'
      + '</scr' + 'ipt>';
    const injection = baseTag + linkInterceptScript;
    if (text.includes('<head>')) {
      text = text.replace('<head>', '<head>' + injection);
    } else if (text.includes('<html>')) {
      text = text.replace('<html>', '<html><head>' + injection + '</head>');
    } else {
      text = injection + text;
    }
    const iframe = document.createElement('iframe');
    iframe.srcdoc = text;
    container.innerHTML = '';
    container.appendChild(iframe);
  } catch {
    const iframe = document.createElement('iframe');
    iframe.src = file.url;
    container.innerHTML = '';
    container.appendChild(iframe);
  }
}

async function renderPdfPreview(container, file) {
  container.innerHTML = `<div class="pdf-container" id="pdfContainer"><div class="empty-state"><div class="spinner"></div><p class="loading-text">${t('loading_pdf')}</p></div></div>`;
  try {
    await loadScript('/static/pdf.min.js');
    const pdfjsLib = window.pdfjsLib;
    if (!pdfjsLib) throw new Error('pdf.js not loaded');
    pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/pdf.worker.min.js';
    const pdf = await pdfjsLib.getDocument(file.url).promise;
    const pdfContainer = container.querySelector('#pdfContainer');
    pdfContainer.innerHTML = '';
    const maxPages = Math.min(pdf.numPages, 30);
    for (let i = 1; i <= maxPages; i++) {
      const page = await pdf.getPage(i);
      const viewport = page.getViewport({ scale: 1.5 });
      const canvas = document.createElement('canvas');
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise;
      pdfContainer.appendChild(canvas);
    }
    if (pdf.numPages > maxPages) {
      const p = document.createElement('p');
      p.className = 'truncation-notice';
      p.textContent = t('showing_pages', { max: maxPages, total: pdf.numPages });
      pdfContainer.appendChild(p);
    }
  } catch (err) {
    console.error('PDF render error:', err);
    container.innerHTML = `<iframe src="${escapeHtml(file.url)}"></iframe>`;
  }
}

async function renderMarkdownPreview(container, file, files, onSelectFile) {
  try {
    const resp = await fetch(file.url);
    let text = await resp.text();
    if (text.length > 500000) text = text.substring(0, 500000) + '\n\n... (truncated)';
    const renderer = new marked.Renderer();
    const origImage = renderer.image.bind(renderer);
    const origLink = renderer.link.bind(renderer);
    renderer.heading = function(token) {
      const slug = token.text.toLowerCase()
        .replace(/<[^>]*>/g, '')
        .replace(/[^\w\u0400-\u04ff\s-]/g, '')
        .replace(/\s+/g, '-');
      return `<h${token.depth} id="${slug}">${token.text}</h${token.depth}>\n`;
    };
    function resolveUrl(href) {
      if (href && !href.startsWith('http') && !href.startsWith('//') && !href.startsWith('data:') && !href.startsWith('#')) {
        const fileDir = file.path.includes('/') ? file.path.substring(0, file.path.lastIndexOf('/')) : '';
        const base = fileDir ? FILES_BASE + '/' + fileDir : FILES_BASE;
        return base + '/' + href;
      }
      return href;
    }
    renderer.image = function(token) { token.href = resolveUrl(token.href); return origImage(token); };
    renderer.link = function(token) { token.href = resolveUrl(token.href); return origLink(token); };
    const htmlContent = marked.parse(text, { renderer });
    container.innerHTML = `<div class="markdown-body">${htmlContent}</div>`;
    const mdBody = container.querySelector('.markdown-body');

    // Link interception
    mdBody.addEventListener('click', function(e) {
      const a = e.target.closest('a');
      if (!a) return;
      e.preventDefault();
      handleLinkClick(a.getAttribute('href'), a.href, files, file, onSelectFile);
    });

    // Syntax highlighting
    mdBody.querySelectorAll('pre code').forEach(el => {
      if (!el.classList.contains('language-mermaid')) hljs.highlightElement(el);
    });

    // Mermaid
    const mermaidBlocks = mdBody.querySelectorAll('pre code.language-mermaid');
    if (mermaidBlocks.length > 0) {
      try {
        await loadScript('/static/mermaid.min.js');
        mermaid.initialize({ startOnLoad: false, theme: window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'default' });
        mermaidBlocks.forEach(codeEl => {
          const pre = codeEl.parentElement;
          const div = document.createElement('div');
          div.className = 'mermaid';
          div.textContent = codeEl.textContent;
          pre.replaceWith(div);
        });
        await mermaid.run({ querySelector: '.mermaid' });
      } catch (e) { console.warn('Mermaid:', e); }
    }

    // KaTeX
    try {
      await loadScript('/static/katex/katex.min.js');
      await loadScript('/static/katex/auto-render.min.js');
      renderMathInElement(mdBody, {
        delimiters: [
          { left: '$$', right: '$$', display: true },
          { left: '$', right: '$', display: false }
        ],
        throwOnError: false
      });
    } catch (e) { console.warn('KaTeX:', e); }
  } catch (err) {
    console.error('Markdown render error:', err);
    container.innerHTML = `<div class="empty-state"><p>${t('load_fail')}</p></div>`;
  }
}

async function renderCodePreview(container, file) {
  try {
    const resp = await fetch(file.url);
    let text = await resp.text();
    if (text.length > 200000) text = text.substring(0, 200000) + '\n... (truncated)';
    const ext = file.name.split('.').pop() || '';
    container.innerHTML = `<pre><code class="language-${ext}">${escapeHtml(text)}</code></pre>`;
    container.querySelectorAll('pre code').forEach(el => {
      hljs.highlightElement(el);
      if (typeof hljs.lineNumbersBlock === 'function') hljs.lineNumbersBlock(el);
    });
  } catch {
    container.innerHTML = `<div class="empty-state"><p>${t('load_fail')}</p></div>`;
  }
}

async function renderSpreadsheetPreview(container, file) {
  try {
    const resp = await fetch(file.url);
    let text = await resp.text();
    if (text.length > 500000) text = text.substring(0, 500000);
    const ext = file.name.split('.').pop().toLowerCase();
    const delimiter = ext === 'tsv' ? '\t' : ',';
    const rows = parseCSV(text, delimiter);
    let tableHtml = '<table><thead><tr>';
    if (rows.length > 0) {
      rows[0].forEach(cell => { tableHtml += `<th>${escapeHtml(cell)}</th>`; });
      tableHtml += '</tr></thead><tbody>';
      for (let i = 1; i < Math.min(rows.length, 1000); i++) {
        tableHtml += '<tr>';
        rows[i].forEach(cell => { tableHtml += `<td>${escapeHtml(cell)}</td>`; });
        tableHtml += '</tr>';
      }
      tableHtml += '</tbody></table>';
      if (rows.length > 1000) {
        tableHtml += `<p class="truncation-notice">${t('showing_rows', { n: rows.length })}</p>`;
      }
    }
    container.innerHTML = `<div class="data-table-wrap">${tableHtml}</div>`;
  } catch {
    container.innerHTML = `<div class="empty-state"><p>${t('load_fail')}</p></div>`;
  }
}

async function renderDocxPreview(container, file) {
  container.innerHTML = '<div class="markdown-body" id="docxContainer"><div class="spinner" style="margin:20px auto"></div></div>';
  try {
    await loadScript('/static/mammoth.browser.min.js');
    const resp = await fetch(file.url);
    const arrayBuffer = await resp.arrayBuffer();
    const result = await mammoth.convertToHtml({ arrayBuffer });
    container.querySelector('#docxContainer').innerHTML = result.value;
  } catch (err) {
    console.error('DOCX render error:', err);
    renderDownloadFallback(container, file, 'fileText');
  }
}

async function renderXlsxPreview(container, file) {
  container.innerHTML = '<div class="data-table-wrap" id="xlsxContainer"><div class="spinner" style="margin:20px auto"></div></div>';
  try {
    await loadScript('/static/xlsx.full.min.js');
    const resp = await fetch(file.url);
    const arrayBuffer = await resp.arrayBuffer();
    const workbook = XLSX.read(arrayBuffer, { type: 'array' });
    let html = '';
    if (workbook.SheetNames.length > 1) {
      html += '<div class="sheet-tabs">';
      workbook.SheetNames.forEach((name, i) => {
        html += `<button class="sheet-tab${i === 0 ? ' active' : ''}" data-sheet="${i}">${escapeHtml(name)}</button>`;
      });
      html += '</div>';
    }
    html += '<div id="sheetContent"></div>';
    const xlsxContainer = container.querySelector('#xlsxContainer');
    xlsxContainer.innerHTML = html;
    function renderSheet(index) {
      const sheet = workbook.Sheets[workbook.SheetNames[index]];
      xlsxContainer.querySelector('#sheetContent').innerHTML = XLSX.utils.sheet_to_html(sheet, { editable: false });
    }
    renderSheet(0);
    xlsxContainer.querySelectorAll('.sheet-tab').forEach(btn => {
      btn.addEventListener('click', function() {
        xlsxContainer.querySelectorAll('.sheet-tab').forEach(b => b.classList.remove('active'));
        this.classList.add('active');
        renderSheet(parseInt(this.getAttribute('data-sheet')));
      });
    });
  } catch (err) {
    console.error('XLSX render error:', err);
    renderDownloadFallback(container, file, 'fileSpreadsheet');
  }
}

async function renderPptxPreview(container, file) {
  container.innerHTML = `<div class="empty-state" id="pptxLoading"><div class="spinner"></div><p class="loading-text">${t('loading')}</p></div><div class="pptx-container" id="pptxContainer" style="display:none"></div>`;
  try {
    await loadScript('/static/jszip.min.js');
    await loadScript('/static/chart.umd.js');
    await loadScript('/static/pptxviewjs.min.js');
    const pptxResp = await fetch(file.url);
    const pptxBuf = await pptxResp.arrayBuffer();
    const pptxContainer = container.querySelector('#pptxContainer');
    const pptxWidth = container.clientWidth;
    const viewer = new PptxViewJS.PPTXViewer();
    await viewer.loadFile(pptxBuf);
    const slideCount = viewer.getSlideCount();
    for (let i = 0; i < slideCount; i++) {
      const canvas = document.createElement('canvas');
      canvas.width = pptxWidth;
      canvas.height = Math.round(pptxWidth * 9 / 16);
      canvas.className = 'pptx-slide';
      pptxContainer.appendChild(canvas);
      viewer.setCanvas(canvas);
      await viewer.goToSlide(i);
      await viewer.render();
    }
    container.querySelector('#pptxLoading')?.remove();
    pptxContainer.style.display = '';
  } catch (err) {
    console.error('PPTX render error:', err);
    renderDownloadFallback(container, file, 'filePresentation', t('pptx_fail'));
  }
}

async function renderDrawioPreview(container, file) {
  container.innerHTML = `<div class="empty-state"><div class="spinner"></div><p class="loading-text">${t('loading')}</p></div>`;
  try {
    const drawioResp = await fetch(file.url);
    const drawioXml = await drawioResp.text();
    const mxDiv = document.createElement('div');
    mxDiv.className = 'mxgraph';
    mxDiv.style.cssText = 'max-width:100%;margin:0 auto;background:#fff;padding:20px;border-radius:8px;';
    mxDiv.setAttribute('data-mxgraph', JSON.stringify({ xml: drawioXml }));
    container.innerHTML = '';
    container.style.display = 'flex';
    container.style.justifyContent = 'center';
    container.style.alignItems = 'flex-start';
    container.appendChild(mxDiv);
    const viewerUrl = 'https://viewer.diagrams.net/js/viewer-static.min.js';
    if (_loadedScripts.has(viewerUrl) && window.GraphViewer) {
      GraphViewer.processElements();
    } else {
      await loadScript(viewerUrl);
    }
  } catch (err) {
    console.error('Draw.io render error:', err);
    renderDownloadFallback(container, file, 'diagram', t('drawio_fail'));
  }
}

function renderDownloadFallback(container, file, iconType, errorMsg) {
  container.innerHTML = `<div class="download-prompt">
    <div class="dl-icon">${fileIconLarge(file.type)}</div>
    <div class="dl-name">${escapeHtml(file.name)}</div>
    <div class="dl-size">${formatSize(file.size)}</div>
    ${errorMsg ? `<div class="dl-error">${escapeHtml(errorMsg)}</div>` : ''}
    <a class="btn" href="${escapeHtml(file.url)}" download>${icon('download')} ${t('download')}</a>
  </div>`;
}

function renderPreviewContent(container, file, files, onSelectFile) {
  switch (file.type) {
    case 'html': renderHtmlPreview(container, file); break;
    case 'image':
      container.innerHTML = `<img src="${escapeHtml(file.url)}" alt="${escapeHtml(file.name)}">`;
      break;
    case 'pdf': renderPdfPreview(container, file); break;
    case 'markdown': renderMarkdownPreview(container, file, files, onSelectFile); break;
    case 'code':
    case 'text': renderCodePreview(container, file); break;
    case 'spreadsheet': renderSpreadsheetPreview(container, file); break;
    case 'docx': renderDocxPreview(container, file); break;
    case 'xlsx': renderXlsxPreview(container, file); break;
    case 'pptx': renderPptxPreview(container, file); break;
    case 'drawio': renderDrawioPreview(container, file); break;
    case 'audio':
      container.innerHTML = `<div class="media-container">
        <div class="media-icon">${icon('music', 48)}</div>
        <div class="media-name">${escapeHtml(file.name)}</div>
        <div class="media-size">${formatSize(file.size)}</div>
        <audio controls preload="metadata" src="${escapeHtml(file.url)}">${t('audio_unsupported')}</audio>
        <a class="btn" href="${escapeHtml(file.url)}" download>${icon('download')} ${t('download')}</a>
      </div>`;
      break;
    case 'video':
      container.innerHTML = `<div class="media-container">
        <video controls preload="metadata" src="${escapeHtml(file.url)}">${t('video_unsupported')}</video>
        <a class="btn" href="${escapeHtml(file.url)}" download>${icon('download')} ${t('download')}</a>
      </div>`;
      break;
    default:
      renderDownloadFallback(container, file);
  }
}

// =============================================================================
// Components
// =============================================================================

function ViewTabs({ currentView, onSwitch, browserActive, terminalActive }) {
  return html`
    <div class="view-tabs">
      <button class="view-tab ${currentView === 'files' ? 'active' : ''}"
              onClick=${() => onSwitch('files')}>
        <span class="icon-inline" dangerouslySetInnerHTML=${{ __html: icon('folder') }}></span> ${t('files')}
      </button>
      <button class="view-tab ${currentView === 'browser' ? 'active' : ''}"
              onClick=${() => onSwitch('browser')}>
        <span class="icon-inline" dangerouslySetInnerHTML=${{ __html: icon('globe') }}></span> ${t('browser')}
        ${browserActive && html`<span class="tab-dot"></span>`}
      </button>
      <button class="view-tab ${currentView === 'terminal' ? 'active' : ''}"
              onClick=${() => onSwitch('terminal')}>
        <span class="icon-inline" dangerouslySetInnerHTML=${{ __html: icon('terminal') }}></span> ${t('subagent')}
        <span class="beta-badge">${t('beta')}</span>
        ${terminalActive && html`<span class="tab-dot"></span>`}
      </button>
    </div>
  `;
}

function FileSelector({ files, selectedFile, seenFiles, onSelect }) {
  const [open, setOpen] = useState(false);
  const [dropdownPath, setDropdownPath] = useState('');
  const ref = useRef(null);

  // Close on click outside
  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, []);

  const prefix = dropdownPath ? dropdownPath + '/' : '';
  const folders = new Set();
  const currentFiles = [];
  for (const f of files) {
    if (prefix && !f.path.startsWith(prefix)) continue;
    const rest = prefix ? f.path.substring(prefix.length) : f.path;
    if (rest.includes('/')) { folders.add(rest.substring(0, rest.indexOf('/'))); }
    else { currentFiles.push(f); }
  }

  const selectedIcon = selectedFile ? fileIcon(selectedFile.type) : icon('folderOpen');
  const hasNew = files.some(f => !seenFiles.has(f.path));

  return html`
    <div class="file-selector" ref=${ref}>
      <button class="file-selector-btn ${open ? 'open' : ''}" type="button"
              onClick=${(e) => { e.stopPropagation(); setOpen(!open); setDropdownPath(''); }}>
        <span class="icon-inline" dangerouslySetInnerHTML=${{ __html: selectedIcon }}></span>
        <span class="selector-name">${selectedFile ? selectedFile.name : t('no_file_selected')}</span>
        <span class="selector-count">${files.length}</span>
        ${hasNew && html`<span class="selector-new-dot"></span>`}
        <span class="selector-arrow icon-inline" dangerouslySetInnerHTML=${{ __html: icon('chevronDown') }}></span>
      </button>
      <ul class="dropdown-menu ${open ? 'open' : ''}">
        ${dropdownPath && html`
          <li class="dropdown-item back" onClick=${(e) => {
            e.stopPropagation();
            setDropdownPath(dropdownPath.includes('/') ? dropdownPath.substring(0, dropdownPath.lastIndexOf('/')) : '');
          }}>
            <span class="item-icon icon-inline" dangerouslySetInnerHTML=${{ __html: icon('arrowLeft') }}></span>
            <span class="item-name">..</span>
          </li>
        `}
        ${[...folders].sort().map(folder => html`
          <li class="dropdown-item folder" onClick=${(e) => { e.stopPropagation(); setDropdownPath(prefix + folder); }}>
            <span class="item-icon icon-inline" dangerouslySetInnerHTML=${{ __html: icon('folder') }}></span>
            <span class="item-name">${folder}</span>
            <span class="item-chevron icon-inline" dangerouslySetInnerHTML=${{ __html: icon('chevronRight') }}></span>
          </li>
        `)}
        ${currentFiles.map(f => html`
          <li class="dropdown-item ${selectedFile && f.path === selectedFile.path ? 'active' : ''}"
              onClick=${() => { onSelect(f); setOpen(false); }}>
            <span class="item-icon icon-inline" dangerouslySetInnerHTML=${{ __html: fileIcon(f.type) }}></span>
            <span class="item-name">${f.name}</span>
            <span class="item-size">${formatSize(f.size)}</span>
            ${!seenFiles.has(f.path) && html`<span class="badge-new"></span>`}
          </li>
        `)}
      </ul>
    </div>
  `;
}

function FilesView({ files, selectedFile, onSelectFile }) {
  const containerRef = useRef(null);
  const prevFileRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current) return;
    if (selectedFile && selectedFile !== prevFileRef.current) {
      prevFileRef.current = selectedFile;
      renderPreviewContent(containerRef.current, selectedFile, files, onSelectFile);
    }
  }, [selectedFile, files]);

  if (!selectedFile) {
    return html`
      <div class="preview">
        <div class="empty-state">
          <div class="empty-icon" dangerouslySetInnerHTML=${{ __html: icon('folder', 48) }}></div>
          <div class="empty-title">${t('no_files_yet')}</div>
          <div class="empty-desc" dangerouslySetInnerHTML=${{ __html: t('no_files_desc') }}></div>
          <div class="empty-example">${t('no_files_example')}</div>
        </div>
      </div>
    `;
  }

  return html`<div class="preview" ref=${containerRef}></div>`;
}

function BrowserView({ chatId, browserActive, onBrowserViewerRef }) {
  const canvasRef = useRef(null);
  const urlBarRef = useRef(null);
  const viewerRef = useRef(null);
  const [connecting, setConnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!browserActive) {
      if (viewerRef.current) { viewerRef.current.disconnect(); viewerRef.current = null; }
      setConnected(false);
      setConnecting(false);
      setError(false);
      return;
    }
    if (viewerRef.current) return;

    setConnecting(true);
    setError(false);
    const canvas = canvasRef.current;
    if (!canvas) return;
    const viewer = new BrowserViewer(canvas, chatId);
    viewerRef.current = viewer;
    if (onBrowserViewerRef) onBrowserViewerRef(viewer);
    viewer.connect().then(ok => {
      setConnecting(false);
      if (ok) {
        setConnected(true);
        canvas.focus();
      } else {
        setError(true);
        viewerRef.current = null;
      }
    });

    return () => {
      if (viewerRef.current) { viewerRef.current.disconnect(); viewerRef.current = null; }
    };
  }, [browserActive]);

  if (!browserActive) {
    return html`
      <div class="browser-panel">
        <div class="empty-state">
          <div class="empty-icon" dangerouslySetInnerHTML=${{ __html: icon('globe', 48) }}></div>
          <div class="empty-title">${t('browser_title')}</div>
          <div class="empty-desc" dangerouslySetInnerHTML=${{ __html: t('browser_desc') }}></div>
          <div class="empty-example" dangerouslySetInnerHTML=${{ __html: t('browser_example') }}></div>
        </div>
      </div>
    `;
  }

  return html`
    <div class="browser-panel">
      ${connecting && html`<div class="browser-connecting"><div class="spinner"></div> ${t('loading_browser')}</div>`}
      ${error && html`<div class="browser-connecting">${t('browser_connect_fail')}</div>`}
      <canvas ref=${canvasRef} tabindex="0" style="display:${connected ? '' : 'none'};flex:1;width:100%;object-fit:contain;cursor:pointer;background:var(--bg-primary)"></canvas>
      <div ref=${urlBarRef} class="browser-url-bar" id="browserUrlBar" style="display:${connected ? '' : 'none'}"></div>
    </div>
  `;
}

function TerminalDashboard({ chatId, dangerousMode, onToggleDangerous, onStartSession, onResumeSession }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [sResp, sessResp, procResp, uplResp] = await Promise.all([
        fetch(`/terminal/${chatId}/status?_t=${Date.now()}`),
        fetch(`/terminal/${chatId}/sessions?_t=${Date.now()}`),
        fetch(`/terminal/${chatId}/processes?_t=${Date.now()}`),
        fetch(`/api/uploads/${chatId}/list?_t=${Date.now()}`),
      ]);
      setData({
        status: await sResp.json(),
        sessions: await sessResp.json(),
        processes: await procResp.json(),
        uploads: await uplResp.json(),
      });
    } catch(e) {
      setData({ status: { active: false }, sessions: { sessions: [] }, processes: { processes: [] }, uploads: { files: [], total: 0 } });
    }
    setLoading(false);
  }, [chatId]);

  useEffect(() => { fetchData(); }, []);

  const uploadFile = useCallback((evt) => {
    if (evt) evt.stopPropagation();
    const input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.style.display = 'none';
    document.body.appendChild(input);
    input.addEventListener('change', async () => {
      for (const file of input.files) {
        const formData = new FormData();
        formData.append('file', file);
        await fetch(`/api/uploads/${chatId}/${encodeURIComponent(file.name)}`, { method: 'POST', body: formData });
      }
      input.remove();
      fetchData();
    });
    input.click();
  }, [chatId]);

  const killProcess = useCallback(async (pid) => {
    try { await fetch(`/terminal/${chatId}/processes/${pid}/kill`, { method: 'POST' }); } catch(e) {}
    fetchData();
  }, [chatId]);

  const copyPath = useCallback((path) => {
    copyText(path).then(() => showToast(t('copied')));
  }, []);

  if (loading || !data) {
    return html`<div class="dash-scroll" style="display:flex;align-items:center;justify-content:center;height:100%"><div class="spinner"></div></div>`;
  }

  const { status, sessions, processes, uploads } = data;
  const hasProcesses = processes.processes.length > 0;
  const hasSessions = sessions.sessions.length > 0;
  const hasUploads = uploads.files && uploads.files.length > 0;

  return html`
    <div class="dash-scroll">
      <div class="dash-hero">
        <h3>Claude Code <span class="badge">${t('beta')}</span></h3>
        <p>${t('hero_desc')}</p>
        <p class="warn">${t('pd_warning')}</p>
        <div class="dangerous-toggle-row ${dangerousMode ? 'active' : ''}" onClick=${() => onToggleDangerous(!dangerousMode)}>
          <div class="dangerous-toggle-track ${dangerousMode ? 'on' : ''}">
            <div class="dangerous-toggle-knob"></div>
          </div>
          <div class="dangerous-toggle-label">
            <span class="dangerous-toggle-title">${t('skip_perms')}</span>
            ${dangerousMode && html`<span class="dangerous-toggle-warn">${t('dangerous_warn')}</span>`}
          </div>
        </div>
        <div class="dash-actions">
          <button class="dash-btn-primary" onClick=${() => onStartSession()}>
            <span class="icon-inline" dangerouslySetInnerHTML=${{ __html: icon('play') }}></span> ${t('open_terminal')}
          </button>
          <button class="dash-btn-secondary" onClick=${uploadFile}>
            <span class="icon-inline" dangerouslySetInnerHTML=${{ __html: icon('upload') }}></span> ${t('upload_file')}
          </button>
          <a class="dash-link" href="https://wiki.example.com/spaces/AIT/pages/286686279" target="_blank">
            <span class="icon-inline" dangerouslySetInnerHTML=${{ __html: icon('book') }}></span> ${t('how_to_use')}
          </a>
        </div>
      </div>

      ${hasProcesses && html`
        <div class="dash-card">
          <h4><span class="icon-inline" dangerouslySetInnerHTML=${{ __html: icon('settings') }}></span> ${t('running_now')}</h4>
          ${processes.processes.map(p => {
            const mins = p.elapsed_minutes || 0;
            const timeStr = mins < 1 ? t('less_than_min') : mins + t('min_suffix');
            return html`
              <div class="dash-process">
                <span class="dot"></span>
                <span>${t('claude_running')} · ${timeStr}</span>
                <button class="action-btn kill-btn" onClick=${() => killProcess(p.pid)}>${t('stop')}</button>
              </div>
            `;
          })}
        </div>
      `}

      ${hasUploads && html`
        <div class="dash-card">
          <h4><span class="icon-inline" dangerouslySetInnerHTML=${{ __html: icon('paperclip') }}></span> ${t('uploaded_files')}</h4>
          <table class="dash-table">
            <thead><tr><th>${t('th_file')}</th><th>${t('th_size')}</th><th></th></tr></thead>
            <tbody>
              ${uploads.files.map(f => html`
                  <tr>
                    <td>${f.name}</td>
                    <td style="white-space:nowrap">${formatSize(f.size)}</td>
                    <td><button class="action-btn" onClick=${() => copyPath(f.container_path)} title=${f.container_path}>
                      <span class="icon-inline" dangerouslySetInnerHTML=${{ __html: icon('copy') }}></span> ${t('copy_path')}
                    </button></td>
                  </tr>
              `)}
            </tbody>
          </table>
        </div>
      `}

      ${hasSessions && html`
        <div class="dash-card">
          <h4><span class="icon-inline" dangerouslySetInnerHTML=${{ __html: icon('fileText') }}></span> ${t('prev_sessions')}</h4>
          <table class="dash-table">
            <thead><tr><th>${t('th_task')}</th><th>${t('th_date')}</th><th></th></tr></thead>
            <tbody>
              ${sessions.sessions.map(s => {
                const dt = s.timestamp ? new Date(s.timestamp * 1000).toLocaleDateString(LANG === 'ru' ? 'ru-RU' : 'en-US', { day: 'numeric', month: 'short' }) : '';
                const name = (s.label || s.session_id.substring(0, 16) + '...').substring(0, 50);
                return html`
                  <tr>
                    <td title=${s.session_id}>${name}</td>
                    <td>${dt}</td>
                    <td><button class="action-btn" onClick=${() => onResumeSession(s.session_id)}>${t('resume')}</button></td>
                  </tr>
                `;
              })}
            </tbody>
          </table>
        </div>
      `}

      ${!status.active && !hasSessions && !hasProcesses && html`
        <div class="dash-hint">${t('dash_hint')}</div>
      `}
    </div>
  `;
}

function TerminalSession({ chatId, resumeId, dangerousMode, onBack }) {
  const containerRef = useRef(null);
  const xtermRef = useRef(null);
  const fitAddonRef = useRef(null);
  const wsRef = useRef(null);
  const reconnectAttemptsRef = useRef(0);
  const dangerousModeRef = useRef(dangerousMode);
  useEffect(() => { dangerousModeRef.current = dangerousMode; }, [dangerousMode]);
  const [startError, setStartError] = useState(null);
  const [selectMode, setSelectMode] = useState(false);

  const connectWs = useCallback((rId) => {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${location.host}/terminal/${chatId}/ws`, ['tty']);
    ws.binaryType = 'arraybuffer';
    wsRef.current = ws;

    let receivedData = false;
    ws.onopen = () => {
      const dims = fitAddonRef.current ? fitAddonRef.current.proposeDimensions() : { cols: 80, rows: 24 };
      ws.send(JSON.stringify({ authToken: '', columns: dims.cols || 80, rows: dims.rows || 24 }));
      if (rId) {
        // Check if Claude Code is running, then send appropriate resume sequence
        (async () => {
          const dangerous = dangerousModeRef.current;
          const flagSuffix = dangerous ? ' --dangerously-skip-permissions' : '';
          try {
            const resp = await fetch(`/terminal/${chatId}/processes?_t=${Date.now()}`);
            const data = await resp.json();
            const hasClaudeRunning = data.processes && data.processes.length > 0;
            if (hasClaudeRunning) {
              // Claude Code active — double Ctrl+C to exit, then resume
              ws.send(new TextEncoder().encode('\x30\x03')); // Ctrl+C #1
              await new Promise(r => setTimeout(r, 500));
              ws.send(new TextEncoder().encode('\x30\x03')); // Ctrl+C #2
              await new Promise(r => setTimeout(r, 1500));
            } else {
              // No Claude Code — just wait for bash prompt
              await new Promise(r => setTimeout(r, 1000));
            }
            ws.send(new TextEncoder().encode('\x30claude --resume ' + rId + flagSuffix + '\r'));
          } catch(e) {
            // Fallback: just send resume after delay
            await new Promise(r => setTimeout(r, 2000));
            ws.send(new TextEncoder().encode('\x30claude --resume ' + rId + (dangerousModeRef.current ? ' --dangerously-skip-permissions' : '') + '\r'));
          }
        })();
      } else if (dangerousModeRef.current) {
        // New session in dangerous mode — CLAUDE_AUTOSTARTED=1 prevented .bashrc autostart,
        // so we wait for the bash prompt and inject the command with the flag.
        // For reconnects where claude is already running — leave it undisturbed.
        (async () => {
          await new Promise(r => setTimeout(r, 1500));
          try {
            const resp = await fetch(`/terminal/${chatId}/processes?_t=${Date.now()}`);
            const data = await resp.json();
            const hasClaudeRunning = data.processes && data.processes.length > 0;
            if (!hasClaudeRunning && ws.readyState === WebSocket.OPEN) {
              ws.send(new TextEncoder().encode('\x30claude --dangerously-skip-permissions\r'));
            }
          } catch(e) {
            if (ws.readyState === WebSocket.OPEN)
              ws.send(new TextEncoder().encode('\x30claude --dangerously-skip-permissions\r'));
          }
        })();
      }
    };

    ws.onmessage = (ev) => {
      if (!receivedData) { receivedData = true; reconnectAttemptsRef.current = 0; }
      if (ev.data instanceof ArrayBuffer && xtermRef.current) {
        const data = new Uint8Array(ev.data);
        if (data.length > 1) {
          const type = data[0];
          if (type === 0x30) { xtermRef.current.write(data.slice(1)); }
          else if (type === 0x31 || type === 0x32) { /* ignore title/prefs */ }
          else { xtermRef.current.write(data); }
        }
      }
    };

    ws.onclose = () => {
      if (xtermRef.current) {
        if (reconnectAttemptsRef.current < 3) {
          const delay = 1000 * Math.pow(2, reconnectAttemptsRef.current);
          reconnectAttemptsRef.current++;
          setTimeout(() => connectWs(), delay);
        } else {
          xtermRef.current.write('\r\n\x1b[90m' + t('session_ended') + '\x1b[0m\r\n');
          setTimeout(() => onBack(), 2000);
        }
      }
    };
  }, [chatId, onBack]);

  const [ready, setReady] = useState(false);

  // Phase 1: start ttyd (if not already running)
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(`/terminal/${chatId}/start-ttyd`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ dangerous_mode: dangerousModeRef.current }),
        });
        if (!resp.ok) {
          if (!cancelled) {
            // Check if container is stopped (can be restarted) or removed with meta (can be resurrected)
            try {
              const statusResp = await fetch(`/terminal/${chatId}/status?_t=${Date.now()}`);
              const statusData = await statusResp.json();
              if (statusData.container_stopped) {
                setStartError('__stopped__');
              } else if (statusData.meta_exists) {
                setStartError('__meta_exists__');
              } else {
                setStartError(t('terminal_fail'));
              }
            } catch { setStartError(t('terminal_fail')); }
          }
          return;
        }
        const data = await resp.json();
        // If already running, shorter wait (just need WS connection)
        const wait = data.already_running ? 500 : 1500;
        await new Promise(r => setTimeout(r, wait));
      } catch(e) { if (!cancelled) setStartError(t('server_fail')); return; }
      if (!cancelled) setReady(true);
    })();
    return () => { cancelled = true; };
  }, [chatId]);

  // Phase 2: init xterm + connect WS (only after ttyd is ready)
  useEffect(() => {
    if (!ready || !containerRef.current) return;

    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: "'JetBrains Mono', 'Fira Code', Monaco, monospace",
      scrollback: 10000,
      fastScrollModifier: 'shift',
      rightClickSelectsWord: true,
      macOptionClickForcesSelection: true,
      theme: {
        background: '#1a1b26',
        foreground: '#c0caf5',
        cursor: '#c0caf5',
        selectionBackground: '#33467c',
      },
    });
    // Copy: Cmd+C (Mac), Ctrl+Shift+C (Linux) — handle directly in key handler, don't send to terminal
    // Paste: Cmd+V (Mac), Ctrl+V / Ctrl+Shift+V (Windows/Linux) — read clipboard and paste
    term.attachCustomKeyEventHandler((ev) => {
      if (ev.type !== 'keydown') return true;
      const isCopy = (ev.metaKey && ev.key === 'c') ||
                     (ev.ctrlKey && ev.shiftKey && ev.key === 'C');
      const isPaste = (ev.metaKey && ev.key === 'v') ||
                      (ev.ctrlKey && ev.key === 'v');
      if (ev.metaKey && ev.key === 'a') {
        term.selectAll();
        return false;
      }
      if (isCopy) {
        if (term.hasSelection()) navigator.clipboard.writeText(term.getSelection()).catch(() => {});
        return false;
      }
      if (isPaste) {
        navigator.clipboard.readText().then(text => {
          if (xtermRef.current) xtermRef.current.paste(text);
        }).catch(() => {});
        return false;
      }
      return true;
    });
    const fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    try { term.loadAddon(new WebLinksAddon.WebLinksAddon()); } catch(e) {}
    term.open(containerRef.current);
    fitAddon.fit();
    xtermRef.current = term;
    // Mouse select auto-copy: onSelectionChange fires synchronously from mouseup (user gesture)
    term.onSelectionChange(() => {
      if (term.hasSelection()) navigator.clipboard.writeText(term.getSelection()).catch(() => {});
    });
    fitAddonRef.current = fitAddon;

    term.onData((data) => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(new TextEncoder().encode('\x30' + data));
      }
    });

    const ro = new ResizeObserver(() => {
      if (fitAddonRef.current && xtermRef.current) {
        fitAddonRef.current.fit();
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
          const dims = fitAddonRef.current.proposeDimensions();
          if (dims) {
            wsRef.current.send(new TextEncoder().encode('\x31' + JSON.stringify({ columns: dims.cols, rows: dims.rows })));
          }
        }
      }
    });
    ro.observe(containerRef.current);

    connectWs(resumeId);

    return () => {
      ro.disconnect();
      if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
      if (xtermRef.current) { xtermRef.current.dispose(); xtermRef.current = null; }
    };
  }, [ready]);

  const handleToggleSelectMode = useCallback(() => {
    if (!xtermRef.current) return;
    setSelectMode(prev => {
      const enabling = !prev;
      if (enabling) {
        // Disable mouse event reporting — xterm stops forwarding mouse to terminal, drag selects text
        xtermRef.current.write('\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l');
      } else {
        // Re-enable mouse event reporting
        xtermRef.current.write('\x1b[?1000h\x1b[?1002h\x1b[?1006h');
      }
      return enabling;
    });
  }, []);

  const handleClear = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      // Send Ctrl+L
      wsRef.current.send(new TextEncoder().encode('\x30\x0c'));
    }
  }, []);

  const handleKill = useCallback(async () => {
    // Send Ctrl+C
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(new TextEncoder().encode('\x30\x03'));
    }
    // Kill claude processes
    try {
      const resp = await fetch(`/terminal/${chatId}/processes?_t=${Date.now()}`);
      const data = await resp.json();
      for (const p of (data.processes || [])) {
        await fetch(`/terminal/${chatId}/processes/${p.pid}/kill`, { method: 'POST' });
      }
    } catch(e) {}
    // Kill ttyd + tmux so next "Open terminal" starts fresh (with .bashrc → Claude Code autostart)
    try {
      await fetch(`/terminal/${chatId}/stop-ttyd`, { method: 'POST' });
    } catch(e) {}
    if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
    if (xtermRef.current) { xtermRef.current.dispose(); xtermRef.current = null; }
    onBack();
  }, [chatId, onBack]);

  if (startError) {
    const isStopped = startError === '__stopped__';
    const isMetaExists = startError === '__meta_exists__';
    const canRecover = isStopped || isMetaExists;
    const [restarting, setRestarting] = useState(false);

    const handleRestart = async () => {
      setRestarting(true);
      try {
        const endpoint = isMetaExists
          ? `/terminal/${chatId}/resurrect-container`
          : `/terminal/${chatId}/restart-container`;
        const resp = await fetch(endpoint, { method: 'POST' });
        if (resp.ok) {
          setStartError(null);
          setReady(false);
          // Re-trigger Phase 1: start ttyd
          const ttydResp = await fetch(`/terminal/${chatId}/start-ttyd`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dangerous_mode: dangerousModeRef.current }),
          });
          if (ttydResp.ok) {
            const data = await ttydResp.json();
            await new Promise(r => setTimeout(r, isMetaExists ? 2500 : (data.already_running ? 500 : 1500)));
            setReady(true);
            return;
          }
        }
        setStartError(t('restore_fail'));
      } catch { setStartError(t('restore_fail')); }
      setRestarting(false);
    };

    return html`
      <div class="empty-state">
        <div class="empty-icon" dangerouslySetInnerHTML=${{ __html: icon('terminal', 48) }}></div>
        <div class="empty-title">${
          isStopped ? t('container_stopped')
          : isMetaExists ? t('container_removed')
          : startError
        }</div>
        <div class="empty-desc">${
          isStopped ? t('container_stopped_desc')
          : isMetaExists ? t('container_removed_desc')
          : t('container_generic_desc')
        }</div>
        ${canRecover && html`
          <button class="dash-btn-primary" onClick=${handleRestart} disabled=${restarting}>
            <span class="icon-inline" dangerouslySetInnerHTML=${{ __html: icon('play') }}></span>
            ${restarting
              ? (isMetaExists ? t('restoring') : t('starting'))
              : (isMetaExists ? t('restore_container') : t('restart_container'))
            }
          </button>
        `}
        <button class="btn" onClick=${onBack}>
          <span class="icon-inline" dangerouslySetInnerHTML=${{ __html: icon('arrowLeft') }}></span> ${t('back')}
        </button>
      </div>
    `;
  }

  if (!ready) {
    return html`
      <div class="empty-state">
        <div class="spinner"></div>
        <div class="empty-title">${t('starting_terminal')}</div>
      </div>
    `;
  }

  return html`
    <div class="terminal-view">
      <div class="terminal-toolbar">
        <button class="terminal-btn" onClick=${onBack}>
          <span class="icon-inline" dangerouslySetInnerHTML=${{ __html: icon('arrowLeft') }}></span> ${t('back')}
        </button>
        <div style="flex:1"></div>
        <button class="terminal-btn ${selectMode ? 'terminal-btn-active' : ''}" onClick=${handleToggleSelectMode} title="${t('select_mode_title')}">
          ${selectMode ? t('select_on') : t('select_off')}
        </button>
        <button class="terminal-btn terminal-btn-danger" onClick=${handleKill}>
          <span class="icon-inline" dangerouslySetInnerHTML=${{ __html: icon('stop') }}></span> ${t('terminate')}
        </button>
      </div>
      <div class="terminal-container" ref=${containerRef}></div>
    </div>
  `;
}

function TerminalView({ chatId }) {
  const [mode, setMode] = useState('dashboard');
  const [resumeId, setResumeId] = useState(null);
  const [dangerousMode, setDangerousMode] = useState(() => {
    try { return localStorage.getItem('claudeDangerousMode') === '1'; } catch(e) { return false; }
  });
  const toggleDangerous = useCallback((val) => {
    setDangerousMode(val);
    try { localStorage.setItem('claudeDangerousMode', val ? '1' : '0'); } catch(e) {}
  }, []);

  if (mode === 'terminal') {
    return html`<${TerminalSession}
      chatId=${chatId}
      resumeId=${resumeId}
      dangerousMode=${dangerousMode}
      onBack=${() => { setMode('dashboard'); setResumeId(null); }}
    />`;
  }

  return html`<${TerminalDashboard}
    chatId=${chatId}
    dangerousMode=${dangerousMode}
    onToggleDangerous=${toggleDangerous}
    onStartSession=${() => { setResumeId(null); setMode('terminal'); }}
    onResumeSession=${(id) => { setResumeId(id); setMode('terminal'); }}
  />`;
}

// =============================================================================
// App
// =============================================================================

function App() {
  const [files, setFiles] = useState([]);
  const [selectedFile, setSelectedFile] = useState(null);
  const [currentView, setCurrentView] = useState('files');
  const [browserActive, setBrowserActive] = useState(false);
  const [terminalActive, setTerminalActive] = useState(false);
  const [seenFiles, setSeenFiles] = useState(new Set());
  const fileModTimesRef = useRef(new Map());
  const browserViewerRef = useRef(null);
  const lastSyncTimeRef = useRef(null);
  const syncDotRef = useRef(null);

  // Fetch files
  const fetchFiles = useCallback(async () => {
    const dot = syncDotRef.current;
    if (dot) { dot.classList.add('syncing'); dot.title = t('checking'); }
    try {
      const resp = await fetch(`${API_URL}?_t=${Date.now()}`, { cache: 'no-store' });
      const data = await resp.json();
      const newFiles = data.files;

      let autoSelectTarget = null;
      const modTimes = fileModTimesRef.current;
      for (const f of newFiles) {
        const prevMod = modTimes.get(f.path);
        const isRoot = !f.path.includes('/');
        if (prevMod === undefined && isRoot) { autoSelectTarget = f; break; }
        else if (f.modified && f.modified !== prevMod && isRoot) { autoSelectTarget = f; break; }
      }

      modTimes.clear();
      for (const f of newFiles) { modTimes.set(f.path, f.modified || null); }

      setFiles(newFiles);

      if (autoSelectTarget) {
        setSelectedFile(autoSelectTarget);
      } else if (newFiles.length > 0) {
        setSelectedFile(prev => {
          if (!prev) return newFiles.find(f => !f.path.includes('/')) || newFiles[0];
          const updated = newFiles.find(f => f.path === prev.path);
          // Return SAME reference if path+modified unchanged — prevents re-render and scroll reset
          return updated && updated.path === prev.path && updated.modified === prev.modified ? prev : (updated || prev);
        });
      }

      setSeenFiles(prev => {
        const next = new Set(prev);
        newFiles.forEach(f => next.add(f.path));
        return next;
      });

      if (dot) { dot.classList.remove('syncing'); dot.title = t('synced'); }
      lastSyncTimeRef.current = Date.now();
    } catch (err) {
      if (dot) { dot.classList.remove('syncing'); dot.title = t('error'); }
      console.error('Poll error:', err);
    }
  }, []);

  // Check browser status
  const checkBrowserStatus = useCallback(async () => {
    try {
      const resp = await fetch(`/browser/${CHAT_ID}/status?_t=${Date.now()}`, { cache: 'no-store' });
      const data = await resp.json();
      setBrowserActive(prev => {
        if (data.active && !prev) {
          // Auto-switch to browser when first active
          setCurrentView('browser');
        }
        if (!data.active && prev && browserViewerRef.current?.connected) {
          return true; // Transient blip, keep active
        }
        return data.active;
      });
      // Update URL bar
      if (data.active && data.pages && data.pages.length > 0) {
        const urlBar = document.getElementById('browserUrlBar');
        if (urlBar) urlBar.textContent = data.pages[0].url || '';
      }
    } catch (e) {}
  }, []);

  // Check terminal status
  const checkTerminalStatus = useCallback(async () => {
    try {
      const resp = await fetch(`/terminal/${CHAT_ID}/processes?_t=${Date.now()}`, { cache: 'no-store' });
      const data = await resp.json();
      setTerminalActive(data.processes && data.processes.length > 0);
    } catch(e) {}
  }, []);

  // Polling loop
  useEffect(() => {
    const poll = async () => {
      await fetchFiles();
      await checkBrowserStatus();
      await checkTerminalStatus();
    };
    poll();
    let timer = setInterval(poll, 3000);

    const visHandler = () => {
      clearInterval(timer);
      if (document.hidden) {
        timer = setInterval(poll, 15000);
      } else {
        poll();
        timer = setInterval(poll, 3000);
      }
    };
    document.addEventListener('visibilitychange', visHandler);

    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', visHandler);
    };
  }, [fetchFiles, checkBrowserStatus, checkTerminalStatus]);

  // Listen for iframe link clicks
  useEffect(() => {
    const handler = (event) => {
      if (!event.data || event.data.type !== 'iframe-link-click') return;
      handleLinkClick(event.data.href, event.data.resolvedUrl, files, selectedFile, setSelectedFile);
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, [files, selectedFile]);

  const onSelectFile = useCallback((file) => {
    setSelectedFile(file);
  }, []);

  return html`
    <div class="toolbar">
      <div class="toolbar-left">
        <${ViewTabs}
          currentView=${currentView}
          onSwitch=${setCurrentView}
          browserActive=${browserActive}
          terminalActive=${terminalActive}
        />
        ${currentView === 'files' && files.length > 0 && html`
          <${FileSelector}
            files=${files}
            selectedFile=${selectedFile}
            seenFiles=${seenFiles}
            onSelect=${onSelectFile}
          />
        `}
      </div>
      <div class="toolbar-right">
        <a class="btn btn-icon" href=${location.href} target="_blank" rel="noopener" title="${t('open_new_tab')}">
          <span class="icon-inline" dangerouslySetInnerHTML=${{ __html: icon('externalLink') }}></span>
        </a>
        <div class="status">
          <span class="dot" ref=${syncDotRef} title="${t('waiting_files')}"></span>
        </div>
        ${currentView === 'files' && selectedFile && html`
          <a class="btn btn-icon" href="${selectedFile.url}?download=1" download title="${t('download_file')}">
            <span class="icon-inline" dangerouslySetInnerHTML=${{ __html: icon('download') }}></span>
          </a>
        `}
        ${currentView === 'files' && files.length > 0 && html`
          <a class="btn btn-icon" href="${FILES_BASE}/archive" download title="${t('download_all')}">
            <span class="icon-inline" dangerouslySetInnerHTML=${{ __html: icon('archive') }}></span>
          </a>
        `}
      </div>
    </div>

    <div style="display:${currentView === 'files' ? 'flex' : 'none'};flex:1;flex-direction:column;overflow:hidden">
      <${FilesView}
        files=${files}
        selectedFile=${selectedFile}
        onSelectFile=${onSelectFile}
      />
    </div>

    <div style="display:${currentView === 'browser' ? 'flex' : 'none'};flex:1;flex-direction:column;overflow:hidden">
      <${BrowserView}
        chatId=${CHAT_ID}
        browserActive=${browserActive}
        onBrowserViewerRef=${(v) => { browserViewerRef.current = v; }}
      />
    </div>

    <div class="terminal-panel" style="display:${currentView === 'terminal' ? 'flex' : 'none'}">
      <${TerminalView} chatId=${CHAT_ID} />
    </div>
  `;
}

// =============================================================================
// Mount
// =============================================================================

render(html`<${App} />`, document.getElementById('app'));
