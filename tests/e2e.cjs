// End-to-end test: two real Chromium browsers join one room with fake cameras.
// Each fake microphone plays a recording (Chrome loops it as mic input), so the
// whole browser path is exercised: getUserMedia -> AudioWorklet -> WebSocket ->
// VAD -> Whisper -> LibreTranslate -> captions on the other screen.
//
//   node tests/e2e.cjs http://localhost:8000 mic_en.wav mic_hi.wav
//   AUTO=1 node tests/e2e.cjs ...      (both people use "I speak: Auto-detect")
//
// If a .json file sits next to a .wav (written by tests/mic_scenario.py), the test
// also checks that the captions match the sentences that were really spoken.
const fs = require("fs");
const { chromium } = require("playwright");

const [url = "http://localhost:8000", wavA, wavB] = process.argv.slice(2);
if (!wavA || !wavB) {
  console.error("usage: node tests/e2e.cjs <url> <alice.wav> <bob.wav>");
  process.exit(2);
}
const room = "e2e-" + Math.random().toString(36).slice(2, 7);
const outDir = process.env.SHOT_DIR || ".";
const LISTEN_S = Number(process.env.LISTEN_S || 45);

function scenario(wav) {
  const json = wav.replace(/\.wav$/, ".json");
  if (!fs.existsSync(json)) return null;
  const meta = JSON.parse(fs.readFileSync(json, "utf8"));
  return { lang: meta.lang, sentences: meta.events.filter((e) => e.kind === "speech").map((e) => e.text) };
}

const words = (s) => s.normalize("NFC").toLowerCase().replace(/[^\p{L}\p{M}\p{N}\s']/gu, " ").split(/\s+/).filter(Boolean);
function wer(ref, hyp) {
  const r = words(ref), h = words(hyp);
  const d = Array.from({ length: r.length + 1 }, (_, i) => [i, ...Array(h.length).fill(0)]);
  for (let j = 1; j <= h.length; j++) d[0][j] = j;
  for (let i = 1; i <= r.length; i++)
    for (let j = 1; j <= h.length; j++)
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (r[i - 1] === h[j - 1] ? 0 : 1));
  return d[r.length][h.length] / Math.max(1, r.length);
}

async function person(name, lang, captionLang, wav) {
  const browser = await chromium.launch({
    args: [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      `--use-file-for-fake-audio-capture=${wav}`,
      "--autoplay-policy=no-user-gesture-required",
    ],
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 760 } });
  page.on("pageerror", (e) => console.log(`[${name}] page error:`, e.message));
  await page.goto(`${url}/?room=${room}`);
  await page.fill("#name", name);
  await page.selectOption("#lang", process.env.AUTO ? "auto" : lang);   // AUTO=1: let the server detect it
  await page.selectOption("#captionLang", captionLang);
  await page.click("#joinBtn:not([disabled])");
  await page.waitForSelector("#call:not(.hidden)");
  // remember whether the "hearing you…" indicator ever lit up
  await page.evaluate(() => {
    window.__heard = false;
    new MutationObserver(() => { if (!document.querySelector("#hearing").classList.contains("hidden")) window.__heard = true; })
      .observe(document.querySelector("#hearing"), { attributes: true });
  });
  return { browser, page, name };
}

async function transcriptOf(p) {
  return p.page.$$eval("#transcript li:not(.interim)", (lis) => lis.map((li) => ({
    who: li.querySelector("b").textContent,
    shown: li.querySelector(".t").textContent,
    orig: li.querySelector(".o")?.textContent || li.querySelector(".t").textContent,
    lat: li.querySelector(".lat")?.textContent || "",
  })));
}

(async () => {
  const sA = scenario(wavA), sB = scenario(wavB);
  const langA = sA?.lang || "en", langB = sB?.lang || "hi";
  const t0 = Date.now();
  const alice = await person("Alice", langA, langA, wavA);
  const bob = await person("Bob", langB, langB, wavB);
  let ok = true;
  try {
    for (const p of [alice, bob]) {
      await p.page.waitForFunction(() => document.querySelector("#remoteVideo").videoWidth > 0, null, { timeout: 30000 });
      console.log(`✓ ${p.name}: peer-to-peer video playing (${((Date.now() - t0) / 1000).toFixed(1)}s)`);
    }
    console.log(`  listening for ${LISTEN_S}s…`);
    await bob.page.waitForTimeout(LISTEN_S * 1000);

    for (const [viewer, speaker, sc] of [[bob, "Alice", sA], [alice, "Bob", sB]]) {
      const rows = (await transcriptOf(viewer)).filter((r) => r.who.startsWith(speaker));
      console.log(`\n--- what ${viewer.name} saw from ${speaker} ---`);
      const matched = new Set();
      for (const r of rows) {
        let note = "";
        if (sc) {
          const best = sc.sentences.map((s, i) => [wer(s, r.orig), i]).sort((a, b) => a[0] - b[0])[0];
          const good = best[0] <= (sc.lang === "hi" ? 0.5 : 0.35);
          if (good) matched.add(best[1]);
          note = good ? `  ✓ matches spoken #${best[1] + 1} (WER ${best[0].toFixed(2)})` : `  ✗ closest: "${sc.sentences[best[1]]}" (WER ${best[0].toFixed(2)})`;
        }
        console.log(`heard: ${r.orig}\nshown: ${r.shown}\n${note}\n${r.lat}`);
      }
      if (!rows.length) { console.log("✗ no captions at all"); ok = false; }
      if (sc) {
        const need = sc.lang === "hi" ? 3 : 4;
        console.log(`${matched.size}/${sc.sentences.length} spoken sentences captioned correctly (need ${need})`);
        if (matched.size < need) ok = false;
      }
    }
    for (const p of [alice, bob]) {
      const heard = await p.page.evaluate(() => window.__heard);
      const banner = await p.page.$eval("#banner", (b) => b.classList.contains("hidden") ? "" : b.textContent.trim());
      console.log(`${heard ? "✓" : "✗"} ${p.name}: "hearing you" indicator ${heard ? "lit up" : "never shown"}` +
        (banner ? ` · banner: ${banner}` : ""));
      if (!heard) ok = false;
      await p.page.screenshot({ path: `${outDir}/e2e-${p.name.toLowerCase()}.png` });
    }
    console.log(ok ? "\nPASS" : "\nFAIL", `· screenshots in ${outDir}`);
  } catch (e) {
    ok = false;
    console.error("✗ e2e failed:", e.message);
    for (const p of [alice, bob]) await p.page.screenshot({ path: `${outDir}/e2e-${p.name.toLowerCase()}-fail.png` });
  } finally {
    await alice.browser.close();
    await bob.browser.close();
  }
  process.exit(ok ? 0 : 1);
})();
