(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);

  const SAMPLE = `Photosynthesis is the process by which green plants, algae and some bacteria convert light energy into chemical energy stored in glucose. It takes place mainly in the chloroplasts, which contain the pigment chlorophyll. Chlorophyll absorbs red and blue light and reflects green light, which is why leaves look green.

The process has two stages. In the light-dependent reactions, which occur in the thylakoid membranes, light energy splits water molecules into oxygen, protons and electrons. The oxygen is released into the atmosphere, and the energy is stored in the carriers ATP and NADPH.

In the Calvin cycle, which occurs in the stroma of the chloroplast, carbon dioxide is fixed into organic molecules. The enzyme RuBisCO catalyses the first major step of carbon fixation. ATP and NADPH from the light reactions provide the energy and reducing power needed to build glucose.

Several factors affect the rate of photosynthesis. Increasing light intensity raises the rate until another factor becomes limiting. Higher carbon dioxide concentration also raises the rate, while temperature affects enzyme activity and the rate drops sharply when enzymes denature. Water availability matters because stomata close during drought, reducing carbon dioxide intake.

Photosynthesis is essential for life on Earth. It produces the oxygen that most organisms need for respiration and forms the base of almost every food chain. Over millions of years, photosynthesis also created the fossil fuels we burn today.`;

  const state = {
    docId: null,
    text: "",
    pack: null,
    cardIdx: 0,
    cardFlipped: false,
    quizIdx: 0,
    quizScore: 0,
    quizAnswered: false,
  };

  // ---------- helpers ----------
  function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    }
    for (const c of children.flat()) {
      if (c == null) continue;
      node.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return node;
  }

  // replaceChildren() would print the word "null" for empty slots, so drop them first
  function fill(node, ...kids) {
    node.replaceChildren(...kids.flat().filter((k) => k != null));
  }

  function setStatus(msg, isError = false) {
    const s = $("#status");
    s.textContent = msg;
    s.classList.toggle("error", isError);
  }

  async function postJSON(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Request failed");
    return data;
  }

  // ---------- weak topics (saved in the browser) ----------
  const WEAK_KEY = "studybuddy.weak";
  function loadWeak() {
    try { return JSON.parse(localStorage.getItem(WEAK_KEY) || "{}"); } catch { return {}; }
  }
  function saveWeak(w) {
    try { localStorage.setItem(WEAK_KEY, JSON.stringify(w)); } catch { /* storage unavailable */ }
  }
  function addWeak(topic) {
    if (!topic) return;
    const w = loadWeak();
    w[topic] = (w[topic] || 0) + 1;
    saveWeak(w);
    renderWeak();
  }
  function weakTopics() {
    const w = loadWeak();
    return Object.keys(w).sort((a, b) => w[b] - w[a]);
  }
  function renderWeak() {
    const list = $("#weak-list");
    const topics = weakTopics();
    list.replaceChildren(...topics.slice(0, 10).map((t) => el("li", { text: t })));
    $("#weak-box").hidden = topics.length === 0;
  }

  // ---------- tabs ----------
  const TABS = ["summary", "cards", "quiz", "ask", "plan"];
  function showTab(name) {
    for (const t of TABS) {
      const selected = t === name;
      $("#tab-" + t).setAttribute("aria-selected", String(selected));
      $("#pane-" + t).hidden = !selected;
    }
  }
  TABS.forEach((t) => $("#tab-" + t).addEventListener("click", () => showTab(t)));

  // ---------- input ----------
  const fileInput = $("#file");
  const drop = $("#drop");
  fileInput.addEventListener("change", () => {
    const f = fileInput.files[0];
    $("#file-label").textContent = f ? f.name : "Choose a PDF or text file, or drop it here";
    drop.classList.toggle("has-file", !!f);
  });
  ["dragenter", "dragover"].forEach((ev) =>
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); })
  );
  ["dragleave", "drop"].forEach((ev) =>
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); })
  );
  drop.addEventListener("drop", (e) => {
    if (e.dataTransfer.files.length) {
      fileInput.files = e.dataTransfer.files;
      fileInput.dispatchEvent(new Event("change"));
    }
  });

  $("#sample").addEventListener("click", () => {
    $("#text").value = SAMPLE;
    fileInput.value = "";
    fileInput.dispatchEvent(new Event("change"));
    setStatus("Sample notes loaded. Choose Make study pack.");
  });

  $("#generate").addEventListener("click", generate);

  async function generate() {
    const btn = $("#generate");
    const text = $("#text").value.trim();
    const file = fileInput.files[0];
    if (!file && text.length < 200) {
      setStatus("Add a file or paste at least a paragraph of notes first.", true);
      return;
    }
    const form = new FormData();
    if (file) form.append("file", file);
    else form.append("text", text);
    form.append("cards", $("#cards").value);
    form.append("questions", $("#questions").value);
    form.append("language", $("#language").value);

    btn.disabled = true;
    setStatus("Reading your notes and building your study pack…");
    try {
      const res = await fetch("/api/generate", { method: "POST", body: form });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Could not build the study pack.");
      state.docId = data.doc_id;
      state.text = data.text || "";
      state.pack = data;
      state.cardIdx = 0;
      state.cardFlipped = false;
      state.quizIdx = 0;
      state.quizScore = 0;
      state.quizAnswered = false;
      renderSummary();
      renderCard();
      renderQuiz();
      $("#chat-log").replaceChildren(
        el("div", { class: "empty", text: "Ask anything about your notes. Answers use only what you uploaded." })
      );
      showTab("summary");
      setStatus(`Done: ${data.flashcards.length} flashcards and ${data.quiz.length} questions.`);
    } catch (err) {
      setStatus(err.message, true);
    } finally {
      btn.disabled = false;
    }
  }

  // ---------- summary ----------
  function renderSummary() {
    const p = state.pack;
    const pane = $("#pane-summary");
    fill(pane, 
      p.note ? el("p", { class: "note", text: p.note }) : null,
      el("h3", { class: "pack-title", text: p.title }),
      el("p", { class: "summary", text: p.summary }),
      el("h3", { text: "Key points" }),
      el("ul", { class: "points" }, p.key_points.map((k) => el("li", { text: k })))
    );
  }

  // ---------- flashcards ----------
  function renderCard() {
    const pane = $("#pane-cards");
    const cards = state.pack ? state.pack.flashcards : [];
    if (!cards.length) {
      fill(pane, el("div", { class: "empty", text: "No flashcards were generated. Try longer notes." }));
      return;
    }
    const c = cards[state.cardIdx];
    const face = el(
      "button",
      {
        class: "flashcard" + (state.cardFlipped ? " back" : ""),
        type: "button",
        "aria-label": state.cardFlipped ? "Answer. Press to show the question" : "Question. Press to show the answer",
        onclick: () => { state.cardFlipped = !state.cardFlipped; renderCard(); $(".flashcard").focus(); },
      },
      el("span", { class: "side", text: state.cardFlipped ? "Answer" : "Question" }),
      el("span", { class: "text", text: state.cardFlipped ? c.back : c.front })
    );
    fill(pane, 
      el("p", { class: "card-count", text: `Card ${state.cardIdx + 1} of ${cards.length} · topic: ${c.topic}` }),
      face,
      el(
        "div",
        { class: "card-nav" },
        el("button", { class: "ghost", type: "button", text: "Previous", onclick: () => moveCard(-1) }),
        el("button", { class: "ghost", type: "button", text: "Next", onclick: () => moveCard(1) }),
        el("button", {
          class: "ghost", type: "button", text: "Still learning",
          onclick: () => { addWeak(c.topic); moveCard(1); },
        })
      )
    );
  }
  function moveCard(step) {
    const n = state.pack.flashcards.length;
    state.cardIdx = (state.cardIdx + step + n) % n;
    state.cardFlipped = false;
    renderCard();
  }

  // ---------- quiz ----------
  function renderQuiz() {
    const pane = $("#pane-quiz");
    const quiz = state.pack ? state.pack.quiz : [];
    if (!quiz.length) {
      fill(pane, el("div", { class: "empty", text: "No quiz questions were generated. Try longer notes." }));
      return;
    }
    if (state.quizIdx >= quiz.length) return renderQuizResult(pane, quiz.length);

    const q = quiz[state.quizIdx];
    const optionsBox = el("div", { class: "options" });
    const feedback = el("div");
    q.options.forEach((opt, i) => {
      optionsBox.append(
        el("button", {
          class: "option", type: "button", text: opt,
          onclick: () => answer(i, q, optionsBox, feedback),
        })
      );
    });
    fill(pane, 
      el("p", { class: "q-progress", text: `Question ${state.quizIdx + 1} of ${quiz.length}` }),
      el("p", { class: "q-text", text: q.question }),
      optionsBox,
      feedback
    );
    state.quizAnswered = false;
  }

  function answer(choice, q, optionsBox, feedback) {
    if (state.quizAnswered) return;
    state.quizAnswered = true;
    const buttons = [...optionsBox.children];
    buttons.forEach((b, i) => {
      b.disabled = true;
      if (i === q.answer_index) b.classList.add("correct");
      else if (i === choice) b.classList.add("wrong");
    });
    const right = choice === q.answer_index;
    if (right) state.quizScore += 1;
    else addWeak(q.topic);
    const last = state.quizIdx + 1 >= state.pack.quiz.length;
    feedback.replaceChildren(
      el("div", { class: "explain", text: (right ? "Correct. " : "Not quite. ") + (q.explanation || "") }),
      el("button", {
        class: "primary", type: "button", text: last ? "See my score" : "Next question",
        onclick: () => { state.quizIdx += 1; renderQuiz(); },
      })
    );
  }

  function renderQuizResult(pane, total) {
    const pct = Math.round((state.quizScore / total) * 100);
    const weak = weakTopics().slice(0, 5);
    fill(pane, 
      el("p", { class: "score", text: `${state.quizScore} / ${total}` }),
      el("p", {
        text: pct >= 80 ? "Strong result. A quick skim of the summary before your exam should be enough."
          : pct >= 50 ? "Good start. Revisit the topics below and try again."
          : "This material needs more time. Go through the flashcards, then retake the quiz.",
      }),
      weak.length ? el("p", { class: "hint", text: "Topics to revise: " + weak.join(", ") }) : null,
      el(
        "div", { class: "actions" },
        el("button", {
          class: "primary", type: "button", text: "Retake quiz",
          onclick: () => { state.quizIdx = 0; state.quizScore = 0; renderQuiz(); },
        }),
        el("button", { class: "ghost", type: "button", text: "Plan my revision", onclick: buildPlanFromWeak })
      )
    );
  }

  // ---------- ask ----------
  async function ask() {
    const input = $("#question");
    const q = input.value.trim();
    if (!q) return;
    if (!state.text) {
      showTab("ask");
      $("#chat-log").replaceChildren(el("div", { class: "empty", text: "Make a study pack first, then ask questions about it." }));
      return;
    }
    const log = $("#chat-log");
    if (log.querySelector(".empty")) log.replaceChildren();
    log.append(el("div", { class: "msg user", text: q }));
    const thinking = el("div", { class: "msg bot", text: "Looking through your notes…" });
    log.append(thinking);
    input.value = "";
    log.scrollTop = log.scrollHeight;
    try {
      const data = await postJSON("/api/ask", { doc_id: state.docId, text: state.text, question: q });
      thinking.textContent = data.answer;
    } catch (err) {
      thinking.textContent = err.message;
    }
    log.scrollTop = log.scrollHeight;
  }
  $("#ask-btn").addEventListener("click", ask);
  $("#question").addEventListener("keydown", (e) => { if (e.key === "Enter") ask(); });

  // ---------- plan ----------
  async function buildPlan() {
    const out = $("#plan-out");
    const btn = $("#plan-btn");
    btn.disabled = true;
    out.replaceChildren(el("p", { class: "hint", text: "Building your plan…" }));
    try {
      const data = await postJSON("/api/plan", {
        days: Number($("#days").value) || 5,
        weak_topics: weakTopics(),
        doc_id: state.docId,
        text: state.text,
      });
      out.replaceChildren(
        ...data.plan.map((d) =>
          el("div", { class: "day" },
            el("h4", { text: `Day ${d.day}: ${d.focus}` }),
            el("ul", {}, d.tasks.map((t) => el("li", { text: t })))
          )
        )
      );
    } catch (err) {
      out.replaceChildren(el("p", { class: "status error", text: err.message }));
    } finally {
      btn.disabled = false;
    }
  }
  function buildPlanFromWeak() { showTab("plan"); buildPlan(); }
  $("#plan-btn").addEventListener("click", buildPlan);
  $("#weak-plan").addEventListener("click", buildPlanFromWeak);
  $("#weak-clear").addEventListener("click", () => { saveWeak({}); renderWeak(); });

  // ---------- keyboard shortcuts for flashcards ----------
  document.addEventListener("keydown", (e) => {
    if (!state.pack || $("#pane-cards").hidden) return;
    if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
    if (e.key === "ArrowRight") moveCard(1);
    if (e.key === "ArrowLeft") moveCard(-1);
  });

  // ---------- startup ----------
  fetch("/api/status")
    .then((r) => r.json())
    .then((s) => {
      const b = $("#mode-badge");
      b.textContent = s.mode === "ai" ? "AI mode" : "Demo mode (offline)";
      b.classList.toggle("ai", s.mode === "ai");
    })
    .catch(() => { $("#mode-badge").textContent = "Offline"; });

  renderWeak();
})();
