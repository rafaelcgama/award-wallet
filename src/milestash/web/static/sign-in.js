// Signing in: shows the site's page from Milestash's hidden Chrome, and passes your clicks and
// keys on to it, as if you clicked and typed in Chrome. Pictures and keys only ever go between this
// window and the app.
(() => {
  const screen = document.getElementById("screen");
  if (!screen) return;
  const canvas = document.getElementById("screen-picture");
  const pen = canvas.getContext("2d");
  const keys = document.getElementById("screen-keys");
  const note = document.getElementById("sign-in-note");
  const waiting = document.getElementById("screen-waiting");
  // Keys passed on by name. Every other key arrives as the text it types, accents and all.
  const named = new Set([
    "Enter", "Backspace", "Tab", "Escape", "Delete", "ArrowLeft", "ArrowUp", "ArrowRight", "ArrowDown", "Home", "End",
  ]);
  // The page's size in its own pixels, as of the picture on screen.
  let page = { width: 0, height: 0 };
  let ended = false;

  // Back to where you came from, once the sign-in ends.
  const leave = () => {
    if (ended) return;
    ended = true;
    window.location.replace(screen.dataset.back);
  };

  // Clicks and keys go out one batch at a time, in the order you made them.
  const outbox = [];
  let sending = false;
  const flush = async () => {
    if (sending || ended || !outbox.length) return;
    sending = true;
    const batch = outbox.splice(0, 50);
    try {
      const body = new URLSearchParams({ csrf_token: screen.dataset.token, events: JSON.stringify(batch) });
      await fetch(screen.dataset.input, { method: "POST", body, cache: "no-store" });
    } catch (error) {
      // The app didn't answer; the next look at the sign-in says what happened.
    }
    sending = false;
    flush();
  };
  const send = (event) => {
    if (!page.width) return;
    outbox.push(event);
    flush();
  };

  // Where on the page a pointer is, in the page's own pixels.
  const place = (event) => {
    const box = canvas.getBoundingClientRect();
    const within = (value, most) => Math.min(Math.max(value, 0), most);
    return {
      x: within(((event.clientX - box.left) / box.width) * page.width, page.width),
      y: within(((event.clientY - box.top) / box.height) * page.height, page.height),
    };
  };

  // What you type lands in a hidden box first, which passes it on: pasted text too.
  const typed = () => {
    const characters = Array.from(keys.value.replace(/[\u0000-\u001f\u007f-\u009f]/g, ""));
    keys.value = "";
    for (let at = 0; at < characters.length; at += 200) {
      send({ kind: "text", text: characters.slice(at, at + 200).join("") });
    }
  };
  keys.addEventListener("input", (event) => {
    if (!event.isComposing) typed();
  });
  keys.addEventListener("compositionend", typed);
  keys.addEventListener("keydown", (event) => {
    if (event.isComposing || event.metaKey || event.ctrlKey || !named.has(event.key)) return;
    event.preventDefault();
    typed();
    send({ kind: "key", key: event.key, shift: event.shiftKey });
  });

  // A click on the picture is a click on the page, and keeps your typing going to the page.
  canvas.addEventListener("mousedown", (event) => {
    event.preventDefault();
    keys.focus({ preventScroll: true });
  });
  canvas.addEventListener("click", (event) => {
    typed();
    send({ kind: "click", ...place(event) });
  });

  // Scrolling, gathered up and sent a few times a second.
  let scroll = null;
  canvas.addEventListener(
    "wheel",
    (event) => {
      if (!page.width) return;
      event.preventDefault();
      const box = canvas.getBoundingClientRect();
      const unit = (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? box.height : 1) * (page.width / box.width);
      if (!scroll) {
        scroll = { kind: "scroll", ...place(event), dx: 0, dy: 0 };
        setTimeout(() => {
          const limit = (value) => Math.round(Math.min(Math.max(value, -5000), 5000));
          send({ ...scroll, dx: limit(scroll.dx), dy: limit(scroll.dy) });
          scroll = null;
        }, 60);
      }
      scroll.dx += event.deltaX * unit;
      scroll.dy += event.deltaY * unit;
    },
    { passive: false },
  );

  // The page as big as fits the window, all of it at once: never larger than the page itself.
  const fit = () => {
    if (!page.width) return;
    const room = screen.clientWidth;
    const tall = Math.max(window.innerHeight - (screen.getBoundingClientRect().top + window.scrollY) - 24, 320);
    const scale = Math.min(room / page.width, tall / page.height, 1);
    canvas.style.width = `${Math.floor(page.width * scale)}px`;
    canvas.style.height = `${Math.floor(page.height * scale)}px`;
  };
  window.addEventListener("resize", fit);

  // The newest picture of the page, drawn once it has loaded, so the screen never flickers.
  let shown = 0;
  const draw = (number, width, height) => {
    const picture = new Image();
    picture.onload = () => {
      if (number < shown || ended) return;
      shown = number;
      if (canvas.width !== picture.naturalWidth || canvas.height !== picture.naturalHeight) {
        canvas.width = picture.naturalWidth;
        canvas.height = picture.naturalHeight;
      }
      pen.drawImage(picture, 0, 0);
      page = { width, height };
      canvas.hidden = false;
      waiting.hidden = true;
      fit();
    };
    picture.src = `${screen.dataset.picture}?n=${number}`;
  };

  const show = (status) => {
    if (status.state !== "open") {
      leave();
      return false;
    }
    note.textContent = status.note || note.dataset.default;
    note.classList.toggle("sign-in-asks", Boolean(status.note));
    if (status.picture > shown) draw(status.picture, status.width, status.height);
    return true;
  };

  // Ask the app what's new; it answers as soon as there is something, or after a while.
  let after = 0;
  const poll = async () => {
    const started = Date.now();
    let pause = 1000;
    try {
      const response = await fetch(`${screen.dataset.status}?after=${after}`, { cache: "no-store" });
      if (response.status >= 400 && response.status < 500) {
        leave();
        return;
      }
      if (response.ok) {
        const status = await response.json();
        if (!show(status)) return;
        after = status.version;
        pause = 100;
      }
    } catch (error) {
      // The app is busy: ask again in a moment.
    }
    setTimeout(poll, Math.max(pause - (Date.now() - started), 0));
  };

  keys.focus({ preventScroll: true });
  poll();
})();
