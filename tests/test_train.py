import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd
import pytest

from flowpred.train import COLUMNS, main, run


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
    r = run(csvs[0])
    check(r)
    assert r["train_flows"] == 210 and r["test_flows"] == 90


def test_separate_test_csv(csvs):
    r = run(csvs[0], csvs[1])
    check(r)
    assert r["train_flows"] == 300 and r["test_flows"] == 300


def test_pkts_pct_reg_thr(csvs):
    r = run(csvs[0], thr_def="pkts_pct", thr_param=0.2, n=0)
    check(r)
    assert r["reg_thr_value"] > 0 and r["reg_thr_value"] != r["thr_value"]
    assert math.isfinite(r["reg_coverage"])


def test_cli_results_csv(csvs, tmp_path, capsys):
    out = tmp_path / "res.csv"
    main([str(csvs[0]), "--out", str(out)])
    assert "precision=" in capsys.readouterr().out
    df = pd.read_csv(out)
    assert list(df.columns) == COLUMNS and len(COLUMNS) == 24 and len(df) == 1
    main([str(csvs[0]), "--test", str(csvs[1]), "--out", str(out)])
    df = pd.read_csv(out)
    assert len(df) == 2 and pd.isna(df["test_csv"][0])
    assert df["test_csv"][1] == str(csvs[1])
