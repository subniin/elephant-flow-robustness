import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd
import pytest

from flowpred.train import COLUMNS, f1_bootstrap_ci, main, run, stratified_recall


def synth(rows=300, seed=0, t0=0.0):
    rng = np.random.default_rng(seed)
    plen = rng.integers(40, 1500, size=(rows, 10))
    big = rng.random(rows) < 0.2
    pkts = np.where(big, rng.integers(50, 500, rows), rng.integers(1, 10, rows))
    d = {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2",
         "src_port": rng.integers(1024, 60000, rows),
         "dst_port": np.where(big, 443, 53), "proto": 6,
         "start_ts": t0 + np.sort(rng.random(rows)) * 100,
         "pkt_count": pkts, "byte_count": pkts * plen[:, 0] + 40}
    for k in range(1, 11):
        d[f"plen_{k}"] = plen[:, k - 1]
    for k in range(1, 10):
        d[f"iat_{k}"] = rng.random(rows) * 0.1
    return pd.DataFrame(d)


@pytest.fixture
def csvs(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    synth(seed=1).to_csv(a, index=False)
    synth(seed=2, t0=1000).to_csv(b, index=False)
    return a, b


def check(r):
    for k in ("precision", "recall", "f1", "tnr", "clf_coverage", "reg_coverage"):
        assert 0 <= r[k] <= 1
    assert r["mae_log10"] >= 0 and math.isfinite(r["mae_log10"])
    for k in ("clf_reduction", "reg_reduction"):
        assert r[k] is None or r[k] >= 1
    assert r["test_pos"] > 0


def test_split_run(csvs):
    # 300 synthetic rows: top 1% (default) can leave 0 test positives, so use p=0.10
    r = run(csvs[0], thr_param=0.10)
    check(r)
    assert r["train_flows"] == 210 and r["test_flows"] == 90


def test_separate_test_csv(csvs):
    r = run(csvs[0], csvs[1], thr_param=0.10)
    check(r)
    assert r["train_flows"] == 300 and r["test_flows"] == 300


def test_default_thr_param_is_1pct(csvs):
    r = run(csvs[0])
    assert r["thr_param"] == 0.01


def test_pkts_pct_reg_thr(csvs):
    r = run(csvs[0], thr_def="pkts_pct", thr_param=0.2, n=0)
    check(r)
    assert r["reg_thr_value"] > 0 and r["reg_thr_value"] != r["thr_value"]
    assert math.isfinite(r["reg_coverage"])


def test_cli_results_csv(csvs, tmp_path, capsys):
    out = tmp_path / "res.csv"
    main([str(csvs[0]), "--thr-param", "0.10", "--out", str(out)])
    o = capsys.readouterr().out
    assert "precision=" in o
    assert all(k + "=" in o for k in ("el_short_frac", "recall_long", "recall_short"))
    assert "seed=0 f1_ci=[" in o
    df = pd.read_csv(out)
    assert list(df.columns) == COLUMNS and len(COLUMNS) == 32 and len(df) == 1
    main([str(csvs[0]), "--test", str(csvs[1]), "--thr-param", "0.10", "--out", str(out)])
    df = pd.read_csv(out)
    assert len(df) == 2 and pd.isna(df["test_csv"][0])
    assert df["test_csv"][1] == str(csvs[1])


def test_train_max_rows(csvs, tmp_path):
    full = run(csvs[0], csvs[1], thr_param=0.10)
    r = run(csvs[0], csvs[1], thr_param=0.10, train_max_rows=100)
    assert r["n_train_used"] == 100 and full["n_train_used"] == 300
    assert r["train_flows"] == 300 and r["test_flows"] == 300
    assert r["thr_value"] == full["thr_value"]
    check(r)
    r2 = run(csvs[0], csvs[1], thr_param=0.10, train_max_rows=100)
    assert r2 == pytest.approx(r, rel=1e-9, nan_ok=True)  # n_jobs=-1: last-digit float noise
    assert run(csvs[0], csvs[1], thr_param=0.10, train_max_rows=1000)["n_train_used"] == 300
    out = tmp_path / "res.csv"
    main([str(csvs[0]), "--test", str(csvs[1]), "--thr-param", "0.10",
          "--train-max-rows", "100", "--out", str(out)])
    main([str(csvs[0]), "--thr-param", "0.10", "--out", str(out)])
    df = pd.read_csv(out)
    assert df["train_max_rows"][0] == 100 and pd.isna(df["train_max_rows"][1])


def test_train_max_rows_keeps_positive_ratio(csvs):
    from flowpred import train
    seen = {}
    orig = train.evaluate

    def spy(Xtr, ytr, *a):
        seen["n"], seen["pos"] = len(ytr), int(ytr.sum())
        return orig(Xtr, ytr, *a)

    train.evaluate = spy
    try:
        run(csvs[0], csvs[1], thr_param=0.10)
        n0, p0 = seen["n"], seen["pos"]
        run(csvs[0], csvs[1], thr_param=0.10, train_max_rows=100)
    finally:
        train.evaluate = orig
    assert seen["n"] == 100 and abs(seen["pos"] - p0 * 100 / n0) <= 1


def test_sample_rate_meta(csvs, tmp_path, capsys):
    import json
    assert run(csvs[0], csvs[1], thr_param=0.10)["sample_rate"] == 1.0  # no meta
    for c in csvs:
        Path(str(c) + ".meta.json").write_text(json.dumps({"sample_rate": 0.25}))
    out = tmp_path / "res.csv"
    r = main([str(csvs[0]), "--test", str(csvs[1]), "--thr-param", "0.10", "--out", str(out)])
    assert r["sample_rate"] == 0.25
    assert capsys.readouterr().out.splitlines()[0].startswith("sample_rate=0.25 ")
    assert pd.read_csv(out)["sample_rate"][0] == 0.25
    Path(str(csvs[1]) + ".meta.json").write_text(json.dumps({"sample_rate": 0.5}))
    with pytest.raises(ValueError):
        run(csvs[0], csvs[1], thr_param=0.10)
    Path(str(csvs[1]) + ".meta.json").unlink()  # missing test meta = 1.0 != 0.25
    with pytest.raises(ValueError):
        run(csvs[0], csvs[1], thr_param=0.10)


def test_columns_tail():
    assert COLUMNS[-7:] == ["reg_reduction", "el_short_frac", "recall_long", "recall_short",
                            "seed", "f1_lo", "f1_hi"]
    assert COLUMNS[-3:] == ["seed", "f1_lo", "f1_hi"]


def test_seed_passed_and_reproducible(csvs, tmp_path, capsys):
    from flowpred import train
    seen = []
    orig = train.RandomForestClassifier

    def spy(*a, **k):
        seen.append(k["random_state"])
        return orig(*a, **k)

    train.RandomForestClassifier = spy
    try:
        run(csvs[0], csvs[1], thr_param=0.10, seed=7)
        run(csvs[0], csvs[1], thr_param=0.10)
    finally:
        train.RandomForestClassifier = orig
    assert seen == [7, 0]
    a = run(csvs[0], csvs[1], thr_param=0.10, seed=3, train_max_rows=100)
    b = run(csvs[0], csvs[1], thr_param=0.10, seed=3, train_max_rows=100)
    assert a == pytest.approx(b, rel=1e-9, nan_ok=True) and a["seed"] == 3
    out = tmp_path / "s.csv"
    main([str(csvs[0]), "--thr-param", "0.10", "--seed", "5", "--out", str(out)])
    assert "seed=5 f1_ci=[" in capsys.readouterr().out
    row = pd.read_csv(out).iloc[0]
    assert row["seed"] == 5 and row["f1_lo"] <= row["f1"] <= row["f1_hi"]


def test_f1_bootstrap_ci():
    y = np.array([1, 1, 0, 0, 1, 0, 0, 1] * 20)
    assert f1_bootstrap_ci(y, y, 0) == (1.0, 1.0)
    assert f1_bootstrap_ci(np.zeros(10), np.ones(10), 0) == (None, None)
    pred = np.array([1, 0, 0, 1, 1, 0, 0, 1] * 20)
    lo, hi = f1_bootstrap_ci(y, pred, 0)
    f1 = 2 * 3 / (2 * 3 + 1 + 1)  # tp=3 fp=1 fn=1 per 8 rows
    assert lo <= f1 <= hi and lo < hi
    assert f1_bootstrap_ci(y, pred, 0) == (lo, hi)


def test_stratified_recall_mixed():
    # n=3; elephants idx 0..3: n_seen 1,2 (short), 3,5 (long); idx4 mouse
    y = [1, 1, 1, 1, 0]
    n_seen = [1, 2, 3, 5, 1]
    pred = [1, 0, 1, 0, 1]
    assert stratified_recall(y, pred, n_seen, 3) == (0.5, 0.5, 0.5)


def test_stratified_recall_one_group_only():
    assert stratified_recall([1, 1], [1, 0], [1, 2], 3) == (1.0, None, 0.5)  # short only
    assert stratified_recall([1, 1], [1, 0], [4, 5], 3) == (0.0, 0.5, None)  # long only
    assert stratified_recall([0, 0], [1, 0], [1, 5], 3) == (None, None, None)  # no elephant


def test_stratified_recall_n0():
    assert stratified_recall([1, 1, 0], [1, 0, 0], None, 0) == (0.0, 0.5, None)


def test_evaluate_calls_stratified(csvs):
    r = run(csvs[0], csvs[1], thr_param=0.10)
    for k in ("el_short_frac", "recall_long", "recall_short"):
        assert r[k] is None or 0 <= r[k] <= 1
    r0 = run(csvs[0], csvs[1], thr_param=0.10, n=0)
    assert r0["el_short_frac"] == 0 and r0["recall_short"] is None
    assert r0["recall_long"] == pytest.approx(r0["recall"])
