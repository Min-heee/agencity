#!/bin/sh
# 맥에서 더블클릭하면 클로드 오피스를 켜요(처음에 막히면 README의 안내대로 한 번 허용).
cd "$(dirname "$0")" && exec python3 start.py
