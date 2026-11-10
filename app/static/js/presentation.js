// Web slide deck: arrow keys, buttons, swipe, #n deep links and full screen.
(function () {
  const slides = Array.from(document.querySelectorAll(".slide"));
  const cur = document.getElementById("cur");
  const bar = document.getElementById("progress");
  const stacked = window.matchMedia("(max-width: 820px), (orientation: portrait) and (max-width: 1024px)");
  let index = 0;

  function show(i, opts) {
    index = Math.max(0, Math.min(slides.length - 1, i));
    slides.forEach((s, k) => s.classList.toggle("is-active", k === index));
    cur.textContent = index + 1;
    bar.style.width = ((index + 1) / slides.length) * 100 + "%";
    if (!(opts && opts.silent)) history.replaceState(null, "", "#" + (index + 1));
    if (stacked.matches && !(opts && opts.noScroll)) slides[index].scrollIntoView({ behavior: "smooth", block: "start" });
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
  });

  // click on the right or left third of a slide (not on a link) moves on or back
  document.getElementById("deck").addEventListener("click", (e) => {
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

  // stacked layout: keep the counter in step with scrolling
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver((entries) => {
      if (!stacked.matches) return;
      entries.forEach((en) => {
        if (en.isIntersecting) {
          index = slides.indexOf(en.target);
          cur.textContent = index + 1;
          bar.style.width = ((index + 1) / slides.length) * 100 + "%";
        }
      });
    }, { threshold: 0.5 });
    slides.forEach((s) => io.observe(s));
  }

  window.addEventListener("hashchange", () => show(fromHash(), { silent: true }));
  show(fromHash(), { silent: true, noScroll: !location.hash });
})();
