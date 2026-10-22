/* Keep existing deep links usable when their destination is inside a disclosure. */
(() => {
  function revealFragment() {
    if (!window.location.hash) return;
    let id;
    try {
      id = decodeURIComponent(window.location.hash.slice(1));
    } catch {
      return;
    }
    const target = document.getElementById(id);
    if (!target) return;
    for (let parent = target.parentElement; parent; parent = parent.parentElement) {
      if (parent.tagName === "DETAILS") parent.open = true;
    }
    target.scrollIntoView({ block: "start", behavior: "auto" });
    if (!target.matches("a, button, input, select, textarea, summary, [tabindex]")) {
      target.setAttribute("tabindex", "-1");
    }
    target.focus({ preventScroll: true });
  }
  window.addEventListener("hashchange", revealFragment);
  revealFragment();
})();
