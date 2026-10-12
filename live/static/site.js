// Trueup site: nav toggle, current page, reveal on scroll, copy buttons.
(function () {
  document.documentElement.classList.remove("no-js");
  const nav = document.querySelector(".nav");
  const toggle = document.querySelector(".nav-toggle");
  if (nav && toggle) {
    toggle.addEventListener("click", () => {
      const open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(open));
    });
    nav.querySelectorAll(".nav-links a").forEach(a => a.addEventListener("click", () => nav.classList.remove("open")));
  }

  const here = location.pathname.replace(/\.html$/, "").replace(/\/index$/, "/") || "/";
  document.querySelectorAll(".nav-links a[data-path]").forEach(a => {
    if (a.dataset.path === here) a.setAttribute("aria-current", "page");
  });

  // The demo page runs its own reveal; only site pages use this one.
  if (document.body.classList.contains("site")) {
    const items = document.querySelectorAll(".reveal");
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (still || !("IntersectionObserver" in window)) {
      items.forEach(e => e.classList.add("in"));
    } else {
      const io = new IntersectionObserver(es => es.forEach(e => {
        if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
      }), { threshold: 0.12 });
      items.forEach(e => io.observe(e));
    }
  }

  document.querySelectorAll("[data-copy]").forEach(b => b.addEventListener("click", () => {
    if (navigator.clipboard) navigator.clipboard.writeText(b.dataset.copy);
    const was = b.textContent;
    b.textContent = "Copied";
    setTimeout(() => { b.textContent = was; }, 1500);
  }));
})();
