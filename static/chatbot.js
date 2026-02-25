(() => {
  const toggle = document.getElementById("chatbotToggle");
  const panel = document.getElementById("chatbotPanel");
  const form = document.getElementById("chatbotForm");
  const input = document.getElementById("chatbotInput");
  const messages = document.getElementById("chatbotMessages");

  if (!toggle || !panel || !form || !input || !messages) {
    return;
  }

  toggle.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) input.focus();
  });

  function appendMessage(text, type = "bot") {
    const el = document.createElement("div");
    el.className = type === "user" ? "user-msg" : "bot-msg";
    el.textContent = text;
    messages.appendChild(el);
    messages.scrollTop = messages.scrollHeight;
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
    } catch (_error) {
      appendMessage("Connection issue. Please try again in a moment.", "bot");
    }
  });
})();
