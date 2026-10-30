import { capabilityLabel } from "./formatters.mjs";
import { requestKey } from "./state.mjs";

const INPUT_KINDS = new Set(["system", "developer", "user", "tool_result", "other"]);
const OUTPUT_KINDS = new Set(["assistant", "tool_call", "error"]);

export class TranscriptView {
  constructor(container) {
    this.container = container;
    this.currentKey = null;
    this.entries = new Map();
    this.sections = new Map();
  }

  update(request, { reasoningVisible = true, search = "", follow = false } = {}) {
    if (!request) {
      this.clear("Select a request to inspect its transcript.");
      return;
    }
    const key = requestKey(request);
    if (key !== this.currentKey) this.build(key);
    const content = Array.isArray(request.content) ? request.content : [];
    const segmentIds = new Set();
    const order = { input: [], reasoning: [], output: [] };
    content.forEach((segment, index) => {
      const segmentKey = segment.segment_id || `${segment.kind || "other"}:${segment.role || ""}:${segment.sequence ?? index}`;
      segmentIds.add(segmentKey);
      const section = segment.kind === "reasoning" ? "reasoning" : OUTPUT_KINDS.has(segment.kind) ? "output" : INPUT_KINDS.has(segment.kind) ? "input" : "input";
      let entry = this.entries.get(segmentKey);
      if (!entry) {
        entry = this.createSegment(segmentKey, section, segment);
        this.entries.set(segmentKey, entry);
        this.sections.get(section).list.append(entry.root);
      }
      entry.text.textContent = typeof segment.text === "string" ? segment.text : "[Non-text content omitted]";
      entry.root.dataset.kind = segment.kind || "other";
      entry.role.textContent = segment.role || section;
      entry.copy.disabled = typeof segment.text !== "string" || !segment.text;
      entry.root.hidden = Boolean(search) && !String(segment.text || "").toLocaleLowerCase().includes(search.toLocaleLowerCase());
      entry.cursor.hidden = segment.streaming !== true;
      entry.truncated.hidden = segment.truncated !== true;
      order[section].push(segmentKey);
    });

    for (const [segmentKey, entry] of this.entries) {
      if (!segmentIds.has(segmentKey)) {
        entry.root.remove();
        this.entries.delete(segmentKey);
      }
    }
    for (const section of ["input", "reasoning", "output"]) {
      const items = order[section].map((id) => this.entries.get(id)?.root).filter(Boolean);
      const state = request.coverage?.[section === "input" ? "structured_input" : section === "reasoning" ? "reasoning_text" : "output_text"] || "unavailable";
      const body = this.sections.get(section);
      items.forEach((item, index) => {
        if (body.list.children[index] !== item) body.list.insertBefore(item, body.list.children[index] || null);
      });
      body.reason.hidden = items.length > 0;
      body.reason.textContent = availabilityMessage(section, state);
      body.root.hidden = section === "reasoning" && !reasoningVisible;
      body.label.textContent = section === "input" && state === "rendered_only" ? "Input · rendered by source" : section;
    }
    this.container.dataset.gap = request.stream_gap === true ? "true" : "false";
    this.gapMessage.hidden = request.stream_gap !== true;
    this.container.dataset.reasoningVisible = String(reasoningVisible);
    if (search && !content.some((item) => String(item.text || "").toLocaleLowerCase().includes(search.toLocaleLowerCase()))) {
      this.searchMessage.textContent = "No transcript segments match this search.";
      this.searchMessage.hidden = false;
    } else {
      this.searchMessage.hidden = true;
    }
    if (follow) this.container.scrollTop = this.container.scrollHeight;
  }

  clear(message) {
    this.currentKey = null;
    this.entries.clear();
    this.sections.clear();
    this.container.replaceChildren();
    const note = document.createElement("p");
    note.className = "content-unavailable";
    note.textContent = message;
    this.container.append(note);
  }

  build(key) {
    this.currentKey = key;
    this.entries.clear();
    this.sections.clear();
    this.container.replaceChildren();
    this.searchMessage = document.createElement("p");
    this.searchMessage.className = "content-unavailable";
    this.searchMessage.hidden = true;
    this.container.append(this.searchMessage);
    for (const section of ["input", "reasoning", "output"]) {
      const root = document.createElement("details");
      root.className = "content-section";
      root.dataset.kind = section;
      root.open = true;
      const summary = document.createElement("summary");
      const label = document.createElement("span");
      label.textContent = section;
      summary.append(label);
      const list = document.createElement("div");
      list.className = "segment-list";
      const reason = document.createElement("p");
      reason.className = "content-unavailable";
      reason.hidden = true;
      root.append(summary, list, reason);
      this.container.append(root);
      this.sections.set(section, { root, label, list, reason });
    }
    this.gapMessage = document.createElement("p");
    this.gapMessage.className = "stream-gap-message";
    this.gapMessage.hidden = true;
    this.gapMessage.textContent = "Stream interruption observed. Later content may be incomplete.";
    this.container.append(this.gapMessage);
  }

  createSegment(key, section, segment) {
    const root = document.createElement("article");
    root.className = "content-segment";
    root.dataset.segmentKey = key;
    root.dataset.kind = segment.kind || "other";
    const roleLine = document.createElement("div");
    roleLine.className = "segment-role";
    const role = document.createElement("span");
    const meta = document.createElement("span");
    const copy = document.createElement("button");
    copy.className = "text-button segment-copy";
    copy.type = "button";
    copy.textContent = "Copy";
    copy.setAttribute("aria-label", `Copy ${section} segment`);
    copy.addEventListener("click", async () => {
      const value = text.textContent;
      try {
        await navigator.clipboard.writeText(value);
        copy.textContent = "Copied";
        window.setTimeout(() => { copy.textContent = "Copy"; }, 900);
      } catch { copy.textContent = "Unavailable"; }
    });
    meta.append(copy);
    roleLine.append(role, meta);
    const text = document.createElement("div");
    text.className = "segment-text";
    const cursor = document.createElement("span");
    cursor.className = "stream-cursor";
    cursor.setAttribute("aria-label", "Streaming");
    cursor.hidden = true;
    const truncated = document.createElement("p");
    truncated.className = "truncation-note";
    truncated.textContent = "Content truncated by the observation source.";
    truncated.hidden = true;
    root.append(roleLine, text, cursor, truncated);
    return { root, role, text, copy, cursor, truncated };
  }
}

function availabilityMessage(section, state) {
  const label = capabilityLabel(state).toLowerCase();
  if (section === "reasoning" && state === "unavailable") return "Reasoning text is unavailable from this source. This does not establish whether the model reasoned.";
  if (section === "input" && state === "rendered_only") return "This source exposes rendered input, not the original structured messages.";
  if (state === "unavailable") return `${section[0].toUpperCase()}${section.slice(1)} content is unavailable from this observation source.`;
  return `No ${section} content has been observed yet · capture ${label}.`;
}
