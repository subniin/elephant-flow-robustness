"""Train + evaluate one run (design.md section 2, steps 3-4).

Usage (from the project root, with src on PYTHONPATH):
    python -m flowpred.train TRAIN_CSV [--test TEST_CSV] [--n 4]
        [--thr-def bytes_pct|bytes_fixed|pkts_pct] [--thr-param 0.01]
        [--thr-fit train|test] [--tail-sec 0] [--train-max-rows N]
        [--model rf] [--seed 0] [--out RESULTS_CSV]

Only TRAIN_CSV is positional. Without --test the train CSV is split 70/30 by
start_ts. --thr-param is the top fraction p for *_pct, bytes for bytes_fixed.
--train-max-rows N: if train has more than N rows (after tail filter), fit on
a y-label stratified sample of N rows (random_state=--seed); threshold, labels and
train_flows still use the full train, test is untouched. Raises ValueError (from
sklearn) if a class has too few rows to stratify; no unstratified fallback.
--seed S (default 0): random_state of both RF models, the stratified sample and
the F1 bootstrap CI (f1_lo, f1_hi: 2.5/97.5 percentiles over B=200 resamples of
test rows; N/A if test has no positives).
--out appends one 32-column row (header written if the file is new).
"""
import argparse
import csv
import json
import math
import os

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import (f1_score, mean_absolute_error, precision_score,
                             recall_score)

from flowpred.features import (drop_tail, features, fit_threshold, label,
                               split_time)

COLUMNS = ["train_csv", "test_csv", "n", "model", "features", "thr_def",
           "thr_param", "thr_fit", "thr_value", "reg_thr_value", "tail_sec",
           "train_max_rows", "sample_rate", "train_flows", "test_flows", "test_pos", "short_flows",
           "precision", "recall", "f1", "tnr", "mae_log10",
           "clf_coverage", "clf_reduction", "reg_coverage", "reg_reduction",
           "el_short_frac", "recall_long", "recall_short", "seed", "f1_lo", "f1_hi"]


def _cov_red(pred, byte_count):
    """(traffic coverage, flow table reduction); reduction None if no positives."""
    pred = np.asarray(pred).astype(bool)
    cov = float(byte_count[pred].sum() / byte_count.sum())
    k = int(pred.sum())
    return cov, (len(pred) / k if k else None)


def stratified_recall(yte, pred, n_seen, n):
    """(el_short_frac, recall_long, recall_short) over test elephants (yte == 1).

    short = n_seen < n; n == 0 (n_seen is None) -> all long. None = N/A."""
    yte, pred = np.asarray(yte) == 1, np.asarray(pred) == 1
    short = np.zeros(len(yte), bool) if n < 1 else np.asarray(n_seen) < n
    el = int(yte.sum())

    def rec(mask):
        k = int(mask.sum())
        return float(pred[mask].sum() / k) if k else None

    return ((float(short[yte].sum() / el) if el else None),
            rec(yte & ~short), rec(yte & short))


def f1_bootstrap_ci(y, pred, seed=0, B=200):
    """(lo, hi) = 2.5/97.5 percentiles of F1 (pos=1) over B resamples of rows.

    (None, None) if y has no positives. A resample with no TP/FP/FN gets F1 0."""
    y, pred = np.asarray(y) == 1, np.asarray(pred) == 1
    if not y.any():
        return None, None
    tp, fp, fn = (y & pred).astype(np.int8), (~y & pred).astype(np.int8), (y & ~pred).astype(np.int8)
    rng, N = np.random.default_rng(seed), len(y)
    f = np.empty(B)
    for b in range(B):
        i = rng.integers(0, N, N)
        t, p, q = tp[i].sum(dtype=np.int64), fp[i].sum(dtype=np.int64), fn[i].sum(dtype=np.int64)
        f[b] = 2 * t / (2 * t + p + q) if t else 0.0
    return tuple(float(v) for v in np.percentile(f, [2.5, 97.5]))


def evaluate(Xtr, ytr, ytr_log, Xte, yte, yte_log, byte_count_te, reg_thr_value, n=0,
             seed=0):
    """Fit rf classifier/regressor on train, return metric dict (None = N/A)."""
    clf = RandomForestClassifier(n_estimators=100, class_weight="balanced",
                                 random_state=seed, n_jobs=-1).fit(Xtr, ytr)
    reg = RandomForestRegressor(n_estimators=100, random_state=seed,
                                n_jobs=-1).fit(Xtr, ytr_log)
    pred = clf.predict(Xte)
    pred_log = reg.predict(Xte)
    bc = np.asarray(byte_count_te, dtype=float)
    m = {
        "precision": precision_score(yte, pred, pos_label=1, zero_division=0),
        "recall": recall_score(yte, pred, pos_label=1, zero_division=0),
        "f1": f1_score(yte, pred, pos_label=1, zero_division=0),
        "tnr": recall_score(yte, pred, pos_label=0, zero_division=0),
        "mae_log10": mean_absolute_error(yte_log, pred_log),
    }
    m["f1_lo"], m["f1_hi"] = f1_bootstrap_ci(yte, pred, seed)
    m["clf_coverage"], m["clf_reduction"] = _cov_red(pred, bc)
    m["reg_coverage"], m["reg_reduction"] = _cov_red(
        pred_log >= math.log10(reg_thr_value), bc)
    m["el_short_frac"], m["recall_long"], m["recall_short"] = stratified_recall(
        yte, pred, Xte["n_seen"] if n >= 1 else None, n)
    return m


def _sample_rate(csv_path):
    """sample_rate from <csv>.meta.json written by preprocess; 1.0 if absent."""
    try:
        with open(str(csv_path) + ".meta.json") as fh:
            return float(json.load(fh)["sample_rate"])
    except FileNotFoundError:
        return 1.0


def run(train_csv, test_csv=None, n=4, thr_def="bytes_pct", thr_param=0.01,
        thr_fit="train", tail_sec=0.0, model="rf", train_max_rows=None, seed=0):
    """Full pipeline for one setting; returns dict with all 32 COLUMNS
    plus n_train_used (rows the models were fit on)."""
    if model != "rf":
        raise ValueError("only model 'rf' is supported")
    if thr_fit not in ("train", "test"):
        raise ValueError("thr_fit must be train or test")
    sr = _sample_rate(train_csv)
    if test_csv and _sample_rate(test_csv) != sr:
        raise ValueError(f"sample_rate differs: train={sr} test={_sample_rate(test_csv)}")
    tr = drop_tail(pd.read_csv(train_csv), tail_sec)
    if test_csv:
        te = drop_tail(pd.read_csv(test_csv), tail_sec)
    else:
        tr, te = split_time(tr)
    ref = tr if thr_fit == "train" else te
    thr = fit_threshold(ref, thr_def, thr_param)
    # pkts_pct: bytes threshold for reg metrics = same p, same reference, byte_count
    reg_thr = (fit_threshold(ref, "bytes_pct", thr_param)
               if thr_def == "pkts_pct" else thr)
    Xtr, ytr_log = features(tr, n)
    Xte, yte_log = features(te, n)
    ytr, yte = label(tr, thr_def, thr), label(te, thr_def, thr)
    if train_max_rows is not None and len(tr) > train_max_rows:
        idx = np.sort(train_test_split(np.arange(len(tr)), train_size=train_max_rows,
                                       stratify=ytr, random_state=seed)[0])
        Xtr, ytr, ytr_log = Xtr.iloc[idx], ytr.iloc[idx], ytr_log.iloc[idx]
    m = evaluate(Xtr, ytr, ytr_log, Xte, yte, yte_log, te["byte_count"], reg_thr, n, seed)
    short = float((Xte["n_seen"] < n).mean()) if n >= 1 else 0.0
    return {"train_csv": str(train_csv), "test_csv": str(test_csv or ""),
            "n": n, "model": model, "features": "all", "thr_def": thr_def,
            "thr_param": thr_param, "thr_fit": thr_fit, "thr_value": thr,
            "reg_thr_value": reg_thr, "tail_sec": tail_sec,
            "train_max_rows": train_max_rows, "sample_rate": sr, "train_flows": len(tr),
            "n_train_used": len(Xtr), "test_flows": len(te),
            "test_pos": int(yte.sum()), "short_flows": short, "seed": seed, **m}


def _f(v, fmt):
    return "N/A" if v is None else fmt.format(v)


def format_report(r):
    return "\n".join([
        f"sample_rate={r['sample_rate']} n={r['n']} flows train={r['train_flows']} test={r['test_flows']} "
        f"threshold_bytes={r['thr_value']:.6g} reg_thr_value={r['reg_thr_value']:.6g} "
        f"test_elephants={r['test_pos']} short_flows={r['short_flows']:.2f} "
        f"tail_sec={r['tail_sec']} "
        f"train_max_rows={r['train_max_rows'] if r['train_max_rows'] is not None else 'all'}",
        f"precision={r['precision']:.2f} recall={r['recall']:.2f} "
        f"f1={r['f1']:.2f} tnr={r['tnr']:.2f}",
        f"el_short_frac={_f(r['el_short_frac'], '{:.2f}')} "
        f"recall_long={_f(r['recall_long'], '{:.2f}')} "
        f"recall_short={_f(r['recall_short'], '{:.2f}')}",
        f"clf coverage={r['clf_coverage']:.2f} "
        f"table_reduction={_f(r['clf_reduction'], '{:.1f}')}",
        f"reg coverage={r['reg_coverage']:.2f} "
        f"table_reduction={_f(r['reg_reduction'], '{:.1f}')}",
        f"mae_log10={r['mae_log10']:.2f}",
        f"seed={r['seed']} f1_ci=[{_f(r['f1_lo'], '{:.2f}')}, {_f(r['f1_hi'], '{:.2f}')}]"])


def append_row(path, r):
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(COLUMNS)
        w.writerow(["" if r[c] is None else r[c] for c in COLUMNS])


def main(argv=None):
    p = argparse.ArgumentParser(prog="flowpred.train")
    p.add_argument("train_csv")
    p.add_argument("--test", dest="test_csv")
    p.add_argument("--n", type=int, default=4)
    p.add_argument("--thr-def", default="bytes_pct",
                   choices=["bytes_pct", "bytes_fixed", "pkts_pct"])
    p.add_argument("--thr-param", type=float, default=0.01)
    p.add_argument("--thr-fit", default="train", choices=["train", "test"])
    p.add_argument("--tail-sec", type=float, default=0.0)
    p.add_argument("--train-max-rows", type=int, default=None)
    p.add_argument("--model", default="rf", choices=["rf"])
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out")
    a = p.parse_args(argv)
    r = run(a.train_csv, a.test_csv, a.n, a.thr_def, a.thr_param, a.thr_fit,
            a.tail_sec, a.model, a.train_max_rows, a.seed)
    print(format_report(r))
    if a.out:
        append_row(a.out, r)
    return r


if __name__ == "__main__":
    main()
