#!/bin/bash

# This script installs all necessary dependencies for the COMP3004 Mininet project.

# Ensure the system is updated
echo "--- Updating and upgrading system packages ---"
sudo apt update && sudo apt upgrade -y

# Install core dependencies: python3, pip, git, and network tools
echo "--- Installing core dependencies ---"
sudo apt install -y python3 python3-pip git net-tools openvswitch-switch

# Install Ryu SDN controller
echo "--- Installing Ryu SDN controller ---"
sudo apt install -y python3-ryu

# Install Nginx, the web server for the edge nodes
echo "--- Installing Nginx web server ---"
sudo apt install -y nginx

# Clone Mininet repository if it doesn't exist and install it
if [ ! -d "mininet" ]; then
    echo "--- Cloning Mininet repository ---"
    git clone https://github.com/mininet/mininet
    cd mininet || { echo "Failed to change directory to mininet. Exiting."; exit 1; }
    
    echo "--- Installing Mininet ---"
    # Change Makefile to use python3
    sudo sed -i 's/^PYTHON ?= python/PYTHON ?= python3/' Makefile
    sudo make install
else
    echo "--- Mininet repository already exists. Skipping clone and install. ---"
fi

echo "--- Installation script completed. ---"
echo "Please reboot your VM if prompted or if you experience any issues."
