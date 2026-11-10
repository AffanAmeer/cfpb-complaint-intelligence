"""
The pieces of the complaint classifier, kept small so the tests can check them:
text cleaning, the time-based split, duplicate handling, the keyword baseline and
the TF-IDF + logistic regression pipeline.

train_classifier.py puts them together.
"""

import re

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

# CFPB scrubs personal details before publishing: dates become XX/XX/XXXX, names and
# account numbers become XXXX, and amounts are wrapped like {$40000.00}.
REDACTED = re.compile(r"\bx{2,}\b", re.IGNORECASE)
AMOUNT = re.compile(r"\{\$[\d,.]+\}")
NOT_LETTERS = re.compile(r"[^a-z]+")


def clean_text(text):
    """Lowercase, drop the redaction marks, keep a token for money amounts, keep letters only."""
    text = AMOUNT.sub(" dollaramount ", str(text))
    text = REDACTED.sub(" ", text).lower()
    return NOT_LETTERS.sub(" ", text).strip()


def time_split(df, test_start, valid_start=None):
    """
    Split by the date the complaint was received, never at random.
    A model in production only ever sees the past, so we test it the same way:
    train on older complaints, test on newer ones it has never seen.

    Returns train, valid (empty if valid_start is None) and test.
    """
    dates = pd.to_datetime(df["date_received"])
    test = df[dates >= pd.Timestamp(test_start)]
    if valid_start is None:
        return df[dates < pd.Timestamp(test_start)], df.iloc[0:0], test
    valid_mask = (dates >= pd.Timestamp(valid_start)) & (dates < pd.Timestamp(test_start))
    return df[dates < pd.Timestamp(valid_start)], df[valid_mask], test


def drop_repeated_text(train, test):
    """
    Some narratives appear many times: form letters, or one consumer filing the same
    story against several companies. Two fixes:
      * in training, keep one copy of each text (so a form letter isn't counted 50 times)
      * in testing, drop texts the model already saw in training, otherwise the test
        rewards memorising instead of generalising.
    """
    train = train.drop_duplicates(subset="clean_text")
    seen = set(train["clean_text"])
    test = test.drop_duplicates(subset="clean_text")
    test = test[~test["clean_text"].isin(seen)]
    return train, test


# A quick hand-written rule set: the kind of thing a team might set up before any
# model. Checked in order; the first group with a matching phrase wins. Anything
# with no match goes to the most common group.
KEYWORD_RULES = [
    ("Student loan", ["student loan", "loan servicer", "mohela", "nelnet", "navient", "pslf", "fafsa"]),
    ("Mortgage", ["mortgage", "escrow", "foreclosure", "refinanc", "loan modification", "home loan"]),
    ("Vehicle loan/lease", ["car loan", "auto loan", "vehicle", "repossess", "lease"]),
    ("Credit reporting", ["credit report", "experian", "equifax", "transunion", "credit bureau"]),
    ("Prepaid card", ["prepaid", "gift card", "ebt"]),
    ("Money transfer", ["zelle", "cash app", "paypal", "venmo", "wire transfer", "crypto", "coinbase", "western union"]),
    ("Payday/personal loan", ["payday", "personal loan", "title loan", "installment loan"]),
    ("Debt or credit mgmt", ["debt settlement", "credit repair", "debt relief"]),
    ("Debt collection", ["debt collector", "collection agency", "collections", "validation", "fdcpa"]),
    ("Credit card", ["credit card", "card", "apr", "statement balance"]),
    ("Checking/savings", ["checking", "savings", "bank account", "overdraft", "deposit"]),
]


def keyword_baseline(texts, fallback):
    """Predict a product group with KEYWORD_RULES. texts should already be cleaned."""
    # \b = start of a word, so "lease" does not match inside "please".
    patterns = [(group, re.compile(r"\b(?:" + "|".join(map(re.escape, phrases)) + ")"))
                for group, phrases in KEYWORD_RULES]
    preds = []
    for text in texts:
        label = fallback
        for group, pattern in patterns:
            if pattern.search(text):
                label = group
                break
        preds.append(label)
    return np.array(preds)


def build_pipeline(C=4.0, class_weight=None):
    """
    TF-IDF turns each narrative into a long, mostly-zero vector: one number per word
    or two-word phrase, high when the phrase is common in this complaint but rare
    across all complaints. Logistic regression then learns one weight per phrase
    per product group.
    """
    return Pipeline([
        ("tfidf", TfidfVectorizer(
            ngram_range=(1, 2),     # single words and two-word phrases ("late fee")
            min_df=5,               # ignore phrases seen in fewer than 5 complaints
            max_df=0.5,             # ignore phrases in more than half of them
            max_features=300_000,
            sublinear_tf=True,      # 10 mentions is not 10x as important as 1
            stop_words="english",
            token_pattern=r"\b[a-z]{2,}\b",
            dtype=np.float32,
        )),
        ("model", LogisticRegression(
            C=C,                    # lower C = stronger regularisation (simpler model)
            class_weight=class_weight,
            max_iter=2000,
        )),
    ])


def top_terms(pipeline, n=12):
    """The phrases with the biggest positive weight for each product group."""
    vocab = np.array(pipeline.named_steps["tfidf"].get_feature_names_out())
    model = pipeline.named_steps["model"]
    rows = []
    for label, weights in zip(model.classes_, model.coef_):
        for rank, i in enumerate(np.argsort(weights)[::-1][:n], start=1):
            rows.append({"product_group": label, "rank": rank, "term": vocab[i], "weight": round(float(weights[i]), 3)})
    return pd.DataFrame(rows)


def confidence_routing(y_true, proba, classes, thresholds=(0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95)):
    """
    If we only auto-route complaints where the model is at least this confident,
    and send the rest to a person, how many get auto-routed and how many of those
    are right?
    """
    y_true = np.asarray(y_true)
    best = proba.max(axis=1)
    pred = np.asarray(classes)[proba.argmax(axis=1)]
    rows = []
    for t in thresholds:
        keep = best >= t
        rows.append({
            "min_confidence": t,
            "share_auto_routed": round(float(keep.mean()), 4),
            "accuracy_auto_routed": round(float((pred[keep] == y_true[keep]).mean()), 4) if keep.any() else np.nan,
            "sent_to_person": int((~keep).sum()),
        })
    return pd.DataFrame(rows)


def adjust_for_new_mix(proba, train_prior, max_iter=200, tol=1e-6):
    """
    Correct the model's probabilities when the product mix has changed since training
    ("label shift"), WITHOUT using any labels from the new period.

    A model learns how common each group was in training. If credit reporting was 55%
    of training but is 2% now, the model still leans towards it. This is the EM method
    of Saerens, Latinne and Decaestecker (2002):
      1. guess the new mix (start from the training mix)
      2. rescale every probability by new_share / train_share, then renormalise
      3. the new guess = the average of the rescaled probabilities
      4. repeat until the guess stops moving

    Returns the adjusted probabilities and the estimated new mix.
    """
    train_prior = np.asarray(train_prior, dtype=float)
    new_prior = train_prior.copy()
    for _ in range(max_iter):
        adjusted = proba * (new_prior / train_prior)
        adjusted /= adjusted.sum(axis=1, keepdims=True)
        estimate = adjusted.mean(axis=0)
        if np.abs(estimate - new_prior).max() < tol:
            new_prior = estimate
            break
        new_prior = estimate
    return adjusted, new_prior
