"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function makeElement(tagName) {
  const listeners = new Map();
  return {
    tagName,
    children: [],
    attributes: {},
    dataset: {},
    className: "",
    _textContent: undefined,
    get textContent() {
      return this._textContent ?? this.children.map((child) => child.textContent || "").join("");
    },
    set textContent(value) { this._textContent = String(value); this.children = []; },
    append(...children) { this._textContent = undefined; this.children.push(...children); },
    replaceChildren(...children) { this._textContent = undefined; this.children = [...children]; },
    setAttribute(name, value) { this.attributes[name] = String(value); },
    addEventListener(name, callback) { listeners.set(name, callback); },
    click() { listeners.get("click")?.(); },
  };
}

const document = { createElement: makeElement };
const context = vm.createContext({ document, Date, globalThis: {} });
const source = fs.readFileSync(path.join(__dirname, "../src/runmux/web_static/assets/history_view.js"), "utf8");
vm.runInContext(source, context);

const events = [];
const body = makeElement("tbody");
context.globalThis.RunmuxHistoryView.renderRunRows(body, [
  { id: "id-one", name: "shared name", status: "finished", created_at: "2026-10-24T10:00:00Z", ended_at: "2026-10-24T10:01:00Z", exit_code: 0 },
  { id: "id-two", name: "shared name", status: "lost" },
  { id: "id-three", name: "<img src=x onerror=alert(1)>", status: "failed" },
  { name: "missing id", status: "finished" },
], (id) => events.push(id));

assert.equal(body.children.length, 3, "rows without immutable run IDs must be omitted");
assert.equal(body.children[0].children[0].textContent, "shared name");
assert.equal(body.children[0].children[1].className, "history-status finished");
assert.equal(body.children[1].children[2].children[0].textContent, "id-two");
assert.match(body.children[1].children[4].textContent, /—/);
assert.equal(body.children[2].children[0].textContent, "<img src=x onerror=alert(1)>", "run names must be inserted as text");
body.children[0].children[2].children[0].click();
body.children[1].children[2].children[0].click();
assert.deepEqual(events, ["id-one", "id-two"], "duplicate names must retain distinct Run ID navigation");

context.globalThis.RunmuxHistoryView.renderRunRows(body, Array.from({ length: 250 }, (_, index) => ({ id: `run-${index}`, status: "finished" })), () => {});
assert.equal(body.children.length, 200, "rendering must stay bounded to the maximum API page");

console.log("history_view_test.js passed");
