(() => {
  const toggle = document.getElementById("chatbotToggle");
  const panel = document.getElementById("chatbotPanel");
  const form = document.getElementById("chatbotForm");
  const input = document.getElementById("chatbotInput");
  const messages = document.getElementById("chatbotMessages");
  const micButton = document.getElementById("chatbotMic");
  const voiceToggle = document.getElementById("chatbotVoiceToggle");

  if (!toggle || !panel || !form || !input || !messages) {
    return;
  }

  let recognition;
  let isListening = false;

  toggle.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) input.focus();
  });

  function speak(text) {
    if (!voiceToggle || !voiceToggle.checked) return;
    if (!("speechSynthesis" in window)) return;

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1;
    utterance.pitch = 1;
    utterance.lang = "en-US";
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  }

  function appendMessage(text, type = "bot") {
    const el = document.createElement("div");
    el.className = type === "user" ? "user-msg" : "bot-msg";
    el.textContent = text;
    messages.appendChild(el);
    messages.scrollTop = messages.scrollHeight;

    if (type === "bot") speak(text);
  }

  function appendReference(text) {
    const el = document.createElement("div");
    el.className = "ref-msg";
    el.textContent = `📄 Source: ${text}`;
    messages.appendChild(el);
    messages.scrollTop = messages.scrollHeight;
  }

  if (micButton && ("webkitSpeechRecognition" in window || "SpeechRecognition" in window)) {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SpeechRecognition();
    recognition.lang = "en-US";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.addEventListener("result", (event) => {
      const transcript = event.results[0][0].transcript;
      input.value = transcript;
      input.focus();
    });

    recognition.addEventListener("end", () => {
      isListening = false;
      micButton.classList.remove("listening");
      micButton.textContent = "🎤";
    });

    micButton.addEventListener("click", () => {
      if (isListening) {
        recognition.stop();
        return;
      }
      isListening = true;
      micButton.classList.add("listening");
      micButton.textContent = "⏹";
      recognition.start();
    });
  } else if (micButton) {
    micButton.disabled = true;
    micButton.title = "Speech recognition is not supported in this browser.";
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question) return;

    appendMessage(question, "user");
    input.value = "";

    try {
      const response = await fetch("/chatbot/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const data = await response.json();
      appendMessage(data.reply || "Sorry, I couldn't answer that right now.", "bot");

      if (Array.isArray(data.references)) {
        data.references.slice(0, 2).forEach((ref) => appendReference(ref));
      }
    } catch (_error) {
      appendMessage("Connection issue. Please try again in a moment.", "bot");
    }
  });
})();
