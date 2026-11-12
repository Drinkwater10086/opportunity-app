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
    parser.feed(Path(__file__).with_name('index.html').read_text(encoding='utf-8'))
    assert len(parser.fields) >= 4
    for field in parser.fields:
        value = Decimal(field['value'])
        minimum = Decimal(field.get('min', '0'))
        maximum = Decimal(field.get('max', 'Infinity'))
        step = Decimal(field.get('step', '1'))
        assert minimum <= value <= maximum, field['id']
        assert (value-minimum) % step == 0, field['id']
