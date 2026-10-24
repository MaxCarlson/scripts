"use strict";

const form = document.querySelector("#login-form");
const error = document.querySelector("#login-error");
const codeInput = document.querySelector("#login-code");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.textContent = "";
  try {
    const response = await fetch("/auth/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: codeInput.value }),
    });
    if (!response.ok) throw new Error("The login code was not accepted.");
    codeInput.value = "";
    const data = await fetch("/api/hello", { credentials: "same-origin" });
    if (!data.ok) throw new Error("The application route could not be reached.");
    document.querySelector("#message").textContent = (await data.json()).message;
    document.querySelector("#app-result").hidden = false;
  } catch (cause) {
    error.textContent = cause.message;
  }
});
