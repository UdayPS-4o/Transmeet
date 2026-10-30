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
  startedAt: 0,          // when this call started (SRT timestamps)
  prefs: {},             // voice + caption settings, see loadPrefs()
  voiceOn: false,        // read the other person's translated words aloud
  speech: { queue: [], playing: null, ctx: null },
  screen: null,          // screen-share stream while sharing
};

const ICON = {
  mic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>',
  micOff: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M9 9v2a3 3 0 0 0 5.1 2.1M15 9.3V6a3 3 0 0 0-5.9-.8M5 11a7 7 0 0 0 11.6 5.3M19 11a7 7 0 0 1-.4 2.3M12 18v3M3 3l18 18"/></svg>',
  cam: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="6" width="13" height="12" rx="2"/><path d="m16 10 5-3v10l-5-3z"/></svg>',
  camOff: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M16 16v1a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h2m4 0h5a1 1 0 0 1 1 1v3.3l5-3.3v10M3 3l18 18"/></svg>',
  panel: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16M18 8h-1M18 11h-1"/></svg>',
  shuffle: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12a8 8 0 1 1-2.3-5.7M20 4v4h-4"/></svg>',
  voice: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/></svg>',
  voiceOff: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="m16 9 5 6M21 9l-5 6"/></svg>',
  screen: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4M9 10l3-3 3 3M12 7v6"/></svg>',
  gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/></svg>',
  send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
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
// A blank room code joins the shared "main" room, so a demo needs no typing at all.
const DEFAULT_ROOM = "main";
const inviteLink = () => location.origin + location.pathname +
  (state.room === DEFAULT_ROOM ? "" : `?room=${encodeURIComponent(state.room)}`);
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
  $("room").value = params.get("room") || "";
  $("name").value = load("name") || "";
  const browserLang = (navigator.language || "en").slice(0, 2);
  const knownLang = state.config.languages.some((l) => l.code === browserLang) ? browserLang : "en";
  const defLang = load("lang") || "auto";      // auto-detect unless the person picked a language before
  fillSelect($("lang"), defLang, true);
  fillSelect($("captionLang"), load("captionLang") || (defLang === "auto" ? knownLang : defLang));
  $("lang").onchange = () => { if ($("lang").value !== "auto") $("captionLang").value = $("lang").value; };
  loadPrefs();
  $("voiceLobby").checked = load("voice") !== "0";   // on unless this person turned it off
  $("voiceLobby").onchange = () => save("voice", $("voiceLobby").checked ? "1" : "0");
  $("onlyLobby").checked = !!state.prefs.translationOnly;
  $("onlyLobby").onchange = () => { state.prefs.translationOnly = $("onlyLobby").checked; savePrefs(); };
  if (!Object.keys(state.config.tts || {}).length && !("speechSynthesis" in window)) {
    $("voiceLobby").closest(".check").classList.add("hidden");   // nothing could speak
  }
  $("newRoom").innerHTML = ICON.shuffle;
  $("newRoom").onclick = () => { $("room").value = randomRoom(); };
  $("name").oninput = setMyInitial;
  setMyInitial();
  const ss = $("serverState");
  ss.innerHTML = `Server online<span class="ss-detail">&nbsp;· ${state.config.translator ? `Whisper + ${state.config.mt}` : "translator loading"}` +
    `${Object.keys(state.config.tts || {}).length ? " + Piper voice" : ""}</span>`;
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
  for (const id of ["previewOff", "localAvatar"]) $(id).firstElementChild.dataset.initial = initial($("name").value || state.name) || "·";
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
  const room = $("room").value.trim().toLowerCase().replace(/[^a-z0-9-]/g, "") || DEFAULT_ROOM;
  const shownName = name || "Guest";
  save("name", name); save("lang", $("lang").value); save("captionLang", $("captionLang").value);
  state.room = room;
  state.name = shownName;
  history.replaceState(null, "", room === DEFAULT_ROOM ? location.pathname : `?room=${encodeURIComponent(room)}`);
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
  state.startedAt = Date.now();
  state.speech.ctx = new AudioContext();     // created on the Join click, so playback is allowed
  state.speech.out = await echoSafeOutput(state.speech.ctx);
  setVoice($("voiceLobby").checked, false);
  $("voiceBtn").title = "Speak translations aloud (S)";
  $("shareBtn").innerHTML = ICON.screen;
  $("settingsBtn").innerHTML = ICON.gear;
  $("chatSend").innerHTML = ICON.send;
  if (!navigator.mediaDevices.getDisplayMedia) $("shareBtn").classList.add("hidden");
  bindCallControls();
  bindSettings();
  bindTranscriptScroll();
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
    fillVoices();
  };
  $("copyLink").onclick = copyInvite;
  $("copyLink2").onclick = copyInvite;
  $("download").onclick = downloadTranscript;
  $("downloadSrt").onclick = downloadSrt;
  $("voiceBtn").onclick = () => setVoice(!state.voiceOn);
  $("shareBtn").onclick = toggleShare;
  $("settingsBtn").onclick = () => toggleSettings();
  $("chatForm").onsubmit = (e) => {
    e.preventDefault();
    const text = $("chatInput").value.trim();
    if (!text) return;
    send({ type: "chat", text });
    $("chatInput").value = "";
  };
  document.addEventListener("keydown", onShortcut);
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
      // Optional (Settings): send silence while the translated voice plays, for browsers whose
      // echo canceller does not remove it (see echoSafeOutput).
      const gated = state.speech.playing && state.prefs.pauseMic;
      state.ws.send(gated ? new ArrayBuffer(e.data.byteLength) : e.data);
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
    ws.send(JSON.stringify({ type: "join", name: state.name, lang: $("langCall").value, captionLang: $("captionLangCall").value }));
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
      $("vocab").value = m.vocab || "";
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
    case "chat":
      onCaption({ ...m, final: true, chat: true });
      break;
    case "vocab":
      $("vocab").value = m.text;
      if (m.by !== state.name || m.text) toast(m.text ? `Room vocabulary: ${m.text}` : "Room vocabulary cleared");
      break;
    case "speaking":
      if (m.id === state.myId) {
        state.meSpeaking = m.speaking;
        $("hearing").classList.toggle("hidden", !m.speaking);
      }
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
  tag.children[2].textContent = `· ${p.lang === "auto" ? "auto-detect" : langName(p.lang)}` +
    (state.remoteVoice === false ? " · translation only" : "");
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
  // tell the other side when the camera goes off (a disabled track would otherwise just show
  // black) and whether they get my real voice or only the translation
  if (state.peer) send({ type: "signal", to: state.peer.id, data: {
    cam: !!(state.screen || state.stream?.getVideoTracks()[0]?.enabled), voice: !state.prefs.translationOnly } });
}

function setTranslationOnly(on) {
  // Interpreter mode for the speaker: my real voice is not sent to the other person at all,
  // they hear only the translated voice. The server still gets the mic (a separate path),
  // so captions and translations carry on as usual.
  state.prefs.translationOnly = on;
  savePrefs();
  $("translationOnly").checked = on;
  state.audioSender?.replaceTrack(on ? null : state.stream.getAudioTracks()[0] || null);
  sendCamState();
  $("localTag").textContent = on ? "You · translation only" : "You";
  toast(on ? "They now hear only the translation, not your real voice" : "They hear your real voice again");
}

function setRemoteVoice(on) {
  state.remoteVoice = on;
  if (state.peer) setPeer(state.peer);
  // they send no real voice, so without the translated voice I would hear nothing
  if (!on && !state.voiceOn) {
    setVoice(true, false);
    toast(`${state.peer?.name || "They"} sends only the translated voice, so it is read aloud for you`);
  }
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
  c.textContent = state.config.translator ? `Whisper ${state.config.model} → ${state.config.mt}` : "translator loading";
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
  for (const t of state.stream.getTracks()) {
    const sender = pc.addTrack(t.kind === "video" && state.screen ? state.screen.getVideoTracks()[0] : t, state.stream);
    if (t.kind === "audio") {
      state.audioSender = sender;
      if (state.prefs.translationOnly) sender.replaceTrack(null);   // see setTranslationOnly
    }
  }
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
    if (state.peer?.id === from) {
      state.remoteCam = data.cam;
      updateRemoteAvatar();
      if ("voice" in data && data.voice !== state.remoteVoice) setRemoteVoice(data.voice);
    }
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
  state.remoteVoice = undefined;
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
  const failed = !m.translated && m.tgt !== m.src && m.src !== "auto";   // translation was wanted but did not come back
  const show = (t) => state.prefs.romanize ? romanize(t) : t;

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
  el.className = `cap${mine ? " mine" : ""}${m.final ? "" : " interim"}${m.chat ? " chat" : ""}`;
  el.innerHTML = `<span class="who"></span><span class="main"></span>${showOrig ? '<span class="orig"></span>' : ""}`;
  el.querySelector(".who").textContent = mine ? "You" : m.name;
  el.querySelector(".main").textContent = show(main) + (m.final ? "" : " …");
  if (showOrig) el.querySelector(".orig").textContent = show(m.text);
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
  li.dataset.seg = m.seg;
  const time = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
  li.innerHTML = `<div class="meta"><span><b></b> · <span class="src"></span>${m.chat ? ' <span class="typed">· typed</span>' : ""}</span>` +
    `<span>${time}${m.final ? `<button class="say" title="Read aloud">${ICON.play}</button>` : ""}</span></div><div class="t"></div>` +
    (showOrig ? '<div class="o"></div>' : "") + (m.final && m.timings ? '<div class="lat"></div>' : "");
  li.querySelector("b").textContent = mine ? "You" : m.name;
  li.querySelector(".src").textContent = m.src === "auto" ? "typed" : langName(m.src);
  li.querySelector(".t").textContent = show(main) + (failed ? "  (not translated)" : "");
  if (showOrig) li.querySelector(".o").textContent = show(m.text);
  const sayLang = m.translated ? m.tgt : m.src;
  if (m.final) li.querySelector(".say").onclick = () => speak({ seg: m.seg, text: main, lang: sayLang, manual: true });
  if (m.final && m.timings) {
    // bar split into pause / ASR (including queue wait) / MT, proportional to the total
    const t = m.timings, lat = li.querySelector(".lat");
    const parts = [["pause", t.vadMs], ["asr", t.queueMs + t.asrMs], ["mt", t.mtMs]];
    const sum = parts.reduce((a, [, v]) => a + v, 0) || 1;
    lat.innerHTML = '<span class="bar">' + parts.map(([k, v]) => `<span class="${k}" style="flex:${v / sum}"></span>`).join("") +
      `</span>${(t.totalMs / 1000).toFixed(2)}s`;
    lat.title = `pause ${t.vadMs} + queue ${t.queueMs} + ASR ${t.asrMs} + MT ${t.mtMs} ms · ${(t.audioMs / 1000).toFixed(1)} s of audio`;
  }
  followTranscript(mine);

  if (m.final) {
    listEls.delete(m.seg);
    // when the sentence was spoken, relative to the start of the call (for .srt export)
    const now = Date.now() - state.startedAt;
    const endMs = m.timings ? now - m.timings.totalMs : now;
    const startMs = m.timings ? endMs - m.timings.audioMs : now;
    state.transcript.push({ time, name: mine ? "You" : m.name, src: m.src, text: m.text, translated: m.translated,
      tgt: m.tgt, chat: !!m.chat, startMs: Math.max(0, startMs), endMs: Math.max(endMs, startMs + 1500) });
    if (m.timings) {
      state.latencies.push(m.timings.totalMs);
      const avg = state.latencies.reduce((a, b) => a + b, 0) / state.latencies.length;
      $("latencyChip").innerHTML = `avg latency <b>${(avg / 1000).toFixed(1)}s</b>`;
      $("latencyChip").title = `Average time from end of speech to caption, over ${state.latencies.length} captions`;
    }
    // interpreter mode: read the other person's words aloud in my language. If we share a
    // language there is nothing to translate, so their real voice is enough.
    // A typed message has no voice of its own, so it is read out even in the same language.
    // When they send only the translated voice, read them out even in a shared language.
    if (state.voiceOn && !mine && (m.chat || (m.translated && m.tgt !== m.src) || state.remoteVoice === false)) {
      speak({ seg: m.seg, text: main, lang: sayLang });
    }
  }
}

// The transcript follows new captions unless you scrolled up to read; then a
// "New captions" button appears instead of yanking the list away from you.
state.follow = true;
function followTranscript(mine) {
  const list = $("transcript");
  if (state.follow || mine) {
    list.scrollTop = list.scrollHeight;
    state.follow = true;
  } else {
    $("newCaps").classList.remove("hidden");
  }
}

function bindTranscriptScroll() {
  const list = $("transcript");
  list.onscroll = () => {
    state.follow = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
    if (state.follow) $("newCaps").classList.add("hidden");
  };
  $("newCaps").onclick = () => {
    state.follow = true;
    list.scrollTo({ top: list.scrollHeight, behavior: "smooth" });
    $("newCaps").classList.add("hidden");
  };
}

function removeCaption(seg) {
  capEls.get(seg)?.remove();
  capEls.delete(seg);
  listEls.get(seg)?.remove();
  listEls.delete(seg);
}

function saveFile(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

function downloadTranscript() {
  const lines = state.transcript.map((r) =>
    `[${r.time}] ${r.name} (${r.chat ? "typed" : r.src}): ${r.text}` + (r.translated && r.translated !== r.text ? `\n           → (${r.tgt}) ${r.translated}` : ""));
  saveFile(`transmeet-${state.room}.txt`,
    `Transmeet transcript · room ${state.room} · ${new Date().toLocaleString()}\n\n${lines.join("\n")}\n`, "text/plain");
}

function downloadSrt() {
  // subtitles timed from the start of the call, e.g. to lay over a recording of it
  const pad = (n, w = 2) => String(Math.floor(n)).padStart(w, "0");
  const ts = (ms) => `${pad(ms / 3600000)}:${pad(ms / 60000 % 60)}:${pad(ms / 1000 % 60)},${pad(ms % 1000, 3)}`;
  const cues = state.transcript.map((r, i) => `${i + 1}\n${ts(r.startMs)} --> ${ts(r.endMs)}\n${r.name}: ` +
    (r.translated && r.translated !== r.text ? `${r.translated}\n${r.text}` : r.text) + "\n");
  saveFile(`transmeet-${state.room}.srt`, cues.join("\n"), "application/x-subrip");
}

// ------------------------------------------------------------------ settings
const PREF_DEFAULTS = { rate: 1, duck: 0.2, pauseMic: false, translationOnly: false, capSize: "m", showOrig: true, romanize: false, voices: {} };

function loadPrefs() {
  let saved = {};
  try { saved = JSON.parse(load("prefs") || "{}"); } catch {}
  state.prefs = { ...PREF_DEFAULTS, ...saved };
}
const savePrefs = () => save("prefs", JSON.stringify(state.prefs));

function bindSettings() {
  const P = state.prefs;
  $("voiceRate").value = P.rate;
  $("duck").value = P.duck;
  $("pauseMic").checked = P.pauseMic;
  $("translationOnly").checked = P.translationOnly;
  $("translationOnly").onchange = () => setTranslationOnly($("translationOnly").checked);
  if (P.translationOnly) $("localTag").textContent = "You · translation only";
  $("showOrig").checked = P.showOrig;
  $("romanize").checked = P.romanize;
  const outputs = () => {
    $("rateOut").textContent = `${(+P.rate).toFixed(2)}×`;
    $("duckOut").textContent = `${Math.round(P.duck * 100)}%`;
  };
  $("voiceRate").oninput = () => { P.rate = +$("voiceRate").value; outputs(); savePrefs(); };
  $("duck").oninput = () => { P.duck = +$("duck").value; outputs(); savePrefs(); if (state.speech.playing) duckRemote(true); };
  $("pauseMic").onchange = () => { P.pauseMic = $("pauseMic").checked; savePrefs(); };
  $("showOrig").onchange = () => { P.showOrig = $("showOrig").checked; savePrefs(); applyCaptionPrefs(); };
  $("romanize").onchange = () => {
    P.romanize = $("romanize").checked;
    savePrefs();
    toast(P.romanize ? "Hindi appears in Roman letters from the next caption" : "Hindi appears in Devanagari");
  };
  for (const b of $("capSize").children) b.onclick = () => { P.capSize = b.dataset.v; savePrefs(); applyCaptionPrefs(); };
  $("voiceSelect").onchange = () => { P.voices[$("captionLangCall").value] = $("voiceSelect").value; savePrefs(); };
  $("vocabForm").onsubmit = (e) => { e.preventDefault(); send({ type: "vocab", text: $("vocab").value }); };
  document.addEventListener("pointerdown", (e) => {
    if (!$("settings").classList.contains("hidden") && !e.target.closest("#settings, #settingsBtn")) toggleSettings(false);
  });
  outputs();
  fillVoices();
  applyCaptionPrefs();
}

function toggleSettings(open = $("settings").classList.contains("hidden")) {
  $("settings").classList.toggle("hidden", !open);
  $("settingsBtn").setAttribute("aria-expanded", open);
}

function applyCaptionPrefs() {
  const c = $("captions");
  c.classList.remove("size-s", "size-m", "size-l");
  c.classList.add(`size-${state.prefs.capSize}`);
  c.classList.toggle("no-orig", !state.prefs.showOrig);
  for (const b of $("capSize").children) b.classList.toggle("on", b.dataset.v === state.prefs.capSize);
}

function fillVoices() {
  // the server's Piper voices for my caption language; without one the browser's own voice is used
  const lang = $("captionLangCall").value;
  const voices = state.config.tts?.[lang] || [];
  const sel = $("voiceSelect");
  sel.innerHTML = voices.length
    ? voices.map((v) => `<option value="${v.id}">${v.label}</option>`).join("")
    : "<option value=\"\">This device's voice</option>";
  sel.disabled = voices.length < 2;
  if (voices.some((v) => v.id === state.prefs.voices[lang])) sel.value = state.prefs.voices[lang];
}

// ------------------------------------------------------------------ translated voice
function setVoice(on, announce = true) {
  state.voiceOn = on;
  save("voice", on ? "1" : "0");
  const b = $("voiceBtn");
  b.classList.toggle("on", on);
  b.innerHTML = on ? ICON.voice : ICON.voiceOff;
  b.setAttribute("aria-pressed", on);
  if (!on) stopSpeech();
  state.speech.ctx?.resume();
  if (announce) toast(on ? `Their words will be read aloud in ${langName($("captionLangCall").value)}` : "Translated voice off");
}

function speak(item) {
  if (!item.text || !item.lang || item.lang === "auto") return;
  const sp = state.speech;
  if (item.manual) stopSpeech();                 // a click on "read aloud" plays right away
  sp.queue.push(item);
  // If the voice falls more than 2 sentences behind, skip the oldest so it stays close to live.
  while (sp.queue.filter((x) => !x.manual).length > 2) sp.queue.splice(sp.queue.findIndex((x) => !x.manual), 1);
  if (!sp.playing && !sp.waiting) playNext();
}

async function playNext() {
  const sp = state.speech;
  // With "Pause my mic" on, don't start the voice in the middle of your own sentence
  // (that would cut the sentence in two); wait up to 6 s for a pause.
  if (state.prefs.pauseMic && sp.queue.length && !sp.queue[0].manual) {
    sp.waiting = true;
    for (let t = 0; state.meSpeaking && t < 40; t++) await new Promise((r) => setTimeout(r, 150));
    sp.waiting = false;
  }
  const item = sp.queue.shift();
  if (!item) { sp.playing = null; setSpeaking(null); duckRemote(false); return; }
  sp.playing = item;
  setSpeaking(item);
  duckRemote(true);
  try {
    if (!(await playServer(item))) await playBrowser(item);
  } catch (e) {
    console.warn("translated voice failed", e);
  }
  if (sp.playing === item) playNext();
}

async function playServer(item) {
  // Piper on the server. Returns false if it has no voice for this language.
  const sp = state.speech;
  let res;
  try {
    res = await fetch("api/tts", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: item.text, lang: item.lang, voice: state.prefs.voices[item.lang] || null, rate: state.prefs.rate }),
    });
  } catch { return false; }
  if (res.status !== 200) return false;
  const buf = await sp.ctx.decodeAudioData(await res.arrayBuffer());
  if (sp.playing !== item) return true;          // stopped while it was being made
  await new Promise((resolve) => {
    const src = sp.ctx.createBufferSource();
    src.buffer = buf;
    src.connect(sp.out || sp.ctx.destination);
    src.onended = resolve;
    sp.stop = () => { try { src.stop(); } catch {} resolve(); };
    src.start();
  });
  return true;
}

function playBrowser(item) {
  // fallback: the browser's own speech synthesis, if this device has a voice for the language
  if (!("speechSynthesis" in window)) return Promise.resolve();
  const tag = { en: "en-IN", es: "es-ES", fr: "fr-FR", de: "de-DE", ur: "ur-PK", ne: "ne-NP" }[item.lang] ||
    (["hi", "bn", "ta", "te", "mr", "gu", "kn", "ml", "pa", "or", "as"].includes(item.lang) ? `${item.lang}-IN` : item.lang);
  const voices = speechSynthesis.getVoices();
  const voice = voices.find((v) => v.lang.replace("_", "-") === tag) || voices.find((v) => v.lang.startsWith(item.lang));
  if (!voice) {
    if (!(state.warnedNoVoice ||= new Set()).has(item.lang)) toast(`No ${langName(item.lang)} voice available on this device`);
    state.warnedNoVoice.add(item.lang);
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    const u = new SpeechSynthesisUtterance(item.text);
    u.voice = voice;
    u.lang = voice.lang;
    u.rate = state.prefs.rate;
    u.onend = u.onerror = resolve;
    state.speech.stop = () => { speechSynthesis.cancel(); resolve(); };
    speechSynthesis.speak(u);
  });
}

async function echoSafeOutput(ctx) {
  // Chrome's echo canceller only removes sound that comes out of a WebRTC connection, so a
  // voice played straight to the speakers would be picked up by the mic and captioned as
  // you. Sending it through a loopback connection inside this page makes the echo
  // canceller treat it like the call audio. Falls back to direct playback if that fails.
  try {
    const dest = ctx.createMediaStreamDestination();
    const a = new RTCPeerConnection(), b = new RTCPeerConnection();
    a.onicecandidate = (e) => e.candidate && b.addIceCandidate(e.candidate).catch(() => {});
    b.onicecandidate = (e) => e.candidate && a.addIceCandidate(e.candidate).catch(() => {});
    const el = new Audio();
    b.ontrack = (e) => { el.srcObject = e.streams[0]; el.play().catch(() => {}); };
    a.addTrack(dest.stream.getAudioTracks()[0], dest.stream);
    await a.setLocalDescription(await a.createOffer());
    await b.setRemoteDescription(a.localDescription);
    await b.setLocalDescription(await b.createAnswer());
    await a.setRemoteDescription(b.localDescription);
    // if the loopback doesn't connect (or its audio can't start), the voice would go
    // nowhere, so fall back to the speakers directly
    for (let t = 0; b.connectionState !== "connected" && t < 30; t++) await new Promise((r) => setTimeout(r, 100));
    if (b.connectionState !== "connected") throw new Error(`loopback ${b.connectionState}`);
    await el.play();
    state.speech.loopback = { a, b, el };
    return dest;
  } catch (e) {
    console.warn("echo-safe voice output unavailable, playing directly", e);
    return ctx.destination;
  }
}

function stopSpeech() {
  const sp = state.speech;
  const stop = sp.stop;
  sp.queue = [];
  sp.playing = null;
  sp.stop = null;
  stop?.();
  setSpeaking(null);
  duckRemote(false);
}

function duckRemote(on) {
  // like an interpreter's booth: the original voice drops under the translation
  $("remoteVideo").volume = on ? state.prefs.duck : 1;
}

function setSpeaking(item) {
  for (const li of document.querySelectorAll("#transcript li.speaking")) li.classList.remove("speaking");
  if (item) document.querySelector(`#transcript li[data-seg="${CSS.escape(item.seg)}"]`)?.classList.add("speaking");
  $("voiceBtn").classList.toggle("playing", !!item);
}

// ------------------------------------------------------------------ screen share
async function toggleShare() {
  if (state.screen) return stopShare();
  let screen;
  try { screen = await navigator.mediaDevices.getDisplayMedia({ video: true }); } catch { return; }
  if (state.pc && !videoSender()) {
    screen.getTracks().forEach((t) => t.stop());
    return toast("Screen sharing needs a camera on this device");
  }
  const track = screen.getVideoTracks()[0];
  state.screen = screen;
  track.onended = stopShare;
  await videoSender()?.replaceTrack(track);
  $("localVideo").srcObject = screen;
  $("localVideo").classList.add("screen");
  $("shareBtn").classList.add("sharing");
  sendCamState();
  toast("Sharing your screen");
}

async function stopShare() {
  if (!state.screen) return;
  state.screen.getTracks().forEach((t) => t.stop());
  state.screen = null;
  await videoSender()?.replaceTrack(state.stream.getVideoTracks()[0] || null);
  $("localVideo").srcObject = state.stream;
  $("localVideo").classList.remove("screen");
  $("shareBtn").classList.remove("sharing");
  sendCamState();
}

const videoSender = () => state.pc?.getSenders().find((s) => s.track?.kind === "video");

// ------------------------------------------------------------------ shortcuts
function onShortcut(e) {
  if (e.ctrlKey || e.metaKey || e.altKey || e.target.closest?.("input, select, textarea")) return;
  const act = {
    m: () => toggleMic(), v: () => toggleCam(), c: () => $("ccBtn").click(),
    s: () => setVoice(!state.voiceOn), t: () => $("sideBtn").click(), escape: () => toggleSettings(false),
  }[e.key.toLowerCase()];
  if (act) { e.preventDefault(); act(); }
}

// ------------------------------------------------------------------ Hindi in Roman letters
// Devanagari -> Roman letters the way Hinglish is usually typed ("aap kaise hain"), not
// scholarly IAST. The inherent "a" is dropped at the end of a word and between a vowel
// and a consonant+vowel (करता -> karta, समझना -> samajhna), the usual Hindi schwa rule.
const DEV = {
  C: { "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h", "ळ": "l" },
  NUKTA: { "क": "q", "ख": "kh", "ग": "gh", "ज": "z", "ड": "r", "ढ": "rh", "फ": "f", "य": "y" },
  V: { "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e" },
  M: { "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "e" },
};

function romanizeWord(w) {
  const u = [];          // one entry per letter: consonant c, vowel v, and whether v is the inherent "a"
  for (let i = 0; i < w.length; i++) {
    const ch = w[i];
    if (DEV.C[ch]) {
      let c = DEV.C[ch];
      if (w[i + 1] === "़") { c = DEV.NUKTA[ch] || c; i++; }        // nukta: ज़ -> z, फ़ -> f
      const next = w[i + 1];
      if (next === "्") { u.push({ c, v: "" }); i++; }               // virama: no vowel (conjunct)
      else if (DEV.M[next]) { u.push({ c, v: DEV.M[next] }); i++; }
      else u.push({ c, v: "a", inherent: true });
    } else if (DEV.V[ch]) u.push({ c: "", v: DEV.V[ch] });
    else if (ch === "ं" || ch === "ँ") u.push({ c: "n", v: "" });   // anusvara, chandrabindu
    else if (ch === "ः") u.push({ c: "h", v: "" });                      // visarga
    else if (ch >= "०" && ch <= "९") u.push({ c: String(ch.charCodeAt(0) - 0x966), v: "" });
    else if (ch !== "़") u.push({ c: ch, v: "" });
  }
  const last = u.length - 1;
  // final schwa goes (कमल -> kamal), except in one-letter words and after a cluster
  // ending in r / y / v (मित्र -> mitra)
  if (last > 0 && u[last].inherent && !(u[last - 1].v === "" && /^[ryv]$/.test(u[last].c))) u[last].v = "";
  for (let i = last - 1; i >= 1; i--) {
    if (u[i].inherent && u[i - 1].v && /^[a-z]/.test(u[i + 1].c) && u[i + 1].v) u[i].v = "";
  }
  return u.map((x) => x.c + x.v).join("").replace(/aa$/, "a").replace(/ee$/, "i").replace(/oo$/, "u");
}

function romanize(text) {
  if (!/[ऀ-ॿ]/.test(text)) return text;
  return text.normalize("NFD").replace(/[।॥]/g, ".").replace(/[ऀ-ॣ०-ॿ]+/g, romanizeWord);
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
