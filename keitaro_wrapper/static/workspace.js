const feedback = document.getElementById("feedback");
const createFeedback = document.getElementById("create-feedback");
const creation = document.querySelector(".new-campaign");
const lookupRetry = document.getElementById("lookup-retry");

const root = document.documentElement;
let scrollbarTimer;
root.dataset.scrollbar = "idle";
window.addEventListener("scroll", () => {
  if (root.dataset.scrollbar !== "active") root.dataset.scrollbar = "active";
  clearTimeout(scrollbarTimer);
  scrollbarTimer = setTimeout(() => { root.dataset.scrollbar = "idle"; }, 700);
}, { passive: true });

document.getElementById("initial-offer")?.addEventListener("invalid", (event) => {
  const input = event.currentTarget;
  if (input.value.trim() || input.form.querySelector(":invalid") !== input) return;
  event.preventDefault();
  const notice = showRequestError({ elt: input }, "Выберите оффер или введите его ID.");
  notice.setAttribute("data-offer-required", "");
  input.focus();
});

function requestFeedback(detail) {
  const path = detail.pathInfo?.requestPath;
  return path === "/ui/campaigns" || path === "/ui/lookups" || detail.elt?.closest(".campaign-form")
    ? createFeedback
    : feedback;
}

creation?.addEventListener("toggle", () => {
  if (creation.open) htmx.trigger(creation.querySelector("#lookups"), "load-settings");
});

document.body.addEventListener("htmx:beforeRequest", (event) => {
  const source = event.detail.elt;
  if (!source.matches("input[hx-get]")) requestFeedback(event.detail).replaceChildren();
});

document.body.addEventListener("htmx:beforeSwap", (event) => {
  if (event.detail.xhr.getResponseHeader("HX-Retarget") !== "#feedback") return;
  event.detail.target = requestFeedback(event.detail);
  event.detail.shouldSwap = true;
  event.detail.isError = false;
});

document.body.addEventListener("htmx:afterRequest", ({ detail }) => {
  if (detail.pathInfo?.requestPath !== "/ui/lookups") return;
  lookupRetry.hidden = detail.xhr.status === 200;
  if (!lookupRetry.hidden) {
    document.querySelectorAll("#lookups select option:only-child").forEach((option) => {
      option.textContent = "Не загружено";
    });
  }
});

function showRequestError(detail, message) {
  const notice = document.createElement("p");
  notice.className = "notice error";
  notice.role = "alert";
  notice.textContent = message;
  requestFeedback(detail).replaceChildren(notice);
  return notice;
}

document.body.addEventListener("htmx:sendError", ({ detail }) => {
  showRequestError(detail, "Связь с приложением потеряна. Проверьте результат перед повтором.");
});

document.body.addEventListener("htmx:timeout", ({ detail }) => {
  showRequestError(detail, "Ответ не получен вовремя. Проверьте результат перед повтором.");
});

document.body.addEventListener("htmx:responseError", ({ detail }) => {
  showRequestError(detail, `Ошибка приложения (HTTP ${detail.xhr.status}). Проверьте результат перед повтором.`);
});
