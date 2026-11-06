// The app's only script on every page. Pages run no other code: their content security policy
// allows scripts from the app's own files only.

document.addEventListener("submit", (event) => {
  // A form that undoes something asks first (data-confirm holds the question).
  const question = event.target.dataset.confirm;
  if (question && !window.confirm(question)) {
    event.preventDefault();
    return;
  }
  // A clicked button says it's working, and can't be clicked twice.
  const button = event.submitter;
  if (event.defaultPrevented || !button || !button.classList.contains("button")) return;
  button.dataset.idle = button.textContent;
  if (button.dataset.busy) button.textContent = button.dataset.busy;
  button.classList.add("is-busy");
  // After the form is sent, so the button's own value still goes with it.
  setTimeout(() => { button.disabled = true; }, 0);
});

// Coming back to a page (with Back) shows its buttons ready again.
window.addEventListener("pageshow", (event) => {
  if (!event.persisted) return;
  for (const button of document.querySelectorAll(".button.is-busy")) {
    button.textContent = button.dataset.idle;
    button.classList.remove("is-busy");
    button.disabled = false;
  }
});
