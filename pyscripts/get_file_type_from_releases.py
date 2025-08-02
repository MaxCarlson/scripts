#!/usr/bin/env zsh

# Script to find and optionally download the latest WezTerm Android APK from GitHub releases.

# --- Configuration ---
REPO="wez/wezterm"
NUM_RELEASES_TO_CHECK=30 # Increased to check more, as APKs might be sporadic
DOWNLOAD_DIR="${HOME}/storage/downloads" # Where to save the APK

# --- Helper Functions ---
print_info() {
  echo "INFO: $1"
}

print_success() {
  echo "SUCCESS: $1"
}

print_warning() {
  echo "WARNING: $1"
}

print_error() {
  echo "ERROR: $1" >&2
}

# --- Main Logic ---

# Check if gh is installed
if ! command -v gh &> /dev/null; then
  print_error "GitHub CLI 'gh' is not installed. Please install it first: pkg install gh"
  exit 1
fi

# Check if jq is installed
if ! command -v jq &> /dev/null; then
  print_error "'jq' is not installed. Please install it first: pkg install jq"
  exit 1
fi


# Check if logged in
if ! gh auth status &> /dev/null; then
  print_warning "Not logged into GitHub CLI. Some operations might fail."
  print_info "Attempting to continue for public repository asset listing..."
fi

print_info "Fetching the latest $NUM_RELEASES_TO_CHECK releases from $REPO..."

local releases_data
releases_data=$(gh release list --repo "$REPO" --limit "$NUM_RELEASES_TO_CHECK" --json tagName,isLatest,isPrerelease,name 2>/dev/null)

if [[ -z "$releases_data" ]]; then
  print_error "Could not fetch release list. Check network or gh authentication."
  exit 1
fi

local release_tags
release_tags=($(echo "$releases_data" | jq -r '.[] | .tagName'))

if (( ${#release_tags[@]} == 0 )); then
  print_error "No release tags found. Something went wrong."
  exit 1
fi

print_info "Found ${#release_tags[@]} tags to check. Iterating..."

local found_apk_tag=""
local found_apk_name=""
local found_apk_url=""

for tag in "${release_tags[@]}"; do
  print_info "Checking release tag: $tag"
  local assets_json
  assets_json=$(gh release view "$tag" --repo "$REPO" --json assets 2>/dev/null)

  if [[ -z "$assets_json" ]]; then
    print_warning "Could not fetch assets for tag $tag. Skipping."
    continue
  fi

  # MODIFIED JQ FILTER:
  # Look for assets where contentType is for Android packages OR name ends with .apk
  # (Prioritize contentType, but also check name as a fallback)
  local apk_info
  apk_info=$(echo "$assets_json" | jq -r '.assets[] | select(
        (.contentType == "application/vnd.android.package-archive") or 
        (.name | test("\\.apk$"; "i"))  # Ends with .apk, case insensitive
    ) | "\(.name)##\(.browserDownloadUrl)"' 2>/dev/null)


  if [[ -n "$apk_info" ]]; then
    local first_match_line=$(echo "$apk_info" | head -n 1)
    found_apk_name="${first_match_line%##*}"
    found_apk_url="${first_match_line#*##}"
    found_apk_tag="$tag"

    print_success "Found APK in tag '$found_apk_tag': $found_apk_name"
    print_info "Download URL: $found_apk_url"
    break 
  else
    print_info "No definitive Android APK found in tag $tag based on filename or contentType."
  fi
done

echo "" 

if [[ -n "$found_apk_tag" && -n "$found_apk_name" && -n "$found_apk_url" ]]; then
  read -q "REPLY?Do you want to download '$found_apk_name' from release '$found_apk_tag'? (y/n): "
  echo"" 
  if [[ "$REPLY" == "y" || "$REPLY" == "Y" ]]; then
    print_info "Downloading to $DOWNLOAD_DIR/$found_apk_name ..."
    mkdir -p "$DOWNLOAD_DIR"
    if gh release download "$found_apk_tag" --repo "$REPO" -p "$found_apk_name" -D "$DOWNLOAD_DIR" --clobber; then
      print_success "Download complete: $DOWNLOAD_DIR/$found_apk_name"
      print_info "You can now install it via your Android file manager."
    else
      print_error "Download failed using 'gh release download'."
      print_info "Attempting fallback with curl..."
      if curl -L -o "$DOWNLOAD_DIR/$found_apk_name" "$found_apk_url"; then
        print_success "Download complete (via curl): $DOWNLOAD_DIR/$found_apk_name"
        print_info "You can now install it via your Android file manager."
      else
        print_error "Fallback download with curl also failed."
      fi
    fi
  else
    print_info "Download skipped by user."
  fi
else
  print_warning "No definitive Android APK found in the latest $NUM_RELEASES_TO_CHECK releases checked."
  print_info "You might need to check older releases or the WezTerm website/F-Droid, or adjust the script's search pattern."
fi

exit 0
