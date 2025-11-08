#!/bin/bash

# Quick Start Script for Outlier Wormhole
# This script helps you get started quickly with Docker Compose

set -e

echo "╔════════════════════════════════════════════════════╗"
echo "║      Outlier Wormhole - Quick Start Setup          ║"
echo "╚════════════════════════════════════════════════════╝"
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Error: Docker is not installed or not in PATH"
    echo "   Please install Docker from https://docs.docker.com/get-docker/"
    exit 1
fi

# Check if Docker Compose is available
if ! docker compose version &> /dev/null; then
    echo "❌ Error: Docker Compose is not available"
    echo "   Please install Docker Compose v2"
    exit 1
fi

echo "✅ Docker and Docker Compose are available"
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  No .env file found. Creating from .env.example..."
    cp .env.example .env
    echo ""
    echo "📝 Please edit .env and add your Outlier.ai credentials:"
    echo "   OUTLIER_EMAIL=your-email@example.com"
    echo "   OUTLIER_PASSWORD=your-password"
    echo ""
    read -p "Press Enter after you've configured .env file..."
fi

# Validate .env has credentials
source .env
if [ -z "$OUTLIER_EMAIL" ] || [ "$OUTLIER_EMAIL" = "your-email@example.com" ]; then
    echo "❌ Error: OUTLIER_EMAIL is not configured in .env"
    exit 1
fi

if [ -z "$OUTLIER_PASSWORD" ] || [ "$OUTLIER_PASSWORD" = "your-password" ]; then
    echo "❌ Error: OUTLIER_PASSWORD is not configured in .env"
    exit 1
fi

echo "✅ Credentials configured"
echo ""

# Ask if user wants to build
echo "🏗️  Building Docker images..."
echo "   This may take a few minutes on first run..."
echo ""

docker compose build

echo ""
echo "✅ Build complete!"
echo ""

# Start services
echo "🚀 Starting services..."
echo ""

docker compose up -d

echo ""
echo "⏳ Waiting for services to be healthy..."
sleep 5

# Show status
docker compose ps

echo ""
echo "╔════════════════════════════════════════════════════╗"
echo "║              Services are starting!                ║"
echo "╚════════════════════════════════════════════════════╝"
echo ""
echo "📊 Check logs with:"
echo "   docker compose logs -f"
echo ""
echo "🧪 Test the API:"
echo "   curl http://localhost:11434/v1/models"
echo ""
echo "🛑 Stop services:"
echo "   docker compose down"
echo ""
echo "📖 For more information, see README.md"
