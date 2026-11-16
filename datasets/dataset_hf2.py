
from datasets import load_dataset
import os

print("Loading HackAPrompt dataset...")

# Load dataset from Hugging Face
ds = load_dataset("hackaprompt/hackaprompt-dataset")

# Access training split
train_data = ds["train"]

print("Dataset loaded successfully!")
print("Total records:", len(train_data))

# Export to CSV
output_file = "hackaprompt_dataset.csv"

train_data.to_csv(output_file, index=False)

print("\nCSV file created successfully!")
print("File location:", os.path.abspath(output_file))
print("Total records exported:", len(train_data))
