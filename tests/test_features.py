import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd

from flowpred.features import (HEADER, drop_tail, features, fit_threshold,
                               label, split_time)


def make(byte_counts, pkt_counts=None, start=None):
    n = len(byte_counts)
    d = {"proto": [6] * n, "src_port": [1] * n, "dst_port": [80] * n,
         "start_ts": start if start is not None else list(range(n)),
         "pkt_count": pkt_counts or [5] * n, "byte_count": byte_counts}
    for k in range(1, 11):
        d[f"plen_{k}"] = [100 * k] * n
    for k in range(1, 10):
        d[f"iat_{k}"] = [0.1 * k] * n
    return pd.DataFrame(d)


def test_feature_columns():
    df = make([100, 200])
    X0, y = features(df, 0)
    assert list(X0.columns) == HEADER
    X1, _ = features(df, 1)
    assert list(X1.columns) == HEADER + ["n_seen", "plen_1"]
    X4, _ = features(df, 4)
    assert list(X4.columns) == (HEADER + ["n_seen", "plen_1", "plen_2", "plen_3",
                                          "plen_4", "iat_1", "iat_2", "iat_3"])
    assert X4.shape[1] == 11 and X1.shape[1] == 5
    assert np.allclose(y, [2, np.log10(200)])


def test_n_seen():
    df = make([100] * 3)
    df.loc[0, ["plen_3", "plen_4"]] = 0
    df.loc[1, ["plen_1", "plen_2", "plen_3", "plen_4"]] = 0
    X, _ = features(df, 4)
    assert list(X["n_seen"]) == [2, 0, 4]
    X, _ = features(df, 2)
    assert list(X["n_seen"]) == [2, 0, 2]


def test_bytes_fixed_boundary():
    df = make([99, 100, 101])
    thr = fit_threshold(df, "bytes_fixed", 100)
    assert thr == 100
    assert list(label(df, "bytes_fixed", thr)) == [0, 1, 1]


def test_bytes_pct_boundary():
    df = make(list(range(1, 11)))  # 1..10
    thr = fit_threshold(df, "bytes_pct", 0.10)
    assert thr == np.quantile(range(1, 11), 0.9)
    assert list(label(df, "bytes_pct", thr)) == [0] * 9 + [1]
    # value == threshold -> 1
    assert label(make([thr]), "bytes_pct", thr).iloc[0] == 1


def test_pkts_pct_boundary():
    df = make([100] * 5, pkt_counts=[1, 2, 3, 4, 5])
    thr = fit_threshold(df, "pkts_pct", 0.2)
    assert thr == np.quantile([1, 2, 3, 4, 5], 0.8)
    df2 = make([100] * 3, pkt_counts=[3, 4, 5])
    assert list(label(df2, "pkts_pct", 4)) == [0, 1, 1]


def test_drop_tail():
    df = make([100] * 5, start=[0, 10, 30, 39.9, 40])
    assert len(drop_tail(df, 0)) == 5
    out = drop_tail(df, 10)  # keep start_ts <= 30
    assert list(out["start_ts"]) == [0, 10, 30]
    assert list(drop_tail(df, 0.05)["start_ts"]) == [0, 10, 30, 39.9]  # just inside
    assert list(drop_tail(df, 0.2)["start_ts"]) == [0, 10, 30]  # tail zone dropped


def test_split_then_train_threshold():
    df = make(list(range(10, 0, -1)), start=list(range(10)))  # bytes 10..1
    train, test = split_time(df)
    assert len(train) == 7 and len(test) == 3
    assert train["start_ts"].max() < test["start_ts"].min()
    thr = fit_threshold(train, "bytes_pct", 0.10)
    assert thr == np.quantile(train["byte_count"], 0.9)
    y = label(test, "bytes_pct", thr)
    assert list(y) == [0, 0, 0]  # test bytes 3,2,1 < train thr
