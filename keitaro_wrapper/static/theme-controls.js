const toggle = document.getElementById("theme-toggle");
let renderer;

function loadTransition() {
  renderer ??= import("./vendor/ink-theme.js")
    .then(({ createThemeTransition }) => createThemeTransition(toggle))
    .catch(() => {
      renderer = undefined;
      return null;
    });
  return renderer;
}

async function changeTheme(point) {
  const transition = await loadTransition();
  if (transition) {
    transition.toggle(point);
  } else {
    const root = document.documentElement;
    const dark = root.dataset.theme !== "dark";
    root.dataset.theme = dark ? "dark" : "light";
    toggle.setAttribute("aria-pressed", String(dark));
    try {
      localStorage.setItem("theme", root.dataset.theme);
    } catch {}
  }
}

if (toggle) {
  toggle.setAttribute("aria-pressed", String(document.documentElement.dataset.theme === "dark"));
  toggle.addEventListener("pointerenter", loadTransition, { once: true });
  toggle.addEventListener("focus", loadTransition, { once: true });
  toggle.addEventListener("click", (event) => {
    changeTheme(event.detail === 0 ? undefined : { x: event.clientX, y: event.clientY });
  });
  document.addEventListener("keydown", async (event) => {
    if (event.repeat || event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.target instanceof Element && event.target.closest("input, textarea, select, [contenteditable]")) return;
    const key = event.key.toLowerCase();
    if (key === "t") {
      event.preventDefault();
      changeTheme();
    } else if (key === "r" && renderer) {
      (await renderer)?.replay();
    }
  });
}
