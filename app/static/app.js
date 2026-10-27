// Transmeet client: lobby, WebRTC call, microphone streaming and caption rendering.
"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  config: null,
  stream: null,          // local camera + mic
  ws: null,
  myId: null,
  room: null,
  peer: null,            // { id, name, lang, captionLang }
  pc: null,              // RTCPeerConnection
  pendingIce: [],
  audioCtx: null,
  leaving: false,
  latencies: [],
  transcript: [],        // { time, name, mine, text, translated, src, tgt }
  captionsOn: true,
  level: 0,              // current mic level (RMS), updated by the meter
  heardAt: 0,            // last time the mic level looked like a voice
  chunksSent: 0,         // audio chunks sent to the server (watchdog)
  meterCtx: null,
};

const ICON = {
  mic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>',
  micOff: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M9 9v2a3 3 0 0 0 5.1 2.1M15 9.3V6a3 3 0 0 0-5.9-.8M5 11a7 7 0 0 0 11.6 5.3M19 11a7 7 0 0 1-.4 2.3M12 18v3M3 3l18 18"/></svg>',
  cam: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="6" width="13" height="12" rx="2"/><path d="m16 10 5-3v10l-5-3z"/></svg>',
  camOff: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M16 16v1a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h2m4 0h5a1 1 0 0 1 1 1v3.3l5-3.3v10M3 3l18 18"/></svg>',
  panel: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16M18 8h-1M18 11h-1"/></svg>',
  shuffle: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12a8 8 0 1 1-2.3-5.7M20 4v4h-4"/></svg>',
};

// ------------------------------------------------------------------ helpers
function toast(text, ms = 2200) {
  const t = $("toast");
  t.textContent = text;
  t.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("show"), ms);
}
const randomRoom = () => {
  const w = ["blue", "red", "swift", "calm", "bright", "lunar", "amber", "nova", "cedar", "delta"];
  return `${w[Math.random() * w.length | 0]}-${w[Math.random() * w.length | 0]}-${Math.random().toString(36).slice(2, 6)}`;
};
const langName = (code) => code === "auto" ? "Auto-detect"
  : (state.config.languages.find((l) => l.code === code) || {}).name || code;
const inviteLink = () => `${location.origin}${location.pathname}?room=${encodeURIComponent(state.room)}`;
const copyInvite = async () => {
  try { await navigator.clipboard.writeText(inviteLink()); toast("Invite link copied"); }
  catch { prompt("Copy this link:", inviteLink()); }
};
const save = (k, v) => { try { localStorage.setItem("tm." + k, v); } catch {} };
const load = (k) => { try { return localStorage.getItem("tm." + k); } catch { return null; } };

function fillSelect(sel, value, withAuto = false) {
  // "Auto-detect" lets Whisper work out the spoken language each sentence (~0.5 s slower on CPU)
  const opts = (withAuto ? [{ code: "auto", name: "Auto-detect" }] : []).concat(state.config.languages);
  sel.innerHTML = opts.map((l) => `<option value="${l.code}">${l.name}</option>`).join("");
  if (value) sel.value = value;
  if (!sel.value) sel.selectedIndex = withAuto ? 1 : 0;
}

function setToggle(btn, on, iconOn, iconOff) {
  btn.classList.toggle("on", on);
  if (iconOn) btn.innerHTML = on ? iconOn : iconOff;
}

// ------------------------------------------------------------------ lobby
async function init() {
  state.config = await (await fetch("api/config")).json();
  const params = new URLSearchParams(location.search);
  $("room").value = params.get("room") || randomRoom();
  $("name").value = load("name") || "";
  const browserLang = (navigator.language || "en").slice(0, 2);
  const knownLang = state.config.languages.some((l) => l.code === browserLang) ? browserLang : "en";
  const defLang = load("lang") || "auto";      // auto-detect unless the person picked a language before
  fillSelect($("lang"), defLang, true);
  fillSelect($("captionLang"), load("captionLang") || (defLang === "auto" ? knownLang : defLang));
  $("lang").onchange = () => { if ($("lang").value !== "auto") $("captionLang").value = $("lang").value; };
  $("newRoom").innerHTML = ICON.shuffle;
  $("newRoom").onclick = () => { $("room").value = randomRoom(); };
  $("name").oninput = setMyInitial;
  setMyInitial();
  const ss = $("serverState");
  ss.innerHTML = `Server online<span class="ss-detail">&nbsp;· ${state.config.translator ? "Whisper + LibreTranslate" : "translator loading"}</span>`;
  ss.className = `server-state ${state.config.translator ? "ok" : "warn"}`;

  setToggle($("pvMic"), true, ICON.mic, ICON.micOff);
  setToggle($("pvCam"), true, ICON.cam, ICON.camOff);
  $("pvMic").onclick = () => toggleMic($("pvMic"));
  $("pvCam").onclick = () => toggleCam($("pvCam"));
  $("joinForm").onsubmit = (e) => { e.preventDefault(); join(); };

  $("joinBtn").disabled = true;            // enabled once camera/mic are ready
  if (await startMedia(load("mic"))) $("joinBtn").disabled = false;
  await listMics();
  $("micSelect").onchange = async () => {
    save("mic", $("micSelect").value);
    state.stream?.getTracks().forEach((t) => t.stop());
    $("joinBtn").disabled = !(await startMedia($("micSelect").value));
  };
}

const initial = (name) => (name || "").trim().charAt(0).toUpperCase();

function setMyInitial() {
  // shown in place of your video while the camera is off
  for (const id of ["previewOff", "localAvatar"]) $(id).firstElementChild.dataset.initial = initial($("name").value) || "·";
}

function showCamOff(off) {
  $("previewOff").classList.toggle("hidden", !off);
  $("localAvatar").classList.toggle("hidden", !off);
}

async function listMics() {
  // device labels are only visible after permission was granted, so do this after getUserMedia
  const mics = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "audioinput");
  const current = state.stream?.getAudioTracks()[0]?.getSettings().deviceId;
  $("micSelect").innerHTML = mics.map((d, i) =>
    `<option value="${d.deviceId}">${(d.label || `Microphone ${i + 1}`).replace(/</g, "&lt;")}</option>`).join("");
  if (current) $("micSelect").value = current;
}

async function startMedia(micId) {
  const audio = { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 };
  if (micId) audio.deviceId = { ideal: micId };
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({ audio, video: { width: 1280, height: 720 } });
  } catch (e) {
    try {
      state.stream = await navigator.mediaDevices.getUserMedia({ audio });
      $("lobbyMsg").textContent = "No camera found. You'll join with audio only.";
      showCamOff(true);
    } catch (e2) {
      $("lobbyMsg").textContent = location.protocol === "https:" || location.hostname === "localhost"
        ? "Transmeet needs your microphone. Allow access in the browser, then reload."
        : "Browsers only allow the microphone and camera over HTTPS. Open this page with https://";
      return false;
    }
  }
  $("preview").srcObject = state.stream;
  levelMeter();
  return true;
}

function levelMeter() {
  // Publishes the live mic level as --lvl: it drives the level bars, the avatar ring and the mic button glow.
  state.meterCtx?.close();
  const ctx = state.meterCtx = new AudioContext();
  const an = ctx.createAnalyser();
  an.fftSize = 1024;
  ctx.createMediaStreamSource(state.stream).connect(an);
  const data = new Float32Array(an.fftSize);
  const tick = () => {
    if (ctx.state === "closed") return;
    an.getFloatTimeDomainData(data);
    const rms = Math.sqrt(data.reduce((s, v) => s + v * v, 0) / data.length);
    const lvl = Math.min(1, rms * 6);
    state.level = rms;
    if (rms > 0.01) state.heardAt = performance.now();
    document.documentElement.style.setProperty("--lvl", lvl.toFixed(2));
    requestAnimationFrame(tick);
  };
  ctx.resume();
  tick();
}

function toggleMic(btn) {
  const t = state.stream?.getAudioTracks()[0];
  if (!t) return;
  t.enabled = !t.enabled;
  for (const b of [$("pvMic"), $("micBtn")]) setToggle(b, t.enabled, ICON.mic, ICON.micOff);
  $("micLabel").textContent = t.enabled ? "Mic live" : "Mic off";
  if (!t.enabled) send({ type: "flush" });   // finish the sentence that was in progress
}

function toggleCam() {
  const t = state.stream?.getVideoTracks()[0];
  if (!t) return toast("No camera found");
  t.enabled = !t.enabled;
  for (const b of [$("pvCam"), $("camBtn")]) setToggle(b, t.enabled, ICON.cam, ICON.camOff);
  showCamOff(!t.enabled);
  sendCamState();
}

// ------------------------------------------------------------------ call setup
async function join() {
  const name = $("name").value.trim();
  const room = $("room").value.trim().toLowerCase().replace(/[^a-z0-9-]/g, "");
  if (!name || !room) return;
  save("name", name); save("lang", $("lang").value); save("captionLang", $("captionLang").value);
  state.room = room;
  history.replaceState(null, "", `?room=${encodeURIComponent(room)}`);
  $("joinBtn").disabled = true;

  await startAudioCapture();
  $("lobby").classList.add("hidden");
  $("call").classList.remove("hidden");
  $("localVideo").srcObject = state.stream;
  $("roomLabel").textContent = room;
  fillSelect($("langCall"), $("lang").value, true);
  fillSelect($("captionLangCall"), $("captionLang").value);
  setToggle($("micBtn"), state.stream.getAudioTracks()[0]?.enabled ?? false, ICON.mic, ICON.micOff);
  setToggle($("camBtn"), state.stream.getVideoTracks()[0]?.enabled ?? false, ICON.cam, ICON.camOff);
  $("sideBtn").innerHTML = ICON.panel;
  setMyInitial();
  if (!state.stream.getVideoTracks()[0]?.enabled) showCamOff(true);
  updateMtChip();
  bindCallControls();
  connect();
}

function bindCallControls() {
  $("micBtn").onclick = () => toggleMic();
  $("camBtn").onclick = () => toggleCam();
  $("ccBtn").onclick = () => {
    state.captionsOn = !state.captionsOn;
    $("ccBtn").classList.toggle("on", state.captionsOn);
    $("captions").classList.toggle("off", !state.captionsOn);
  };
  $("sideBtn").onclick = () => {
    const stage = document.querySelector(".stage");
    stage.classList.toggle("no-side");
    $("sideBtn").classList.toggle("on", !stage.classList.contains("no-side"));
  };
  $("langCall").onchange = () => { save("lang", $("langCall").value); send({ type: "update", lang: $("langCall").value }); };
  $("captionLangCall").onchange = () => {
    save("captionLang", $("captionLangCall").value);
    send({ type: "update", captionLang: $("captionLangCall").value });
  };
  $("copyLink").onclick = copyInvite;
  $("copyLink2").onclick = copyInvite;
  $("download").onclick = downloadTranscript;
  $("leaveBtn").onclick = leave;
  $("bannerClose").onclick = () => hideBanner(true);
  startWatchdog();
}

// ------------------------------------------------------------------ banner + mic watchdog
function showBanner(key, text, button, onClick) {
  if (state.dismissed?.has(key)) return;
  state.bannerKey = key;
  $("bannerText").textContent = text;
  $("bannerBtn").classList.toggle("hidden", !button);
  $("bannerBtn").textContent = button || "";
  $("bannerClose").textContent = button ? "Later" : "Dismiss";
  $("bannerBtn").onclick = () => { onClick?.(); hideBanner(); };
  $("banner").classList.remove("hidden");
}

function hideBanner(dismiss = false, key = null) {
  if (key && state.bannerKey !== key) return;
  if (dismiss) (state.dismissed ||= new Set()).add(state.bannerKey);
  state.bannerKey = null;
  $("banner").classList.add("hidden");
}

function startWatchdog() {
  // Explains, in plain words, why no captions appear for you.
  const joinedAt = performance.now();
  let lastChunks = 0;
  setInterval(() => {
    const mic = state.stream?.getAudioTracks()[0];
    const now = performance.now();
    const flowing = state.chunksSent > lastChunks;
    lastChunks = state.chunksSent;
    if (!state.myId) return;
    if (!mic || mic.readyState === "ended") {
      showBanner("nomic", "Your microphone was disconnected. Reload the page to pick it again.");
    } else if (!mic.enabled) {
      showBanner("muted", "You are muted, so nothing you say is captioned.", "Unmute", () => toggleMic());
    } else if (!flowing) {
      showBanner("noflow", "Your microphone audio isn't reaching the server. Check your connection or reload.");
    } else if (now - Math.max(state.heardAt, joinedAt) > 10000) {
      showBanner("silent", "No sound from your microphone. Check the selected input.");
    } else if (["muted", "noflow", "silent", "nomic"].includes(state.bannerKey)) {
      hideBanner();
    }
  }, 2000);
}

async function startAudioCapture() {
  // Microphone -> AudioWorklet (16 kHz PCM) -> WebSocket -> server ASR
  state.audioCtx = new AudioContext();
  await state.audioCtx.audioWorklet.addModule("pcm-worklet.js");
  const src = state.audioCtx.createMediaStreamSource(state.stream);
  const node = new AudioWorkletNode(state.audioCtx, "pcm-capture", { numberOfInputs: 1, numberOfOutputs: 1 });
  node.port.onmessage = (e) => {
    if (state.ws?.readyState === WebSocket.OPEN && state.myId) {
      state.ws.send(e.data);
      state.chunksSent++;
    }
  };
  const mute = state.audioCtx.createGain();
  mute.gain.value = 0;               // keep the node pulled by the graph without playing it back
  src.connect(node).connect(mute).connect(state.audioCtx.destination);
  await state.audioCtx.resume();
}

function send(msg) {
  if (state.ws?.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify(msg));
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}${location.pathname.replace(/[^/]*$/, "")}ws/${state.room}`);
  ws.binaryType = "arraybuffer";
  state.ws = ws;
  setConn("Connecting", "warn");

  ws.onopen = () => {
    ws.send(JSON.stringify({ type: "join", name: load("name"), lang: $("langCall").value, captionLang: $("captionLangCall").value }));
    clearInterval(state.pingTimer);
    state.pingTimer = setInterval(() => send({ type: "ping" }), 20000);
  };
  ws.onmessage = (e) => onMessage(JSON.parse(e.data));
  ws.onclose = () => {
    clearInterval(state.pingTimer);
    state.myId = null;
    closePeer();
    if (state.leaving) return;
    setConn("Offline", "bad", "reconnecting");
    setTimeout(connect, 2000);
  };
}

async function onMessage(m) {
  switch (m.type) {
    case "joined":
      state.myId = m.id;
      setConn("Ready", "warn", "waiting for peer");
      // the newcomer starts the WebRTC negotiation with whoever is already there
      for (const p of m.peers) { setPeer(p); await startPeer(true); }
      break;
    case "peer-joined":
      setPeer(m.peer);
      toast(`${m.peer.name} joined` + (m.peer.lang === "auto" ? "" : ` (speaks ${langName(m.peer.lang)})`));
      await startPeer(false);
      break;
    case "peer-updated":
      if (m.peer.id === state.myId) break;
      setPeer(m.peer);
      break;
    case "peer-left":
      if (state.peer?.id === m.id) toast(`${state.peer.name} left`);
      closePeer();
      break;
    case "signal":
      await onSignal(m.from, m.data);
      break;
    case "caption":
      onCaption(m);
      break;
    case "speaking":
      if (m.id === state.myId) $("hearing").classList.toggle("hidden", !m.speaking);
      else $("remoteName").classList.toggle("talking", m.speaking);
      break;
    case "lang-hint":
      showBanner("lang", `You selected ${langName(m.selected)}, but it sounds like you are speaking ` +
        `${langName(m.detected)}. Captions will be wrong until this matches.`, `Switch to ${langName(m.detected)}`, () => {
        $("langCall").value = m.detected;
        save("lang", m.detected);
        send({ type: "update", lang: m.detected });
        toast(`Now transcribing you as ${langName(m.detected)}`);
      });
      break;
    case "error":
      state.leaving = true;
      alert(m.message || m.code);
      location.href = location.pathname;
      break;
  }
}

function setPeer(p) {
  state.peer = p;
  const tag = $("remoteName");
  tag.innerHTML = '<span class="bars" aria-hidden="true"><i></i><i></i><i></i><i></i></span><span></span><span class="lang"></span>';
  tag.children[1].textContent = p.name;
  tag.children[2].textContent = `· ${p.lang === "auto" ? "auto-detect" : langName(p.lang)}`;
  tag.classList.remove("hidden");
  $("remoteAvatar").firstElementChild.dataset.initial = initial(p.name) || "·";
  updateRemoteAvatar();
}

function updateRemoteAvatar() {
  // the avatar stands in for the other person's video until it arrives, or while their camera is off
  const hasVideo = $("remoteVideo").srcObject && state.remoteCam !== false;
  $("remoteAvatar").classList.toggle("hidden", !state.peer || hasVideo);
}

function sendCamState() {
  // tell the other side when the camera goes off; a disabled track would otherwise just show black
  if (state.peer) send({ type: "signal", to: state.peer.id, data: { cam: !!state.stream?.getVideoTracks()[0]?.enabled } });
}

function setConn(label, cls, detail = "") {
  const c = $("connState");
  c.innerHTML = "<i></i><b></b><span></span>";
  c.children[1].textContent = label;
  c.children[2].textContent = detail ? `· ${detail}` : "";
  c.className = `conn ${cls}`;
  c.title = detail ? `${label}, ${detail}` : label;
}

function updateMtChip() {
  const c = $("mtState");
  c.textContent = state.config.translator ? `Whisper ${state.config.model} → LibreTranslate` : "translator loading";
  c.className = `mono ${state.config.translator ? "dim" : "warn"}`;
}

// ------------------------------------------------------------------ WebRTC
async function startPeer(initiator) {
  closePeer(true);
  const pc = new RTCPeerConnection({ iceServers: state.config.iceServers });
  state.pc = pc;
  state.pendingIce = [];
  // Only the newcomer makes offers; this fires once the tracks below are added.
  pc.onnegotiationneeded = async () => {
    if (!initiator) return;
    await pc.setLocalDescription(await pc.createOffer());
    send({ type: "signal", to: state.peer.id, data: { sdp: pc.localDescription } });
  };
  for (const t of state.stream.getTracks()) pc.addTrack(t, state.stream);
  sendCamState();

  pc.onicecandidate = (e) => { if (e.candidate) send({ type: "signal", to: state.peer.id, data: { candidate: e.candidate } }); };
  pc.ontrack = (e) => {
    $("remoteVideo").srcObject = e.streams[0];
    $("waiting").classList.add("hidden");
    updateRemoteAvatar();
  };
  pc.onconnectionstatechange = () => {
    const s = pc.connectionState;
    if (s === "connected") setConn("Live", "ok", "peer-to-peer");
    else if (s === "failed") {
      setConn("Live", "bad", "video blocked, captions only");
      if (initiator) pc.restartIce?.();
    } else if (s === "disconnected") setConn("Live", "warn", "connection unstable");
  };
}

async function onSignal(from, data) {
  if ("cam" in data) {
    if (state.peer?.id === from) { state.remoteCam = data.cam; updateRemoteAvatar(); }
    return;
  }
  if (!state.pc || state.peer?.id !== from) return;
  const pc = state.pc;
  if (data.sdp) {
    await pc.setRemoteDescription(data.sdp);
    if (data.sdp.type === "offer") {
      await pc.setLocalDescription(await pc.createAnswer());
      send({ type: "signal", to: from, data: { sdp: pc.localDescription } });
    }
    for (const c of state.pendingIce.splice(0)) await pc.addIceCandidate(c).catch(() => {});
  } else if (data.candidate) {
    if (pc.remoteDescription) await pc.addIceCandidate(data.candidate).catch(() => {});
    else state.pendingIce.push(data.candidate);
  }
}

function closePeer(keepPeerInfo = false) {
  if (state.pc) { state.pc.close(); state.pc = null; }
  if (keepPeerInfo) return;
  state.peer = null;
  $("remoteVideo").srcObject = null;
  $("waiting").classList.remove("hidden");
  $("remoteName").classList.add("hidden");
  $("remoteName").classList.remove("talking");
  state.remoteCam = undefined;
  $("remoteAvatar").classList.add("hidden");
  if (state.myId) setConn("Ready", "warn", "waiting for peer");
}

function leave() {
  state.leaving = true;
  state.ws?.close();
  closePeer();
  state.stream?.getTracks().forEach((t) => t.stop());
  location.href = location.pathname;
}

// ------------------------------------------------------------------ captions
const capEls = new Map();   // seg id -> overlay element
const listEls = new Map();  // seg id -> transcript <li>

function onCaption(m) {
  const mine = m.speaker === state.myId;
  const main = m.translated || m.text;
  const showOrig = m.translated && m.translated !== m.text;
  const failed = !m.translated && m.tgt !== m.src;   // translation was wanted but did not come back

  if (m.final && !m.text) { removeCaption(m.seg); return; }

  // ---- overlay
  let el = capEls.get(m.seg);
  if (!el) {
    // one line per side: a new sentence replaces that speaker's previous caption
    for (const [k, v] of capEls) if (v.classList.contains("mine") === mine) { v.remove(); capEls.delete(k); }
    el = document.createElement("div");
    capEls.set(m.seg, el);
    if (mine) $("captions").prepend(el); else $("captions").appendChild(el);
  }
  el.className = `cap${mine ? " mine" : ""}${m.final ? "" : " interim"}`;
  el.innerHTML = `<span class="who"></span><span class="main"></span>${showOrig ? '<span class="orig"></span>' : ""}`;
  el.querySelector(".who").textContent = mine ? "You" : m.name;
  el.querySelector(".main").textContent = main + (m.final ? "" : " …");
  if (showOrig) el.querySelector(".orig").textContent = m.text;
  clearTimeout(el.fadeTimer);
  el.fadeTimer = setTimeout(() => {
    el.classList.add("fade");
    setTimeout(() => { el.remove(); capEls.delete(m.seg); }, 500);
  }, m.final ? 7000 : 4000);

  // ---- transcript
  let li = listEls.get(m.seg);
  if (!li) {
    li = document.createElement("li");
    listEls.set(m.seg, li);
    $("transcript").appendChild(li);
  }
  li.className = `${mine ? "mine" : ""} ${m.final ? "" : "interim"}`;
  const time = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
  li.innerHTML = `<div class="meta"><span><b></b> · <span class="src"></span></span><span>${time}</span></div><div class="t"></div>` +
    (showOrig ? '<div class="o"></div>' : "") + (m.final && m.timings ? '<div class="lat"></div>' : "");
  li.querySelector("b").textContent = mine ? "You" : m.name;
  li.querySelector(".src").textContent = langName(m.src);
  li.querySelector(".t").textContent = main + (failed ? "  (not translated)" : "");
  if (showOrig) li.querySelector(".o").textContent = m.text;
  if (m.final && m.timings) {
    // bar split into pause / ASR (including queue wait) / MT, proportional to the total
    const t = m.timings, lat = li.querySelector(".lat");
    const parts = [["pause", t.vadMs], ["asr", t.queueMs + t.asrMs], ["mt", t.mtMs]];
    const sum = parts.reduce((a, [, v]) => a + v, 0) || 1;
    lat.innerHTML = '<span class="bar">' + parts.map(([k, v]) => `<span class="${k}" style="flex:${v / sum}"></span>`).join("") +
      `</span>${(t.totalMs / 1000).toFixed(2)}s`;
    lat.title = `pause ${t.vadMs} + queue ${t.queueMs} + ASR ${t.asrMs} + MT ${t.mtMs} ms · ${(t.audioMs / 1000).toFixed(1)} s of audio`;
  }
  const list = $("transcript");
  if (list.scrollHeight - list.scrollTop - list.clientHeight < 120) list.scrollTop = list.scrollHeight;

  if (m.final) {
    listEls.delete(m.seg);
    state.transcript.push({ time, name: mine ? "You" : m.name, src: m.src, text: m.text, translated: m.translated, tgt: m.tgt });
    if (m.timings) {
      state.latencies.push(m.timings.totalMs);
      const avg = state.latencies.reduce((a, b) => a + b, 0) / state.latencies.length;
      $("latencyChip").innerHTML = `avg latency <b>${(avg / 1000).toFixed(1)}s</b>`;
      $("latencyChip").title = `Average time from end of speech to caption, over ${state.latencies.length} captions`;
    }
  }
}

function removeCaption(seg) {
  capEls.get(seg)?.remove();
  capEls.delete(seg);
  listEls.get(seg)?.remove();
  listEls.delete(seg);
}

function downloadTranscript() {
  const lines = state.transcript.map((r) =>
    `[${r.time}] ${r.name} (${r.src}): ${r.text}` + (r.translated && r.translated !== r.text ? `\n           → (${r.tgt}) ${r.translated}` : ""));
  const blob = new Blob([`Transmeet transcript · room ${state.room} · ${new Date().toLocaleString()}\n\n${lines.join("\n")}\n`], { type: "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `transmeet-${state.room}.txt`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// re-check translator status occasionally so the pipeline note updates once LibreTranslate is up
setInterval(async () => {
  if (!state.config || state.config.translator || $("call").classList.contains("hidden")) return;
  try {
    const c = await (await fetch("api/config")).json();
    state.config.translator = c.translator;
    updateMtChip();
  } catch {}
}, 10000);

init();
