import argparse
from .automator import WebAIAutomator
from .log_utils import setup_logger

def main():
    parser = argparse.ArgumentParser(
        description="Web AI Automator CLI. Automates interaction with web-based AI platforms.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the JSON configuration file for the target website."
    )
    parser.add_argument(
        "--prompt",
        help="The prompt to send to the AI. If not provided, the browser will open for manual interaction."
    )
    parser.add_argument(
        "--browser",
        default="chrome",
        choices=["chrome", "firefox"],
        help="Browser to use (default: chrome)."
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=False,
        help="Run the browser in headless mode (no GUI)."
    )
    args = parser.parse_args()

    # Setup logger for CLI usage
    setup_logger("web_ai_automator")

    auto = WebAIAutomator(args.config, browser=args.browser, headless=args.headless)
    try:
        auto.start_browser()
        
        if args.prompt:
            auto.enter_prompt(args.prompt)
            auto.submit()
            print("Waiting for response...")
            response = auto.get_response()
            print("\n" + "="*20 + " AI Response " + "="*20)
            print(response if response else "Failed to get a response.")
            print("="*53 + "\n")
        else:
            print("Browser started. No prompt provided.")
            input("Press Enter to close the browser...")

    except Exception as e:
        print(f"\nAn error occurred: {e}")
    finally:
        auto.close_browser()
