import gzip
import json
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import dpkt
import pandas as pd
import pytest

from flowpred.preprocess import columns, main, preprocess

A, B = "10.0.0.1", "10.0.0.2"


def pkt(src, dst, sport, dport, payload=0, proto=6, flags=dpkt.tcp.TH_ACK, offset=0):
    if proto == 6:
        l4 = dpkt.tcp.TCP(sport=sport, dport=dport, flags=flags)
        hdr = 20
    else:
        l4 = dpkt.udp.UDP(sport=sport, dport=dport)
        l4.ulen = 8 + payload
        hdr = 8
    l4.data = b"x" * payload
    ip = dpkt.ip.IP(src=socket.inet_aton(src), dst=socket.inet_aton(dst), p=proto, offset=offset)
    ip.data = l4
    ip.len = 20 + hdr + payload
    return bytes(dpkt.ethernet.Ethernet(data=ip)), ip.len


def write_pcap(path, pkts, gz=False):
    f = gzip.open(path, "wb") if gz else open(path, "wb")
    with f:
        w = dpkt.pcap.Writer(f)
        for ts, buf in pkts:
            w.writepkt(buf, ts)


def synth():
    """Return ([(ts, bytes)], expected byte_count sum of kept packets)."""
    p = []  # (ts, buf, ip_len, kept)
    # flow 1 (TCP, started at t=2): SYN, data 100, bare ACK, data 200
    for ts, kw in [(2.0, dict(flags=dpkt.tcp.TH_SYN)), (2.5, dict(payload=100)),
                   (3.0, {}), (4.0, dict(payload=200))]:
        p.append((ts, *pkt(A, B, 1000, 80, **kw), True))
    # flow 2 (UDP, started at t=1)
    p.append((1.0, *pkt(A, B, 53, 53, payload=30, proto=17), True))
    p.append((1.2, *pkt(A, B, 53, 53, payload=40, proto=17), True))
    # dropped: fragment with offset != 0, non-IPv4
    p.append((5.0, *pkt(A, B, 1, 2, payload=10, offset=100), False))
    arp = bytes(dpkt.ethernet.Ethernet(type=dpkt.ethernet.ETH_TYPE_ARP, data=bytes(28)))
    p.append((5.1, arp, 0, False))
    p.sort(key=lambda x: x[0])
    return [(ts, b) for ts, b, _, _ in p], sum(n for _, _, n, k in p if k)


def test_flows(tmp_path):
    pk, total = synth()
    f = tmp_path / "a.pcap"
    write_pcap(f, pk)
    df = preprocess(f)
    assert len(df) == 2 and df.shape[1] == 27
    assert list(df.columns) == columns()
    assert df.byte_count.sum() == total
    assert list(df.start_ts) == [1.0, 2.0]  # sorted
    udp, tcp = df.iloc[0], df.iloc[1]
    assert udp.proto == 17 and udp.pkt_count == 2 and udp.plen_1 == 30 and udp.plen_2 == 40
    assert abs(udp.iat_1 - 0.2) < 1e-6
    # SYN and bare ACK counted in pkt/byte count, not in plen_*
    assert tcp.pkt_count == 4 and tcp.byte_count == 40 + 140 + 40 + 240
    assert (tcp.plen_1, tcp.plen_2, tcp.plen_3) == (100, 200, 0)
    assert abs(tcp.iat_1 - 1.5) < 1e-6 and tcp.iat_2 == 0


def test_gz_and_max_packets(tmp_path):
    pk, _ = synth()
    f = tmp_path / "a.pcap.gz"
    write_pcap(f, pk, gz=True)
    assert len(preprocess(f)) == 2
    df = preprocess(f, max_packets=2)  # first two packets: UDP t=1.0, 1.2
    assert len(df) == 1 and df.iloc[0].proto == 17


def test_csv_roundtrip(tmp_path):
    pk, _ = synth()
    f = tmp_path / "a.pcap"
    write_pcap(f, pk)
    out = tmp_path / "o.csv"
    preprocess(f).to_csv(out, index=False)
    assert list(pd.read_csv(out).columns) == columns()


def many(n=200):
    """n UDP flows (distinct sport), 1-3 packets each."""
    p = []
    for i in range(n):
        for j in range(i % 3 + 1):
            p.append((i + j * 0.01, pkt(A, B, 2000 + i, 53, payload=10 + i, proto=17)[0]))
    p.sort(key=lambda x: x[0])
    return p


def test_sample_rate(tmp_path):
    f = tmp_path / "m.pcap"
    write_pcap(f, many())
    full = preprocess(f)
    assert len(full) == 200 and full.equals(preprocess(f, sample_rate=1.0))
    half = preprocess(f, sample_rate=0.5)
    assert half.equals(preprocess(f, sample_rate=0.5))  # deterministic
    assert list(half.columns) == columns()
    assert 0 < len(half) < len(full)
    keys = ["src_ip", "dst_ip", "src_port", "dst_port", "proto"]
    m = half.merge(full, on=keys, suffixes=("", "_f"))
    assert len(m) == len(half)
    assert (m.pkt_count == m.pkt_count_f).all() and (m.byte_count == m.byte_count_f).all()
    for bad in (0, -0.1, 1.5):
        with pytest.raises(ValueError):
            preprocess(f, sample_rate=bad)


def test_cli_meta(tmp_path):
    f, out = tmp_path / "m.pcap", tmp_path / "o.csv"
    write_pcap(f, many())
    main([str(f), str(out), "--sample-rate", "0.5"])
    assert json.loads(Path(str(out) + ".meta.json").read_text()) == {"sample_rate": 0.5}
    assert 0 < len(pd.read_csv(out)) < 200
    main([str(f), str(out), "10"])  # positional max_packets, default rate
    assert json.loads(Path(str(out) + ".meta.json").read_text()) == {"sample_rate": 1.0}
    assert list(pd.read_csv(out).columns) == columns()


def test_progress_and_default_quiet(tmp_path, capsys):
    f = tmp_path / "m.pcap"
    write_pcap(f, many())
    preprocess(f)
    assert capsys.readouterr().err == ""
    preprocess(f, every=100)
    assert "packets=100 " in capsys.readouterr().err


def test_checkpoint_resume(tmp_path, monkeypatch):
    f, ck = tmp_path / "m.pcap", str(tmp_path / "c.ckpt")
    write_pcap(f, many())
    full = preprocess(f)
    real, calls = dpkt.ethernet.Ethernet, [0]

    def dying(buf):
        calls[0] += 1
        if calls[0] == 230:  # after the checkpoint at packet 200
            raise RuntimeError("killed")
        return real(buf)

    monkeypatch.setattr(dpkt.ethernet, "Ethernet", dying)
    with pytest.raises(RuntimeError):
        preprocess(f, checkpoint=ck, every=100)
    monkeypatch.setattr(dpkt.ethernet, "Ethernet", real)
    assert Path(ck).exists()
    with pytest.raises(ValueError):
        preprocess(f, checkpoint=ck, every=100, sample_rate=0.5)
    with pytest.raises(ValueError):
        preprocess(f, checkpoint=ck, every=100, n_max=5)
    resumed = preprocess(f, checkpoint=ck, every=100)
    assert resumed.equals(full)
    assert not Path(ck).exists()


def test_cli_checkpoint(tmp_path):
    f, out, ck = tmp_path / "m.pcap", tmp_path / "o.csv", tmp_path / "c.ckpt"
    write_pcap(f, many())
    main([str(f), str(out), "--checkpoint", str(ck), "--every", "100"])
    assert json.loads(Path(str(out) + ".meta.json").read_text()) == {"sample_rate": 1.0}
    assert pd.read_csv(out).shape[0] == 200 and not ck.exists()
