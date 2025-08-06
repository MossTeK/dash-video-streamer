#!/bin/bash

#install dependencies
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-ryu nginx help2man git net-tools open-vm-tools-desktop openvswitch-switch
git clone https://github.com/mininet/mininet
cd mininet
git fetch
git tag
git checkout -b mininet-2.3.0 2.3.0
sed -i 's/^PYTHON ?= python/PYTHON ?= python3/' Makefile