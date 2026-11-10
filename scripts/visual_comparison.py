"""Create a portable before/after report from saved production fixture outputs."""
import base64
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    before = ROOT / 'build/quality-baseline/pointwise-v2'
    after = ROOT / 'build/test-results/pointwise-device'
    out = ROOT / 'build/candidate-evidence'
    out.mkdir(parents=True, exist_ok=True)
    metrics = [{row['filter']: row for row in json.loads((folder / 'pixels-and-timing.json').read_text())}
               for folder in (before, after)]
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><title>TFM candidate visual comparison</title>',
             '<style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:0 20px;background:#202328;color:#eee}'
             'img{display:block;width:100%;height:88px;image-rendering:pixelated;border:1px solid #666}'
             'table{border-collapse:collapse;width:100%}td,th{padding:9px;text-align:left;border-bottom:1px solid #555}'
             'section{margin:40px 0}small{color:#bbc}</style>',
             '<h1>TFM: production fixture before / after</h1><p>These synthetic 1024 × 4 previews show four alpha/HDR bands. '
             'PNG previews cannot demonstrate HDR or float precision: use the accompanying raw metrics. '
             'Skin protection and CPU temperature tint corrections intentionally change affected U8 pixels. '
             'This is offline native evidence, not live Krita acceptance.</p>']
    rows = []
    for effect in ('vibrance', 'temperature', 'grain', 'vignette'):
        for depth in ('U8', 'U16', 'F16', 'F32'):
            key = f'{effect}-{depth}-profile1'
            parts.append('<section><h2>' + html.escape(key) + ' (sRGB)</h2>')
            record = {'fixture': key}
            for label, folder, values in zip(('Before', 'After'), (before, after), metrics):
                raw = (folder / (key + '.png')).read_bytes()
                parts.append(f'<p>{label}</p><img alt="{label}: {key}" src="data:image/png;base64,' + base64.b64encode(raw).decode() + '">')
                record[label.lower()] = {name: values[key][name] for name in
                    ('gradient_levels', 'alpha_max_error', 'blend_zero_unchanged', 'minimum_red', 'maximum_red')}
            parts.append('<table><tr><th>Metric</th><th>Before</th><th>After</th></tr>')
            for field in record['before']:
                parts.append(f'<tr><td>{field}</td><td>{record["before"][field]}</td><td>{record["after"][field]}</td></tr>')
            parts.append('</table></section>')
            rows.append(record)
    spatial = []
    for path in sorted((ROOT / 'build/quality-baseline/spatial').glob('U8-*.raw')):
        current = ROOT / 'build/test-results/spatial' / path.name
        spatial.append({'fixture': path.name, 'byte_identical': path.read_bytes() == current.read_bytes()})
    assert len(spatial) == 9 and all(row['byte_identical'] for row in spatial)
    parts.append('<p>All nine spatial U8 raw outputs remain byte-identical to baseline.</p></html>')
    (out / 'visual-comparison.html').write_text('\n'.join(parts), encoding='utf-8')
    (out / 'visual-comparison.json').write_text(json.dumps({'pointwise': rows, 'spatial_u8': spatial}, indent=2), encoding='utf-8')
    print('VISUAL_COMPARISON', out / 'visual-comparison.html')


if __name__ == '__main__':
    main()
