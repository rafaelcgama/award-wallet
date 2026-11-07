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

// Countdowns to an expiration ("in 89 days") go down by one each midnight even while the window
// stays open, worked out the same way as when the page was made.
function countdowns() {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  for (const element of document.querySelectorAll(".countdown[data-expires-on]")) {
    const [year, month, day] = element.dataset.expiresOn.split("-").map(Number);
    // Rounded, because a day with a clock change has 23 or 25 hours.
    const days = Math.round((new Date(year, month - 1, day) - today) / 86400000);
    element.textContent =
      days === 0 ? "today"
      : days === 1 ? "tomorrow"
      : days < 0 ? "already expired"
      : `in ${days.toLocaleString("en-US")} days`;
  }
}
countdowns();
// Checked every minute rather than timed to midnight: a Mac that sleeps through midnight would
// otherwise wake up still showing yesterday's count.
setInterval(countdowns, 60 * 1000);

// Coming back to a page (with Back) shows its buttons ready again.
window.addEventListener("pageshow", (event) => {
  if (!event.persisted) return;
  for (const button of document.querySelectorAll(".button.is-busy")) {
    button.textContent = button.dataset.idle;
    button.classList.remove("is-busy");
    button.disabled = false;
  }
});
