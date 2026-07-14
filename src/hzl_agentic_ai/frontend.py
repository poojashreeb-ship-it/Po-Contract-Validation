"""Self-contained browser page for manually running the full-report pipeline.

No build step, no external CDN/framework — a single HTML file with inline
CSS/JS, matching the project's minimal-dependency footprint. The only
non-obvious part is the API key: every other route requires the `X-API-Key`
header (see auth.py), but a browser's plain navigation to `/` can't attach
one, so the server embeds the key it already has (from `.env`) straight into
this page's JS, and every fetch() call from here attaches it itself.
"""
import json
from string import Template

_PAGE = Template(r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PO/Contract Validation</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>%F0%9F%93%8B</text></svg>">
<style>
  :root {
    color-scheme: light dark;
    --bg: #f4f6f8;
    --card: #ffffff;
    --text: #1a2027;
    --muted: #667085;
    --border: #dde3ea;
    --accent: #2f5fd9;
    --accent-hover: #2650b8;
    --accent-soft: #eaf0ff;
    --ok: #1e7e34;
    --ok-bg: #e9f7ef;
    --warn: #b45309;
    --error: #c62828;
    --error-bg: #fdecea;
    --shadow: 0 1px 3px rgba(16, 24, 40, 0.08), 0 8px 24px rgba(16, 24, 40, 0.06);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #10151c;
      --card: #1a212b;
      --text: #e6e9ee;
      --muted: #9aa5b1;
      --border: #2b3440;
      --accent: #6a8dfb;
      --accent-hover: #85a1fc;
      --accent-soft: #1e2942;
      --ok: #4caf6d;
      --ok-bg: #10281a;
      --warn: #e0a458;
      --error: #ef5350;
      --error-bg: #2c1616;
      --shadow: 0 1px 3px rgba(0, 0, 0, 0.3), 0 8px 24px rgba(0, 0, 0, 0.35);
    }
  }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    margin: 0;
    padding: 2.5rem 1rem;
    display: flex;
    justify-content: center;
  }
  .card {
    width: 100%;
    max-width: 560px;
    background: var(--card);
    border-radius: 16px;
    box-shadow: var(--shadow);
    padding: 2rem;
  }
  header { margin-bottom: 1.75rem; }
  h1 { font-size: 1.4rem; margin: 0 0 0.35rem; }
  .subtitle { color: var(--muted); font-size: 0.9rem; margin: 0; line-height: 1.5; }

  .dropzone {
    display: flex;
    align-items: center;
    gap: 0.85rem;
    border: 1.5px dashed var(--border);
    border-radius: 12px;
    padding: 0.9rem 1rem;
    margin-top: 0.9rem;
    cursor: pointer;
    transition: border-color 0.15s ease, background 0.15s ease;
    position: relative;
  }
  .dropzone:hover, .dropzone.drag-over { border-color: var(--accent); background: var(--accent-soft); }
  .dropzone.has-file { border-style: solid; border-color: var(--accent); }
  .dropzone .icon { font-size: 1.4rem; line-height: 1; flex-shrink: 0; }
  .dropzone .text { min-width: 0; }
  .dropzone .label { font-weight: 600; font-size: 0.92rem; }
  .dropzone .filename {
    display: block;
    font-size: 0.82rem;
    color: var(--muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    margin-top: 0.1rem;
  }
  .dropzone input[type=file] {
    position: absolute;
    inset: 0;
    opacity: 0;
    cursor: pointer;
    width: 100%;
    height: 100%;
  }

  button#process-btn {
    width: 100%;
    margin-top: 1.5rem;
    padding: 0.8rem 1.2rem;
    font-size: 1rem;
    font-weight: 600;
    color: #fff;
    background: var(--accent);
    border: none;
    border-radius: 10px;
    cursor: pointer;
    transition: background 0.15s ease;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
  }
  button#process-btn:hover:not(:disabled) { background: var(--accent-hover); }
  button#process-btn:disabled { cursor: not-allowed; opacity: 0.7; }

  .spinner {
    width: 16px;
    height: 16px;
    border: 2px solid rgba(255, 255, 255, 0.4);
    border-top-color: #fff;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    display: none;
  }
  button#process-btn.busy .spinner { display: inline-block; }
  @keyframes spin { to { transform: rotate(360deg); } }

  #status {
    margin-top: 1.1rem;
    padding: 0.85rem 1rem;
    border-radius: 10px;
    font-size: 0.88rem;
    white-space: pre-wrap;
    line-height: 1.5;
    display: none;
  }
  #status.show { display: block; }
  #status.info { background: var(--accent-soft); color: var(--text); }
  #status.ok { background: var(--ok-bg); color: var(--ok); }
  #status.error { background: var(--error-bg); color: var(--error); }

  #downloads {
    margin-top: 1.1rem;
    display: none;
    gap: 0.75rem;
  }
  #downloads button {
    flex: 1;
    padding: 0.65rem 1rem;
    font-size: 0.9rem;
    font-weight: 600;
    border-radius: 10px;
    border: 1.5px solid var(--border);
    background: transparent;
    color: var(--text);
    cursor: pointer;
    transition: border-color 0.15s ease, background 0.15s ease;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.4rem;
  }
  #downloads button:hover { border-color: var(--accent); background: var(--accent-soft); }
</style>
</head>
<body>
  <div class="card">
    <header>
      <h1>PO / Contract Validation</h1>
      <p class="subtitle">Upload the PO, contract, and SAP data below to run extraction and both validation checks in one go.</p>
    </header>

    <form id="report-form">
      <label class="dropzone" id="po_file-zone" for="po_file">
        <span class="icon">📄</span>
        <span class="text">
          <span class="label">Purchase Order</span>
          <span class="filename" data-placeholder="PDF file">PDF file</span>
        </span>
        <input type="file" id="po_file" name="po_file" accept="application/pdf" required>
      </label>

      <label class="dropzone" id="contract_file-zone" for="contract_file">
        <span class="icon">📝</span>
        <span class="text">
          <span class="label">Contract</span>
          <span class="filename" data-placeholder="PDF file">PDF file</span>
        </span>
        <input type="file" id="contract_file" name="contract_file" accept="application/pdf" required>
      </label>

      <label class="dropzone" id="sap_file-zone" for="sap_file">
        <span class="icon">🧾</span>
        <span class="text">
          <span class="label">SAP Data</span>
          <span class="filename" data-placeholder="JSON file">JSON file</span>
        </span>
        <input type="file" id="sap_file" name="sap_file" accept="application/json" required>
      </label>

      <button type="submit" id="process-btn">
        <span class="spinner"></span>
        <span class="btn-label">Process</span>
      </button>
    </form>

    <div id="status"></div>

    <div id="downloads">
      <button type="button" id="download-json">⬇ JSON</button>
      <button type="button" id="download-pdf">⬇ PDF</button>
    </div>
  </div>

<script>
const API_KEY = $api_key_json;

const form = document.getElementById("report-form");
const processBtn = document.getElementById("process-btn");
const btnLabel = processBtn.querySelector(".btn-label");
const statusEl = document.getElementById("status");
const downloads = document.getElementById("downloads");

function setStatus(text, kind) {
  statusEl.textContent = text;
  statusEl.className = "show" + (kind ? " " + kind : "");
}

function clearStatus() {
  statusEl.className = "";
  statusEl.textContent = "";
}

// Wire up each dropzone: click-to-browse (native), filename preview, drag & drop.
["po_file", "contract_file", "sap_file"].forEach((id) => {
  const input = document.getElementById(id);
  const zone = document.getElementById(id + "-zone");
  const filenameEl = zone.querySelector(".filename");
  const placeholder = filenameEl.dataset.placeholder;

  function refresh() {
    if (input.files && input.files.length > 0) {
      filenameEl.textContent = input.files[0].name;
      zone.classList.add("has-file");
    } else {
      filenameEl.textContent = placeholder;
      zone.classList.remove("has-file");
    }
  }

  input.addEventListener("change", refresh);

  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("drag-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("drag-over");
    if (e.dataTransfer.files.length > 0) {
      input.files = e.dataTransfer.files;
      refresh();
    }
  });
});

async function downloadFile(path, filename) {
  const res = await fetch(path, { headers: { "X-API-Key": API_KEY } });
  if (!res.ok) {
    setStatus("Download failed: " + res.status + " " + (await res.text()), "error");
    return;
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

document.getElementById("download-json").addEventListener("click", () => {
  downloadFile("/ui/download/json", "full_report.json");
});
document.getElementById("download-pdf").addEventListener("click", () => {
  downloadFile("/ui/download/pdf", "full_report.pdf");
});

const STATUS_ICON = { PASS: "✅", PASS_WITH_WARNINGS: "⚠️", FAIL: "❌" };

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  processBtn.disabled = true;
  processBtn.classList.add("busy");
  btnLabel.textContent = "Processing...";
  downloads.style.display = "none";
  clearStatus();
  setStatus("Running extraction and validation — this can take 1-3 minutes.", "info");

  const formData = new FormData(form);
  try {
    const res = await fetch("/ui/process-full-report", {
      method: "POST",
      headers: { "X-API-Key": API_KEY },
      body: formData,
    });
    if (!res.ok) {
      const detail = await res.text();
      setStatus("Failed (" + res.status + ")\n" + detail, "error");
      return;
    }
    const bundle = await res.json();
    const lines = bundle.reports.map(
      (r) => (STATUS_ICON[r.overall_status] || "") + " " + r.validation_type + ": " + r.overall_status
    );
    setStatus("Done.\n" + lines.join("\n"), "ok");
    downloads.style.display = "flex";
  } catch (err) {
    setStatus("Request failed: " + err, "error");
  } finally {
    processBtn.disabled = false;
    processBtn.classList.remove("busy");
    btnLabel.textContent = "Process";
  }
});
</script>
</body>
</html>
""")


def render_page(api_key: str) -> str:
    return _PAGE.substitute(api_key_json=json.dumps(api_key))
