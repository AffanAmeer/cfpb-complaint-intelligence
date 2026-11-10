"""
Train and evaluate the complaint classifier: read a complaint's narrative, predict
which product group it belongs to (Credit card, Mortgage, Debt collection, ...).

Why this is useful
    Every complaint has to reach the team that owns that product. Consumers pick the
    product themselves on the CFPB form, but at a bank, complaints also come in by
    email, chat and phone with no label at all. A model that reads the text and
    suggests the product is the first step of routing them.

Steps
    1. Read the narratives (load_narratives.py) and clean the text.
    2. Split by date: train on older complaints, test on the newest months.
       The months just before the test period are a validation set for choosing
       settings, so the test set is only used once, at the end.
    3. Handle repeated texts (form letters) so the test can't be passed by memory.
    4. Baselines: always guess the most common group, and a hand-written keyword
       rule set. A model is only worth it if it clearly beats these.
    5. Tune TF-IDF + logistic regression on the validation months, refit on all
       training months, and score the test months once.
    5b. The product mix changed a lot between 2025 and 2026 (credit reporting fell
       from 55% of narratives to 2%). Re-estimate the new mix from the model's own
       predictions, without test labels, and adjust the probabilities (EM, see
       text_model.adjust_for_new_mix). Both versions are reported.
    6. Save the metrics, confusion matrix, top phrases per group and the
       confidence-routing table to reports/classifier/.

How to run it on the Mac (project folder, venv active)
    python src/classifier/train_classifier.py
The tuning step trains 6 models and takes most of the time (about an hour in
total). To skip it and reuse the settings that won (saved in
reports/classifier/tuning_validation.csv):
    python src/classifier/train_classifier.py --skip-tuning
"""

import argparse
import json
import time
from pathlib import Path

import duckdb
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (accuracy_score, classification_report, confusion_matrix,
                             f1_score)

import text_model as tm

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "narratives" / "narratives.duckdb"
OUT_DIR = PROJECT_ROOT / "reports" / "classifier"
MODEL_PATH = PROJECT_ROOT / "data" / "models" / "product_classifier.joblib"

TEST_START = "2026-01-01"     # test: Jan-Feb 2026
VALID_START = "2025-11-01"    # validation: Nov-Dec 2025 (train for tuning: before that)
GRID = [(C, cw) for C in (1.0, 4.0, 16.0) for cw in (None, "balanced")]


def scores(name, y_true, y_pred):
    return {
        "model": name,
        "accuracy": round(accuracy_score(y_true, y_pred), 4),
        "macro_f1": round(f1_score(y_true, y_pred, average="macro"), 4),
        "weighted_f1": round(f1_score(y_true, y_pred, average="weighted"), 4),
    }


def load():
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        df = con.execute(
            "select complaint_id, date_received, product_group, narrative from narratives"
        ).df()
    df["date_received"] = pd.to_datetime(df["date_received"]).dt.date
    df["clean_text"] = df["narrative"].map(tm.clean_text)
    return df[df["clean_text"].str.len() > 0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-start", default=TEST_START)
    parser.add_argument("--valid-start", default=VALID_START)
    parser.add_argument("--skip-tuning", action="store_true",
                        help="reuse the best settings from the last tuning_validation.csv")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    df = load()
    train_all, _, test_raw = tm.time_split(df, args.test_start)
    tune_train_raw, valid_raw, _ = tm.time_split(df, args.test_start, args.valid_start)

    train, test = tm.drop_repeated_text(train_all, test_raw)
    tune_train, valid = tm.drop_repeated_text(tune_train_raw, valid_raw)

    summary = {
        "narratives_loaded": len(df),
        "first_date": str(df["date_received"].min()),
        "last_date": str(df["date_received"].max()),
        "train_period": f"{df['date_received'].min()} to before {args.test_start}",
        "test_period": f"{args.test_start} to {test_raw['date_received'].max()}",
        "train_rows_before_dedup": len(train_all),
        "train_rows": len(train),
        "test_rows_before_dedup": len(test_raw),
        "test_rows": len(test),
        "test_rows_dropped_seen_in_train": len(test_raw.drop_duplicates("clean_text")) - len(test),
        "classes": int(train["product_group"].nunique()),
    }
    print(json.dumps(summary, indent=2))

    label_mix = pd.concat([
        train["product_group"].value_counts().rename("train"),
        test["product_group"].value_counts().rename("test"),
    ], axis=1).fillna(0).astype(int)
    label_mix["train_share"] = (label_mix["train"] / label_mix["train"].sum()).round(4)
    label_mix["test_share"] = (label_mix["test"] / label_mix["test"].sum()).round(4)
    label_mix.rename_axis("product_group").to_csv(OUT_DIR / "label_mix.csv")

    # Baselines, scored on the test set.
    majority = train["product_group"].mode()[0]
    results = [
        scores("Always the most common group", test["product_group"], [majority] * len(test)),
        scores("Keyword rules", test["product_group"], tm.keyword_baseline(test["clean_text"], majority)),
    ]

    # Tuning on the validation months only.
    if args.skip_tuning:
        tuning = pd.read_csv(OUT_DIR / "tuning_validation.csv")
    else:
        tuning = []
        for C, cw in GRID:
            start = time.time()
            pipe = tm.build_pipeline(C=C, class_weight=cw).fit(tune_train["clean_text"], tune_train["product_group"])
            row = scores("tfidf_logreg", valid["product_group"], pipe.predict(valid["clean_text"]))
            row.update({"C": C, "class_weight": cw or "none", "seconds": round(time.time() - start)})
            print(row)
            tuning.append(row)
        tuning = pd.DataFrame(tuning).drop(columns="model")
        tuning.to_csv(OUT_DIR / "tuning_validation.csv", index=False)
    best = tuning.sort_values("macro_f1", ascending=False).iloc[0]
    best_C = float(best["C"])
    best_cw = None if best["class_weight"] == "none" else best["class_weight"]
    print(f"Best on validation: C={best_C}, class_weight={best_cw}")

    # Refit on all training months, then the one and only look at the test set.
    pipe = tm.build_pipeline(C=best_C, class_weight=best_cw).fit(train["clean_text"], train["product_group"])
    raw_proba = pipe.predict_proba(test["clean_text"])
    classes = pipe.named_steps["model"].classes_
    results.append(scores("TF-IDF + logistic regression", test["product_group"], classes[raw_proba.argmax(axis=1)]))

    # The product mix of the test months is very different from 2025 (see label_mix.csv).
    # Re-estimate it from the model's own predictions (no test labels) and correct for it.
    train_prior = train["product_group"].value_counts(normalize=True).reindex(classes).to_numpy()
    proba, estimated_mix = tm.adjust_for_new_mix(raw_proba, train_prior)
    pred = classes[proba.argmax(axis=1)]
    results.append(scores("TF-IDF + logistic regression, adjusted for new mix", test["product_group"], pred))
    pd.DataFrame({
        "product_group": classes,
        "train_share": train_prior.round(4),
        "estimated_test_share": estimated_mix.round(4),
        "actual_test_share": test["product_group"].value_counts(normalize=True).reindex(classes).fillna(0).round(4).to_numpy(),
    }).to_csv(OUT_DIR / "mix_adjustment.csv", index=False)

    results = pd.DataFrame(results)
    results.to_csv(OUT_DIR / "model_comparison.csv", index=False)
    print(results.to_string(index=False))

    report = pd.DataFrame(classification_report(test["product_group"], pred, output_dict=True, zero_division=0)).T
    report.index.name = "product_group"
    report.round(4).to_csv(OUT_DIR / "classification_report.csv")

    cm = pd.DataFrame(confusion_matrix(test["product_group"], pred, labels=classes), index=classes, columns=classes)
    cm.index.name = "actual \\ predicted"
    cm.to_csv(OUT_DIR / "confusion_matrix.csv")

    tm.top_terms(pipe).to_csv(OUT_DIR / "top_terms.csv", index=False)
    tm.confidence_routing(test["product_group"], proba, classes).to_csv(OUT_DIR / "confidence_routing.csv", index=False)

    summary.update({"best_C": best_C, "best_class_weight": best_cw or "none"})
    (OUT_DIR / "run_summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, MODEL_PATH)
    print(f"Saved results to {OUT_DIR.relative_to(PROJECT_ROOT)} and the model to {MODEL_PATH.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
