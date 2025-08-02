from web_ai_automator.automator import WebAIAutomator

auto = WebAIAutomator("configs/gemini.json", headless=False)
auto.start_browser()
input("Browser started. Press enter after manual login.")
auto.enter_prompt("Hello, Gemini!")
auto.submit()
print("Waiting for response...")
response = auto.get_response()
print("Gemini says:", response)
auto.close_browser()
