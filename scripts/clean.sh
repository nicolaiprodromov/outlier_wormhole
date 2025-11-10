#!/bin/bash
cd "$(dirname "$0")"
if [ -d "../data" ]; then
    rm -rf ../data/*
    echo "success"
else
    echo "data folder not found or empty"
fi
