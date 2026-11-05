"""The lab server's file content (crates/labserver/src/content.rs), for checking downloads.

Byte i of the file with seed s is byte (i % 8) of splitmix64(s * 0xD1B54A32D192ED03 ^ (i // 8))
in little-endian order, so the SHA-256 of any generated file can be computed without the server.
"""

import hashlib

import numpy as np

M1 = np.uint64(0x9E3779B97F4A7C15)
M2 = np.uint64(0xBF58476D1CE4E5B9)
M3 = np.uint64(0x94D049BB133111EB)
K = 0xD1B54A32D192ED03
CHUNK = 1 << 22  # words per step (32 MiB)


def splitmix64(x):
    with np.errstate(over="ignore"):
        z = x + M1
        z = (z ^ (z >> np.uint64(30))) * M2
        z = (z ^ (z >> np.uint64(27))) * M3
        return z ^ (z >> np.uint64(31))


def sha256(seed, size):
    """SHA-256 (hex) of the generated file `seed` of `size` bytes."""
    h = hashlib.sha256()
    key = np.uint64((seed * K) & 0xFFFFFFFFFFFFFFFF)
    words = (size + 7) // 8
    done = 0
    for start in range(0, words, CHUNK):
        n = min(CHUNK, words - start)
        idx = np.arange(start, start + n, dtype=np.uint64)
        data = splitmix64(key ^ idx).astype("<u8").tobytes()
        take = min(len(data), size - done)
        h.update(data[:take])
        done += take
    return h.hexdigest()


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(1 << 22)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


if __name__ == "__main__":
    import sys
    import urllib.request

    # Check against a running lab server: python tools/bench/content.py http://127.0.0.1:8097
    base = sys.argv[1]
    for seed, size in ((0, 1), (1, 7), (2, 4096 + 3), (7, 1 << 20)):
        with urllib.request.urlopen(f"{base}/gen/{size}?seed={seed}") as r:
            got = hashlib.sha256(r.read()).hexdigest()
        print(seed, size, got == sha256(seed, size))
