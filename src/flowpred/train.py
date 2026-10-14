"""Train + evaluate one run (design.md section 2, steps 3-4).

Usage (from the project root, with src on PYTHONPATH):
    python -m flowpred.train TRAIN_CSV [--test TEST_CSV] [--n 4]
        [--thr-def bytes_pct|bytes_fixed|pkts_pct] [--thr-param 0.10]
        [--thr-fit train|test] [--tail-sec 0] [--model rf] [--out RESULTS_CSV]

Only TRAIN_CSV is positional. Without --test the train CSV is split 70/30 by
start_ts. --thr-param is the top fraction p for *_pct, bytes for bytes_fixed.
--out appends one 24-column row (header written if the file is new).
"""
import argparse
import csv
import math
import os

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import (f1_score, mean_absolute_error, precision_score,
                             recall_score)

from flowpred.features import (drop_tail, features, fit_threshold, label,
                               split_time)

COLUMNS = ["train_csv", "test_csv", "n", "model", "features", "thr_def",
           "thr_param", "thr_fit", "thr_value", "reg_thr_value", "tail_sec",
           "train_flows", "test_flows", "test_pos", "short_flows",
           "precision", "recall", "f1", "tnr", "mae_log10",
           "clf_coverage", "clf_reduction", "reg_coverage", "reg_reduction"]


def _cov_red(pred, byte_count):
    """(traffic coverage, flow table reduction); reduction None if no positives."""
    pred = np.asarray(pred).astype(bool)
    cov = float(byte_count[pred].sum() / byte_count.sum())
    k = int(pred.sum())
    return cov, (len(pred) / k if k else None)


def evaluate(Xtr, ytr, ytr_log, Xte, yte, yte_log, byte_count_te, reg_thr_value):
    """Fit rf classifier/regressor on train, return metric dict (None = N/A)."""
    clf = RandomForestClassifier(n_estimators=100, class_weight="balanced",
                                 random_state=0).fit(Xtr, ytr)
    reg = RandomForestRegressor(n_estimators=100, random_state=0).fit(Xtr, ytr_log)
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
    m["clf_coverage"], m["clf_reduction"] = _cov_red(pred, bc)
    m["reg_coverage"], m["reg_reduction"] = _cov_red(
        pred_log >= math.log10(reg_thr_value), bc)
    return m


def run(train_csv, test_csv=None, n=4, thr_def="bytes_pct", thr_param=0.10,
        thr_fit="train", tail_sec=0.0, model="rf"):
    """Full pipeline for one setting; returns dict with all 24 COLUMNS."""
    if model != "rf":
        raise ValueError("only model 'rf' is supported")
    if thr_fit not in ("train", "test"):
        raise ValueError("thr_fit must be train or test")
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
    m = evaluate(Xtr, ytr, ytr_log, Xte, yte, yte_log, te["byte_count"], reg_thr)
    short = float((Xte["n_seen"] < n).mean()) if n >= 1 else 0.0
    return {"train_csv": str(train_csv), "test_csv": str(test_csv or ""),
            "n": n, "model": model, "features": "all", "thr_def": thr_def,
            "thr_param": thr_param, "thr_fit": thr_fit, "thr_value": thr,
            "reg_thr_value": reg_thr, "tail_sec": tail_sec,
            "train_flows": len(tr), "test_flows": len(te),
            "test_pos": int(yte.sum()), "short_flows": short, **m}


def _f(v, fmt):
    return "N/A" if v is None else fmt.format(v)


def format_report(r):
    return "\n".join([
        f"n={r['n']} flows train={r['train_flows']} test={r['test_flows']} "
        f"threshold_bytes={r['thr_value']:.6g} reg_thr_value={r['reg_thr_value']:.6g} "
        f"test_elephants={r['test_pos']} short_flows={r['short_flows']:.2f} "
        f"tail_sec={r['tail_sec']}",
        f"precision={r['precision']:.2f} recall={r['recall']:.2f} "
        f"f1={r['f1']:.2f} tnr={r['tnr']:.2f}",
        f"clf coverage={r['clf_coverage']:.2f} "
        f"table_reduction={_f(r['clf_reduction'], '{:.1f}')}",
        f"reg coverage={r['reg_coverage']:.2f} "
        f"table_reduction={_f(r['reg_reduction'], '{:.1f}')}",
        f"mae_log10={r['mae_log10']:.2f}"])


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
    p.add_argument("--thr-param", type=float, default=0.10)
    p.add_argument("--thr-fit", default="train", choices=["train", "test"])
    p.add_argument("--tail-sec", type=float, default=0.0)
    p.add_argument("--model", default="rf", choices=["rf"])
    p.add_argument("--out")
    a = p.parse_args(argv)
    r = run(a.train_csv, a.test_csv, a.n, a.thr_def, a.thr_param, a.thr_fit,
            a.tail_sec, a.model)
    print(format_report(r))
    if a.out:
        append_row(a.out, r)
    return r


if __name__ == "__main__":
    main()
