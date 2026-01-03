import os
import requests
from urllib.parse import urlparse, unquote
from requests.adapters import HTTPAdapter, Retry
import logging

# Configure logging
logging.basicConfig(
    format='%(levelname)s: %(message)s', level=logging.INFO
)
logger = logging.getLogger()

# Setup HTTP session with retries
session = requests.Session()
retries = Retry(total=3, backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retries)
session.mount('http://', adapter)
session.mount('https://', adapter)

# User-agent header to mimic a browser
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
}

# List of resources to download (only free/open-access)
# Each entry: {url, category_folder (relative), filename (optional)}
resources = [
    # General Organic Chemistry
    {"url": "http://www2.chemistry.msu.edu/faculty/reusch/virttxtjml/Intro.htm", 
     "category": "General"},
    {"url": "https://kpu.pressbooks.pub/organicchemistry1/download", 
     "category": "General"},
    {"url": "https://assets.openstax.org/oscms-prodcms/media/documents/OrganicChemistry-SAMPLE_9ADraVJ.pdf",
     "category": "General"},
    # MIT OCW Lecture Notes (examples)
    {"url": "https://ocw.mit.edu/courses/5-12-organic-chemistry-i-spring-2003/resources/lecture-notes/acidity.pdf", 
     "category": "General"},
    {"url": "https://ocw.mit.edu/courses/5-13-organic-chemistry-ii-fall-2006/pages/lecture-notes/lec021.pdf", 
     "category": "Spectroscopy"},
    # Lab Techniques (LibreTexts PDF)
    {"url": "https://chem.libretexts.org/@api/deki/files/182332/Organic_Chemistry_Lab_Techniques.pdf", 
     "category": "Lab"},
    # Organic Chemistry Tutor (example page)
    {"url": "https://www.organicchemistrytutor.com/topic/introduction-to-mass-spectrometry/", 
     "category": "Spectroscopy"},
    # Organic Chemistry Portal
    {"url": "https://www.organic-chemistry.org/namedreactions/", 
     "category": "Reagents"},
    # Master Organic Chemistry (blog)
    {"url": "https://www.masterorganicchemistry.com/2011/05/26/the-organic-chemistry-reagent-guide-is-here/", 
     "category": "Reagents"},
    # Leah4Sci (mechanism page)
    {"url": "https://leah4sci.com/reaction-mechanisms-in-organic-chemistry/", 
     "category": "Mechanisms"},
    # Retrosynthesis (LibreTexts page)
    {"url": "https://chem.libretexts.org/Courses/Winona_State_University/Klein_and_Straumanis_Guided/12:_Synthesis/12.02:_Retrosynthetic_Analysis", 
     "category": "Synthesis"},
    # Stereochemistry (LibreTexts)
    {"url": "https://chem.libretexts.org/Bookshelves/Introductory_Chemistry/Introduction_to_Organic_and_Biochemistry_(Malik)/03:_Stereochemistry/3.01:_Introduction_to_stereochemistry", 
     "category": "Stereochemistry"},
    # Safety (Cerritos PDF)
    {"url": "https://www.cerritos.edu/chemistry/chem_212/Documents/Lab/Organic_Chemistry_Laboratory_Safety_Notes_new.pdf", 
     "category": "Safety"},
    # Safety (CSUB PDF)
    {"url": "https://www.csub.edu/chemistry/_files/Topic1_Safety.pdf", 
     "category": "Safety"},
]

# Base folder for downloads
base_dir = "organic_chem_resources"
os.makedirs(base_dir, exist_ok=True)

def clean_filename(url):
    """Generate a safe file name from URL."""
    path = urlparse(url).path
    name = os.path.basename(path)
    if not name:
        name = "index"
    name = unquote(name)
    # Remove query parameters from filename
    name = name.split('?')[0]
    return name

for res in resources:
    url = res["url"]
    category = res["category"]
    folder = os.path.join(base_dir, category)
    os.makedirs(folder, exist_ok=True)

    filename = res.get("filename") or clean_filename(url)
    if not filename.lower().endswith(('.pdf', '.html', '.htm')):
        # If no clear extension, try to get from headers later
        filename = filename + ".html"

    filepath = os.path.join(folder, filename)
    if os.path.exists(filepath):
        logger.info(f"Already downloaded: {filepath}")
        continue

    try:
        logger.info(f"Downloading: {url}")
        resp = session.get(url, headers=HEADERS, timeout=15)
        status = resp.status_code
        if status != 200:
            logger.warning(f"Failed ({status}) for {url}, skipping.")
            continue

        content_type = resp.headers.get('Content-Type', '').lower()
        # Decide how to save content
        if 'application/pdf' in content_type or filename.lower().endswith('.pdf'):
            # Save PDF directly
            with open(filepath, 'wb') as f:
                f.write(resp.content)
            logger.info(f"Saved PDF: {filepath}")
        else:
            # Convert HTML to Markdown-like plain text (simple approach)
            text = resp.text
            # Optionally strip scripts/styles for readability
            # Here we just save as .html for manual processing
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(text)
            logger.info(f"Saved HTML: {filepath}")
    except Exception as e:
        logger.error(f"Error downloading {url}: {e}")

logger.info("Download complete.")

