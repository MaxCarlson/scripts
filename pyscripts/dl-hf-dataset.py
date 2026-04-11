import argparse
import os
from textwrap import dedent


def download_datasets(dataset_names, output_dir):
    """
    Downloads datasets from Hugging Face and saves them to a local directory.
    """
    from datasets import load_dataset

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
    parser = argparse.ArgumentParser(
        description="Download Hugging Face datasets and save them locally with datasets.save_to_disk().",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent(
            """\
            What this does:
              - Loads each dataset ID with datasets.load_dataset().
              - Saves each loaded dataset under the output directory in Apache Arrow format.
              - Replaces "/" with "_" in the local dataset folder name.

            Defaults:
              - Dataset: Anthropic/EconomicIndex
              - Output directory: ./hf_datasets

            Output layout:
              ./hf_datasets/
                Anthropic_EconomicIndex/
                  dataset_dict.json
                  <split directories and Arrow files>

            Examples:
              Download the default dataset:
                python dl-hf-dataset.py

              Download one dataset:
                python dl-hf-dataset.py -d Anthropic/EconomicIndex

              Download multiple datasets in one run:
                python dl-hf-dataset.py -d Anthropic/EconomicIndex squad glue

              Save downloads to a custom directory:
                python dl-hf-dataset.py -d squad -o D:\\datasets\\huggingface

              Use long option names:
                python dl-hf-dataset.py --datasets squad glue --output-dir ./data/hf

              Show this help:
                python dl-hf-dataset.py -h
                python dl-hf-dataset.py --help

            Notes:
              - Dataset IDs must be valid Hugging Face Hub dataset IDs.
              - Private or gated datasets may require Hugging Face authentication.
              - Downloads use the Hugging Face datasets cache before being saved to output-dir.
              - Existing output folders may be overwritten or updated by save_to_disk().
            """
        ),
    )

    # -d, --datasets: List of dataset IDs (e.g., Anthropic/EconomicIndex)
    parser.add_argument(
        "-d",
        "--datasets",
        nargs="+",
        default=["Anthropic/EconomicIndex"],
        help="List of Hugging Face dataset IDs to download.",
    )

    # -o, --output-dir: Local directory to save the datasets
    parser.add_argument(
        "-o",
        "--output-dir",
        type=str,
        default="./hf_datasets",
        help="Local directory to save the downloaded datasets.",
    )

    args = parser.parse_args()

    download_datasets(args.datasets, args.output_dir)


if __name__ == "__main__":
    main()

# download_datasets.py
