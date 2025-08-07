#!/bin/bash

# Update and upgrade system packages
echo "Updating and upgrading system packages..."
sudo apt update && sudo apt upgrade -y

# Install core dependencies including Mininet, Ryu, Nginx, FFmpeg, and GPAC (for MP4Box)
echo "Installing necessary packages: python3, pip, ryu, nginx, help2man, git, net-tools, open-vm-tools-desktop, openvswitch-switch, ffmpeg, gpac..."
sudo apt install -y python3 python3-pip python3-ryu nginx help2man git net-tools open-vm-tools-desktop openvswitch-switch ffmpeg gpac

# Clone Mininet repository if not already present
if [ ! -d "mininet" ]; then
    echo "Cloning Mininet repository..."
    git clone https://github.com/mininet/mininet
else
    echo "Mininet repository already exists. Skipping clone."
fi

# Navigate into the Mininet directory
cd mininet || { echo "Failed to change directory to mininet. Exiting."; exit 1; }

# Fetch all tags and checkout a specific stable version (2.3.0)
echo "Fetching Mininet tags and checking out version 2.3.0..."
git fetch
git tag
git checkout -b mininet-2.3.0 2.3.0

# Modify Mininet's Makefile to use python3
echo "Modifying Mininet Makefile to use python3..."
sed -i 's/^PYTHON ?= python/PYTHON ?= python3/' Makefile

# Install Mininet
echo "Installing Mininet..."
sudo make install

echo "Installation script completed. Please reboot your VM if prompted or if you experience issues."
