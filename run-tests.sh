#!/bin/bash
set -e
echo "Running pytest suite with coverage..."
pytest tests/ --cov=services/segmentation --cov-report=term-missing -v
echo ""
echo "Tests passed!"
