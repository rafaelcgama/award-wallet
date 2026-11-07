// Follow the update's download until the app closes to install it.
(() => {
  const box = document.getElementById("update");
  if (!box) return;
  const bar = box.querySelector(".progress-bar");
  const meter = box.querySelector(".progress");
  const step = document.getElementById("update-step");
  const title = document.getElementById("update-title");
  const actions = document.getElementById("update-actions");
  bar.style.width = `${Number(bar.dataset.percent) || 0}%`;
  const show = (status) => {
    if (status.state === "failed") {
      title.textContent = "The update didn't finish";
      step.textContent = status.error;
      meter.hidden = true;
      actions.hidden = false;
      return false;
    }
    if (status.percent === null) {
      bar.classList.add("progress-bar-unknown");
    } else {
      bar.classList.remove("progress-bar-unknown");
      bar.style.width = `${status.percent}%`;
      meter.setAttribute("aria-valuenow", status.percent);
    }
    if (status.state === "installing") {
      step.textContent = "Installing. Milestash closes and reopens by itself in a moment.";
      return false;
    }
    step.textContent = status.percent === null ? "Downloading…" : `Downloading (${status.percent}%)…`;
    return true;
  };
  const poll = async () => {
    try {
      const response = await fetch("/update/status", { cache: "no-store" });
      if (response.ok && !show(await response.json())) return;
    } catch (error) {
      return; // the app is closing to install the update
    }
    setTimeout(poll, 400);
  };
  if (box.dataset.state === "downloading") poll();
})();
