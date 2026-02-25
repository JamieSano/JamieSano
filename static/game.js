(() => {
  let audioCtx;

  function ensureContext() {
    if (!audioCtx) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (Ctx) audioCtx = new Ctx();
    }
    return audioCtx;
  }

  function beep({ frequency = 440, duration = 0.08, type = "sine", volume = 0.04 } = {}) {
    const ctx = ensureContext();
    if (!ctx) return;

    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();
    oscillator.type = type;
    oscillator.frequency.value = frequency;
    gain.gain.value = volume;
    oscillator.connect(gain);
    gain.connect(ctx.destination);

    const now = ctx.currentTime;
    gain.gain.setValueAtTime(volume, now);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);

    oscillator.start(now);
    oscillator.stop(now + duration);
  }

  function playSound(kind) {
    if (kind === "start") {
      beep({ frequency: 440, duration: 0.08, type: "triangle" });
      setTimeout(() => beep({ frequency: 660, duration: 0.09, type: "triangle" }), 80);
      return;
    }
    if (kind === "next") {
      beep({ frequency: 520, duration: 0.06, type: "square" });
      setTimeout(() => beep({ frequency: 740, duration: 0.06, type: "square" }), 60);
      return;
    }
    if (kind === "select") {
      beep({ frequency: 580, duration: 0.04, type: "sine", volume: 0.03 });
      return;
    }
    beep({ frequency: 480, duration: 0.05, type: "sine", volume: 0.03 });
  }

  document.addEventListener("click", (event) => {
    const target = event.target.closest("[data-sound]");
    if (!target) return;
    playSound(target.dataset.sound || "click");
  });
})();
