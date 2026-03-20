#!/bin/bash

VERSION=""

if [[ $1 ]]; then
  VERSION="==$1"
fi

uv tool install "s-peach-tts[chatterbox]${VERSION}" \
    --overrides <(echo -e "numpy>=2.0\ntorch>=2.6.0\ntorchaudio>=2.6.0") \
    --index https://test.pypi.org/simple/ \
    --index https://pypi.org/simple/ \
    --index-strategy unsafe-best-match
