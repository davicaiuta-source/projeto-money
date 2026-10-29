(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const HISTORY_KEY = "cupons-v1";
  const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
  const qtyFmt = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 3 });

  const views = ["scan", "loading", "error", "result", "history"];
  let current = null;      // cupom exibido
  let stream = null;
  let scanning = false;
  let detector = null;

  // ------------------------------------------------------------------ navegação

  function show(view, title) {
    views.forEach((v) => ($("view-" + v).hidden = v !== view));
    $("title").textContent = title || "Leitor de Cupom";
    $("btn-back").hidden = view === "scan" || view === "loading";
    $("btn-history").hidden = view === "history";
    if (view !== "scan") stopCamera();
    window.scrollTo(0, 0);
  }

  $("btn-back").onclick = () => show("scan");
  $("btn-retry").onclick = () => show("scan");
  $("btn-new").onclick = () => { show("scan"); startCamera(); };
  $("btn-history").onclick = () => { renderHistory(); show("history", "Histórico"); };

  function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => t.classList.remove("show"), 2500);
  }

  // ------------------------------------------------------------------ câmera

  async function getDetector() {
    if (detector !== null) return detector;
    detector = false;
    try {
      if ("BarcodeDetector" in window) {
        const formats = await BarcodeDetector.getSupportedFormats();
        if (formats.includes("qr_code")) detector = new BarcodeDetector({ formats: ["qr_code"] });
      }
    } catch (_) { /* usa jsQR */ }
    return detector;
  }

  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d", { willReadFrequently: true });

  // Decodifica a partir de <video> ou <img>; usa BarcodeDetector nativo quando existe.
  async function decode(source, w, h, maxSide = 800) {
    const det = await getDetector();
    if (det) {
      try {
        const codes = await det.detect(source);
        if (codes.length) return codes[0].rawValue;
      } catch (_) { /* cai no jsQR */ }
    }
    const scale = Math.min(1, maxSide / Math.max(w, h));
    canvas.width = Math.round(w * scale);
    canvas.height = Math.round(h * scale);
    ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
    const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const code = window.jsQR && jsQR(img.data, img.width, img.height, { inversionAttempts: "dontInvert" });
    return code ? code.data : null;
  }

  async function startCamera() {
    const hint = $("camera-hint");
    hint.hidden = true;
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      hint.textContent = "A câmera ao vivo só funciona em HTTPS. Use \"Ler de uma foto\" — funciona igual.";
      hint.hidden = false;
      return;
    }
    if (stream) return;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 1280 } },
      });
    } catch (e) {
      hint.textContent = e.name === "NotAllowedError"
        ? "Permissão da câmera negada. Libere nas configurações do navegador ou use \"Ler de uma foto\"."
        : "Não consegui abrir a câmera. Use \"Ler de uma foto\".";
      hint.hidden = false;
      return;
    }
    const video = $("video");
    video.srcObject = stream;
    await video.play().catch(() => {});
    $("scanner").classList.add("live");
    $("btn-camera").textContent = "Parar câmera";
    setupTorch();
    scanning = true;
    scanLoop();
  }

  function stopCamera() {
    scanning = false;
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
    $("video").srcObject = null;
    $("scanner").classList.remove("live");
    $("btn-camera").textContent = "Abrir câmera";
    $("btn-torch").hidden = true;
    $("btn-torch").classList.remove("on");
  }

  async function scanLoop() {
    const video = $("video");
    while (scanning) {
      if (video.readyState >= 2 && video.videoWidth) {
        const text = await decode(video, video.videoWidth, video.videoHeight, 640);
        if (text && scanning) {
          navigator.vibrate?.(80);
          handleCode(text);
          return;
        }
      }
      await new Promise((r) => setTimeout(r, 120));
    }
  }

  function setupTorch() {
    const track = stream?.getVideoTracks()[0];
    const caps = track?.getCapabilities?.() || {};
    const btn = $("btn-torch");
    if (!caps.torch) return;
    btn.hidden = false;
    btn.onclick = async () => {
      const on = !btn.classList.contains("on");
      try {
        await track.applyConstraints({ advanced: [{ torch: on }] });
        btn.classList.toggle("on", on);
      } catch (_) { toast("Lanterna indisponível"); }
    };
  }

  $("btn-camera").onclick = () => (stream ? stopCamera() : startCamera());

  // ------------------------------------------------------------------ foto

  $("file").onchange = async (ev) => {
    const file = ev.target.files[0];
    ev.target.value = "";
    if (!file) return;
    const url = URL.createObjectURL(file);
    try {
      const img = new Image();
      img.src = url;
      await img.decode();
      // Fotos de celular são grandes; tenta em alguns tamanhos até achar o QR.
      let text = null;
      for (const side of [1000, 1600, 700, 2400]) {
        text = await decode(img, img.naturalWidth, img.naturalHeight, side);
        if (text) break;
      }
      if (text) handleCode(text);
      else toast("Não achei um QR Code na foto. Tente aproximar e focar.");
    } catch (_) {
      toast("Não consegui abrir a imagem.");
    } finally {
      URL.revokeObjectURL(url);
    }
  };

  $("form-url").onsubmit = (ev) => {
    ev.preventDefault();
    handleCode($("input-url").value.trim());
  };

  // ------------------------------------------------------------------ consulta

  async function handleCode(text) {
    stopCamera();
    if (!/^https?:\/\//i.test(text)) {
      showError("Esse QR Code não é de um cupom fiscal. Procure o QR Code da NFC-e no rodapé do cupom.");
      return;
    }
    const cached = loadHistory().find((c) => c.url === text);
    if (cached) { showResult(cached); toast("Cupom já lido antes"); return; }

    show("loading");
    try {
      const resp = await fetch("/api/nfce?url=" + encodeURIComponent(text));
      const data = await resp.json().catch(() => ({ erro: "Resposta inválida do servidor." }));
      if (!resp.ok) { showError(data.erro, data.url); return; }
      data.lidoEm = new Date().toISOString();
      saveHistory(data);
      showResult(data);
    } catch (_) {
      showError("Sem conexão com o servidor. Verifique se o celular está na mesma rede do computador.");
    }
  }

  function showError(msg, url) {
    $("error-msg").textContent = msg || "Algo deu errado.";
    const link = $("error-link");
    link.hidden = !url;
    if (url) link.href = url;
    show("error", "Ops");
  }

  // ------------------------------------------------------------------ resultado

  function showResult(data) {
    current = data;
    $("r-store").textContent = data.emitente || "Estabelecimento";
    $("r-meta").textContent = [data.cnpj && "CNPJ " + data.cnpj, data.emissao].filter(Boolean).join(" · ");
    $("r-total").textContent = brl.format(data.total || 0);
    $("r-count").textContent = data.itens.length + (data.itens.length === 1 ? " item" : " itens");
    $("r-filter").value = "";
    renderItems();
    show("result", "Produtos");
  }

  function renderItems() {
    const q = normalize($("r-filter").value);
    const ul = $("r-items");
    ul.replaceChildren();
    for (const it of current.itens) {
      if (q && !normalize(it.nome).includes(q)) continue;
      const li = document.createElement("li");
      const name = document.createElement("span");
      name.className = "name";
      name.textContent = it.nome;
      const price = document.createElement("span");
      price.className = "price";
      price.textContent = it.valorTotal != null ? brl.format(it.valorTotal) : "—";
      const detail = document.createElement("span");
      detail.className = "detail";
      const parts = [`${qtyFmt.format(it.quantidade ?? 0)} ${it.unidade || ""}`.trim()];
      if (it.valorUnitario != null) parts.push("× " + brl.format(it.valorUnitario));
      if (it.codigo) parts.push("cód. " + it.codigo);
      detail.textContent = parts.join("  ");
      li.append(name, price, detail);
      ul.append(li);
    }
  }

  const normalize = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  $("r-filter").oninput = renderItems;

  function asText(c) {
    const lines = c.itens.map((i) =>
      `${i.nome} — ${qtyFmt.format(i.quantidade ?? 0)} ${i.unidade || ""} — ${i.valorTotal != null ? brl.format(i.valorTotal) : ""}`);
    return [c.emitente, c.emissao, "", ...lines, "", "Total: " + brl.format(c.total || 0)].filter((l) => l != null).join("\n");
  }

  $("btn-share").onclick = async () => {
    const text = asText(current);
    if (navigator.share) {
      try { await navigator.share({ title: "Cupom " + (current.emitente || ""), text }); } catch (_) {}
      return;
    }
    try { await navigator.clipboard.writeText(text); toast("Lista copiada"); }
    catch (_) { toast("Não foi possível copiar"); }
  };

  $("btn-csv").onclick = () => {
    const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const num = (n) => (n == null ? "" : String(n).replace(".", ","));
    const rows = [["Produto", "Código", "Quantidade", "Unidade", "Valor unitário", "Valor total"]];
    current.itens.forEach((i) => rows.push([i.nome, i.codigo, num(i.quantidade), i.unidade, num(i.valorUnitario), num(i.valorTotal)]));
    const csv = "﻿" + rows.map((r) => r.map(esc).join(";")).join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const date = (current.emissao || "").slice(0, 10).split("/").reverse().join("-");
    a.download = `cupom-${date || "nfce"}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };

  // ------------------------------------------------------------------ histórico

  function loadHistory() {
    try { return JSON.parse(localStorage.getItem(HISTORY_KEY)) || []; }
    catch (_) { return []; }
  }

  function storeHistory(list) {
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, 100))); } catch (_) {}
  }

  function saveHistory(data) {
    storeHistory([data, ...loadHistory().filter((c) => c.url !== data.url)]);
  }

  function renderHistory() {
    const list = loadHistory();
    const ul = $("h-list");
    ul.replaceChildren();
    $("h-empty").hidden = list.length > 0;
    list.forEach((c) => {
      const li = document.createElement("li");
      const info = document.createElement("div");
      info.className = "info";
      const b = document.createElement("b");
      b.textContent = c.emitente || "Estabelecimento";
      const span = document.createElement("span");
      span.textContent = `${c.emissao || new Date(c.lidoEm).toLocaleString("pt-BR")} · ${c.itens.length} itens`;
      info.append(b, span);
      info.onclick = () => showResult(c);
      const amount = document.createElement("span");
      amount.className = "amount";
      amount.textContent = brl.format(c.total || 0);
      const del = document.createElement("button");
      del.className = "icon-btn";
      del.setAttribute("aria-label", "Apagar");
      del.innerHTML = '<svg viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/></svg>';
      del.onclick = () => {
        storeHistory(loadHistory().filter((x) => x.url !== c.url));
        renderHistory();
      };
      li.append(info, amount, del);
      ul.append(li);
    });
  }

  // Abre direto a câmera quando possível (ou mostra a dica sobre HTTPS).
  startCamera();
})();
