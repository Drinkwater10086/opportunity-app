"""Catch browser step validation blocking the default analysis submission."""
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path


def test_default_numeric_inputs_satisfy_html_constraints():
    class Inputs(HTMLParser):
        def __init__(self):
            super().__init__()
            self.fields = []

        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag == 'input' and values.get('type') == 'number':
                self.fields.append(values)

    parser = Inputs()
    parser.feed(Path(__file__).with_name('local.html').read_text(encoding='utf-8'))
    assert len(parser.fields) >= 4
    for field in parser.fields:
        value = Decimal(field['value'])
        minimum = Decimal(field.get('min', '0'))
        maximum = Decimal(field.get('max', 'Infinity'))
        step = Decimal(field.get('step', '1'))
        assert minimum <= value <= maximum, field['id']
        assert (value-minimum) % step == 0, field['id']


def test_collection_limit_is_editable_and_matches_backend_bounds():
    import app
    import pytest
    class Inputs(HTMLParser):
        def __init__(self):super().__init__();self.limit=None
        def handle_starttag(self,tag,attrs):
            attrs=dict(attrs)
            if tag=='input' and attrs.get('id')=='limit':self.limit=attrs
    parser=Inputs();parser.feed(Path(__file__).with_name('index.html').read_text(encoding='utf8'))
    assert parser.limit is not None
    assert parser.limit['type']=='number'
    assert (parser.limit['min'],parser.limit['max'],parser.limit['step'],parser.limit['value'])==('1','500','1','100')
    for amount in (1,37,500):assert app.BatchInput(direction='办公',query='meeting',limit=amount).limit==amount
    for amount in (0,501,1.5):
        with pytest.raises(ValueError):app.BatchInput(direction='办公',query='meeting',limit=amount)
