"""读取 AZW3/MOBI 的 EXTH 元数据（只读）。用法: python3 -I mobi_meta.py <dir> <out.tsv>"""
import os, struct, sys

TAGS = {100: 'author', 101: 'publisher', 103: 'desc', 104: 'isbn', 106: 'date', 108: 'contributor',
        113: 'asin', 501: 'cdetype', 503: 'title', 524: 'lang', 535: 'creator_build'}

def meta(path):
    d = open(path, 'rb').read()
    n = struct.unpack('>H', d[76:78])[0]
    r0 = struct.unpack('>I', d[78:82])[0]
    rec0 = d[r0:]
    enc = struct.unpack('>H', rec0[12:14])[0]  # 加密类型，0=无 DRM
    mh_len = struct.unpack('>I', rec0[20:24])[0]
    ver = struct.unpack('>I', rec0[36:40])[0]
    out = {'drm': enc, 'mobi_ver': ver}
    flags = struct.unpack('>I', rec0[128:132])[0]
    if flags & 0x40:
        e = rec0[16 + mh_len:]
        assert e[:4] == b'EXTH'
        cnt = struct.unpack('>I', e[8:12])[0]
        p = 12
        for _ in range(cnt):
            t, l = struct.unpack('>II', e[p:p + 8])
            v = e[p + 8:p + l]
            if t in TAGS and t != 103:
                out.setdefault(TAGS[t], v.decode('utf-8', 'replace'))
            p += l
    return out

rows = []
for dp, _, fs in os.walk(sys.argv[1]):
    for f in fs:
        p = os.path.join(dp, f)
        try:
            m = meta(p)
        except Exception as ex:
            m = {'err': repr(ex)[:50]}
        m['file'] = f; m['MB'] = round(os.path.getsize(p) / 1e6, 1)
        rows.append(m)
cols = ['file', 'MB', 'drm', 'mobi_ver', 'title', 'author', 'publisher', 'asin', 'cdetype', 'contributor', 'creator_build', 'date', 'lang', 'err']
with open(sys.argv[2], 'w') as o:
    o.write('\t'.join(cols) + '\n')
    for m in rows:
        o.write('\t'.join(str(m.get(c, '')).replace('\t', ' ') for c in cols) + '\n')
from collections import Counter
print(len(rows), 'DRM', Counter(r.get('drm') for r in rows), 'cdetype', Counter(r.get('cdetype') for r in rows))
print('asin前缀', Counter((r.get('asin') or '')[:2] for r in rows).most_common(5))
print('contributor', Counter((r.get('contributor') or '')[:30] for r in rows).most_common(6))
print('publisher', Counter(r.get('publisher') for r in rows).most_common(15))
