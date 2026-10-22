"""把 calibre `calibre-debug -x` 解包出的目录原样打包成 EPUB（不改任何内容）。

用法: python pack_exploded.py <解包目录>... -o <输出目录>
"""
import argparse
import os
import zipfile

CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="metadata.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
SKIP = {'.__explode_fmt__', 'mimetype'}


def pack(src, dst):
    with zipfile.ZipFile(dst, 'w') as z:
        z.writestr(zipfile.ZipInfo('mimetype'), 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
        z.writestr('META-INF/container.xml', CONTAINER, compress_type=zipfile.ZIP_DEFLATED)
        for dp, _, fs in os.walk(src):
            for f in sorted(fs):
                full = os.path.join(dp, f)
                rel = os.path.relpath(full, src).replace(os.sep, '/')
                if rel in SKIP or rel.startswith('META-INF/'):
                    continue
                z.write(full, rel, compress_type=zipfile.ZIP_DEFLATED)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('dirs', nargs='+')
    ap.add_argument('-o', '--out', required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for d in a.dirs:
        name = os.path.basename(os.path.normpath(d)) + '.epub'
        pack(d, os.path.join(a.out, name))
        print('packed', name)
