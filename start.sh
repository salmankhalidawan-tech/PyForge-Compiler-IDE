#!/bin/bash
echo "🐍 Starting PyForge — Compiler Construction Edition"
echo ""
echo "Installing dependencies..."
pip install flask flask-cors numpy pandas matplotlib scipy sympy Pillow requests --break-system-packages -q

echo ""
echo "✅ Starting backend on http://localhost:5000"
echo "📂 Open index.html in your browser"
echo ""
echo "Press Ctrl+C to stop."
echo "─────────────────────────────────────"
cd "$(dirname "$0")"
python server.py
