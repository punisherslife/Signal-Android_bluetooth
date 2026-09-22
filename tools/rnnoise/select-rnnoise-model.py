#!/usr/bin/env python3
"""Select Little weights and the header actually referenced by their C source."""
from pathlib import Path
import re
import sys


def select(root):
    candidates=list(root.rglob('rnnoise_data_little.c'))
    if len(candidates)!=1:raise ValueError(f'Expected one Little model C file, found {len(candidates)}')
    source=candidates[0];text=source.read_text()
    includes=re.findall(r'(?m)^\s*#\s*include\s+"(rnnoise_data(?:_little)?\.h)"\s*$',text)
    if len(includes)!=1:raise ValueError('Little model must include exactly one recognized model header')
    header=source.with_name(includes[0])
    if not header.is_file():raise ValueError(f'Model header referenced by Little weights is missing: {header}')
    header_text=header.read_text()
    destination=root/'src'
    if not (destination/'nnet.h').is_file():raise ValueError('Destination is not the pinned RNNoise source layout')
    # Exporters may name both outputs *_little, or ship a shared default header.
    # Match the real include and normalize it before removing duplicate models.
    text=text.replace('"'+includes[0]+'"','"rnnoise_data.h"',1)
    (destination/'rnnoise_data.c').write_text(text)
    (destination/'rnnoise_data.h').write_text(header_text)
    print('RNNoise Little source/header selected and canonicalized')


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('usage: select-rnnoise-model.py <unpacked-rnnoise-source>')
    select(Path(sys.argv[1]))
