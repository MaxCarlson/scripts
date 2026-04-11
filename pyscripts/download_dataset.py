import argparse
import os
from datasets import load_dataset

def download_datasets(dataset_names, output_dir):
    """
    Downloads datasets from Hugging Face and saves them to a local directory.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    for name in dataset_names:
        print(f"Attempting to download: {name}")
        try:
            # Load the dataset from the hub
            # This will cache it locally via the datasets library
            dataset = load_dataset(name)
            
            # Create a specific subdirectory for this dataset
            dataset_path = os.path.join(output_dir, name.replace("/", "_"))
            
            # Save the dataset to disk in the arrow format
            dataset.save_to_disk(dataset_path)
            print(f"Successfully saved {name} to {dataset_path}")
            
        except Exception as e:
            print(f"Failed to download {name}: {e}")

def main():
    parser = argparse.ArgumentParser(description="Download datasets from Hugging Face.")
    
    # -d, --datasets: List of dataset IDs (e.g., Anthropic/EconomicIndex)
    parser.add_argument(
        "-d", "--datasets",
        nargs="+",
        default=["Anthropic/EconomicIndex"],
        help="List of Hugging Face dataset IDs to download."
    )
    
    # -o, --output-dir: Local directory to save the datasets
    parser.add_argument(
        "-o", "--output-dir",
        type=str,
        default="./hf_datasets",
        help="Local directory to save the downloaded datasets."
    )

    args = parser.parse_args()

    download_datasets(args.datasets, args.output_dir)

if __name__ == "__main__":
    main()

# download_datasets.py
