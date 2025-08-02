import json
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from .log_utils import setup_logger

logger = setup_logger("web_ai_automator.automator")

class WebAIAutomator:
    """
    Automates interactions with a web-based AI platform using Selenium.
    """
    def __init__(self, config_path, browser="chrome", headless=False):
        self.config_path = config_path
        self.browser_name = browser.lower()
        self.headless = headless
        self.driver = None
        self.config = self._load_config()
        self.wait = None
        self.pre_submit_response_count = 0

    def _load_config(self):
        """Loads the JSON configuration file."""
        logger.info(f"Loading configuration from {self.config_path}")
        with open(self.config_path, 'r') as f:
            return json.load(f)

    def start_browser(self):
        """Initializes the WebDriver and navigates to the target URL."""
        logger.info(f"Starting {self.browser_name} browser (headless: {self.headless})")
        if self.browser_name == "chrome":
            options = webdriver.ChromeOptions()
            if self.headless:
                options.add_argument("--headless")
                options.add_argument("--disable-gpu")
                options.add_argument("--window-size=1920,1080")
            self.driver = webdriver.Chrome(options=options)
        elif self.browser_name == "firefox":
            options = webdriver.FirefoxOptions()
            if self.headless:
                options.add_argument("--headless")
            self.driver = webdriver.Firefox(options=options)
        else:
            raise ValueError(f"Unsupported browser: {self.browser_name}")

        self.wait = WebDriverWait(self.driver, 30) # Increased wait time for robustness
        self.driver.get(self.config["url"])
        logger.info(f"Navigated to {self.config['url']}")

    def close_browser(self):
        """Closes the WebDriver session."""
        if self.driver:
            logger.info("Closing browser.")
            self.driver.quit()
            self.driver = None

    def _find_element(self, selector_key, wait_time=20):
        """Finds an element using a selector from the config."""
        selector_info = self.config["selectors"].get(selector_key)
        if not selector_info:
            raise ValueError(f"Selector key '{selector_key}' not found in config.")

        by = getattr(By, selector_info.get("by", "CSS_SELECTOR").upper())
        selector = selector_info["value"]
            
        try:
            wait = self.wait if wait_time == 30 else WebDriverWait(self.driver, wait_time)
            return wait.until(EC.presence_of_element_located((by, selector)))
        except TimeoutException:
            logger.error(f"Element with selector '{selector}' not found within {wait_time} seconds.")
            raise

    def set_parameters(self, params: dict):
        """Sets various parameters on the page as defined in the config."""
        if "parameters" not in self.config.get("selectors", {}):
            logger.warning("No 'parameters' section in config selectors. Skipping.")
            return

        for key, value in params.items():
            if key not in self.config["selectors"]["parameters"]:
                logger.warning(f"Parameter key '{key}' not found in config parameters. Skipping.")
                continue
            
            logger.info(f"Setting parameter '{key}' with value '{value}'")
            element = self._find_element(key, wait_time=10)
            element.clear()
            element.send_keys(value)

    def enter_prompt(self, prompt: str):
        """Enters the given prompt into the text input area."""
        logger.info("Entering prompt...")
        prompt_element = self._find_element("prompt_input")
        prompt_element.click() # Ensure the element is focused
        prompt_element.send_keys(prompt)
        logger.info("Prompt entered.")

    def submit(self):
        """Clicks the submit button to send the prompt."""
        logger.info("Submitting prompt...")
        try:
            response_selector = self.config["selectors"]["response_area"]["value"]
            self.pre_submit_response_count = len(self.driver.find_elements(By.CSS_SELECTOR, response_selector))
        except (NoSuchElementException, KeyError):
            self.pre_submit_response_count = 0
        
        submit_button = self._find_element("submit_button")
        self.driver.execute_script("arguments[0].click();", submit_button) # More reliable click
        logger.info("Prompt submitted.")

    def get_response(self) -> str:
        """Waits for and retrieves the new response text."""
        logger.info("Waiting for response...")
        
        response_area_selector = self.config["selectors"]["response_area"]["value"]
        last_response_selector = self.config["selectors"]["last_response"]["value"]

        try:
            # Wait for a new response container to be added
            self.wait.until(
                lambda driver: len(driver.find_elements(By.CSS_SELECTOR, response_area_selector)) > self.pre_submit_response_count
            )
            
            # Wait for the last response element to be populated
            response_element = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, last_response_selector))
            )
            
            # Wait for text to appear, as it might render slowly
            self.wait.until(
                lambda driver: driver.find_element(By.CSS_SELECTOR, last_response_selector).text.strip() != ""
            )

            time.sleep(1) # Extra pause for stability
            
            final_text = self.driver.find_element(By.CSS_SELECTOR, last_response_selector).text
            logger.info("Response received.")
            return final_text
        except TimeoutException:
            logger.error("Timed out waiting for a new response to appear or populate.")
            return None
