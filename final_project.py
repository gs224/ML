# -*- coding: utf-8 -*-
"""final-project.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1ugQUgglJjLJMAbJz5z9udIidEZ3GtON6
"""

!pip install transformers datasets evaluate librosa torchaudio jiwer

!huggingface-cli login

from datasets import load_dataset, DatasetDict
import librosa
import os
from transformers import WhisperProcessor
import torch
from transformers import WhisperForConditionalGeneration
from evaluate import load
from transformers import TrainingArguments
from transformers import DataCollatorWithPadding
from transformers import Trainer
import os


dataset = load_dataset("FBK-MT/Speech-MASSIVE-test", 'pl-PL', split='test', trust_remote_code=True)
print(dataset)

dataset = dataset.select_columns(['utt','audio'])
dataset[0]

processor = WhisperProcessor.from_pretrained("openai/whisper-tiny")

def preprocess_function(batch):

    audio = batch["audio"]
    input_features = processor(
        audio["array"], sampling_rate=audio["sampling_rate"], return_tensors="pt"
    ).input_features

    batch["input_features"] = input_features
    batch["input_ids"] = processor.tokenizer(batch["utt"]).input_ids

    return batch

processed_dataset = dataset.map(preprocess_function)
# processed_dataset = processed_dataset.remove_columns(["utt", "audio"])
# to train -> comment / to evaluate -> uncomment !!!!!

train_val_dataset = processed_dataset.train_test_split(test_size=0.2, seed=42)

train_val_split = train_val_dataset["train"].train_test_split(test_size=0.25, seed=42)

processed_dataset = DatasetDict({
    "train": train_val_split["train"],
    "validation": train_val_split["test"],
    "test": train_val_dataset["test"]
})


device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using device: {device}")

model = WhisperForConditionalGeneration.from_pretrained("openai/whisper-tiny")
model.to(device)

def transcribe(batch):
    input_features = batch["input_features"]
    input_features = torch.tensor(input_features).to(device)

    with torch.no_grad():
        predicted_ids = model.generate(input_features)

    transcription = processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]
    return transcription


results = processed_dataset["test"].select(range(5)).map(lambda x: {"transcription": transcribe(x)})

for result in results:
    print(f"Original Text: {result['utt']}")
    print(f"Transcription: {result['transcription'].lower()}")
    print("-" * 50)

wer_metric = load("wer")

results = processed_dataset["test"].map(lambda x: {"transcription": transcribe(x)})

wer = wer_metric.compute(
    predictions=results["transcription"], references=results["utt"]
)


print(f"Word Error Rate (WER) on the test set: {wer:.4f}")

"""Word Error Rate (WER) on the test set: 0.8435"""


training_args = TrainingArguments(
    output_dir="./whisper-tiny-polish",
    eval_strategy="epoch",
    learning_rate=5e-5,
    per_device_train_batch_size=16,
    per_device_eval_batch_size=16,
    num_train_epochs=10,
    remove_unused_columns=False,
    push_to_hub=False,
    report_to="none",
)

def data_collator(features):
    input_features = [{"input_features": torch.tensor(feature["input_features"]).squeeze(0)} for feature in features]
    input_features = processor.feature_extractor.pad(input_features, return_tensors="pt")

    labels = [{"input_ids": feature["input_ids"]} for feature in features]
    labels = processor.tokenizer.pad(labels, return_tensors="pt")

    return {
        "input_features": input_features["input_features"],
        "labels": labels["input_ids"],
    }

os.environ["WANDB_DISABLED"] = "true"

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=processed_dataset["train"],
    eval_dataset=processed_dataset["validation"],
    data_collator=data_collator,
    tokenizer=processor.tokenizer,
)
trainer.train()

results = processed_dataset["test"].map(lambda x: {"transcription": transcribe(x)})

wer = wer_metric.compute(
    predictions=results["transcription"], references=results["utt"]
)


print(f"Word Error Rate (WER) on the test set: {wer:.4f}")

model.push_to_hub("whisper-tiny-polish")
processor.push_to_hub("whisper-tiny-polish")