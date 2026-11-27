"""Fine-tune a multilingual encoder (MuRIL, IndicBERT, XLM-R) for the 7 classes with the HF Trainer.

Needs requirements-transformers.txt. Picks the checkpoint with the best dev macro-F1 and stops early
when dev macro-F1 stops improving.
"""
import os

from common.labels import CLASSES


class HFClassifier:
    def __init__(self, params: dict, seed: int = 13, output_dir: str = "checkpoints/hf"):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        self.torch = torch
        self.p, self.seed, self.output_dir = params, seed, output_dir
        self.label2id = {c: i for i, c in enumerate(CLASSES)}
        self.id2label = {i: c for c, i in self.label2id.items()}
        self.tok = AutoTokenizer.from_pretrained(params["model_name"])
        self.model = AutoModelForSequenceClassification.from_pretrained(
            params["model_name"], num_labels=len(CLASSES), id2label=self.id2label, label2id=self.label2id)
        self.device = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")

    def _dataset(self, texts, labels):
        from datasets import Dataset
        ds = Dataset.from_dict({"text": texts, "label": [self.label2id[y] for y in labels]})
        return ds.map(lambda b: self.tok(b["text"], truncation=True, max_length=self.p.get("max_length", 256)),
                      batched=True, remove_columns=["text"])

    def fit(self, texts, labels, dev_texts=None, dev_labels=None):
        import numpy as np
        from transformers import (DataCollatorWithPadding, EarlyStoppingCallback, Trainer, TrainingArguments,
                                  set_seed)

        from models.metrics import macro_f1
        set_seed(self.seed)
        torch = self.torch
        train_ds = self._dataset(texts, labels)
        dev_ds = self._dataset(dev_texts, dev_labels) if dev_texts else None

        weights = None
        if self.p.get("class_weighted_loss", True):
            counts = np.bincount(train_ds["label"], minlength=len(CLASSES)).astype(float)
            w = np.where(counts > 0, counts.sum() / (len(CLASSES) * np.maximum(counts, 1)), 0.0)
            weights = torch.tensor(w, dtype=torch.float)

        class WeightedTrainer(Trainer):
            def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
                labels_t = inputs.pop("labels")
                outputs = model(**inputs)
                lw = weights.to(outputs.logits.device) if weights is not None else None
                loss = torch.nn.functional.cross_entropy(outputs.logits, labels_t, weight=lw)
                return (loss, outputs) if return_outputs else loss

        def metrics(ev):
            logits, y = ev
            pred = logits.argmax(-1)
            return {"macro_f1": macro_f1([CLASSES[i] for i in y], [CLASSES[i] for i in pred])}

        has_dev = dev_ds is not None and len(dev_ds) > 0
        args = TrainingArguments(
            output_dir=self.output_dir, seed=self.seed, report_to="none",
            learning_rate=float(self.p.get("learning_rate", 2e-5)),
            num_train_epochs=float(self.p.get("epochs", 5)),
            per_device_train_batch_size=int(self.p.get("batch_size", 16)),
            per_device_eval_batch_size=int(self.p.get("eval_batch_size", 64)),
            gradient_accumulation_steps=int(self.p.get("grad_accum", 1)),
            weight_decay=float(self.p.get("weight_decay", 0.01)),
            warmup_ratio=float(self.p.get("warmup_ratio", 0.1)),
            fp16=bool(self.p.get("fp16", True)) and torch.cuda.is_available(),
            eval_strategy="epoch" if has_dev else "no",
            save_strategy="epoch" if has_dev else "no",
            load_best_model_at_end=has_dev, metric_for_best_model="macro_f1", greater_is_better=True,
            save_total_limit=1, logging_steps=50,
        )
        trainer = WeightedTrainer(
            model=self.model, args=args, train_dataset=train_ds, eval_dataset=dev_ds if has_dev else None,
            data_collator=DataCollatorWithPadding(self.tok), compute_metrics=metrics if has_dev else None,
            callbacks=[EarlyStoppingCallback(int(self.p.get("early_stopping_patience", 2)))] if has_dev else None)
        trainer.train()
        self.model = trainer.model
        return self

    def predict(self, texts):
        torch = self.torch
        self.model.to(self.device).eval()
        out, bs = [], int(self.p.get("eval_batch_size", 64))
        with torch.no_grad():
            for i in range(0, len(texts), bs):
                enc = self.tok(texts[i:i + bs], truncation=True, max_length=self.p.get("max_length", 256),
                               padding=True, return_tensors="pt").to(self.device)
                logits = self.model(**enc).logits
                out += [self.id2label[int(j)] for j in logits.argmax(-1).cpu()]
        return out

    def save(self, path):
        os.makedirs(path, exist_ok=True)
        self.model.save_pretrained(path)
        self.tok.save_pretrained(path)
