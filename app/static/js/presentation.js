// Web slide deck: arrow keys, buttons, swipe, #n deep links, full screen, and the entrance animations.
(function () {
  const deck = document.getElementById("deck");
  const slides = Array.from(document.querySelectorAll(".slide"));
  const cur = document.getElementById("cur");
  const bar = document.getElementById("progress");
  const stacked = window.matchMedia("(max-width: 820px), (orientation: portrait) and (max-width: 1024px)");
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)");
  let index = 0;

  // ---------------------------------------------------------------- animation helpers
  // Give every repeated item its position in its group, so the CSS can stagger it.
  const GROUPS = [".stats", ".cards", ".points", ".bullets", ".steps", "tbody", ".col ul", ".t-meta"];
  slides.forEach((s) => {
    GROUPS.forEach((sel) => s.querySelectorAll(sel).forEach((g) => {
      Array.from(g.children).forEach((el, k) => el.style.setProperty("--i", k));
    }));
  });

  // Big numbers on the stat slides count up to their value ("36.7%", "28/28", "0.18 s").
  function countUp(slide) {
    slide.querySelectorAll(".stat-value").forEach((el, k) => {
      const final = el.dataset.final || (el.dataset.final = el.textContent.trim());
      const m = final.match(/\d+(?:\.\d+)?/);
      if (!m || calm.matches) { el.textContent = final; return; }
      const target = parseFloat(m[0]);
      const decimals = (m[0].split(".")[1] || "").length;
      const before = final.slice(0, m.index), after = final.slice(m.index + m[0].length);
      const delay = 350 + k * 110, dur = 1100;
      const t0 = performance.now() + delay;
      el.textContent = before + (0).toFixed(decimals) + after;
      const tick = (now) => {
        if (!slide.classList.contains("play")) { el.textContent = final; return; }
        const p = Math.min(1, Math.max(0, (now - t0) / dur));
        const eased = 1 - Math.pow(1 - p, 3);
        el.textContent = p >= 1 ? final : before + (target * eased).toFixed(decimals) + after;
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
  }

  function play(slide) {
    slide.classList.remove("play");
    void slide.offsetWidth;            // restart the CSS animations
    slide.classList.add("play");
    countUp(slide);
  }

  // ---------------------------------------------------------------- navigation
  function show(i, opts) {
    const next = Math.max(0, Math.min(slides.length - 1, i));
    deck.dataset.dir = next < index ? "prev" : "next";
    const changed = next !== index || !slides[next].classList.contains("is-active");
    index = next;
    slides.forEach((s, k) => s.classList.toggle("is-active", k === index));
    cur.textContent = index + 1;
    bar.style.width = ((index + 1) / slides.length) * 100 + "%";
    if (!(opts && opts.silent)) history.replaceState(null, "", "#" + (index + 1));
    if (stacked.matches) {
      if (!(opts && opts.noScroll)) slides[index].scrollIntoView({ behavior: calm.matches ? "auto" : "smooth", block: "start" });
    } else if (changed || (opts && opts.replay)) {
      play(slides[index]);
    }
  }

  function fromHash() {
    const n = parseInt(location.hash.replace("#", ""), 10);
    return Number.isFinite(n) ? n - 1 : 0;
  }

  document.getElementById("prev").addEventListener("click", () => show(index - 1));
  document.getElementById("next").addEventListener("click", () => show(index + 1));
  document.getElementById("full").addEventListener("click", toggleFull);

  function toggleFull() {
    if (document.fullscreenElement) document.exitFullscreen();
    else if (document.documentElement.requestFullscreen) document.documentElement.requestFullscreen();
  }

  document.addEventListener("keydown", (e) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    if (["ArrowRight", "PageDown", " ", "Enter"].includes(e.key)) { e.preventDefault(); show(index + 1); }
    else if (["ArrowLeft", "PageUp", "Backspace"].includes(e.key)) { e.preventDefault(); show(index - 1); }
    else if (e.key === "Home") show(0);
    else if (e.key === "End") show(slides.length - 1);
    else if (e.key === "f" || e.key === "F") toggleFull();
    else if (e.key === "r" || e.key === "R") show(index, { replay: true });   // replay this slide's animation
  });

  // click on the right or left third of a slide (not on a link) moves on or back
  deck.addEventListener("click", (e) => {
    if (stacked.matches || e.target.closest("a, button")) return;
    const x = e.clientX / window.innerWidth;
    if (x > 0.66) show(index + 1);
    else if (x < 0.34) show(index - 1);
  });

  // swipe on touch screens when one slide is shown at a time
  let startX = null;
  document.addEventListener("touchstart", (e) => { startX = e.touches[0].clientX; }, { passive: true });
  document.addEventListener("touchend", (e) => {
    if (startX === null || stacked.matches) return;
    const dx = e.changedTouches[0].clientX - startX;
    if (Math.abs(dx) > 50) show(index + (dx < 0 ? 1 : -1));
    startX = null;
  }, { passive: true });

  // stacked layout (phones): keep the counter in step with scrolling, animate each slide as it comes into view
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver((entries) => {
      if (!stacked.matches) return;
      entries.forEach((en) => {
        if (!en.isIntersecting) return;
        const k = slides.indexOf(en.target);
        if (!en.target.classList.contains("play")) play(en.target);
        if (en.intersectionRatio >= 0.5) {
          index = k;
          cur.textContent = index + 1;
          bar.style.width = ((index + 1) / slides.length) * 100 + "%";
        }
      });
    }, { threshold: [0.25, 0.5] });
    slides.forEach((s) => io.observe(s));
  } else {
    slides.forEach((s) => s.classList.add("play"));
  }

  window.addEventListener("hashchange", () => show(fromHash(), { silent: true }));
  index = -1;
  show(fromHash(), { silent: true, noScroll: !location.hash });
})();
