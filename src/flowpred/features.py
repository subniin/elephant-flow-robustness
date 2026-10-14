"""flow table -> split, labels, feature matrix (design.md section 2, step 2)."""
import numpy as np

N_MAX = 10
THR_DEFS = ("bytes_pct", "bytes_fixed", "pkts_pct")
HEADER = ["proto", "src_port", "dst_port"]
# size/timing depend on n; these are the column-name prefixes of each bundle.
SIZE = ["n_seen", "plen_*"]
TIMING = ["iat_*"]
FEATURE_GROUPS = {"header": HEADER, "size": SIZE, "timing": TIMING}


def drop_tail(df, tail_sec):
    """Drop flows that started within tail_sec of this df's max(start_ts)."""
    if tail_sec <= 0:
        return df
    return df[df["start_ts"] <= df["start_ts"].max() - tail_sec]


def split_time(df, train_frac=0.7):
    """First 70% by start_ts -> train, rest -> test."""
    df = df.sort_values("start_ts", kind="stable").reset_index(drop=True)
    k = int(len(df) * train_frac)
    return df.iloc[:k].reset_index(drop=True), df.iloc[k:].reset_index(drop=True)


def fit_threshold(df, definition, value):
    """bytes_pct/pkts_pct: value = top fraction p; bytes_fixed: value = bytes."""
    if definition == "bytes_fixed":
        return float(value)
    col = {"bytes_pct": "byte_count", "pkts_pct": "pkt_count"}.get(definition)
    if col is None:
        raise ValueError(f"unknown threshold definition: {definition}")
    return float(np.quantile(df[col], 1 - value))


def label(df, definition, threshold):
    """1 if value >= threshold."""
    col = "pkt_count" if definition == "pkts_pct" else "byte_count"
    if definition not in THR_DEFS:
        raise ValueError(f"unknown threshold definition: {definition}")
    return (df[col] >= threshold).astype(int)


def features(df, n=4):
    """Return (X, y_log). X columns: proto, src_port, dst_port, [n_seen,
    plen_1..n, iat_1..n-1]; 3 cols for n=0, else 2n+3."""
    if not 0 <= n <= N_MAX:
        raise ValueError(f"n must be in 0..{N_MAX}")
    plen = [f"plen_{k}" for k in range(1, n + 1)]
    iat = [f"iat_{k}" for k in range(1, n)]
    X = df[HEADER + plen + iat].copy()
    if n >= 1:
        X.insert(3, "n_seen", (df[plen] != 0).sum(axis=1))
    return X, np.log10(df["byte_count"])
