"""pcap(.pcap / .pcap.gz) -> flow table CSV (design.md section 2, step 1).

Only Ethernet link type is supported (MAWI). Raw-IP link type (CAIDA) is
a later addition: add a branch here that parses from IP without Ethernet.

Usage: python -m flowpred.preprocess <pcap> <out.csv> [max_packets] [--sample-rate r]

--sample-rate r (0<r<=1, default 1.0) keeps only flows whose directed 5-tuple
raw-byte crc32 is < r*2**32 (deterministic across runs); kept flows keep all
packets. The CLI also writes <out.csv>.meta.json = {"sample_rate": r}.
"""
import argparse
import gzip
import json
import socket
import struct
import zlib

import dpkt
import pandas as pd

N_MAX = 10
KEY_COLS = ["src_ip", "dst_ip", "src_port", "dst_port", "proto"]


def columns(n_max=N_MAX):
    return (KEY_COLS + ["start_ts", "pkt_count", "byte_count"]
            + [f"plen_{k}" for k in range(1, n_max + 1)]
            + [f"iat_{k}" for k in range(1, n_max)])


def _open(path):
    f = open(path, "rb")
    magic = f.read(2)
    f.seek(0)
    return gzip.GzipFile(fileobj=f) if magic == b"\x1f\x8b" else f


def preprocess(pcap_path, max_packets=None, n_max=N_MAX, sample_rate=1.0):
    """Return the flow table as a DataFrame sorted by start_ts."""
    if not 0 < sample_rate <= 1:
        raise ValueError("sample_rate must be in (0, 1]")
    limit = sample_rate * 2**32
    flows = {}  # key -> [start_ts, pkts, bytes, plens, iats, last_data_ts]
    with _open(pcap_path) as f:
        reader = dpkt.pcap.Reader(f)
        if reader.datalink() != dpkt.pcap.DLT_EN10MB:
            raise ValueError("only Ethernet link type is supported")
        for i, (ts, buf) in enumerate(reader):
            if max_packets is not None and i >= max_packets:
                break
            try:
                ip = dpkt.ethernet.Ethernet(buf).data
            except dpkt.UnpackError:
                continue
            if not isinstance(ip, dpkt.ip.IP) or ip.offset != 0:
                continue
            l4 = ip.data
            if isinstance(l4, dpkt.tcp.TCP):
                plen = ip.len - 4 * ip.hl - 4 * l4.off
            elif isinstance(l4, dpkt.udp.UDP):
                plen = ip.len - 4 * ip.hl - 8
            else:
                continue
            if sample_rate < 1.0 and zlib.crc32(
                    ip.src + ip.dst + struct.pack("!HHB", l4.sport, l4.dport, ip.p)) >= limit:
                continue  # dropped flow: nothing cached
            key = (socket.inet_ntoa(ip.src), socket.inet_ntoa(ip.dst),
                   l4.sport, l4.dport, ip.p)
            fl = flows.get(key)
            if fl is None:
                fl = flows[key] = [ts, 0, 0, [], [], None]
            fl[1] += 1
            fl[2] += ip.len
            if plen > 0 and len(fl[3]) < n_max:
                if fl[5] is not None:
                    fl[4].append(ts - fl[5])
                fl[3].append(plen)
                fl[5] = ts
    rows = []
    for key, (ts, pk, by, plens, iats, _) in flows.items():
        plens = plens + [0] * (n_max - len(plens))
        iats = iats + [0.0] * (n_max - 1 - len(iats))
        rows.append([*key, ts, pk, by, *plens, *iats])
    df = pd.DataFrame(rows, columns=columns(n_max))
    return df.sort_values("start_ts", kind="stable").reset_index(drop=True)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="flowpred.preprocess")
    ap.add_argument("pcap")
    ap.add_argument("out_csv")
    ap.add_argument("max_packets", nargs="?", type=int)
    ap.add_argument("--sample-rate", type=float, default=1.0)
    a = ap.parse_args(argv)
    df = preprocess(a.pcap, a.max_packets, sample_rate=a.sample_rate)
    df.to_csv(a.out_csv, index=False)
    with open(a.out_csv + ".meta.json", "w") as fh:
        json.dump({"sample_rate": a.sample_rate}, fh)


if __name__ == "__main__":
    main()
