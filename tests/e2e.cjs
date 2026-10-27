// End-to-end test: two real Chromium browsers join one room with fake cameras.
// Alice's fake microphone plays an English recording and Bob's plays a Hindi one.
// The test passes when the peer-to-peer video connects and each side receives
// the other's speech as a translated final caption.
//
//   node tests/e2e.cjs http://localhost:8000 alice_en.wav bob_hi.wav
//
// The WAV files must be 16-bit PCM. Chrome loops them as microphone input.
const { chromium } = require("playwright");

const [url = "http://localhost:8000", wavA, wavB] = process.argv.slice(2);
if (!wavA || !wavB) {
  console.error("usage: node tests/e2e.cjs <url> <alice.wav> <bob.wav>");
  process.exit(2);
}
const room = "e2e-" + Math.random().toString(36).slice(2, 7);
const outDir = process.env.SHOT_DIR || ".";

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
  await page.selectOption("#lang", lang);
  await page.selectOption("#captionLang", captionLang);
  await page.click("#joinBtn:not([disabled])");
  await page.waitForSelector("#call:not(.hidden)");
  return { browser, page, name };
}

function finalCaptionFrom(p, speaker, timeout = 90000) {
  return p.page.waitForFunction(
    (who) => [...document.querySelectorAll("#transcript li:not(.interim)")]
      .find((li) => li.querySelector("b")?.textContent.startsWith(who) && li.querySelector(".lat")),
    speaker, { timeout });
}

(async () => {
const t0 = Date.now();
const alice = await person("Alice", "en", "en", wavA);
const bob = await person("Bob", "hi", "hi", wavB);
let ok = true;
try {
  for (const p of [alice, bob]) {
    await p.page.waitForFunction(() => document.querySelector("#remoteVideo").videoWidth > 0, null, { timeout: 30000 });
    console.log(`✓ ${p.name}: remote video playing (${((Date.now() - t0) / 1000).toFixed(1)}s)`);
  }
  await Promise.all([finalCaptionFrom(bob, "Alice"), finalCaptionFrom(alice, "Bob")]);
  // let a few more sentences arrive for the screenshot
  await bob.page.waitForTimeout(12000);
  for (const p of [alice, bob]) {
    const rows = await p.page.$$eval("#transcript li:not(.interim)", (lis) => lis.map((li) => ({
      who: li.querySelector("b").textContent, text: li.querySelector(".t").textContent,
      orig: li.querySelector(".o")?.textContent || "", lat: li.querySelector(".lat")?.textContent || "",
    })));
    console.log(`\n--- ${p.name}'s transcript ---`);
    for (const r of rows) console.log(`${r.who}: ${r.text}${r.orig ? `\n    (orig) ${r.orig}` : ""}\n    ${r.lat}`);
    await p.page.screenshot({ path: `${outDir}/e2e-${p.name.toLowerCase()}.png` });
  }
  console.log(`\n✓ captions translated both ways. Screenshots in ${outDir}`);
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
