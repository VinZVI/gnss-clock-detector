#!/bin/bash
set -e

# Build script for Render.com

# Install dependencies using uv
pip install -e .

# Set NASA as default data source for Render (FTP may be blocked)
export GNSS_DATA_SOURCE=nasa

echo "✓ Build complete - configured for NASA CDDIS source"
