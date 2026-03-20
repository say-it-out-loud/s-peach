#!/bin/bash

rm -rf dist/
uv lock
uv build
