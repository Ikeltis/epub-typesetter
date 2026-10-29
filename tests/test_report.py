"""检查报告格式（guide/07 §6）与按书豁免（§7）。"""
import json

import pytest

from epub_typesetter import cli, engine, report
from epub_typesetter.book import Book
from epub_typesetter.waivers import WaiverFileError, WaiverSet
from epub_typesetter.xhtml import X, rename_file

from conftest import XHTML11, make_epub

C1 = 'OEBPS/Text/c1.xhtml'
C2 = 'OEBPS/Text/c2.xhtml'


def book_with(c1_body: str, c2_body: str = '<h1>第二章</h1><p>正文二。</p>') -> Book:
    return Book.load(make_epub({C1: XHTML11.format(title='第一章', body=c1_body),
                                C2: XHTML11.format(title='第二章', body=c2_body)}))


EMPTY3 = '<h1>第一章</h1><p id="blank">　</p><p> </p><p>正文<br/></p><p>正文一。</p>'


def ws(*entries, **top) -> WaiverSet:
    return WaiverSet.from_dict({'version': 1, 'ignore': list(entries), **top})


def find(rep, key):
    return next(d for d in rep['issues'] if d['key'] == key)


def test_rules_meta_covers_registered_rules():
    meta = engine.rules_meta()
    assert len(meta['rules']) >= 170 and meta['spec_version']
    for r in engine.all_rules():
        m = meta['rules'].get(r.id)
        assert m and m['hint'] and m['severity'], r.id


def test_report_structure_and_merge():
    b = book_with(EMPTY3)
    rep = report.build(engine.audit(b), b)
    d = find(rep, f'TYP-002@{C1}')
    # 空段两个 + 段尾 br 一个：同规则同文件合并为一条，命中三处
    assert d['hit_count'] == 3 and d['status'] == 'open'
    assert d['hint'] and d['spec'] == ['04 4.5.1.1', '04 4.5.1.7']
    assert {h['selector'] for h in d['hits']} >= {'p#blank'}
    assert all(h['xpath'].startswith('/html/body/') and h['line'] for h in d['hits'])
    assert rep['summary']['warning'] >= 1 and rep['summary']['waived'] == 0
    keys = [d['key'] for d in rep['issues']]
    assert len(keys) == len(set(keys))
    text = report.format_text(rep)
    assert 'TYP-002' in text and '提示：' in text and '规范：04 4.5.1.1' in text


def test_selector_waiver_partial_fix_keeps_waived_node():
    b = book_with(EMPTY3)
    w = ws({'rule': 'TYP-002', 'file': C1, 'where': {'selector': 'p#blank'}, 'reason': '有意留白'})
    rep = engine.fix(b, waivers=w)
    before = report.build(rep.before, b, w)
    assert find(before, f'TYP-002@{C1}')['status'] == 'partial'
    out = Book.load(b.to_bytes())
    ps = list(out.tree(C1).getroot().iter(X + 'p'))
    assert [p.get('id') for p in ps if not ''.join(p.itertext()).strip()] == ['blank']
    assert not any(br.getparent().tag == X + 'p' for br in out.tree(C1).getroot().iter(X + 'br'))
    after = report.build(engine.audit(out, waivers=w), out, w)
    d = find(after, f'TYP-002@{C1}')
    assert d['status'] == 'waived' and d['waivers'][0]['reason'] == '有意留白'
    assert after['summary']['waived'] == 1
    # 幂等：再修一遍零改动
    assert engine.fix(out, waivers=w).changes == []


def test_whole_file_glob_waiver_skips_fix():
    b = book_with('<h1>第一章</h1><p>正文。</p>', '<h1>第二章</h1><p>　</p><p>正文二。</p>')
    w = ws({'rule': 'TYP-*', 'file': '**/c2.xhtml', 'reason': '原样保留'})
    engine.fix(b, waivers=w)
    out = Book.load(b.to_bytes())
    assert len(list(out.tree(C2).getroot().iter(X + 'p'))) == 2
    rep = report.build(engine.audit(out, waivers=w), out, w)
    assert find(rep, f'TYP-002@{C2}')['status'] == 'waived'


def test_anchor_waiver_on_text_hit():
    b = book_with('<h1>第一章</h1><p>甲​乙，丙​丁。</p>')
    w = ws({'rule': 'TXT-001', 'file': C1, 'where': {'anchor': {'quote': '​', 'prefix': '丙'}},
            'reason': '此处零宽空格是有意的'})
    rep = engine.fix(b, waivers=w)
    out = Book.load(b.to_bytes())
    text = ''.join(out.tree(C1).getroot().find(f'.//{X}p').itertext())
    # 补丁拆开：只保留「丙」后面被豁免的那一个
    assert text == '甲乙，丙​丁。'
    d = find(report.build(rep.before, b, w), f'TXT-001@{C1}')
    assert d['hit_count'] == 2 and d['waived_count'] == 1
    assert [h['range'] for h in d['hits'] if h['waived']] == [[5, 6]]


def test_waiver_survives_rename():
    b = book_with('<h1>第一章</h1><p>　</p><p>正文。</p>')
    rename_file(b, C1, 'OEBPS/Text/chapter01.xhtml')
    w = ws({'rule': 'TYP-002', 'file': C1, 'reason': '改名后仍应命中'})
    rep = report.build(engine.audit(b, waivers=w), b, w)
    assert find(rep, 'TYP-002@OEBPS/Text/chapter01.xhtml')['status'] == 'waived'
    assert WaiverSet.renames_of(b) == {C1: 'OEBPS/Text/chapter01.xhtml'}
    # 新书旁的豁免文件只靠 renames 也能对上
    fresh = Book.load(b.to_bytes())
    w2 = ws({'rule': 'TYP-002', 'file': C1, 'reason': 'x'}, renames=WaiverSet.renames_of(b))
    assert find(report.build(engine.audit(fresh, waivers=w2), fresh, w2),
                'TYP-002@OEBPS/Text/chapter01.xhtml')['status'] == 'waived'


def test_where_needs_node_hit():
    """没有节点级命中的问题（只到文件级），带定位的豁免对不上，不能误豁免。"""
    b = book_with('<h1>第一章</h1><p>正文  一。</p>')
    w = ws({'rule': 'TXT-002', 'file': C1, 'where': {'selector': 'p'}, 'reason': 'x'})
    rep = report.build(engine.audit(b, waivers=w), b, w)
    assert find(rep, f'TXT-002@{C1}')['status'] == 'open'


def test_self_check_str024():
    b = book_with(EMPTY3)
    w = ws({'rule': 'TYP-002'},                                             # 缺理由
           {'rule': 'TYP-002', 'where': {'line': 3}, 'reason': 'x'},        # 行号
           {'rule': 'TXT-999', 'reason': 'x'},                              # 规则不存在
           {'rule': 'SEM-003', 'file': 'nope/*.xhtml', 'reason': 'x'},      # 文件对不上
           {'rule': 'TXT-001', 'file': C1, 'reason': 'x'},                  # 没命中
           {'rule': 'TYP-002', 'file': C1, 'where': {'selector': 'p:nth-of-type(2)'}, 'reason': 'x'})
    assert len(w.entries) == 3
    issues = engine.audit(b, waivers=w)
    s = next(i for i in issues if i.rule_id == 'STR-024')
    assert s.severity == 'error' and s.file is None
    text = ' '.join(h.snippet for h in s.hits)
    for frag in ('缺少理由', '行号', 'TXT-999', '对不上任何现存文件', '没有命中', '位置序号'):
        assert frag in text, frag
    # 写回时无效条目原样保留，缺省 id 补上
    d = w.to_dict()
    assert len(d['ignore']) == 6 and d['ignore'][0] == {'rule': 'TYP-002'}
    assert [e.get('id') for e in d['ignore'] if 'id' in e] == ['w-001', 'w-002', 'w-003']
    with pytest.raises(WaiverFileError):
        WaiverSet.from_dict({'version': 2, 'ignore': []})
    with pytest.raises(WaiverFileError):
        WaiverSet.from_dict({'version': 1, 'ignore': [], 'extra': 1})
    with pytest.raises(ValueError):
        WaiverSet().add('TYP-002', '  ')


def test_cli_exit_codes(tmp_path, capsys):
    p = tmp_path / 'b.epub'
    p.write_bytes(make_epub())
    assert cli.main(['check', str(p)]) == 1                 # EPUB 2 等 error
    assert 'STR-004' in capsys.readouterr().out
    assert cli.main(['check', str(p), '--format', 'json']) == 1
    rep = json.loads(capsys.readouterr().out)
    assert rep['report_version'] == 1 and rep['issues'][0]['key']
    (tmp_path / 'b.epub.typeset-ignore.json').write_text('{bad json', encoding='utf-8')
    assert cli.main(['check', str(p)]) == 2
    assert cli.main(['check', str(p), '--no-waivers']) == 1
    out = tmp_path / 'o.epub'
    (tmp_path / 'b.epub.typeset-ignore.json').write_text(json.dumps(
        {'version': 1, 'ignore': [{'rule': 'A11Y-003', 'reason': '暂不写无障碍元数据'}]}), encoding='utf-8')
    assert cli.main(['fix', str(p), '-o', str(out)]) == 0
    capsys.readouterr()
    assert cli.main(['check', str(out)]) == 0
    assert '已豁免' in capsys.readouterr().out
    assert json.loads((tmp_path / 'o.epub.typeset-ignore.json').read_text())['ignore'][0]['id'] == 'w-001'
